"""Platform query pipeline: memory → rewrite → role-scoped agents → filter →
trace → chart.

The evidence boundary itself lives inside the (company, role) agent instance
(schema subset, AST allowlist, RAG department filter). This service adds the
per-employee layers on top: session memory, follow-up rewrite, refusal
wording, citation re-filtering, chart specs, and the saved product trace.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Optional

from nexus_platform import store
from nexus_platform.access_policy import classify_restricted_intent, refusal_message
from nexus_platform.auth import AccessContext
from nexus_platform.charts import build_chart_spec, wants_chart
from nexus_platform.contexts import get_company_fusion_agent

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


def run_query(ctx: AccessContext, question: str, session_id: str) -> dict:
    """Execute one analyst query inside the caller's access boundary."""
    started = time.time()
    company = ctx.company.slug
    employee = ctx.employee.email
    role = ctx.employee.role
    prefs = store.get_prefs(company, employee)

    key = f"company:{company}:{role.lower()}"
    agent = get_company_fusion_agent(company, role)
    turns = store.recent_turns(company, employee, session_id, limit=10)

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
    }
    return result
