"""Platform query pipeline: memory → rewrite → role-scoped agents → filter →
trace → chart.

The evidence boundary itself lives inside the (company, role) agent instance
(schema subset, AST allowlist, RAG department filter). This service adds the
per-employee layers on top: session memory, follow-up rewrite, refusal
wording, citation re-filtering, chart specs, and the saved product trace.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from typing import Optional

from nexus_platform import store
from nexus_platform.access_policy import classify_restricted_intent, refusal_message
from nexus_platform.auth import AccessContext
from nexus_platform.charts import build_chart_spec, wants_chart
from nexus_platform.contexts import get_company_fusion_agent
from nexus_platform.dashboard import build_dashboard, wants_dashboard
from nexus_platform.deterministic import Intent, execute as deterministic_execute, parse_intent

# One lock per (company, role) agent — history seeding must not interleave.
_agent_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        if key not in _agent_locks:
            _agent_locks[key] = threading.Lock()
        return _agent_locks[key]


def _is_access_denied(result: dict) -> Optional[str]:
    """Detect the AST-level table denial raised by the role allowlist."""
    for section in ("sql_result",):
        err = str(((result.get(section) or {}).get("error")) or "")
        if "ACCESS_DENIED_TABLE" in err:
            return err.split("ACCESS_DENIED_TABLE:")[-1].strip().split()[0].strip("'\"")
    if "ACCESS_DENIED_TABLE" in str(result.get("error") or ""):
        return str(result.get("error")).split("ACCESS_DENIED_TABLE:")[-1].strip()
    return None


def _filter_sources(sources: list, allowed_departments: tuple[str, ...]) -> list:
    """Defense-in-depth: drop any citation whose department is not allowed."""
    out = []
    allowed = set(allowed_departments)
    for s in sources or []:
        if isinstance(s, dict):
            dept = (s.get("metadata") or {}).get("department") or s.get("department")
            if dept is not None and dept not in allowed:
                continue
        out.append(s)
    return out


def _update_prefs(ctx: AccessContext, question: str, chart_spec: Optional[dict]) -> None:
    if chart_spec and chart_spec.get("type") in ("bar", "line"):
        store.set_pref(ctx.company.slug, ctx.employee.email,
                       "preferred_chart_type", chart_spec["type"])
    topic_words = [w for w in question.lower().split()
                   if w in ("revenue", "orders", "customers", "tickets", "invoices",
                            "headcount", "attrition", "csat", "mrr", "products")]
    if topic_words:
        store.set_pref(ctx.company.slug, ctx.employee.email,
                       "recent_topic", topic_words[0])


def _finish_deterministic(ctx: AccessContext, question: str, session_id: str,
                          intent: Intent, det: dict, memory_turns: int) -> dict:
    """Package a deterministic template answer: trace, memory, response."""
    started = time.time()
    company, employee, role = ctx.company.slug, ctx.employee.email, ctx.employee.role

    refused = bool(det["denied"])
    if refused:
        denied_area = ", ".join(det["denied_tables"])
        answer = refusal_message(role, ctx.company.name,
                                 detail=f"the '{denied_area}' data area is outside your role")
        decision = "denied"
    else:
        answer = det["answer"]
        decision = "allowed"

    if intent.followup_kind:
        # Human-readable description of the merged intent
        from nexus_platform.deterministic import _METRIC_LABELS
        parts = [_METRIC_LABELS.get(intent.metric or "", intent.metric or "")]
        if intent.group_by:
            parts.append(f"by {intent.group_by}")
        if intent.period:
            parts.append(f"for {intent.period[0]}")
        if intent.selected_periods:
            parts.append("for " + " and ".join(p[0] for p in intent.selected_periods))
        if intent.compare:
            parts.append(f"vs {intent.compare[0]}")
        resolved = " ".join(p for p in parts if p).capitalize()
    else:
        resolved = question
    trace_payload = {
        "employee": employee,
        "employee_name": ctx.employee.name,
        "company": company,
        "company_name": ctx.company.name,
        "role": role,
        "session_id": session_id,
        "question": question,
        "resolved_question": resolved,
        "followup_rewritten": intent.followup_kind is not None,
        "memory_turns_used": memory_turns,
        "intent": {
            "metric": intent.metric,
            "period": list(intent.period) if intent.period else None,
            "compare": list(intent.compare) if intent.compare else None,
            "selected_periods": [list(p) for p in intent.selected_periods] if intent.selected_periods else None,
            "group_by": intent.group_by,
            "top_n": intent.top_n,
            "output": intent.output,
            "followup_kind": intent.followup_kind,
        },
        "access_policy": {
            "allowed_tables": list(ctx.policy.allowed_tables),
            "allowed_departments": list(ctx.policy.allowed_departments),
        },
        "access_decision": decision,
        "denied_reason": (f"tables outside role: {det['denied_tables']}" if refused else None),
        "route": "deterministic_sql_template",
        "template_id": det["template_id"],
        "llm_skipped": True,
        "model_used": None,
        "confidence": "HIGH",
        "sql": det["sql"],
        "tables_touched": det["tables"],
        "citations": [],
        "chart_generated": det["chart"] is not None and not refused,
        "chart_type": (det["chart"] or {}).get("type"),
        "latency_s": round(time.time() - started, 3),
    }
    trace_id = store.save_trace(company, employee, role, question, decision, trace_payload)
    # Intent is stored even for refused turns: a follow-up like "what about
    # Q4?" then re-resolves against the same denied metric and is refused
    # deterministically again — policy is re-applied on every turn, so stored
    # intent can never widen access.
    store.save_turn(company, employee, session_id, question, resolved,
                    answer[:500], "deterministic_sql_template",
                    (det["chart"] or {}).get("type"), refused,
                    intent_json=intent.to_json(),
                    sql=det["sql"], route="deterministic_sql_template",
                    tables_json=json.dumps(det["tables"]))

    followups: list[str] = []
    if not refused:
        if intent.period and intent.period[0].startswith("Q"):
            other = "Q4" if not intent.period[0].startswith("Q4") else "Q1"
            followups.append(f"What about {other}?")
        if not intent.group_by:
            grouped_hint = {"headcount": "by department", "terminations": "by department",
                            "tickets": "by priority", "csat": "by category"}
            followups.append(grouped_hint.get(intent.metric, "by region"))
        if not intent.compare and intent.period:
            followups.append("Compare that with Q3" if not intent.period[0].startswith("Q3")
                             else "Compare that with Q2")
        if (det["chart"] or {}).get("type") == "kpi":
            followups.append("Show monthly trend")

    return {
        "answer": answer,
        "confidence": "HIGH",
        "confidence_reason": ("Access policy refusal — no restricted data was read."
                              if refused else
                              "Deterministic SQL template over your company workspace — no LLM in the loop."),
        "validation": {
            "confidence": "HIGH",
            "confidence_reason": ("Access policy refusal — no restricted data was read."
                                  if refused else
                                  "Deterministic SQL template — no LLM in the loop."),
        },
        "source_type": "deterministic_sql_template",
        "sources": [],
        "sql_result": (None if refused else {
            "success": True, "query": det["sql"],
            "row_count": len(det["rows"]), "results": det["rows"][:5],
        }),
        "platform": {
            "trace_id": trace_id,
            "resolved_question": resolved,
            "followup_rewritten": intent.followup_kind is not None,
            "access_decision": decision,
            "refused": refused,
            "chart": None if refused else det["chart"],
            "dashboard": None,
            "role": role,
            "company": ctx.company.name,
            "route": "deterministic_sql_template",
            "llm_skipped": True,
            "model_used": None,
            "followups": followups[:3],
        },
    }


def _run_dashboard(ctx: AccessContext, question: str, session_id: str) -> dict:
    """Deterministic dashboard answer: KPIs + charts from role-allowed SQL."""
    started = time.time()
    company, employee, role = ctx.company.slug, ctx.employee.email, ctx.employee.role
    dashboard = build_dashboard(ctx)

    if dashboard is None:
        answer = refusal_message(role, ctx.company.name,
                                 detail="no dashboard data areas are inside your role")
        refused, decision = True, "denied"
    else:
        n_k, n_c = len(dashboard["kpis"]), len(dashboard["charts"])
        answer = (f"Here is your {ctx.company.name} dashboard — {n_k} KPIs and "
                  f"{n_c} charts computed live from the workspace data your "
                  f"{role} role can access. Every number comes from deterministic "
                  f"SQL (shown under each block); nothing is model-generated.")
        refused, decision = False, "allowed"

    trace_payload = {
        "employee": employee,
        "employee_name": ctx.employee.name,
        "company": company,
        "company_name": ctx.company.name,
        "role": role,
        "session_id": session_id,
        "question": question,
        "resolved_question": question,
        "followup_rewritten": False,
        "memory_turns_used": 0,
        "access_policy": {
            "allowed_tables": list(ctx.policy.allowed_tables),
            "allowed_departments": list(ctx.policy.allowed_departments),
        },
        "access_decision": decision,
        "denied_reason": None if not refused else "no dashboard data areas in role",
        "route": "dashboard",
        "confidence": "HIGH",
        "sql": "; ".join((dashboard or {}).get("sql_used", [])) or None,
        "citations": [],
        "chart_generated": dashboard is not None,
        "chart_type": "dashboard",
        "latency_s": round(time.time() - started, 2),
    }
    trace_id = store.save_trace(company, employee, role, question, decision, trace_payload)
    store.save_turn(company, employee, session_id, question, question,
                    answer[:500], "dashboard", "dashboard", refused)

    return {
        "answer": answer,
        "confidence": "HIGH",
        "confidence_reason": "Deterministic SQL over the company workspace — no LLM in the loop.",
        "validation": {
            "confidence": "HIGH",
            "confidence_reason": "Deterministic SQL over the company workspace — no LLM in the loop.",
        },
        "source_type": "dashboard",
        "sources": [],
        "platform": {
            "trace_id": trace_id,
            "resolved_question": question,
            "followup_rewritten": False,
            "access_decision": decision,
            "refused": refused,
            "chart": None,
            "dashboard": dashboard,
            "role": role,
            "company": ctx.company.name,
        },
    }


def run_query(ctx: AccessContext, question: str, session_id: str) -> dict:
    """Execute one analyst query inside the caller's access boundary."""
    started = time.time()
    company = ctx.company.slug
    employee = ctx.employee.email
    role = ctx.employee.role
    prefs = store.get_prefs(company, employee)

    # Dashboard requests are deterministic role-filtered SQL — no LLM, no
    # follow-up rewrite needed, instant.
    if wants_dashboard(question):
        return _run_dashboard(ctx, question, session_id)

    turns = store.recent_turns(company, employee, session_id, limit=10)

    # Deterministic analyst layer: common business-analytics families answer
    # from template SQL with the LLM skipped entirely. Follow-ups merge with
    # the previous deterministic intent stored in session memory.
    prev_intent = None
    for t in reversed(turns):
        if t.get("intent_json"):
            prev_intent = Intent.from_json(t["intent_json"])
            break
    intent = parse_intent(question, prev_intent)
    if intent is not None:
        det = deterministic_execute(ctx, intent)
        if det is not None:
            return _finish_deterministic(ctx, question, session_id, intent,
                                         det, memory_turns=len(turns))

    key = f"company:{company}:{role.lower()}"
    agent = get_company_fusion_agent(company, role)

    with _lock_for(key):
        # Seed this employee's session history into the shared role agent,
        # run, then always clear so no other employee can see it.
        agent._history = [
            {"question": t["question"], "answer": t["answer_summary"] or ""}
            for t in turns[-5:]
        ]
        try:
            resolved = agent._resolve_question(question)
            denied_intent = classify_restricted_intent(resolved, ctx.policy)
            if denied_intent is None:
                result = agent.query(resolved)
            else:
                # Clearly restricted — refuse before any retrieval happens.
                result = {"answer": "", "sources": [], "source_type": "access_refusal"}
        finally:
            agent._history = []

    rewritten = resolved != question
    denied_table = _is_access_denied(result)
    denied_reason = None
    if denied_table is not None:
        denied_reason = f"the '{denied_table}' data area is outside your role"
    elif denied_intent is not None:
        denied_reason = denied_intent

    sources = _filter_sources(result.get("sources") or [],
                              ctx.policy.allowed_departments)
    rag_sources = None
    if result.get("rag_result"):
        rag_sources = _filter_sources(result["rag_result"].get("sources") or [],
                                      ctx.policy.allowed_departments)
        result["rag_result"]["sources"] = rag_sources
    result["sources"] = sources

    refused = False
    if denied_reason is not None:
        refused = True
        answer = refusal_message(role, ctx.company.name, detail=denied_reason)
        result["answer"] = answer
        result["confidence"] = "HIGH"
        result["confidence_reason"] = "Access policy refusal — no restricted data was read."
        result["sql_result"] = None
        result["sources"] = []
        sources = []

    chart_spec = None
    if not refused:
        preferred = prefs.get("preferred_chart_type")
        if wants_chart(question) or preferred:
            chart_spec = build_chart_spec(resolved, result.get("sql_result"),
                                          preferred_type=preferred)
        _update_prefs(ctx, resolved, chart_spec if wants_chart(question) else None)

    access_decision = "denied" if refused else "allowed"
    trace_payload = {
        "employee": employee,
        "employee_name": ctx.employee.name,
        "company": company,
        "company_name": ctx.company.name,
        "role": role,
        "session_id": session_id,
        "question": question,
        "resolved_question": resolved,
        "followup_rewritten": rewritten,
        "memory_turns_used": len(turns),
        "access_policy": {
            "allowed_tables": list(ctx.policy.allowed_tables),
            "allowed_departments": list(ctx.policy.allowed_departments),
        },
        "access_decision": access_decision,
        "denied_reason": denied_reason,
        "route": result.get("source_type"),
        "llm_skipped": False,
        "model_used": result.get("model_used") or None,
        "provider_failures": [
            {"model": m.get("model"), "error": str(m.get("error"))[:120]}
            for m in (result.get("models_tried") or [])
            if isinstance(m, dict) and "FAILED" in str(m.get("status", ""))
        ][:5],
        "confidence": result.get("confidence"),
        "sql": (result.get("sql_result") or {}).get("query"),
        "citations": [
            {"filename": s.get("filename") or s.get("source"),
             "department": (s.get("metadata") or {}).get("department") or s.get("department")}
            for s in sources if isinstance(s, dict)
        ],
        "chart_generated": chart_spec is not None,
        "chart_type": (chart_spec or {}).get("type"),
        "engine_trace": result.get("trace"),
        "latency_s": round(time.time() - started, 2),
    }
    trace_id = store.save_trace(company, employee, role, question,
                                access_decision, trace_payload)

    answer_text = str(result.get("answer") or "")
    store.save_turn(company, employee, session_id, question, resolved,
                    answer_text[:500], str(result.get("source_type") or ""),
                    (chart_spec or {}).get("type"), refused)

    result["platform"] = {
        "trace_id": trace_id,
        "resolved_question": resolved,
        "followup_rewritten": rewritten,
        "access_decision": access_decision,
        "refused": refused,
        "chart": chart_spec,
        "role": role,
        "company": ctx.company.name,
        "route": result.get("source_type"),
        "llm_skipped": False,
        "model_used": result.get("model_used") or None,
    }
    return result
