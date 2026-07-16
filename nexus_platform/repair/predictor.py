"""Hidden-bug prediction for the repair pipeline: predict, then PROVE.

Given a finding's evidence, one reasoning-tier LLM call proposes up to N
*related* hidden bugs — each as a concrete question a real employee could
ask. Every prediction is then verified by actually running that question
through the product (locally, tagged simulated) and grading the outcome with
the health review's deterministic tier — recomputed ground truth, zero LLM.

Three honest tiers come out, and they are never mixed:
  - verified:   the predicted failing input reproduced a real failure
                (a graded wrong/false_refusal verdict, with a trace id)
  - unverified: a hypothesis that did NOT reproduce, or could not be
                deterministically graded — reported, never counted
  - the surfaced finding itself is tracked separately by the caller

The prediction prompt is a generic template: it asks for same-class inputs
from the evidence shown; it never encodes what any specific bug's fix looks
like (the §2e bright line).
"""

from __future__ import annotations

import re
import time
from typing import Optional

from nexus_platform import store
from nexus_platform.repair.context_pack import EvidencePack

MAX_PREDICTIONS = 3
VERIFY_DELAY_SECONDS = 5.0  # pacing between verification runs (quota floor)

_PRED_RE = re.compile(
    r"^\s*PREDICTION:\s*(?P<q>[^|]+?)\s*\|\s*ROLE:\s*(?P<role>[A-Za-z]+)\s*"
    r"\|\s*WHY:\s*(?P<why>.+)$", re.MULTILINE)


def _prediction_prompt(pack: EvidencePack) -> str:
    return (
        "You are the repair module of an AI data analyst's Health Check "
        "Agent. A real defect was just confirmed (evidence below). Defects "
        "rarely travel alone: the same missing check or wrong assumption "
        "usually breaks OTHER inputs of the same shape.\n\n"
        f"{pack.evidence_text()}\n\n"
        f"Predict up to {MAX_PREDICTIONS} related hidden bugs. Each must be "
        "a CONCRETE question a real employee could type — a plausible "
        "same-class input you predict the product will also answer wrongly, "
        "refuse wrongly, or fabricate on. Vary the shape (different metric, "
        "different phrasing, different period), do not repeat the evidence "
        "questions, and never invent table or metric names that make no "
        "sense for a business.\n\n"
        "Answer with ONLY lines in exactly this format, one per prediction:\n"
        "PREDICTION: <the question, verbatim as an employee would type it> "
        "| ROLE: <Admin|CEO|Analyst|Finance|HR|Support|Ops> "
        "| WHY: <one sentence: why the same defect should hit this input>\n")


def _validate(resp: str) -> tuple[bool, str]:
    if not _PRED_RE.search(resp or ""):
        return False, ("no valid 'PREDICTION: … | ROLE: … | WHY: …' line "
                       "found — follow the format exactly")
    return True, ""


def _verify_one(company: str, role: str, question: str) -> Optional[dict]:
    """Run the predicted question through the product locally and grade it
    deterministically. Returns a verified-failure record, or None when it
    did not reproduce / could not be deterministically decided."""
    from nexus_platform.health_review import _ctx_for, _grade_deterministic
    from nexus_platform.query_service import run_query

    email = f"sim-predict-{role.lower()}@{company}"
    ctx = _ctx_for(company, role, email)
    if ctx is None:
        return None
    with store.tagged_trace_source("simulated"):
        res = run_query(ctx, question, f"predict-verify-{company}")
    plat = res.get("platform") or {}
    answer = str(res.get("answer") or "")
    graded = _grade_deterministic(ctx, question, answer, plat)
    if graded is None:
        return None  # not deterministically decidable — stays a hypothesis
    if graded["verdict"] in ("wrong", "false_refusal"):
        return {"question": question, "role": role,
                "verdict": graded["verdict"],
                "expected": graded.get("expected"),
                "reality": graded.get("reality"),
                "trace_id": plat.get("trace_id") or ""}
    return None  # graded fine — the prediction did not reproduce


def predict_and_verify(proposer, pack: EvidencePack) -> dict:
    """Run the predict stage on the proposer's throttled/budgeted invoker,
    then verify each prediction by reproducing it. Failures of this stage
    never sink a repair — the caller treats an empty result as 'no verified
    predictions'."""
    out = {"verified": [], "unverified": []}
    try:
        resp = proposer._invoke("predict", _prediction_prompt(pack), _validate)
    except Exception:
        return out
    seen = set()
    for m in _PRED_RE.finditer(resp):
        q = m.group("q").strip()
        role = m.group("role").strip().capitalize()
        why = m.group("why").strip()
        if not q or q.lower() in seen:
            continue
        seen.add(q.lower())
        try:
            hit = _verify_one(pack.company, role, q)
        except Exception:
            hit = None
        if hit:
            hit["why"] = why
            out["verified"].append(hit)
        else:
            out["unverified"].append({"question": q, "role": role, "why": why})
        time.sleep(VERIFY_DELAY_SECONDS)
    return out
