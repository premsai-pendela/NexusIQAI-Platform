"""The repair pipeline's conductor: finding → worktree → staged fix → gate.

This is stage-6 glue plus the deterministic control flow around the
proposer's LLM stages. Sequencing matters and is enforced here, not asked
of the model:

1. Worktree branch off master; BEFORE suite baseline captured on the
   untouched tree.
2. The regression test is written FIRST and must FAIL on the untouched
   tree (that failing run is the eval gate's repro_before). A test that
   passes pre-fix is rejected and regenerated with that exact feedback.
3. Code steps apply one at a time (syntax-checked each).
4. The repro must now PASS; the full suite must show zero new failures
   (eval_gate.gate). Pytest output is fed back verbatim on failure — the
   external correction signal weak models can actually use.
5. On a clean gate: local commit only. Publishing happens exactly once, at
   the true end of the mission, via repair/pr.py (see CONTEXT.md §2g).

No merge path exists anywhere in this package — see
tests/platform_mode/test_repair_no_merge_path.py.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from nexus_platform import store
from nexus_platform.repair import apply as apply_mod
from nexus_platform.repair import context_pack, eval_gate, pr
from nexus_platform.repair.proposer import (Plan, Proposer, StageFailed,
                                            _parse_plan)

SUITE_ARGS = ["tests/platform_mode/"]
MAX_TEST_REGENERATIONS = 2
MAX_FIX_ROUNDS = 2


@dataclass
class RepairOutcome:
    finding_id: str
    ok: bool
    reason: str
    branch: str = ""
    worktree: str = ""
    commit: str = ""
    files_changed: list = field(default_factory=list)
    session_log: str = ""
    evidence_path: str = ""
    plan: Optional[Plan] = None
    llm_calls: int = 0
    models_used: list = field(default_factory=list)


_WRONG_REASON_RE = re.compile(
    r"ImportError|ModuleNotFoundError|fixture '\w+' not found|"
    r"collected 0 items|errors? during collection|"
    r"(TypeError|AttributeError)(?![\s\S]*AssertionError)")


def _fails_for_wrong_reason(pytest_tail: str) -> bool:
    """Heuristic: the failure is a bug in the test (bad import, invented
    API, broken fixture), not the product failing an honest assertion.
    Findings in this product manifest as wrong *answers*, so a genuine
    repro fails on an assertion; crash-shaped failures get regenerated
    (and soft-accepted only after retries are exhausted)."""
    return bool(_WRONG_REASON_RE.search(pytest_tail or ""))


def _load_resume_seed(resume_session, finding_id: str) -> Optional[dict]:
    """Recover the reasoning stages from a previous session log — either
    its top-level keys or, for attempts that died mid-run, reconstructed
    from the raw stage records. Returns None unless every seeded stage is
    present and belongs to the same finding."""
    if not resume_session:
        return None
    data = json.loads(Path(resume_session).read_text())
    if data.get("finding") != finding_id:
        return None
    from nexus_platform.repair.proposer import _parse_list

    def _last_valid(stage: str) -> Optional[str]:
        hits = [e["response"] for e in data.get("stages", [])
                if e["stage"] == stage and e.get("valid")]
        return hits[-1] if hits else None

    located = data.get("located")
    if not located:
        loc_resp = _last_valid("localize")
        if loc_resp:
            located = {"files": _parse_list(loc_resp, "FILES")[:3],
                       "functions": _parse_list(loc_resp, "FUNCTIONS")[:6]}
    understanding = data.get("understanding") or _last_valid("understand")
    hypothesis = data.get("hypothesis")
    if not hypothesis:
        hypothesis = _last_valid("hypothesize")
        critique = _last_valid("critique")
        if critique and "VERDICT:" in critique and \
                "REVISE" in critique.split("VERDICT:", 1)[1][:20]:
            hypothesis = critique.split("VERDICT:", 1)[1]
    plan = data.get("plan") or _last_valid("plan")
    if all([located, located.get("files") if located else None,
            understanding, hypothesis, plan]):
        return {"located": located, "understanding": understanding,
                "hypothesis": hypothesis, "plan": plan}
    return None


def _dirty_paths(worktree: Path) -> list[str]:
    """Modified + untracked paths from `git status -z` — NUL-delimited so
    no line-oriented stripping can mangle a leading-space status prefix
    (that exact bug silently dropped a plan file from a commit once)."""
    proc = subprocess.run(["git", "status", "--porcelain", "-z"],
                          cwd=str(worktree), capture_output=True, text=True,
                          timeout=60)
    paths = []
    for entry in proc.stdout.split("\0"):
        if len(entry) > 3:
            paths.append(entry[3:])
    return paths


def _pytest_tail(repo_root: Path, args: list[str]) -> str:
    """Re-run a failing pytest target to capture output for feedback. Kept
    separate from eval_gate so its EvalRun stays a clean record."""
    import sys
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", *args],
                          cwd=str(repo_root), capture_output=True, text=True,
                          timeout=1800)
    out = (proc.stdout + proc.stderr)
    return out[-3000:]


def run_repair(company: str, finding_id: str, repo_root: str | Path,
               worktree_dir: Optional[str | Path] = None,
               llm: Optional[Callable] = None,
               keep_worktree_on_failure: bool = True,
               resume_session: Optional[str | Path] = None) -> RepairOutcome:
    """Run the full pipeline for one finding. Returns an outcome either way;
    raises only on infrastructure errors (bad finding id, git failure)."""
    repo_root = Path(repo_root).resolve()
    pack = context_pack.load_evidence(company, finding_id, repo_root)
    fingerprint = pack.finding["fingerprint"][:8]
    branch = f"healthfix/{fingerprint}"
    if worktree_dir is None:
        worktree_dir = repo_root.parent / f"NexusIQAI-healthfix-{fingerprint}"
    worktree_dir = Path(worktree_dir)

    outcome = RepairOutcome(finding_id=finding_id, ok=False, reason="",
                            branch=branch, worktree=str(worktree_dir))

    if not worktree_dir.exists():
        pr.create_fix_worktree(repo_root, branch, worktree_dir, base="master")
    else:
        # A previous attempt may have left edits behind. The pipeline's own
        # attempt worktree resets to its branch's last commit — uncommitted
        # leftovers from a failed attempt must never leak into a new one.
        subprocess.run(["git", "checkout", "--", "."],
                       cwd=str(worktree_dir), capture_output=True)
        subprocess.run(["git", "clean", "-fd", "--", "tests/",
                        "nexus_platform/", "agents/"],
                       cwd=str(worktree_dir), capture_output=True)
    # The proposer reasons about — and edits — the worktree, never the main
    # checkout. Evidence still comes from the main checkout's store.
    pack.repo_root = worktree_dir
    pack.candidate_files = [f for f in pack.candidate_files
                            if (worktree_dir / f).exists()]
    pack.manifest = context_pack.build_manifest(worktree_dir)

    proposer = Proposer(pack=pack, llm=llm)
    log_dir = repo_root / "data" / "repair_sessions"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session_path = log_dir / f"{finding_id}_{stamp}.json"
    outcome.session_log = str(session_path)

    def _save_session(extra: dict) -> None:
        session_path.write_text(json.dumps({
            "finding": finding_id, "company": company, "branch": branch,
            "worktree": str(worktree_dir),
            "llm_calls": proposer.calls_made,
            "stages": proposer.log, **extra}, indent=2, default=str))

    try:
        # ── baseline on the untouched tree ────────────────────────────
        before = eval_gate.run_pytest(SUITE_ARGS, "before", cwd=worktree_dir)

        # ── LLM stages: localize → understand → hypothesize → plan ────
        # A resumed run reloads the pipeline's own prior outputs (its
        # operational memory) so scarce quota goes to the unfinished
        # stages, not to re-deriving finished ones.
        seed = _load_resume_seed(resume_session, finding_id)
        if seed:
            located = seed["located"]
            proposer.seed_context(located.get("files", []),
                                  located.get("functions", []))
            understanding = seed["understanding"]
            hypothesis = seed["hypothesis"]
            plan, problem = _parse_plan(seed["plan"])
            if problem:
                raise StageFailed(f"resumed plan no longer valid: {problem}")
            # A resumed continuation may find its test file already on the
            # branch from a prior round — the test steps then edit it
            # rather than create it.
            proposer.log.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "stage": "resume", "attempt": 0, "model_used": None,
                "prompt": f"(resumed from {resume_session})",
                "response": "", "valid": True,
                "validator_reason": "stages seeded from prior session"})
        else:
            located = proposer.localize()
            understanding = proposer.understand()
            hypothesis = proposer.hypothesize(understanding)
            plan = proposer.plan(hypothesis)
        outcome.plan = plan

        # ── the regression test first; it must fail pre-fix ───────────
        repro_args = [plan.test_file]
        repro_before = None
        feedback = ""
        failing_questions = [t.get("question") for t in pack.traces
                             if t.get("question")]
        for regen_round in range(MAX_TEST_REGENERATIONS + 1):
            # Every round writes the test file fresh (deleting at round
            # START, never at the end — attempt-4 lesson). A stale draft
            # from a previous run/round invites SEARCH/REPLACE fumbling
            # (attempt 8 burned two of three rounds failing to edit the
            # committed helper test); git history keeps every version.
            for step in plan.test_steps:
                target = worktree_dir / step["file"]
                if target.exists():
                    target.unlink()
            for step in plan.test_steps:
                resp = proposer.implement_step(plan, step, feedback=feedback)
                if resp.strip().startswith("REPLAN:"):
                    raise StageFailed(f"model asked to re-plan during test "
                                      f"step: {resp.strip()[:200]}")
                applied = apply_mod.apply_all(worktree_dir, resp,
                                              plan.files_touched)
                if not applied.ok:
                    feedback = applied.reason
                    break
            else:
                test_text = ""
                test_path = worktree_dir / plan.test_file
                if test_path.exists():
                    test_text = test_path.read_text()
                if failing_questions and not any(q in test_text
                                                 for q in failing_questions):
                    # Attempt-7 lesson: a repro that never exercises the
                    # failing input lets a vacuous fix through the gate. A
                    # helper-existence test is not a repro.
                    feedback = (
                        "your regression test never exercises the actual "
                        "failing input from the trace. It must send the "
                        "exact question "
                        f"{failing_questions[0]!r} through the product's "
                        "behavior (routing/orchestration), assert the "
                        "honest expected outcome, and fail on today's "
                        "code because of that assertion.")
                    continue
                run = eval_gate.run_pytest(repro_args, "repro_before",
                                           cwd=worktree_dir)
                if run.exit_code != 0:
                    tail = _pytest_tail(worktree_dir, repro_args)
                    # Only exit code 1 is "tests ran and failed"; 2/4/5
                    # (interrupted / usage error / nothing collected) are
                    # never a valid repro.
                    if run.exit_code == 1 and not _fails_for_wrong_reason(tail):
                        repro_before = run
                        break
                    feedback = (
                        "your regression test fails, but for the WRONG "
                        "reason — it crashes inside the test itself "
                        "(bad import, wrong API usage, missing fixture) "
                        "instead of asserting the product's honest "
                        "expected behavior and failing on that assertion. "
                        "Use only APIs that exist in the code shown to "
                        f"you. Test output:\n{tail}")
                else:
                    feedback = (
                        "your regression test PASSED against the current, "
                        "still-buggy code — it does not encode the observed "
                        "failure. The trace shows the product's actual "
                        "wrong behavior; write the test so it asserts the "
                        "honest expected behavior and therefore fails "
                        "today. Test output:\n"
                        f"{_pytest_tail(worktree_dir, repro_args)}")
        if repro_before is None:
            # No soft-accept: a repro that doesn't encode the behavioral
            # failure is how a vacuous fix passed the gate once. Fail the
            # attempt honestly instead.
            raise StageFailed("could not produce a regression test that "
                              "exercises the failing input and fails on "
                              "the un-fixed tree")

        # ── code steps, one at a time ──────────────────────────────────
        for step in plan.code_steps:
            feedback = ""
            for _ in range(3):
                resp = proposer.implement_step(plan, step, feedback=feedback)
                if resp.strip().startswith("REPLAN:"):
                    raise StageFailed(f"model asked to re-plan: "
                                      f"{resp.strip()[:200]}")
                applied = apply_mod.apply_all(worktree_dir, resp,
                                              plan.files_touched)
                if applied.ok:
                    outcome.files_changed.extend(applied.files_changed)
                    break
                feedback = applied.reason
            else:
                raise StageFailed(f"step could not be applied after "
                                  f"retries: {feedback}")

        # ── the repro must now pass; regressions must be zero ─────────
        repro_after = eval_gate.run_pytest(repro_args, "repro_after",
                                           cwd=worktree_dir)
        rounds = 0
        while repro_after.exit_code != 0 and rounds < MAX_FIX_ROUNDS:
            rounds += 1
            fix_feedback = (
                "the fix is applied but the regression test still fails. "
                "Failing output:\n"
                f"{_pytest_tail(worktree_dir, repro_args)}")
            for step in plan.code_steps:
                resp = proposer.implement_step(plan, step,
                                               feedback=fix_feedback)
                if resp.strip().startswith("REPLAN:"):
                    raise StageFailed(f"model asked to re-plan mid-repair: "
                                      f"{resp.strip()[:200]}")
                applied = apply_mod.apply_all(worktree_dir, resp,
                                              plan.files_touched)
                if applied.ok:
                    outcome.files_changed.extend(applied.files_changed)
            repro_after = eval_gate.run_pytest(repro_args, "repro_after",
                                               cwd=worktree_dir)

        after = eval_gate.run_pytest(SUITE_ARGS, "after", cwd=worktree_dir)
        passed, reason = eval_gate.gate(before, after, repro_before,
                                        repro_after)

        # ── advisory self-review, one revision round, then re-gate ─────
        if passed:
            diff = pr._git(["diff"], worktree_dir)
            review = proposer.self_review(plan, diff[:20000])
            if "REVISE" in review.split("VERDICT:", 1)[1][:20]:
                applied = apply_mod.apply_all(worktree_dir, review,
                                              plan.files_touched)
                if applied.ok:
                    repro_after = eval_gate.run_pytest(
                        repro_args, "repro_after", cwd=worktree_dir)
                    after = eval_gate.run_pytest(SUITE_ARGS, "after",
                                                 cwd=worktree_dir)
                    passed, reason = eval_gate.gate(before, after,
                                                    repro_before, repro_after)

        evidence_path = worktree_dir / "eval_evidence.json"
        eval_gate.save_evidence(evidence_path,
                                [before, repro_before, repro_after, after],
                                (passed, reason))
        outcome.evidence_path = str(evidence_path)
        outcome.ok = passed
        outcome.reason = reason
        outcome.llm_calls = proposer.calls_made
        outcome.models_used = sorted({e.get("model_used") for e in
                                      proposer.log if e.get("model_used")})

        if passed:
            body = _pr_body(pack, plan, hypothesis, understanding,
                            before, after, repro_before, repro_after,
                            outcome)
            (worktree_dir / "pr_body.md").write_text(body)
            # Commit what actually changed on disk, bounded by the plan's
            # allowlist — the authoritative record is the tree, not the
            # per-step bookkeeping.
            new_files = sorted(f for f in _dirty_paths(worktree_dir)
                               if f in plan.files_touched)
            outcome.files_changed = new_files
            outcome.commit = pr.commit_paths(
                worktree_dir, new_files,
                _commit_message(pack, plan, outcome))
            store.update_finding_status(
                finding_id, "fixed", actor="health_repair_pipeline",
                note=f"fix staged locally by the repair pipeline "
                     f"(models: {', '.join(outcome.models_used)}); "
                     f"publish pending mission end",
                linked_branch=branch, linked_eval=str(evidence_path))
            store.add_lesson(
                scope="repair",
                lesson=f"pipeline fixed {finding_id} "
                       f"({pack.finding['payload'].get('kind')}) in "
                       f"{proposer.calls_made} LLM calls; gate: {reason}",
                evidence=[finding_id] + [t.get("id", "") for t in
                                         pack.traces if t.get("id")],
                campaign_id=pack.finding["payload"].get("campaign_id"))
        else:
            store.add_lesson(
                scope="repair",
                lesson=f"pipeline attempt on {finding_id} failed the gate: "
                       f"{reason} (after {proposer.calls_made} LLM calls)",
                evidence=[finding_id],
                campaign_id=pack.finding["payload"].get("campaign_id"))

        _save_session({"outcome": outcome.reason, "gate_passed": passed,
                       "located": located, "understanding": understanding,
                       "hypothesis": hypothesis,
                       "plan": plan.raw if plan else None,
                       "files_changed": outcome.files_changed,
                       "commit": outcome.commit})
        return outcome

    except Exception as exc:
        outcome.reason = f"{type(exc).__name__}: {exc}"
        outcome.llm_calls = proposer.calls_made
        partial = {k: v for k, v in (
            ("located", locals().get("located")),
            ("understanding", locals().get("understanding")),
            ("hypothesis", locals().get("hypothesis")),
            ("plan", getattr(locals().get("plan"), "raw", None)),
        ) if v}
        _save_session({"outcome": outcome.reason, "gate_passed": False,
                       **partial})
        if not keep_worktree_on_failure:
            subprocess.run(["git", "worktree", "remove", "--force",
                            str(worktree_dir)], cwd=str(repo_root),
                           capture_output=True)
        return outcome


def _commit_message(pack, plan: Plan, outcome: RepairOutcome) -> str:
    kind = pack.finding["payload"].get("kind", "finding")
    return (f"Fix {kind}: {pack.finding['summary'][:100]}\n\n"
            f"Diagnosed, planned, and written by the Health Check Agent "
            f"repair pipeline\nrunning on the product's shared free-tier "
            f"LLM chain (models used: {', '.join(outcome.models_used)}).\n"
            f"Finding: {pack.finding['id']}; evidence traces: "
            f"{', '.join(t.get('id', '?') for t in pack.traces)}.\n"
            f"Eval gate: {outcome.reason}")


def _pr_body(pack, plan: Plan, hypothesis: str, understanding: str,
             before, after, repro_before, repro_after,
             outcome: RepairOutcome) -> str:
    f = pack.finding
    return f"""## What this fixes

{f['summary']}

Found unprompted by the Health Check Agent's simulation loop
(campaign `{f['payload'].get('campaign_id')}`, finding `{f['id']}`,
evidence trace(s): {', '.join(t.get('id', '?') for t in pack.traces)}).

## Who did the work

Every step of this fix — diagnosis, plan, regression test, and code —
was produced by the Health Check Agent's own repair pipeline
(`nexus_platform/repair/`), running on the product's shared free-tier
LLM chain ({', '.join(outcome.models_used) or 'fallback chain'}),
in {outcome.llm_calls} LLM calls. The full stage-by-stage session log
(prompts, responses, validator verdicts) is preserved locally at
`{outcome.session_log}`.

## The pipeline's root-cause analysis

{hypothesis.strip()}

## The pipeline's plan

{plan.raw}

## Eval evidence (before → after)

- BEFORE (untouched tree): suite {before.passed} passed / \
{before.failed} failed; repro **{repro_before.failed or 'n'} failed** \
(the bug is real and encoded).
- AFTER (fix applied): suite {after.passed} passed, zero new failures; \
repro **passed**.
- Gate verdict: **{outcome.reason}**

## Review

A human (Prem) reviews and merges — this pipeline cannot merge and has no
merge code path (structurally enforced by
`tests/platform_mode/test_repair_no_merge_path.py`).
"""
