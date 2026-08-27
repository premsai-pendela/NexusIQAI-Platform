"""CLI reasoning brain for the repair agent — invokes Claude Code headlessly.

CONTEXT.md revised §2e (2026-07-16): weak free-tier models cannot do complex
program repair, so the repair agent's HARD sub-tasks (understand, hypothesize,
critique, plan, confirm_plan, implement, self_review) route here — a strong
model reached by shelling out to ``claude -p``, the same external-CLI-brain
pattern ``sim_employees/`` already uses for question generation. The cheap
sub-task (localization) stays on the product's free-tier gateway; see
``proposer._default_llm`` for the split.

Per-sub-task tiering INSIDE the CLI is **automatic**, not a hardcoded
stage→model map (that map let a cheap model rubber-stamp a review). Two rules
choose the tier per call from an ordered ladder (weak→strong):

  1. **A reviewer is never weaker than the author it reviews.** The review /
     judgement stages (critique, confirm_plan, self_review) always run on the
     ladder's TOP tier. A weak reviewer that "AGREE"s a bad fix is worse than
     no review — no downstream validator catches a rubber-stamp, so these can
     never start cheap.
  2. **Generation stages start at a complexity-appropriate tier and escalate
     on failure.** Inherently-hard stages (implement, plan) and any call whose
     prompt is large (lots of code context) start strong; the lighter
     generation stages (understand, hypothesize, predict) start cheap and
     escalate one tier each time the stage validator rejects the answer (the
     proposer threads the retry ``attempt`` in). So a stage is never *silently*
     stuck on a model too weak to pass its own check.

Everything is env-configurable, so a run can trade cost for strength without
code changes:

  NEXUSIQ_REPAIR_CLI_TIERS   ordered ladder weak→strong (default "haiku,sonnet")
  NEXUSIQ_REPAIR_CLI_MODEL        strong model   (back-compat; overrides top tier)
  NEXUSIQ_REPAIR_CLI_CHEAP_MODEL  lighter model  (back-compat; overrides bottom tier)
  NEXUSIQ_REPAIR_CLI_TIMEOUT      per-call seconds (default 420)
  NEXUSIQ_REPAIR_CLI_BIN          claude binary  (default "claude" on PATH)
  NEXUSIQ_REPAIR_CLI_BIG_PROMPT   chars above which a generation stage starts
                                  strong (default 14000)

The turn runs with **all tools disabled and a single turn** — the prompt
already carries every slice of code/trace context, and the model only emits
text (analysis or SEARCH/REPLACE blocks). It never reads or edits the repo
itself, so this stays a drop-in brain swap for the gateway, not a second
autonomous agent loose in the worktree.

The return dict mirrors ``utils.llm_gateway.invoke_with_fallback``'s contract
so the proposer's existing validate → feedback → retry machinery works
unchanged. It never raises: any failure comes back as ``success=False``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable, Optional

# Review / judgement stages: their OUTPUT is the guardrail, and nothing
# downstream catches a rubber-stamp — so they always run on the top tier
# (rule 1). A reviewer must be at least as strong as the author it reviews.
_REVIEW_STAGES = {"critique", "confirm_plan", "self_review"}

# Generation stages that are inherently hard enough to start on the strong
# tier rather than pay a cheap-model round that will almost always be
# escalated (rule 2). `plan` designs the whole change and is worth the strong
# model up front. `implement` is deliberately NOT here: applying a
# SEARCH/REPLACE from an already-confirmed, detailed plan is mechanical, so
# it starts cheap and escalates — and it is never *silently* weak because
# three concrete signals force a stronger retry: the apply guardrails
# (verbatim SEARCH match, syntax check, scope fence), the "repro must flip
# fail→pass" eval gate, and the "zero new suite failures" gate. A large
# implement prompt still starts strong via the BIG_PROMPT heuristic.
_HARD_START_STAGES = {"plan"}

_DENY_TOOLS = ["Bash", "Read", "Edit", "Write", "Grep", "Glob",
               "WebFetch", "WebSearch", "Task", "NotebookEdit"]


def _stage_of(task: str) -> str:
    return (task or "").split(".")[-1]


def _ladder() -> list[str]:
    """Ordered model tiers weak→strong. Back-compat: if the old
    single-model env vars are set they pin the bottom/top of a 2-tier
    ladder so existing configs keep working."""
    raw = os.environ.get("NEXUSIQ_REPAIR_CLI_TIERS")
    if raw:
        tiers = [t.strip() for t in raw.split(",") if t.strip()]
    else:
        cheap = os.environ.get("NEXUSIQ_REPAIR_CLI_CHEAP_MODEL", "haiku")
        strong = os.environ.get("NEXUSIQ_REPAIR_CLI_MODEL", "sonnet")
        tiers = [cheap, strong]
    return tiers or ["sonnet"]


def model_for(task: str, attempt: int = 0, prompt: str = "") -> str:
    """Automatically choose the model tier for one repair sub-task call.

    Rule 1 — review stages (critique/confirm_plan/self_review) always get the
    ladder's top tier (a reviewer is never weaker than the author).
    Rule 2 — generation stages start at a complexity-appropriate tier
    (inherently-hard stages or large prompts start strong) and escalate one
    tier per prior validator-rejected ``attempt`` (0-based)."""
    ladder = _ladder()
    top = len(ladder) - 1
    stage = _stage_of(task)

    if stage in _REVIEW_STAGES:
        return ladder[top]

    base = 0
    if stage in _HARD_START_STAGES:
        base = top
    else:
        big = int(os.environ.get("NEXUSIQ_REPAIR_CLI_BIG_PROMPT", "14000"))
        if len(prompt or "") > big:
            base = top
    idx = min(base + max(0, int(attempt)), top)
    return ladder[idx]


def _claude_bin() -> Optional[str]:
    name = os.environ.get("NEXUSIQ_REPAIR_CLI_BIN", "claude")
    return shutil.which(name) or (name if os.path.exists(name) else None)


def _fail(model: str, status: str, response: str = "",
          invalid: Optional[str] = None) -> dict:
    # brain="cli" tells the proposer this failure is NOT free-tier
    # starvation — the Claude CLI has no quota cooldown, so a timeout/error
    # here must be a fast bounded retry, never a multi-minute cooldown wait.
    tried = {"model": model, "status": status, "brain": "cli"}
    if invalid is not None:
        tried["invalid_content"] = invalid
    return {"response": response, "success": False,
            "model_used": model, "models_tried": [tried]}


def cli_llm(prompt: str, task: str,
            validator: Optional[Callable[[str], bool]] = None,
            reasoning: bool = True, attempt: int = 0) -> dict:
    """Run one repair-reasoning turn on Claude Code (headless ``claude -p``).

    Signature matches ``proposer._default_llm`` so it is a drop-in tier.
    ``attempt`` (0-based retry index, threaded in by the proposer) drives the
    automatic tier escalation in ``model_for``. Returns
    ``{response, success, model_used, models_tried}`` and never raises — a
    hard failure surfaces as ``success=False`` so the proposer's bounded
    retry/feedback loop handles it rather than the stage crashing.
    """
    model = model_for(task, attempt=attempt, prompt=prompt)
    binary = _claude_bin()
    if not binary:
        return _fail(model, "ERROR: claude CLI not found on PATH")

    timeout = float(os.environ.get("NEXUSIQ_REPAIR_CLI_TIMEOUT", "420"))
    cmd = [binary, "-p", "--model", model, "--output-format", "text",
           "--max-turns", "1", "--disallowedTools", *_DENY_TOOLS]
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout,
            env={**os.environ, "CLAUDE_DISABLE_AUTOUPDATER": "1"})
    except subprocess.TimeoutExpired:
        return _fail(model, f"ERROR: timed out after {timeout:.0f}s")
    except Exception as exc:  # never propagate into the proposer
        return _fail(model, f"ERROR: {exc}")

    text = (proc.stdout or "").strip()
    if proc.returncode != 0 or not text:
        err = (proc.stderr or "").strip()[:300] or "empty output"
        return _fail(model, f"ERROR: rc={proc.returncode}: {err}", response=text)
    if validator is not None and not validator(text):
        # Well-formed run whose content flunked the stage validator: hand the
        # rejected text back as invalid_content so the proposer derives the
        # concrete reason and feeds it into the corrected retry prompt.
        return _fail(model, "INVALID", response=text, invalid=text)
    return {"response": text, "success": True, "model_used": f"cli:{model}",
            "models_tried": [{"model": model, "status": "OK"}]}
