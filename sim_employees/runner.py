"""The mechanical half of a simulation-employee run.

Given questions (from the external CLI brain), drive them through the analyst
inside the employee's own access boundary, tagged `source="simulated"`, paced
so the free tier survives, and record each outcome to the employee's private
memory + the simulated-query ledger. This half is deterministic — no LLM of
its own; the *analyst* it calls uses NexusIQ's free tier, the *questions* come
from the CLI brain.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from nexus_platform import store
from nexus_platform.query_service import run_query

from sim_employees import memory
from sim_employees.roster import context_for

# Cheap, LLM-free health heuristics: when does an answer deserve a "re-probe"
# weak-spot flag? (A correct role refusal is NOT weak — that's the analyst
# working as designed, so denials are not flagged here.)
_WEAK_ROUTES = {"degraded_mode", "no_data"}


def _verdict(route: str, decision: str, confidence: str, answer: str) -> tuple[str, bool, str]:
    """Return (verdict, weak, note) from cheap signals only."""
    if route in _WEAK_ROUTES:
        return "degraded", True, f"answered via {route} — provider/data gap to re-probe"
    if (confidence or "").upper() == "LOW":
        return "low_confidence", True, "LOW confidence answer — try a sharper phrasing"
    if not (answer or "").strip():
        return "empty", True, "empty answer — the question found a hole"
    if route == "clarification":
        return "clarified", False, ""
    if decision == "denied":
        return "refused", False, ""  # correct-by-design; not a weak spot
    return "answered", False, ""


def ask(company: str, email: str, questions: list,
        *, delay: float = 15.0, llm_extra_delay: float = 20.0,
        campaign_id: Optional[str] = None, quiet: bool = False) -> list[dict]:
    """Run a batch of questions for one simulation employee.

    `questions` items may be a plain string or a dict
    {question, family?, difficulty?}. Traces are tagged simulated; memory is
    updated in place; pacing sleeps between questions (longer after any turn
    that actually spent an LLM call).
    """
    ctx = context_for(company, email)
    role = ctx.employee.role
    name = ctx.employee.name
    mem = memory.load(company, email, role=role, name=name)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    campaign_id = campaign_id or f"empday_{day}"
    session_id = f"sim-emp-{memory._slug(email)}-{day}"

    results = []
    for idx, q in enumerate(questions):
        if isinstance(q, dict):
            qtext = q.get("question", "")
            family = q.get("family", "adhoc")
            difficulty = q.get("difficulty", "unknown")
        else:
            qtext, family, difficulty = str(q), "adhoc", "unknown"
        if not qtext.strip():
            continue

        with store.tagged_trace_source("simulated"):
            res = run_query(ctx, qtext, session_id)
        plat = res.get("platform") or {}
        trace_id = plat.get("trace_id") or ""
        answer = str(res.get("answer") or "")
        route = plat.get("route") or "unknown"
        decision = plat.get("access_decision") or "unknown"
        confidence = plat.get("confidence") or "N/A"
        llm_used = not plat.get("llm_skipped", False)

        verdict, weak, note = _verdict(route, decision, confidence, answer)
        interaction = {
            "question": qtext, "family": family, "difficulty": difficulty,
            "route": route, "access_decision": decision,
            "confidence": confidence, "llm_used": llm_used,
            "answer_summary": answer[:300], "trace_id": trace_id,
            "verdict": verdict,
        }
        memory.append_interaction(mem, interaction, weak=weak, weak_note=note)

        store.save_sim_query(
            company, campaign_id, role, qtext, "cli_brain", family, difficulty,
            route, trace_id, session_id, llm_used,
            tokens_estimated=(len(qtext) + len(answer)) // 4)

        results.append({**interaction, "weak": weak})
        if not quiet:
            flag = "  ⚠ weak" if weak else ""
            print(f"  [{role}] {qtext[:60]!r} -> {route}/{decision} "
                  f"({confidence}){flag}")

        # pace: keep the free tier alive; longer breather after an LLM turn
        if idx < len(questions) - 1:
            time.sleep(delay + (llm_extra_delay if llm_used else 0.0))

    memory.save(mem)
    return results
