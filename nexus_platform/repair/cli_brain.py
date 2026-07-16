"""CLI reasoning brain for the repair agent — invokes Claude Code headlessly.

CONTEXT.md revised §2e (2026-07-16): weak free-tier models cannot do complex
program repair, so the repair agent's HARD sub-tasks (understand, hypothesize,
critique, plan, confirm_plan, implement, self_review) route here — a strong
model reached by shelling out to ``claude -p``, the same external-CLI-brain
pattern ``sim_employees/`` already uses for question generation. The cheap
sub-task (localization) stays on the product's free-tier gateway; see
``proposer._default_llm`` for the split.

Per-sub-task tiering INSIDE the CLI (so cheap work stays on a cheap model even
here): the generation-heavy stages use the strong model; the lighter review
stages use a cheaper Claude tier. Both are env-configurable, so a run can
trade cost for strength without code changes:

  NEXUSIQ_REPAIR_CLI_MODEL        strong model   (default "sonnet")
  NEXUSIQ_REPAIR_CLI_CHEAP_MODEL  lighter model  (default "haiku")
  NEXUSIQ_REPAIR_CLI_TIMEOUT      per-call seconds (default 420)
  NEXUSIQ_REPAIR_CLI_BIN          claude binary  (default "claude" on PATH)

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

# Generation-heavy stages that need the strong model; other stages routed
# here (critique, self_review) are review work and use the lighter tier.
_HEAVY_STAGES = {"understand", "hypothesize", "plan", "confirm_plan",
                 "implement", "predict"}

_DENY_TOOLS = ["Bash", "Read", "Edit", "Write", "Grep", "Glob",
               "WebFetch", "WebSearch", "Task", "NotebookEdit"]


def _stage_of(task: str) -> str:
    return (task or "").split(".")[-1]


def model_for(task: str) -> str:
    """Strong model for the heavy generation stages, cheaper model for the
    lighter review stages — the in-CLI half of per-sub-task routing."""
    strong = os.environ.get("NEXUSIQ_REPAIR_CLI_MODEL", "sonnet")
    cheap = os.environ.get("NEXUSIQ_REPAIR_CLI_CHEAP_MODEL", "haiku")
    return strong if _stage_of(task) in _HEAVY_STAGES else cheap


def _claude_bin() -> Optional[str]:
    name = os.environ.get("NEXUSIQ_REPAIR_CLI_BIN", "claude")
    return shutil.which(name) or (name if os.path.exists(name) else None)


def _fail(model: str, status: str, response: str = "",
          invalid: Optional[str] = None) -> dict:
    tried = {"model": model, "status": status}
    if invalid is not None:
        tried["invalid_content"] = invalid
    return {"response": response, "success": False,
            "model_used": model, "models_tried": [tried]}


def cli_llm(prompt: str, task: str,
            validator: Optional[Callable[[str], bool]] = None,
            reasoning: bool = True) -> dict:
    """Run one repair-reasoning turn on Claude Code (headless ``claude -p``).

    Signature matches ``proposer._default_llm`` so it is a drop-in tier.
    Returns ``{response, success, model_used, models_tried}`` and never
    raises — a hard failure surfaces as ``success=False`` so the proposer's
    bounded retry/feedback loop handles it rather than the stage crashing.
    """
    model = model_for(task)
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
