"""Health Check agent — Wave 1: judge every trace, produce a report.

Wave 1 reads a company's traces and grades each one on a 3-tier escalation:

  1. Deterministic (free, exact): recompute the ground truth from the
     company's own data (numeric oracle) or the role policy (allow/deny), and
     compare it to what the analyst actually did.
  2. LLM judge (capped): for the fuzzy traces the deterministic layer can't
     grade (RAG/narrative answers, clarifications), ask a capped LLM whether
     the answer is right — on the product's gateway (reasoning tier, e.g.
     Bedrock), with a hard per-run call budget so it never drains quota.
  3. Human review: if neither tier can judge confidently, the trace is flagged
     "needs human review" in the report — never a silent guess.

The output is a structured, plain-language report grouped by employee, with a
"fixes needed" section at the end. Wave 1 changes no code — diagnosing and
repairing the analyst is Wave 2 (nexus_platform/repair/), run separately.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from nexus_platform import store
from nexus_platform.access_policy import get_policy
from nexus_platform.auth import AccessContext
from nexus_platform.deterministic import execute as det_execute, parse_intent
from nexus_platform.registry import Employee, get_registry
from nexus_platform.sim.classifier import _num_match, _numbers, compute_oracle

# Per-trace verdicts. correct/correct_refusal are healthy; the rest are issues.
VERDICTS = ("correct", "partly_correct", "wrong", "false_refusal",
            "correct_refusal", "needs_human_review", "not_applicable")
_ISSUE_VERDICTS = ("wrong", "partly_correct", "false_refusal", "needs_human_review")
_ANSWER_ROUTES = ("deterministic_sql_template", "sql_agent", "rag_agent",
                  "sql_plus_rag", "llm_planner", "sql_only", "rag_only",
                  "degraded_mode")


def _ctx_for(company: str, role: str, email: str) -> Optional[AccessContext]:
    reg = get_registry()
    comp = reg.get_company(company)
    if comp is None or role not in _ALL_ROLES():
        return None
    emp = reg.get_employee(email) or Employee(
        email=email or f"sim-{role}@{company}", name=email.split("@")[0] if email else role,
        company_slug=company, role=role, password_hash="", title=role)
    return AccessContext(employee=emp, company=comp, policy=get_policy(role))


def _ALL_ROLES() -> set:
    from nexus_platform.access_policy import ROLE_POLICIES
    return set(ROLE_POLICIES)


# ── Tier 1: deterministic grading ───────────────────────────────────────

def _grade_deterministic(ctx: AccessContext, question: str, answer: str,
                         payload: dict) -> Optional[dict]:
    """Return a verdict dict if the deterministic layer can judge, else None
    (meaning: escalate to the LLM)."""
    decision = payload.get("access_decision")
    route = payload.get("route")

    # Cross-company scope: asking about another company is correctly kept to
    # the employee's own company — not a role refusal, and never a bug.
    if route == "cross_company_scope_clarification":
        return _v("correct_refusal", "deterministic",
                  "The question was about a different company; the analyst "
                  "correctly kept the employee to their own company's data.",
                  expected="own-company scope", reality="scoped to own company")

    # Refusals: was the refusal correct for this role? Re-derive from policy.
    if route == "access_refusal" or (decision == "denied" and route != "clarification"):
        intent = parse_intent(question)
        if intent is None:
            return None  # can't tell what was asked -> escalate
        det = det_execute(ctx, intent)
        if det is None:
            return None
        if det.get("denied"):
            return _v("correct_refusal", "deterministic",
                      "Refused, and the role genuinely cannot access the data "
                      "this question needs — access control working as designed.",
                      expected="a refusal", reality="refused")
        return _v("false_refusal", "deterministic",
                  "Refused, but the role IS allowed the data this question "
                  "needs — the analyst restricted access it shouldn't have.",
                  expected="an answer (role has access)", reality="refused")

    # Answered turns: numeric ground truth from the company's own data.
    if decision == "allowed" and route in _ANSWER_ROUTES:
        oracle = compute_oracle(ctx, payload.get("resolved_question") or question)
        if oracle:
            got = _numbers(answer)
            if not got:
                return None  # numeric expected but the answer has no number
            if _num_match(got, oracle):
                return _v("correct", "deterministic",
                          "Answer matches the value recomputed from the "
                          "company's own data.",
                          expected=_fmt(oracle), reality=_fmt(got))
            return _v("wrong", "deterministic",
                      "Answer does NOT match the value recomputed from the "
                      "company's own data.",
                      expected=_fmt(oracle), reality=_fmt(got))
        return None  # non-deterministic answer -> escalate to the LLM

    # Clarifications / repeat-choices / no-data etc.: not a right/wrong answer.
    if route in ("clarification", "repeat_question_choice",
                 "cross_company_scope_clarification", "repeat_used_previous"):
        return _v("not_applicable", "deterministic",
                  f"This turn was a {route}, not a final answer — nothing to "
                  "grade for correctness.", expected="—", reality="—")
    return None


def _v(verdict: str, tier: str, reason: str, expected: str = "", reality: str = "") -> dict:
    return {"verdict": verdict, "tier": tier, "reason": reason,
            "expected": expected, "reality": reality}


def _fmt(nums: list) -> str:
    return ", ".join(str(int(n)) if float(n).is_integer() else str(round(n, 2))
                     for n in nums[:4])


# ── Tier 2: capped LLM judge ────────────────────────────────────────────

def _llm_judge(ctx: AccessContext, question: str, answer: str,
               budget: dict) -> dict:
    """Grade a fuzzy trace with a capped LLM. Falls through to human review
    when the budget is spent or the model abstains/fails."""
    if budget.get("remaining", 0) <= 0:
        return _v("needs_human_review", "human",
                  "The deterministic layer couldn't grade this, and the LLM "
                  "judge budget for this run was already spent — a person "
                  "should check it.", expected="—", reality="—")
    try:
        from config.settings import settings
        from utils.llm_gateway import (get_llm_gateway, insert_bedrock_fallback,
                                       insert_cerebras_fallback)
        from utils.quota_tracker import quota_tracker
        models = []
        if settings.google_api_key:
            models.append({"name": settings.gemini_flash_model, "type": "gemini",
                           "description": "Gemini Flash"})
        if settings.groq_api_key:
            models.append({"name": settings.groq_model, "type": "groq",
                           "description": "Groq"})
        models = insert_bedrock_fallback(
            insert_cerebras_fallback(models, reasoning=True), reasoning=True)
        if not models:
            return _v("needs_human_review", "human",
                      "No judge model was reachable — a person should review "
                      "this trace.", expected="—", reality="—")
        tables = ", ".join(sorted(getattr(ctx.policy, "allowed_tables", []) or [])[:20])
        docs = ", ".join(sorted(getattr(ctx.policy, "allowed_departments", []) or []))
        prompt = (
            "You grade an internal AI data analyst's answer. Be strict and use "
            "ONLY what is given; never invent facts. If you cannot tell, say "
            "CANNOT_TELL.\n\n"
            f"Employee role: {ctx.employee.role}\n"
            f"Data this role may use — tables: {tables or 'none'}; "
            f"documents: {docs or 'none'}\n"
            f"Question: {question}\n"
            f"Analyst's answer: {answer[:900]}\n\n"
            "Reply with EXACTLY one label then a colon then a one-sentence "
            "reason. Labels: CORRECT (right and complete), PARTLY (partly "
            "right or incomplete), WRONG (incorrect or fabricated), "
            "CANNOT_TELL (not enough to judge).\n"
            "Example: WRONG: it reports a metric the company doesn't track."
        )
        budget["remaining"] -= 1
        res = get_llm_gateway().invoke_with_fallback(
            prompt=prompt, models=models, tracker=quota_tracker,
            task="health_review.judge", temperature=0.0,
            metadata={"agent": "health_check_wave1"},
            response_validator=lambda c: ":" in c or len(c.strip()) > 3)
        if not res.get("success"):
            return _v("needs_human_review", "human",
                      "The LLM judge was unavailable for this trace — a "
                      "person should review it.", expected="—", reality="—")
        text = str(res["response"]).strip()
        label = re.split(r"[:\-\n]", text, 1)[0].strip().upper()
        reason = text.split(":", 1)[1].strip() if ":" in text else text
        model = res.get("model_used", "llm")
        if label.startswith("CORRECT"):
            return _v("correct", "llm", f"{reason} (judged by {model})")
        if label.startswith("PARTLY"):
            return _v("partly_correct", "llm", f"{reason} (judged by {model})")
        if label.startswith("WRONG"):
            return _v("wrong", "llm", f"{reason} (judged by {model})",
                      reality="see answer")
        return _v("needs_human_review", "human",
                  f"The LLM couldn't judge confidently ({reason[:120]}) — "
                  "a person should review this trace.")
    except Exception as exc:  # pragma: no cover - defensive
        return _v("needs_human_review", "human",
                  f"Judging errored ({str(exc)[:80]}) — human review needed.")


# ── Per-trace grade ─────────────────────────────────────────────────────

def grade_trace(company: str, trace: dict, budget: dict) -> dict:
    payload = trace.get("payload") or {}
    role = trace.get("role") or payload.get("role") or ""
    email = trace.get("employee") or payload.get("employee") or ""
    question = trace.get("question") or payload.get("question") or ""
    answer = store.answer_for_trace(company, trace["id"]) or ""
    ctx = _ctx_for(company, role, email)

    base = {"trace_id": trace["id"], "employee": email, "role": role,
            "ts": trace.get("ts"), "question": question,
            "answer": answer[:400], "route": payload.get("route"),
            "access_decision": payload.get("access_decision")}

    if ctx is None or not question:
        return {**base, **_v("needs_human_review", "human",
                             "Trace is incomplete (missing role/company/"
                             "question) — a person should review it.")}

    verdict = _grade_deterministic(ctx, question, answer, payload)
    if verdict is None:
        verdict = _llm_judge(ctx, question, answer, budget)
    return {**base, **verdict}


# ── The report ──────────────────────────────────────────────────────────

def run_health_review(company: str, requested_by: str = "admin",
                      window_days: int = 30, source: str = "real",
                      llm_budget: int = 25, save: bool = True) -> dict:
    """Grade every trace in the window and build the Wave 1 report."""
    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=window_days)).isoformat()
    traces = store.list_traces_with_payload(company, date_from=date_from,
                                            source=source)
    reg = get_registry()
    comp = reg.get_company(company)
    budget = {"remaining": llm_budget}

    by_emp: dict = defaultdict(list)
    for tr in traces:
        by_emp[tr.get("employee") or "unknown"].append(grade_trace(company, tr, budget))

    employees = []
    for email, rows in sorted(by_emp.items()):
        rows.sort(key=lambda r: r.get("ts") or "", reverse=True)
        counts = Counter(r["verdict"] for r in rows)
        emp = reg.get_employee(email)
        employees.append({
            "email": email,
            "name": emp.name if emp else email.split("@")[0],
            "role": rows[0].get("role") if rows else "",
            "trace_count": len(rows),
            "verdict_counts": dict(counts),
            "issues": sum(counts.get(v, 0) for v in _ISSUE_VERDICTS),
            "traces": rows,
        })
    employees.sort(key=lambda e: (-e["issues"], -e["trace_count"]))

    all_counts: Counter = Counter()
    for e in employees:
        all_counts.update(e["verdict_counts"])
    graded = sum(all_counts.get(v, 0) for v in VERDICTS if v != "not_applicable")
    issues = sum(all_counts.get(v, 0) for v in _ISSUE_VERDICTS)
    llm_used = llm_budget - budget["remaining"]

    fixes = _fixes_needed(employees)
    narrative = (
        f"Reviewed {len(traces)} question{'s' if len(traces) != 1 else ''} from "
        f"{len(employees)} employee(s) over the last {window_days} days. "
        f"{all_counts.get('correct', 0)} answered correctly, "
        f"{issues} need attention "
        f"({all_counts.get('wrong', 0)} wrong, "
        f"{all_counts.get('false_refusal', 0)} wrongly refused, "
        f"{all_counts.get('partly_correct', 0)} partly right, "
        f"{all_counts.get('needs_human_review', 0)} need a human's eyes). "
        f"Grading used the deterministic layer first and {llm_used} LLM "
        f"call(s) for the harder ones."
    )

    report = {
        "kind": "health_review",
        "company": company,
        "company_name": comp.name if comp else company,
        "requested_by": requested_by,
        "generated_at": now.isoformat(),
        "report_date": now.strftime("%B %d, %Y"),
        "window_days": window_days,
        "date_from": date_from,
        "date_to": now.isoformat(),
        "source": source,
        "traces_reviewed": len(traces),
        "graded": graded,
        "summary": {
            "total_traces": len(traces),
            "employees_active": len(employees),
            "verdict_counts": dict(all_counts),
            "issues": issues,
            "llm_calls_used": llm_used,
            "needs_human_review": all_counts.get("needs_human_review", 0),
            "per_employee": [{"name": e["name"], "role": e["role"],
                              "email": e["email"], "traces": e["trace_count"],
                              "issues": e["issues"]} for e in employees],
        },
        "narrative": narrative,
        "employees": employees,
        "fixes_needed": fixes,
    }
    if save:
        report["report_id"] = store.save_health_report(
            company, requested_by, window_days, report)
    return report


def _fixes_needed(employees: list) -> list:
    """Roll the non-correct verdicts up into a short, plain-language list of
    what needs fixing — the last page of the report."""
    buckets: dict = defaultdict(lambda: {"count": 0, "traces": [], "employees": set()})
    labels = {
        "wrong": ("Wrong answers", "high",
                  "The analyst gave an answer that doesn't match the company's "
                  "real data. Re-check the SQL/template or retrieval for these "
                  "questions and add each as a regression test."),
        "false_refusal": ("Wrongly refused questions", "high",
                          "The analyst blocked questions the employee's role is "
                          "actually allowed to ask. Review the access check for "
                          "these phrasings."),
        "partly_correct": ("Partly-right answers", "medium",
                           "The answer was incomplete or only partly correct. "
                           "Tighten the answer for these questions."),
        "needs_human_review": ("Need a human's review", "medium",
                              "Neither the deterministic check nor the LLM could "
                              "judge these confidently — a person should look."),
    }
    for e in employees:
        for t in e["traces"]:
            v = t["verdict"]
            if v in labels:
                b = buckets[v]
                b["count"] += 1
                b["employees"].add(e["name"])
                if len(b["traces"]) < 6:
                    b["traces"].append(t["trace_id"])
    out = []
    for v, (title, sev, rec) in labels.items():
        if v in buckets:
            b = buckets[v]
            out.append({"issue": title, "severity": sev, "count": b["count"],
                        "employees": sorted(b["employees"])[:8],
                        "example_trace_ids": b["traces"], "recommendation": rec})
    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda f: (order.get(f["severity"], 9), -f["count"]))
    return out
