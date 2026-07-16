"""The repair proposer: staged LLM reasoning with per-sub-task model routing.

This module is the Health Check Agent's stages 3–5 (plan → write tests →
edit code). Per the corrected §2e (2026-07-16), reasoning is tiered by
sub-task: the **cheap** sub-task (fault localization) runs on the product's
shared free-tier chain via ``utils.llm_gateway.invoke_with_fallback`` (the
same Gemini → Groq → NVIDIA NIM → Cerebras → Bedrock chain the AI Data
Analyst uses); the **hard** sub-tasks (understand, hypothesize, critique,
plan, confirm, implement, review) run on **Claude Code via CLI**
(``repair.cli_brain``) because weak free-tier models cannot do complex
program repair. ``NEXUSIQ_REPAIR_BRAIN=gateway`` forces the old free-tier-only
path. In both cases Fable never hand-writes a specific fix — the agent's own
loop does, this just chooses the brain.

Design (rationale + citations in ARCHITECTURE_LOG Entry 7): a fixed staged
pipeline, not a free agent loop — Agentless-style. Reliability on a weak
model comes from (a) breaking the task into small steps whose outputs feed
the next, (b) deterministic validators between stages with concrete error
feedback on retry (external correction signals, which weak models can use,
unlike intrinsic self-critique, which they mostly can't), and (c) hard
guardrails: the plan's file allowlist, the scope fence, syntax checks per
edit, and the before/after eval gate downstream.

Prompts are generic templates — reusable unchanged on findings this code
has never seen. Nothing in them encodes any specific bug's fix.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from nexus_platform.repair import context_pack
from nexus_platform.repair.context_pack import EvidencePack

MAX_LLM_CALLS_PER_ATTEMPT = 25
DELAY_SECONDS = 8.0
EXHAUSTION_WAIT_SECONDS = 150.0  # fallback when the tracker can't say
# Cooldowns observed live run up to ~60 min (Groq hourly quota, Cerebras
# 429). One attempt may ride out at most this much total cooldown before
# giving up — wall-clock is cheap for an unattended loop; quota is not.
MAX_EXHAUSTION_WAIT_TOTAL = 4500.0
MAX_PLAN_FILES = 4
MAX_PLAN_STEPS = 6
# Groq's free tier rejects requests over ~12k tokens outright (observed
# live: HTTP 413 at ~52k chars), and Gemini Flash 504s on the same
# prompts. Implement-step prompts must slice large files, not embed them.
IMPLEMENT_SLICE_THRESHOLD_LINES = 400


class BudgetExhausted(RuntimeError):
    pass


class StageFailed(RuntimeError):
    pass


def build_models(reasoning: bool = True) -> list:
    """The product's own fallback chain — mirrors health_check's usage.
    Ollama is deliberately not appended: it is not available on this
    machine for this initiative (HEALTH_CHECK_AGENT_MISSION.md).

    Per-sub-task tiering: reasoning=True appends the chain's reasoning-tier
    Cerebras/Bedrock models (diagnosis, planning, code); reasoning=False the
    fast tier (cheap mechanical sub-tasks like localization)."""
    from config.settings import settings
    from utils.llm_gateway import insert_bedrock_fallback, insert_cerebras_fallback

    models = []
    if settings.google_api_key:
        models.append({"name": settings.gemini_flash_model, "type": "gemini",
                       "description": "Gemini Flash"})
    if settings.groq_api_key:
        models.append({"name": settings.groq_model, "type": "groq",
                       "description": "Groq"})
    if settings.nvidia_api_key:
        models.append({"name": settings.nvidia_model, "type": "nvidia",
                       "description": "NVIDIA NIM"})
    return insert_bedrock_fallback(
        insert_cerebras_fallback(models, reasoning=reasoning),
        reasoning=reasoning)


# Which chain tier each stage deserves: genuine reasoning (diagnosis, fix
# design, prediction, code) gets the reasoning tier; mechanical narrowing
# (pick files from a manifest) runs on the fast tier.
STAGE_REASONING = {
    "localize": False,
}


# Corrected §2e (2026-07-16): the hard repair sub-tasks route to Claude Code
# via CLI (a strong model — weak free-tier models can't do complex program
# repair); the cheap sub-task (localization) stays on the free-tier gateway.
# `reasoning` carries the split: STAGE_REASONING marks localize False → cheap
# → gateway; everything else True → CLI brain. Set NEXUSIQ_REPAIR_BRAIN=gateway
# to force the whole pipeline back onto the free-tier chain (the old path).
def _use_cli_brain(reasoning: bool) -> bool:
    mode = os.environ.get("NEXUSIQ_REPAIR_BRAIN", "cli").strip().lower()
    if mode == "gateway":
        return False
    if mode == "cli":
        return bool(reasoning)
    return bool(reasoning)


def _gateway_llm(prompt: str, task: str,
                 validator: Optional[Callable[[str], bool]],
                 reasoning: bool = True) -> dict:
    from utils.llm_gateway import get_llm_gateway
    from utils.quota_tracker import quota_tracker

    return get_llm_gateway().invoke_with_fallback(
        prompt=prompt, models=build_models(reasoning=reasoning),
        tracker=quota_tracker,
        task=task, temperature=0.2,
        metadata={"agent": "health_repair"},
        response_validator=validator)


def _default_llm(prompt: str, task: str,
                 validator: Optional[Callable[[str], bool]],
                 reasoning: bool = True, attempt: int = 0) -> dict:
    if _use_cli_brain(reasoning):
        from nexus_platform.repair.cli_brain import cli_llm
        return cli_llm(prompt=prompt, task=task, validator=validator,
                       reasoning=reasoning, attempt=attempt)
    return _gateway_llm(prompt, task, validator, reasoning=reasoning)


_PREAMBLE = (
    "You are the repair module of the Health Check Agent for NexusIQ, an "
    "internal AI data analyst platform. A simulation campaign surfaced a "
    "real defect in the product. You work the way a careful senior engineer "
    "works: read the evidence and the actual code before believing "
    "anything, state a hypothesis and check it against the evidence, write "
    "a plan before writing code, and make the smallest change that "
    "genuinely fixes the class of failure — never a rewrite, never a "
    "drive-by edit. Refer only to files, functions, and behavior you can "
    "actually see in what you are given.\n")

_EDIT_FORMAT = (
    "Emit your change as one or more blocks in EXACTLY this format:\n\n"
    "FILE: <repo-relative path>\n"
    "<<<<<<< SEARCH\n"
    "(lines copied VERBATIM from the current file content shown to you; "
    "leave empty only when creating a new file)\n"
    "=======\n"
    "(the replacement lines)\n"
    ">>>>>>> REPLACE\n\n"
    "Rules: the SEARCH lines must match the current file exactly, including "
    "indentation; keep each block as small as possible while staying "
    "unique; do not touch code unrelated to the current step; match the "
    "surrounding code's naming, docstring, and comment style.\n")


@dataclass
class Plan:
    steps: list  # [{"file": str, "text": str}]
    files_touched: list
    test_file: str
    raw: str = ""

    @property
    def test_steps(self):
        return [s for s in self.steps
                if s["file"].startswith("tests/")]

    @property
    def code_steps(self):
        return [s for s in self.steps
                if not s["file"].startswith("tests/")]


@dataclass
class Proposer:
    pack: EvidencePack
    llm: Callable[..., dict] = field(default=None)  # injectable for tests
    log: list = field(default_factory=list)
    calls_made: int = 0
    delay_seconds: float = DELAY_SECONDS
    exhaustion_wait: float = EXHAUSTION_WAIT_SECONDS
    max_exhaustion_wait_total: float = MAX_EXHAUSTION_WAIT_TOTAL
    max_calls: int = MAX_LLM_CALLS_PER_ATTEMPT
    _code_context: str = ""
    _known_symbols: set = field(default_factory=set)
    _located_functions: list = field(default_factory=list)
    _exhaustion_waited: float = 0.0

    def __post_init__(self):
        if self.llm is None:
            self.llm = _default_llm

    # ── plumbing ─────────────────────────────────────────────────────────

    def _invoke(self, stage: str, prompt: str,
                validator: Callable[[str], tuple[bool, str]],
                retries: int = 2) -> str:
        """One throttled, budgeted, validated LLM call with feedback retry.
        The validator returns (ok, reason); on failure the reason is
        appended to the prompt — an external correction signal."""
        attempt_prompt = prompt
        feedback_left = retries
        call_no = 0
        while True:
            if self.calls_made >= self.max_calls:
                raise BudgetExhausted(
                    f"repair attempt hit the {self.max_calls}-call budget "
                    f"at stage {stage!r}")
            if self.calls_made > 0:
                time.sleep(self.delay_seconds)
            self.calls_made += 1
            call_no += 1
            # The stage validator rides into the gateway too: a provider
            # whose output flunks it is skipped in-call and the next
            # provider tries immediately (the gateway discards the bad
            # response without cooling the provider down).
            kwargs = dict(prompt=attempt_prompt,
                          task=f"health_repair.{stage}",
                          validator=lambda c: bool(c and c.strip())
                          and validator(c)[0])
            # Per-stage tier routing + automatic escalation; injected test
            # doubles that don't take these kwargs keep working unchanged.
            # `attempt` = number of prior substantive (validator) failures for
            # this stage — cooldown waits don't decrement feedback_left, so
            # they never spuriously escalate the model tier.
            import inspect
            try:
                params = inspect.signature(self.llm).parameters
                if "reasoning" in params:
                    kwargs["reasoning"] = STAGE_REASONING.get(stage, True)
                if "attempt" in params:
                    kwargs["attempt"] = retries - feedback_left
            except (ValueError, TypeError):
                pass
            result = self.llm(**kwargs)
            response = str(result.get("response") or "").strip()
            ok = bool(result.get("success")) and bool(response)
            if ok:
                ok, reason = validator(response)
                exhausted = False
            else:
                tried = result.get("models_tried") or []
                had_invalid = any("INVALID" in str(t.get("status", ""))
                                  for t in tried)
                # A CLI-brain failure (timeout/error) is never free-tier
                # starvation — the Claude CLI has no quota cooldown, so it
                # must be a fast bounded retry, not a multi-minute wait (a
                # misclassification here spiralled a single hung call into a
                # whole 10-min window of timeout+wait cycles).
                had_cli = any(t.get("brain") == "cli" for t in tried)
                # Providers answered but every answer flunked the check →
                # a substantive failure worth feedback; nobody answered at
                # all → starvation worth waiting out (gateway only).
                exhausted = not had_invalid and not had_cli
                reason = ("the response failed the format/content check "
                          "described in the prompt"
                          if (had_invalid or had_cli)
                          else "no provider produced a response")
                if had_invalid:
                    # Derive the CONCRETE stage-validator reason from the
                    # last rejected answer — a weak model can act on "TEST_
                    # FILE already exists", not on "your answer failed".
                    invalids = [t.get("invalid_content") for t in tried
                                if t.get("invalid_content")]
                    if invalids:
                        response = invalids[-1]
                        _, why = validator(invalids[-1])
                        if why:
                            reason = why
            self.log.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "stage": stage, "attempt": call_no - 1,
                "model_used": result.get("model_used"),
                "prompt": attempt_prompt, "response": response,
                "valid": ok, "validator_reason": reason,
            })
            if ok:
                return response
            if exhausted:
                # Every provider is cooling down or over-limit — feedback
                # is meaningless and this must NOT consume a feedback
                # retry (attempt-6 lesson: a bounded for-loop quietly
                # spent its retries on starved calls). Ask the shared
                # tracker when the soonest provider recovers, wait that
                # long, and try the same prompt again — bounded only by
                # the wall-clock budget and the call cap.
                wait = self._cooldown_wait()
                if wait is None:
                    raise StageFailed(
                        f"stage {stage!r} starved: providers cooling down "
                        f"beyond the {self.max_exhaustion_wait_total:.0f}s "
                        "wait budget")
                time.sleep(wait)
                continue
            if feedback_left == 0:
                raise StageFailed(f"stage {stage!r} failed after "
                                  f"{retries + 1} substantive attempts: "
                                  f"{reason}")
            feedback_left -= 1
            attempt_prompt = (
                prompt + "\n\nYOUR PREVIOUS ANSWER WAS REJECTED for this "
                f"concrete reason: {reason}\nProduce a corrected answer "
                "that fixes exactly that problem.")

    def _cooldown_wait(self) -> Optional[float]:
        """Seconds to sleep until the soonest provider recovers, or None
        when the attempt's total wait budget is spent. Uses the shared
        tracker's own cooldown clocks rather than a blind fixed delay."""
        if self._exhaustion_waited >= self.max_exhaustion_wait_total:
            return None
        if self.exhaustion_wait == 0:  # test/disabled mode: never sleep,
            self._exhaustion_waited += 60.0  # but still bound the loop
            return 0.0
        wait = self.exhaustion_wait
        try:
            from utils.quota_tracker import quota_tracker
            retry_ins = []
            for state in quota_tracker.get_status_report().values():
                raw = str(state.get("retry_in", "0")).rstrip("s")
                try:
                    retry_ins.append(float(raw))
                except ValueError:
                    continue
            pending = [r for r in retry_ins if r > 0]
            if pending:
                wait = min(pending) + 15.0
        except Exception:
            pass
        wait = max(30.0, min(wait,
                             self.max_exhaustion_wait_total
                             - self._exhaustion_waited))
        self._exhaustion_waited += wait
        return wait

    def seed_context(self, files: list, functions: list) -> None:
        """Rebuild code context from a previous session's localization —
        the agent's own memory, so a resumed attempt doesn't re-spend
        LLM budget re-deriving what it already worked out."""
        files = [f for f in files if (self.pack.repo_root / f).exists()]
        slices = [context_pack.file_slice(self.pack.repo_root, f, functions)
                  for f in files]
        self._code_context = "\n\n".join(slices)
        self._located_functions = list(functions)
        self._known_symbols = set(functions) | {
            name for f in files
            for name in re.findall(r"def (\w+)", (self.pack.repo_root / f)
                                   .read_text())}

    # ── L: localization ──────────────────────────────────────────────────

    def localize(self) -> dict:
        """Narrow from the manifest to the files/functions worth reading."""
        candidates = ", ".join(self.pack.candidate_files) or "(none)"
        prompt = (
            f"{_PREAMBLE}\n"
            "Your job in THIS step is fault localization only — deciding "
            "which code to read. No diagnosis yet, no fix.\n\n"
            f"{self.pack.evidence_text()}\n"
            "The trace's route was handled by these modules (from the "
            f"platform's architecture): {candidates}\n\n"
            "Full manifest of in-scope product code:\n"
            f"{self.pack.manifest}\n\n"
            "Name the files most likely to contain the code responsible "
            "for this behavior, and the specific functions worth reading "
            "in full. Answer in exactly this format:\n"
            "FILES: <up to 3 comma-separated repo-relative paths>\n"
            "FUNCTIONS: <up to 6 comma-separated function names>\n")

        def _validate(resp: str) -> tuple[bool, str]:
            files = _parse_list(resp, "FILES")
            if not files:
                return False, "no FILES: line found"
            missing = [f for f in files
                       if not (self.pack.repo_root / f).exists()]
            if missing:
                return False, (f"these files do not exist: {missing}; pick "
                               "paths from the manifest verbatim")
            return True, ""

        resp = self._invoke("localize", prompt, _validate)
        files = _parse_list(resp, "FILES")[:3]
        functions = _parse_list(resp, "FUNCTIONS")[:6]
        slices = [context_pack.file_slice(self.pack.repo_root, f, functions)
                  for f in files]
        self._code_context = "\n\n".join(slices)
        self._located_functions = functions
        self._known_symbols = set(functions) | {
            name for f in files
            for name in re.findall(r"def (\w+)", (self.pack.repo_root / f)
                                   .read_text())}
        return {"files": files, "functions": functions}

    # ── P1: understand ───────────────────────────────────────────────────

    def understand(self) -> str:
        prompt = (
            f"{_PREAMBLE}\n"
            "Your job in THIS step is comprehension only — no fix, no plan, "
            "no code.\n\n"
            f"{self.pack.evidence_text()}\n"
            "Relevant source code:\n\n"
            f"{self._code_context}\n\n"
            "Explain, step by step, what the system actually did when it "
            "produced this behavior: which function received the question, "
            "which decisions routed it where, and at which exact point the "
            "behavior stopped being what an honest data-analyst product "
            "should do. Cite the real function names from the code above. "
            "Finish with one paragraph starting exactly with 'MECHANISM:' "
            "that summarizes the causal chain in plain language.\n")

        def _validate(resp: str) -> tuple[bool, str]:
            if "MECHANISM:" not in resp:
                return False, "missing the required 'MECHANISM:' paragraph"
            if len(resp) < 300:
                return False, "explanation too shallow — walk the actual code path"
            if not any(s in resp for s in self._known_symbols):
                return False, ("cites no function that actually exists in "
                               "the code shown — name the real functions")
            return True, ""

        return self._invoke("understand", prompt, _validate)

    # ── P2: hypothesis + framed critique ─────────────────────────────────

    def hypothesize(self, understanding: str) -> str:
        prompt = (
            f"{_PREAMBLE}\n"
            "Your job in THIS step: a root-cause hypothesis. Not code, not "
            "a plan.\n\n"
            f"{self.pack.evidence_text()}\n"
            f"Relevant source code:\n\n{self._code_context}\n\n"
            f"An earlier mechanism analysis concluded:\n{understanding}\n\n"
            "Answer with ONLY the three sections below, in this order, "
            "nothing before them and nothing after. Do not think out loud "
            "first — reasoning models that narrate run out of output space "
            "before reaching the answer. Keep the whole reply under 250 "
            "words.\n"
            "ROOT_CAUSE: <one or two sentences naming the missing or "
            "incorrect logic>\n"
            "LOCATION: <file path and function where a fix belongs — the "
            "narrowest place that fixes every question of this shape, not "
            "only this one question>\n"
            "EXPECTED: <what the product should honestly do instead>\n")

        def _validate(resp: str) -> tuple[bool, str]:
            for key in ("ROOT_CAUSE:", "LOCATION:", "EXPECTED:"):
                if key not in resp:
                    return False, f"missing required section {key}"
            return True, ""

        hypothesis = self._invoke("hypothesize", prompt, _validate)

        critique_prompt = (
            "You are reviewing a colleague's root-cause analysis of a "
            "product defect before it goes to implementation planning. Be "
            "skeptical and concrete — your judgment is checked against the "
            "evidence, not against politeness.\n\n"
            f"{self.pack.evidence_text()}\n"
            f"Relevant source code:\n\n{self._code_context}\n\n"
            f"The colleague's analysis:\n{hypothesis}\n\n"
            "Check three things: (1) does the claimed root cause match the "
            "trace evidence, step by step? (2) is LOCATION the narrowest "
            "place that fixes the whole class of failure? (3) would the "
            "EXPECTED behavior break any legitimate behavior visible in "
            "the code? Reply with either 'VERDICT: AGREE' plus one sentence "
            "of why, or 'VERDICT: REVISE' followed by corrected "
            "ROOT_CAUSE:/LOCATION:/EXPECTED: sections in the same format. "
            "Output only that — no preamble, no narrated reasoning, under "
            "250 words total.\n")

        def _validate_critique(resp: str) -> tuple[bool, str]:
            if "VERDICT:" not in resp:
                return False, "missing 'VERDICT:' line"
            if "REVISE" in resp.split("VERDICT:", 1)[1][:20]:
                for key in ("ROOT_CAUSE:", "LOCATION:", "EXPECTED:"):
                    if key not in resp:
                        return False, (f"a REVISE verdict must include the "
                                       f"corrected {key} section")
            return True, ""

        critique = self._invoke("critique", critique_prompt,
                                _validate_critique)
        if "REVISE" in critique.split("VERDICT:", 1)[1][:20]:
            return critique.split("VERDICT:", 1)[1]
        return hypothesis

    # ── P3: plan ─────────────────────────────────────────────────────────

    def plan(self, hypothesis: str, feedback: str = "") -> Plan:
        prompt = (
            f"{_PREAMBLE}\n"
            "Your job in THIS step: write the implementation plan. No code "
            "yet.\n\n"
            f"{self.pack.evidence_text()}\n"
            f"Relevant source code:\n\n{self._code_context}\n\n"
            f"The confirmed root-cause analysis:\n{hypothesis}\n\n"
            + (f"A reviewer REJECTED your previous plan for this concrete "
               f"reason — the new plan must fix it:\n{feedback}\n\n"
               if feedback else "")
            + "Hard constraints on the plan:\n"
            f"- Touch at most {MAX_PLAN_FILES} files, all inside "
            "nexus_platform/, agents/, or tests/platform_mode/.\n"
            "- Include exactly one NEW regression test file under "
            "tests/platform_mode/ that encodes the failing case. It must "
            "FAIL on today's code and PASS after the fix, and must not "
            "depend on any live LLM call. Make it genuine, not a helper "
            "unit-test that a reviewer will (rightly) call inadequate:\n"
            "    * It must exercise the ACTUAL defective FUNCTION(S) with "
            "realistic inputs and assert the honest outcome — NOT a new "
            "helper in isolation, but ALSO not necessarily the whole "
            "request pipeline. Testing the real function where the bug "
            "lives (e.g. calling the actual `refusal_message` / "
            "`_is_access_denied` with a constructed denied-table result) "
            "IS a valid end-to-end-of-the-defect test and is PREFERRED over "
            "driving the top-level entry point when that would require "
            "monkeypatching deep internals. Stub only a live LLM/SQL call "
            "if one is unavoidable; never stub the code under test.\n"
            "    * Include a CLOSE VARIANT (a different input of the same "
            "shape) so the fix is proven to address the class, not one "
            "literal string, AND a BOUNDARY case (e.g. the empty/None/"
            "already-correct input) proving the fix doesn't break the "
            "healthy path.\n"
            "- Prefer a narrow, localized check that matches how this "
            "codebase already handles similar situations in the code shown "
            "above — the fix should look like it was written by the same "
            "author.\n"
            "- Smallest change that fixes the CLASS of failure, not just "
            "this literal question.\n"
            "- Tenancy rule: this product serves several companies with one "
            "shared analyst. If the defect is specific to ONE company's "
            "vocabulary or data (not a flaw in shared logic), the code "
            "change belongs in that company's override pack "
            "(nexus_platform/company_overrides/<company>.py — see its "
            "hooks), never in a shared module. A genuine shared-logic flaw "
            "still belongs in the shared module.\n\n"
            "Answer with ONLY this format — no preamble, no narrated "
            "reasoning, under 300 words total:\n"
            "PLAN:\n"
            "1. FILE: <path> — <one small, checkable step>\n"
            "2. FILE: <path> — <next step>\n"
            "(as few steps as possible, at most "
            f"{MAX_PLAN_STEPS})\n"
            "FILES_TOUCHED: <comma-separated paths, no others may change>\n"
            "TEST_FILE: <the new test file's path>\n")

        def _validate(resp: str) -> tuple[bool, str]:
            parsed = _parse_plan(resp)
            if parsed is None:
                return False, ("could not parse PLAN/FILES_TOUCHED/"
                               "TEST_FILE sections — follow the format "
                               "exactly")
            plan_obj, problem = parsed
            if problem:
                return False, problem
            if (self.pack.repo_root / plan_obj.test_file).exists():
                return False, (f"TEST_FILE {plan_obj.test_file} already "
                               "exists — the regression test must be a new "
                               "file; pick an unused name")
            return True, ""

        resp = self._invoke("plan", prompt, _validate)
        plan_obj, _ = _parse_plan(resp)
        return plan_obj

    # ── P3.5: self-confirm the plan before any code changes ─────────────

    def confirm_plan(self, plan: Plan, hypothesis: str) -> tuple[bool, str]:
        """The pipeline's own gate on its own plan — a self-check, not a
        human pause. Returns (confirmed, notes): notes are either the
        reviewer's EVAL_NOTES (what new evals the change needs) when
        confirmed, or the concrete reason to re-plan when not."""
        prompt = (
            "You are reviewing a colleague's implementation plan for a "
            "product-defect fix BEFORE any code is written. Be skeptical "
            "and concrete.\n\n"
            f"{self.pack.evidence_text()}\n"
            f"The root-cause analysis:\n{hypothesis}\n\n"
            f"The plan:\n{plan.raw}\n\n"
            "Check four things: (1) the plan's regression test exercises "
            "the real DEFECTIVE FUNCTION with realistic inputs and would "
            "fail on today's code — a test that calls the actual buggy "
            "function (e.g. refusal_message/_is_access_denied) with a "
            "constructed input IS adequate and preferred; do NOT demand it "
            "drive the whole request pipeline / monkeypatch deep internals "
            "(that makes the test unwritable), only reject a test that "
            "checks a NEW helper in isolation or never encodes the failure; "
            "(2) the code change is the narrowest one that fixes the whole "
            "CLASS of failure, not just these literal questions; (3) nothing "
            "in the plan touches code unrelated to the failure; (4) decide "
            "what NEW evaluation coverage this change needs beyond the "
            "regression test (edge phrasings, adjacent behaviors that must "
            "NOT change) — the plan's test should encode those too.\n\n"
            "Reply in EXACTLY one of these two formats, nothing else:\n"
            "VERDICT: CONFIRMED\nEVAL_NOTES: <one short paragraph: the new "
            "eval coverage this change needs>\n"
            "or\n"
            "VERDICT: REVISE\nREASON: <the one concrete problem the new "
            "plan must fix>\n")

        def _validate(resp: str) -> tuple[bool, str]:
            if "VERDICT:" not in resp:
                return False, "missing 'VERDICT:' line"
            tail = resp.split("VERDICT:", 1)[1]
            if "CONFIRMED" in tail[:20] and "EVAL_NOTES:" not in resp:
                return False, "a CONFIRMED verdict must include EVAL_NOTES:"
            if "REVISE" in tail[:20] and "REASON:" not in resp:
                return False, "a REVISE verdict must include REASON:"
            return True, ""

        resp = self._invoke("confirm_plan", prompt, _validate)
        tail = resp.split("VERDICT:", 1)[1]
        if "CONFIRMED" in tail[:20]:
            return True, resp.split("EVAL_NOTES:", 1)[1].strip()
        return False, resp.split("REASON:", 1)[1].strip()

    # ── P4: implement, one step at a time ────────────────────────────────

    def implement_step(self, plan: Plan, step: dict,
                       feedback: str = "") -> str:
        path = self.pack.repo_root / step["file"]
        slice_note = ""
        new_file = not path.exists()
        if new_file:
            current = ("THIS FILE DOES NOT EXIST YET. Create it the EASY way: "
                       "emit exactly one line 'FILE: " + step["file"] + "' "
                       "followed immediately by a single fenced code block "
                       "(```python … ```) containing the COMPLETE file "
                       "content. Do NOT use SEARCH/REPLACE for a new file. "
                       "Output nothing else — no prose before or after.")
        else:
            lines = path.read_text().splitlines()
            if (len(lines) > IMPLEMENT_SLICE_THRESHOLD_LINES
                    and not step["file"].startswith("tests/")):
                # Large file: show only the located/mentioned functions so
                # the prompt stays inside every provider's request ceiling
                # (observed live: whole-file prompts got 413'd by Groq and
                # 504'd by Gemini). SEARCH text still matches — the slice
                # is verbatim file content.
                wanted = list(self._located_functions)
                wanted += re.findall(r"(\w+)\s*\(", step["text"])
                current = context_pack.file_slice(
                    self.pack.repo_root, step["file"],
                    [w for w in wanted if w])
                slice_note = (
                    "\nNOTE: only the relevant parts of the file are shown "
                    "(separated by '# …'). Your SEARCH lines must be copied "
                    "verbatim from the parts shown.\n")
            else:
                current = "\n".join(lines)
        style_example = ""
        if step["file"].startswith("tests/"):
            # The test writer must see every product file the plan touches
            # (not only the originally-localized ones) — the natural
            # deterministic test seam often lives in a plan target the
            # localization pass skipped.
            # Show the test writer the FULL source of every product file the
            # plan touches (and the localized ones) — not slices. The test
            # writer kept REPLANning because a needed entry point / call site
            # wasn't in a narrow slice; the CLI brain handles large prompts
            # fine, so give it whole files (capped) and end the REPLAN loop.
            want_files = list(dict.fromkeys(
                [s["file"] for s in plan.code_steps]
                + [f for f in getattr(self.pack, "candidate_files", [])]))
            parts = []
            for extra in want_files:
                fp = self.pack.repo_root / extra
                if fp.exists():
                    parts.append(f"### {extra} (full source)\n{fp.read_text()}")
            test_context = "\n\n".join(parts) or self._code_context
            style_example = (
                "\nTHE OBSERVED FAILURE THIS TEST MUST ENCODE — the test "
                "must exercise the exact failing input below (the question "
                "verbatim) through the product's behavior and assert the "
                "honest expected outcome, not merely check that a helper "
                "function exists:\n"
                + self.pack.evidence_text()[:3500] + "\n"
                "\nHard requirements for the test: it must be fully "
                "deterministic — no live LLM call, no network. Prefer "
                "exercising a deterministic entry point (e.g. the "
                "routing/clarification decision for the failing question); "
                "monkeypatch or stub anything that would call an LLM, the "
                "way the style example below does.\n"
                "\nAn existing test file from this codebase, "
                "as a style pattern:\n"
                + context_pack.test_style_example(
                    self.pack.repo_root) + "\n"
                "\nThe product code under test (read it before "
                "writing the test — use only APIs that "
                "actually exist in it):\n"
                + test_context[:22000] + "\n")
        # For a CODE step, show the regression test that was already written
        # and now FAILS — the code edit must make exactly that test pass, so
        # the model needs to see what behavior the test asserts (keeps the
        # code and test coherent; a mismatched pair fails repro_after).
        test_under_fix = ""
        if not step["file"].startswith("tests/"):
            test_path = self.pack.repo_root / plan.test_file
            if test_path.exists():
                test_under_fix = (
                    "\nThe regression test your change must make PASS (it "
                    f"fails today — read what it asserts):\n```python\n"
                    + test_path.read_text()[:6000] + "\n```\n")
        surgical_note = ""
        if not step["file"].startswith("tests/"):
            surgical_note = (
                "\nSURGICAL EDIT RULE (avoids breaking other tests): make the "
                "SMALLEST possible change — add a new branch/guard for the "
                "defect's specific case only. Do NOT alter the wording, "
                "return value, or logic of any EXISTING code path (e.g. the "
                "current denial/refusal message for legitimate cases must "
                "stay byte-for-byte identical). Other tests depend on today's "
                "behavior for the non-defect cases; change only the defect "
                "case.\n")
        prompt = (
            f"{_PREAMBLE}\n"
            "You are implementing ONE step of an approved plan. Change "
            "only what this step describes — if the step seems to require "
            "touching a file the plan did not name, emit the single line "
            "REPLAN: <why> instead of any edit.\n\n"
            f"The approved plan:\n{plan.raw}\n\n"
            f"THIS step: FILE: {step['file']} — {step['text']}\n\n"
            f"{test_under_fix}{surgical_note}"
            f"Current content of {step['file']}:\n```\n{current}\n```\n"
            f"{slice_note}{style_example}\n"
            f"{_EDIT_FORMAT}"
            + (f"\nFEEDBACK ON YOUR PREVIOUS ATTEMPT (fix exactly this):\n"
               f"{feedback}\n" if feedback else ""))

        def _validate(resp: str) -> tuple[bool, str]:
            if resp.strip().startswith("REPLAN:"):
                return True, ""
            from nexus_platform.repair.apply import parse_blocks
            blocks = parse_blocks(resp)
            if not blocks:
                return False, ("no valid SEARCH/REPLACE block found — emit "
                               "the exact block format specified")
            stray = [b.path for b in blocks
                     if b.path.strip().lstrip("./") != step["file"]]
            if stray:
                return False, (f"this step may only edit {step['file']}, "
                               f"but blocks target {stray}")
            return True, ""

        # The new-test-file write is the highest-variance step (a fresh file
        # from scratch); give it more format-retry chances so a couple of
        # malformed CLI rolls don't sink the whole attempt.
        retries = 3 if new_file else 2
        return self._invoke("implement", prompt, _validate, retries=retries)

    # ── P5: self-review of the final diff ────────────────────────────────

    def self_review(self, plan: Plan, diff: str) -> str:
        prompt = (
            "You are reviewing a colleague's completed change before it "
            "goes to the test gate. The approved plan and the actual diff "
            "are below.\n\n"
            f"The plan:\n{plan.raw}\n\n"
            f"The diff:\n```diff\n{diff}\n```\n\n"
            "Check: (1) the diff implements every plan step and nothing "
            "else; (2) no file outside FILES_TOUCHED changed; (3) the new "
            "code matches the codebase's style visible in the diff "
            "context; (4) no debug prints, dead code, or TODOs left "
            "behind. Reply 'VERDICT: OK' plus one sentence, or "
            "'VERDICT: REVISE' followed by SEARCH/REPLACE blocks (in the "
            "standard format, FILE: line included) that correct the "
            "specific problem.\n")

        def _validate(resp: str) -> tuple[bool, str]:
            if "VERDICT:" not in resp:
                return False, "missing 'VERDICT:' line"
            return True, ""

        return self._invoke("self_review", prompt, _validate)


# ── parsing helpers ──────────────────────────────────────────────────────

def _parse_list(text: str, key: str) -> list:
    m = re.search(rf"{key}:\s*(.+)", text)
    if not m:
        return []
    return [p.strip().strip("`").lstrip("./") for p in m.group(1).split(",")
            if p.strip()]


_STEP_RE = re.compile(r"^\s*\d+\.\s*FILE:\s*(?P<file>[^\s—-]+)\s*[—-]+\s*"
                      r"(?P<text>.+)$", re.MULTILINE)


def _parse_plan(text: str):
    """Returns (Plan, problem) or None when structurally unparseable.
    `problem` is a human-readable guardrail violation, empty when clean."""
    steps = [{"file": m.group("file").strip().strip("`").lstrip("./"),
              "text": m.group("text").strip()}
             for m in _STEP_RE.finditer(text)]
    files_touched = _parse_list(text, "FILES_TOUCHED")
    test_files = _parse_list(text, "TEST_FILE")
    if not steps or not files_touched or not test_files:
        return None
    plan = Plan(steps=steps, files_touched=files_touched,
                test_file=test_files[0], raw=text.strip())

    problems = []
    if len(steps) > MAX_PLAN_STEPS:
        problems.append(f"too many steps ({len(steps)} > {MAX_PLAN_STEPS})")
    if len(files_touched) > MAX_PLAN_FILES:
        problems.append(f"too many files ({len(files_touched)} > "
                        f"{MAX_PLAN_FILES})")
    out_of_scope = [f for f in files_touched if not context_pack.in_scope(f)]
    if out_of_scope:
        problems.append(f"files outside the scope fence: {out_of_scope}")
    if not (plan.test_file.startswith("tests/platform_mode/")
            and plan.test_file.endswith(".py")):
        problems.append("TEST_FILE must be a .py file under "
                        "tests/platform_mode/")
    stray_steps = [s["file"] for s in steps
                   if s["file"] not in files_touched]
    if stray_steps:
        problems.append(f"plan steps name files missing from "
                        f"FILES_TOUCHED: {stray_steps}")
    if plan.test_file not in files_touched:
        problems.append("TEST_FILE must itself appear in FILES_TOUCHED")
    if not plan.test_steps:
        problems.append("no plan step creates the regression test file")
    if not plan.code_steps:
        problems.append("no plan step changes product code — a test alone "
                        "does not fix anything")
    return plan, "; ".join(problems)
