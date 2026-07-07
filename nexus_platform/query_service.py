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

import re

from nexus_platform import store
from nexus_platform.access_policy import classify_restricted_intent, refusal_message
from nexus_platform.auth import AccessContext
from nexus_platform.charts import build_chart_spec, wants_chart
from nexus_platform.contexts import get_company_fusion_agent
from nexus_platform.dashboard import build_dashboard, wants_dashboard
from nexus_platform.deterministic import Intent, execute as deterministic_execute, parse_intent
from nexus_platform.orchestrator import RouteDecision, decide_route
from nexus_platform.registry import Company, get_registry

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
        "route": "access_refusal" if refused else "deterministic_sql_template",
        "engine_route": "deterministic_sql_template",
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
                    tables_json=json.dumps(det["tables"]),
                    trace_id=trace_id,
                    chart_json=(json.dumps(det["chart"]) if det["chart"] and not refused else None))

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
            "route": "access_refusal" if refused else "deterministic_sql_template",
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
            "route": "access_refusal" if refused else "dashboard",
            "llm_skipped": True,
            "model_used": None,
        },
    }


_ANSWERED_ROUTES = ("deterministic_sql_template", "sql_agent", "rag_agent",
                    "sql_plus_rag", "llm_planner", "sql_only", "rag_only",
                    "sql_rag", "all", "comparison")


def _normalize_question(q: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", q.lower())).strip()


def _company_aliases(company: Company) -> list[str]:
    aliases = {company.slug, company.name.lower()}
    domain_root = company.domain.split(".", 1)[0].lower()
    aliases.add(domain_root)
    name_words = re.findall(r"[a-z0-9]+", company.name.lower())
    if name_words:
        aliases.add(name_words[0])
    return sorted((a for a in aliases if len(a) >= 4), key=len, reverse=True)


def _mentioned_other_companies(question: str, ctx: AccessContext) -> list[Company]:
    normalized = f" {_normalize_question(question)} "
    mentioned: list[Company] = []
    for company in get_registry().companies.values():
        if company.slug == ctx.company.slug:
            continue
        for alias in _company_aliases(company):
            pattern = rf" {re.escape(_normalize_question(alias))} "
            if re.search(pattern, normalized):
                mentioned.append(company)
                break
    return mentioned


def _replace_company_mentions(question: str, mentioned: list[Company],
                              current_name: str) -> str:
    rewritten = question
    for company in mentioned:
        for alias in _company_aliases(company):
            rewritten = re.sub(rf"\b{re.escape(alias)}\b", current_name,
                               rewritten, flags=re.IGNORECASE)
    return rewritten


def _find_repeat(turns: list, question: str) -> Optional[dict]:
    """Latest prior turn in this session that answered the same question."""
    norm = _normalize_question(question)
    if not norm:
        return None
    for t in reversed(turns):
        if t.get("refused"):
            continue
        route = (t.get("route") or t.get("source_type") or "")
        if route not in _ANSWERED_ROUTES:
            continue
        if _normalize_question(t.get("question") or "") == norm:
            return t
    return None


def _base_trace(ctx: AccessContext, question: str, session_id: str,
                memory_turns: int) -> dict:
    return {
        "employee": ctx.employee.email,
        "employee_name": ctx.employee.name,
        "company": ctx.company.slug,
        "company_name": ctx.company.name,
        "role": ctx.employee.role,
        "session_id": session_id,
        "question": question,
        "resolved_question": question,
        "followup_rewritten": False,
        "memory_turns_used": memory_turns,
        "access_policy": {
            "allowed_tables": list(ctx.policy.allowed_tables),
            "allowed_departments": list(ctx.policy.allowed_departments),
        },
        "citations": [],
    }


def _finish_clarification(ctx: AccessContext, question: str, session_id: str,
                          decision: RouteDecision, memory_turns: int) -> dict:
    """Ask one short question back instead of guessing. No data is read."""
    started = time.time()
    clar = decision.clarification.to_payload()
    answer = clar["question"]

    trace_payload = {
        **_base_trace(ctx, question, session_id, memory_turns),
        "access_decision": "allowed",
        "denied_reason": None,
        "route": "clarification",
        "clarification_kind": clar["kind"],
        "clarification_choices": clar["choices"],
        "route_reason": decision.reason,
        "llm_skipped": True,
        "model_used": None,
        "confidence": "N/A",
        "sql": None,
        "chart_generated": False,
        "chart_type": None,
        "latency_s": round(time.time() - started, 3),
    }
    trace_id = store.save_trace(ctx.company.slug, ctx.employee.email,
                                ctx.employee.role, question, "allowed",
                                trace_payload)
    store.save_turn(ctx.company.slug, ctx.employee.email, session_id,
                    question, question, answer[:500], "clarification",
                    None, False, route="clarification", trace_id=trace_id)

    reason = "The question was ambiguous — asking for one detail beats a confidently wrong answer."
    return {
        "answer": answer,
        "confidence": "N/A",
        "confidence_reason": reason,
        "validation": {"confidence": "N/A", "confidence_reason": reason},
        "source_type": "clarification",
        "sources": [],
        "sql_result": None,
        "platform": {
            "trace_id": trace_id,
            "resolved_question": question,
            "followup_rewritten": False,
            "access_decision": "allowed",
            "refused": False,
            "chart": None,
            "dashboard": None,
            "role": ctx.employee.role,
            "company": ctx.company.name,
            "route": "clarification",
            "clarification": clar,
            "llm_skipped": True,
            "model_used": None,
        },
    }


def _finish_cross_company_scope(ctx: AccessContext, question: str,
                                session_id: str, mentioned: list[Company]) -> dict:
    """Named another demo company: clarify/refuse before reading any data."""
    started = time.time()
    names = ", ".join(c.name for c in mentioned)
    current_version = _replace_company_mentions(question, mentioned, ctx.company.name)
    choices = [current_version]
    if not wants_dashboard(question):
        choices.append(f"Give me a {ctx.company.name} dashboard")
    choices = [c for i, c in enumerate(choices) if c and c not in choices[:i]][:3]
    question_back = (
        f"I can only access {ctx.company.name} from your current session. "
        f"You mentioned {names}. I can answer the {ctx.company.name} version, "
        f"or you can sign into a {names} account."
    )
    clar = {
        "kind": "cross_company_scope",
        "question": question_back,
        "choices": choices,
        "mentioned_companies": [c.name for c in mentioned],
        "current_company": ctx.company.name,
    }
    trace_payload = {
        **_base_trace(ctx, question, session_id, 0),
        "access_decision": "denied",
        "denied_reason": f"requested another company workspace: {names}",
        "route": "cross_company_scope_clarification",
        "clarification_kind": "cross_company_scope",
        "clarification_choices": choices,
        "mentioned_companies": [c.slug for c in mentioned],
        "route_reason": "question named a different company workspace",
        "llm_skipped": True,
        "model_used": None,
        "confidence": "N/A",
        "sql": None,
        "chart_generated": False,
        "chart_type": None,
        "latency_s": round(time.time() - started, 3),
    }
    trace_id = store.save_trace(ctx.company.slug, ctx.employee.email,
                                ctx.employee.role, question, "denied",
                                trace_payload)
    store.save_turn(ctx.company.slug, ctx.employee.email, session_id,
                    question, question, question_back[:500],
                    "cross_company_scope_clarification", None, True,
                    route="cross_company_scope_clarification",
                    trace_id=trace_id)
    reason = "Tenant scope clarification — no other-company data was read."
    return {
        "answer": question_back,
        "confidence": "N/A",
        "confidence_reason": reason,
        "validation": {"confidence": "N/A", "confidence_reason": reason},
        "source_type": "cross_company_scope_clarification",
        "sources": [],
        "sql_result": None,
        "platform": {
            "trace_id": trace_id,
            "resolved_question": question,
            "followup_rewritten": False,
            "access_decision": "denied",
            "refused": True,
            "chart": None,
            "dashboard": None,
            "role": ctx.employee.role,
            "company": ctx.company.name,
            "route": "cross_company_scope_clarification",
            "clarification": clar,
            "llm_skipped": True,
            "model_used": None,
        },
    }


def _finish_repeat_choice(ctx: AccessContext, question: str, session_id: str,
                          prior: dict, memory_turns: int) -> dict:
    """Same question again in one session → offer choices, don't silently redo."""
    started = time.time()
    prior_ts = prior.get("ts")
    answer = ("You asked this earlier in this session. Want the previous "
              "answer, a fresh recomputation from current data, or an AI "
              "reinterpretation of the question?")
    repeat_payload = {
        "options": ["use_previous", "rerun", "analyze_with_ai"],
        "previous": {
            "trace_id": prior.get("trace_id"),
            "ts": prior_ts,
            "answer": prior.get("answer_summary"),
            "route": prior.get("route") or prior.get("source_type"),
        },
    }
    trace_payload = {
        **_base_trace(ctx, question, session_id, memory_turns),
        "access_decision": "allowed",
        "denied_reason": None,
        "route": "repeat_question_choice",
        "previous_trace_id": prior.get("trace_id"),
        "llm_skipped": True,
        "model_used": None,
        "confidence": "N/A",
        "sql": None,
        "chart_generated": False,
        "chart_type": None,
        "latency_s": round(time.time() - started, 3),
    }
    trace_id = store.save_trace(ctx.company.slug, ctx.employee.email,
                                ctx.employee.role, question, "allowed",
                                trace_payload)
    store.save_turn(ctx.company.slug, ctx.employee.email, session_id,
                    question, question, answer[:500], "repeat_question_choice",
                    None, False, route="repeat_question_choice", trace_id=trace_id)

    reason = "Repeated question — waiting for your choice instead of silently re-answering."
    return {
        "answer": answer,
        "confidence": "N/A",
        "confidence_reason": reason,
        "validation": {"confidence": "N/A", "confidence_reason": reason},
        "source_type": "repeat_question_choice",
        "sources": [],
        "sql_result": None,
        "platform": {
            "trace_id": trace_id,
            "resolved_question": question,
            "followup_rewritten": False,
            "access_decision": "allowed",
            "refused": False,
            "chart": None,
            "dashboard": None,
            "role": ctx.employee.role,
            "company": ctx.company.name,
            "route": "repeat_question_choice",
            "repeat": repeat_payload,
            "llm_skipped": True,
            "model_used": None,
        },
    }


def _finish_use_previous(ctx: AccessContext, question: str, session_id: str,
                         prior: dict, memory_turns: int) -> dict:
    """Return the prior answer with its provenance — zero recomputation."""
    started = time.time()
    answer = prior.get("answer_summary") or ""
    chart = None
    if prior.get("chart_json"):
        try:
            chart = json.loads(prior["chart_json"])
        except (ValueError, TypeError):
            chart = None
    trace_payload = {
        **_base_trace(ctx, question, session_id, memory_turns),
        "access_decision": "allowed",
        "denied_reason": None,
        "route": "repeat_used_previous",
        "previous_trace_id": prior.get("trace_id"),
        "llm_skipped": True,
        "model_used": None,
        "confidence": "HIGH",
        "sql": prior.get("sql"),
        "chart_generated": chart is not None,
        "chart_type": (chart or {}).get("type"),
        "latency_s": round(time.time() - started, 3),
    }
    trace_id = store.save_trace(ctx.company.slug, ctx.employee.email,
                                ctx.employee.role, question, "allowed",
                                trace_payload)
    store.save_turn(ctx.company.slug, ctx.employee.email, session_id,
                    question, question, answer[:500], "repeat_used_previous",
                    (chart or {}).get("type"), False,
                    route="repeat_used_previous", trace_id=trace_id)

    reason = (f"Reused your previous answer from this session "
              f"(trace {prior.get('trace_id')}) — data was not recomputed.")
    return {
        "answer": answer,
        "confidence": "HIGH",
        "confidence_reason": reason,
        "validation": {"confidence": "HIGH", "confidence_reason": reason},
        "source_type": "repeat_used_previous",
        "sources": [],
        "sql_result": None,
        "platform": {
            "trace_id": trace_id,
            "resolved_question": question,
            "followup_rewritten": False,
            "access_decision": "allowed",
            "refused": False,
            "chart": chart,
            "dashboard": None,
            "role": ctx.employee.role,
            "company": ctx.company.name,
            "route": "repeat_used_previous",
            "previous_trace_id": prior.get("trace_id"),
            "previous_ts": prior.get("ts"),
            "llm_skipped": True,
            "model_used": None,
        },
    }


_PLANNER_FRAMING = (
    "\n\nAnswer like a careful data analyst: state what happened using only "
    "numbers from the data sources, the likely drivers, what evidence "
    "supports them, what remains uncertain, and one recommended follow-up "
    "analysis. Never invent numbers."
)

_ROUTE_LABELS = {
    "sql_only": "sql_agent",
    "rag_only": "rag_agent",
    "sql_rag": "sql_plus_rag",
    "all": "sql_plus_rag",
    "comparison": "rag_agent",
    "web_only": "web_agent",
    "no_data": "no_data",
    "access_refusal": "access_refusal",
}


def _degraded_suggestions(ctx: AccessContext) -> list:
    from nexus_platform.orchestrator import role_metric_choices
    return role_metric_choices(ctx.policy)


def run_query(ctx: AccessContext, question: str, session_id: str,
              repeat_action: Optional[str] = None) -> dict:
    """Execute one analyst query inside the caller's access boundary."""
    started = time.time()
    company = ctx.company.slug
    employee = ctx.employee.email
    role = ctx.employee.role
    prefs = store.get_prefs(company, employee)

    mentioned = _mentioned_other_companies(question, ctx)
    if mentioned:
        return _finish_cross_company_scope(ctx, question, session_id, mentioned)

    # Dashboard requests are deterministic role-filtered SQL — no LLM, no
    # follow-up rewrite needed, instant.
    if wants_dashboard(question):
        return _run_dashboard(ctx, question, session_id)

    turns = store.recent_turns(company, employee, session_id, limit=10)

    prev_intent = None
    for t in reversed(turns):
        if t.get("intent_json"):
            prev_intent = Intent.from_json(t["intent_json"])
            break

    # Repeated question → choice card (or the chosen action).
    prior = _find_repeat(turns, question)
    if prior is not None:
        if repeat_action is None:
            return _finish_repeat_choice(ctx, question, session_id, prior, len(turns))
        if repeat_action == "use_previous":
            return _finish_use_previous(ctx, question, session_id, prior, len(turns))
        # "rerun" falls through to normal routing; "analyze_with_ai" is
        # handled by the route decision below.

    decision = decide_route(question, ctx.policy, prev_intent, repeat_action)

    if decision.route == "clarification":
        return _finish_clarification(ctx, question, session_id, decision, len(turns))

    if decision.route == "deterministic_sql":
        det = deterministic_execute(ctx, decision.intent)
        if det is not None:
            return _finish_deterministic(ctx, question, session_id,
                                         decision.intent, det,
                                         memory_turns=len(turns))
        decision = RouteDecision(route="agent",
                                 reason="deterministic combo unsupported; engine routes")

    # ── LLM engine path (SQL agent / RAG agent / planner) ────────────────
    force_source = decision.force_source
    if decision.route == "llm_planner":
        force_source = force_source or "sql_rag"

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
                engine_question = resolved
                if decision.insight:
                    engine_question = resolved + _PLANNER_FRAMING
                try:
                    result = agent.query(engine_question, force_source=force_source)
                except TypeError:
                    # Engine stand-ins without force_source keep working.
                    result = agent.query(engine_question)
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

    # Provider exhaustion / engine failure → honest degraded mode, never a
    # raw error or a made-up answer.
    degraded = (not refused
                and (str(result.get("source_type") or "") == "error"
                     or (not str(result.get("answer") or "").strip()
                         and result.get("error"))))
    if degraded:
        suggestions = _degraded_suggestions(ctx)
        result["answer"] = (
            "The reasoning models are unavailable right now, so I can't "
            "analyze this question yet. Deterministic analytics still work — "
            "try one of these, or ask me again in a few minutes: "
            + "; ".join(f"“{s}”" for s in suggestions[:3]) + "."
        )
        result["confidence"] = "LOW"
        result["confidence_reason"] = "All model providers failed; no analysis was performed."
        result["validation"] = {"confidence": "LOW",
                                "confidence_reason": result["confidence_reason"]}
        result["sql_result"] = None
        result["sources"] = []
        sources = []

    chart_spec = None
    if not refused and not degraded:
        preferred = prefs.get("preferred_chart_type")
        if wants_chart(question) or preferred:
            chart_spec = build_chart_spec(resolved, result.get("sql_result"),
                                          preferred_type=preferred)
        _update_prefs(ctx, resolved, chart_spec if wants_chart(question) else None)

    if refused:
        route_label = "access_refusal"
    elif degraded:
        route_label = "degraded_mode"
    elif decision.route in ("llm_planner", "sql_plus_rag"):
        route_label = decision.route
    else:
        engine_type = str(result.get("source_type") or "")
        route_label = _ROUTE_LABELS.get(engine_type, engine_type or "unknown")

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
        "route": route_label,
        "engine_route": result.get("source_type"),
        "route_reason": decision.reason,
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
                    (chart_spec or {}).get("type"), refused,
                    route=route_label, trace_id=trace_id,
                    chart_json=(json.dumps(chart_spec) if chart_spec else None))

    result["platform"] = {
        "trace_id": trace_id,
        "resolved_question": resolved,
        "followup_rewritten": rewritten,
        "access_decision": access_decision,
        "refused": refused,
        "chart": chart_spec,
        "role": role,
        "company": ctx.company.name,
        "route": route_label,
        "engine_route": result.get("source_type"),
        "llm_skipped": False,
        "model_used": result.get("model_used") or None,
    }
    if degraded:
        result["platform"]["degraded"] = True
        result["platform"]["followups"] = _degraded_suggestions(ctx)[:3]
    return result
