"""Admin/CEO Analyst Health Check agent — the analyst of the analyst.

Reverse-engineers problems from saved traces and feedback and produces
actionable recommendations: where the platform should improve (routing, SQL,
RAG, charting, UI, access policy, data quality, providers, or human/Admin
process) and which items only look resolved.

Deliberately deterministic at its core: every finding is reproducible from
the stored records, testable offline, and cheap enough to run on demand. An
optional LLM executive summary can be layered on top (it runs rarely, so a
stronger model is acceptable there), with an honest degraded fallback.

Key honesty rule: a correct role refusal is NOT a bug. The agent separates
valid access denials from patterns that indicate real product problems.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from nexus_platform import store
from nexus_platform.deterministic import parse_intent
from nexus_platform.orchestrator import _DOC_TERMS_RE, _INSIGHT_RE

# Classifications a finding can carry (the fix-ownership taxonomy).
CLASSIFICATIONS = (
    "needs_admin",                # a human must look / decide
    "needs_employee_clarification",  # admin should ask the employee
    "needs_routing_fix",          # Ask Analyst route decision was wrong
    "needs_sql_rag_fix",          # SQL/RAG agent behavior was wrong
    "needs_chart_fix",            # chart type/shape problem
    "needs_ui_fix",               # workflow/UI confusion
    "needs_access_policy_review", # policy may be too tight/loose or unclear
    "data_gap",                   # missing tables/docs/glossary
    "provider_ops",               # provider failures / degraded operations
    "likely_resolved",
    "suspiciously_resolved",
    "valid_access_denial",        # correct behavior — explicitly not a bug
)

_ANSWER_ROUTES = ("deterministic_sql_template", "sql_agent", "rag_agent",
                  "sql_plus_rag", "llm_planner", "sql_only", "rag_only")


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (q or "").lower())).strip()


def _finding(kind: str, classification: str, severity: str, summary: str,
             recommendation: str, evidence: list, suggested_eval: Optional[dict] = None,
             self_fixable: bool = False) -> dict:
    assert classification in CLASSIFICATIONS
    return {
        "kind": kind,
        "classification": classification,
        "severity": severity,          # high | medium | low | info
        "summary": summary,
        "recommendation": recommendation,
        "evidence": evidence[:6],      # trace/feedback ids
        "suggested_eval": suggested_eval,
        "self_fixable": self_fixable,
    }


# ── Individual analyzers ────────────────────────────────────────────────

def _check_wrong_answer_feedback(traces_by_id: dict, feedback: list) -> list:
    """Wrong-answer reports, especially against HIGH-confidence answers."""
    out = []
    for fb in feedback:
        if fb.get("category") not in ("wrong_answer", "issue"):
            continue
        if fb.get("status") == "resolved":
            continue  # handled by the suspicious-resolved analyzer
        tr = traces_by_id.get(fb.get("trace_id"))
        if tr and (tr["payload"].get("confidence") == "HIGH"):
            route = tr["payload"].get("route")
            out.append(_finding(
                "confident_answer_reported_wrong", "needs_sql_rag_fix", "high",
                f"Employee reported a HIGH-confidence {route} answer as wrong: "
                f"“{tr['question'][:90]}”.",
                "Re-run this question against ground-truth SQL; if the answer is "
                "wrong, fix the template/agent and add it as a regression eval. "
                "If the answer is right, reply to the employee with the evidence.",
                [fb["id"], tr["id"]],
                suggested_eval={"question": tr["question"],
                                "expect": "verified numeric answer with provenance"},
            ))
        elif tr is None and fb.get("trace_id"):
            # The trace may simply predate the analysis window.
            if store.get_trace(fb["company"], fb["trace_id"]) is not None:
                continue
            out.append(_finding(
                "feedback_orphan_trace", "needs_admin", "low",
                "Feedback references a trace that no longer exists.",
                "Check trace retention; ask the employee for the question text.",
                [fb["id"]],
            ))
        else:
            out.append(_finding(
                "wrong_answer_no_trace", "needs_employee_clarification", "medium",
                f"Wrong-answer report without a linked trace: “{(fb.get('message') or '')[:90]}”.",
                "Ask the employee which question produced the wrong answer so it "
                "can be reproduced and turned into an eval case.",
                [fb["id"]],
            ))
    return out


def _check_suspicious_resolved(traces_by_id: dict, feedback: list) -> list:
    """Resolved feedback whose underlying trace still looks unhealthy."""
    out = []
    for fb in feedback:
        if fb.get("status") != "resolved":
            continue
        tr = traces_by_id.get(fb.get("trace_id"))
        suspicious_reason = None
        if fb.get("category") in ("wrong_answer", "issue") and tr is not None:
            p = tr["payload"]
            if p.get("route") == "degraded_mode" or p.get("provider_failures"):
                suspicious_reason = "the linked answer ran in degraded/provider-failure mode"
            elif p.get("access_decision") == "denied":
                suspicious_reason = "the linked question was refused — resolution may have just closed the ticket"
            elif p.get("confidence") == "HIGH" and p.get("route") in _ANSWER_ROUTES:
                suspicious_reason = ("the answer was never recomputed after the report "
                                     "(no newer trace for the same question)")
                norm_q = _norm(tr["question"])
                newer = [t for t in traces_by_id.values()
                         if _norm(t["question"]) == norm_q and t["ts"] > tr["ts"]]
                if newer:
                    suspicious_reason = None
        elif fb.get("category") in ("wrong_answer",) and tr is None:
            suspicious_reason = "no trace is linked, so the wrong answer cannot have been verified"

        if suspicious_reason:
            out.append(_finding(
                "suspiciously_resolved_feedback", "suspiciously_resolved", "high",
                f"Feedback {fb['id']} was marked resolved, but {suspicious_reason}.",
                "Reopen and verify: rerun the question, compare with the report, "
                "and only resolve with evidence attached.",
                [fb["id"]] + ([tr["id"]] if tr else []),
            ))
        elif fb.get("status") == "resolved":
            out.append(_finding(
                "resolved_feedback", "likely_resolved", "info",
                f"Feedback {fb['id']} ({fb.get('category')}) appears properly resolved.",
                "No action needed.",
                [fb["id"]],
            ))
    return out


def _check_repeat_without_choice(traces: list) -> list:
    """Same employee+session asked the same question twice and got a full
    re-answer both times with no repeat-choice step in between."""
    out = []
    seen: dict = defaultdict(list)
    for tr in sorted(traces, key=lambda t: t["ts"]):
        p = tr["payload"]
        key = (tr["employee"], p.get("session_id"), _norm(tr["question"]))
        if p.get("route") in _ANSWER_ROUTES and p.get("access_decision") == "allowed":
            if seen[key] and not any(r == "repeat_question_choice" for _, r in seen[key]):
                prior_id = seen[key][-1][0]
                out.append(_finding(
                    "repeat_answered_without_choice", "needs_routing_fix", "medium",
                    f"“{tr['question'][:80]}” was re-answered in the same session "
                    "without offering use-previous / rerun / analyze choices.",
                    "The repeat-question gate should intercept this; add the "
                    "question to the repeat-detection regression tests.",
                    [prior_id, tr["id"]],
                    suggested_eval={"question": tr["question"],
                                    "expect": "repeat_question_choice on second ask"},
                    self_fixable=True,
                ))
        seen[key].append((tr["id"], p.get("route")))
    return out


def _check_clarification_misses(traces: list) -> list:
    """HIGH-confidence answers to questions the clarification gate would now
    stop — replays the current gate over history."""
    from nexus_platform.access_policy import get_policy
    from nexus_platform.orchestrator import find_clarification
    from nexus_platform.deterministic import extract_features

    out = []
    for tr in traces:
        p = tr["payload"]
        if p.get("route") not in ("deterministic_sql_template",):
            continue
        if p.get("confidence") != "HIGH" or p.get("access_decision") != "allowed":
            continue
        if p.get("followup_rewritten"):
            continue  # follow-ups legitimately lean on session context
        f = extract_features(tr["question"])
        clar = find_clarification(tr["question"], f, get_policy(tr["role"]), None)
        if clar is not None:
            out.append(_finding(
                "deterministic_answered_ambiguous_question", "needs_routing_fix", "high",
                f"“{tr['question'][:80]}” got a HIGH-confidence deterministic "
                f"answer but is ambiguous ({clar.kind}) — it should have asked "
                "a clarification question.",
                "Route this phrasing through the clarification gate and add it "
                "as a gate regression test.",
                [tr["id"]],
                suggested_eval={"question": tr["question"],
                                "expect": f"clarification ({clar.kind})"},
                self_fixable=True,
            ))
    return out


def _check_misrouting(traces: list) -> list:
    """LLM answered what SQL should have; SQL answered alone when documents
    were also needed; mixed questions sent to a single source."""
    out = []
    for tr in traces:
        p = tr["payload"]
        route = p.get("route")
        q = tr["question"]
        if p.get("access_decision") != "allowed":
            continue
        # llm_planner is excluded: repeated-question "Analyze with AI" and
        # insight questions deliberately send parseable questions there.
        if route in ("rag_agent", "rag_only"):
            if (not _INSIGHT_RE.search(" " + q.lower() + " ")
                    and not _DOC_TERMS_RE.search(" " + q.lower() + " ")
                    and parse_intent(q) is not None):
                out.append(_finding(
                    "llm_answered_deterministic_question", "needs_routing_fix", "medium",
                    f"“{q[:80]}” went to {route} but parses as a deterministic "
                    "SQL family — slower, costlier, and less verifiable.",
                    "Confirm the deterministic parser covers this phrasing and "
                    "add it to the parser regression tests.",
                    [tr["id"]],
                    suggested_eval={"question": q, "expect": "deterministic_sql_template"},
                    self_fixable=True,
                ))
        if route in ("sql_agent", "sql_only", "deterministic_sql_template"):
            if _DOC_TERMS_RE.search(" " + q.lower() + " "):
                out.append(_finding(
                    "sql_answer_missing_document_context", "needs_routing_fix", "medium",
                    f"“{q[:80]}” mentions policies/documents but was answered "
                    "from SQL only — the document side of the question was dropped.",
                    "Route policy+numbers questions to sql_plus_rag so the answer "
                    "cites both evidence types.",
                    [tr["id"]],
                    suggested_eval={"question": q, "expect": "sql_plus_rag"},
                    self_fixable=True,
                ))
        if route in ("rag_agent", "rag_only"):
            citations = p.get("citations") or []
            if not citations:
                out.append(_finding(
                    "rag_answer_without_citations", "needs_sql_rag_fix", "high",
                    f"Document-routed answer for “{q[:80]}” cites no documents — "
                    "either evidence was weak (should have abstained/clarified) "
                    "or citation capture is broken.",
                    "Check retrieval for this question; if evidence is genuinely "
                    "thin, the company corpus has a gap for this topic.",
                    [tr["id"]],
                ))
    return out


def _check_chart_issues(traces: list) -> list:
    out = []
    for tr in traces:
        p = tr["payload"]
        q = (tr["question"] or "").lower()
        if p.get("access_decision") != "allowed":
            continue
        wanted_pie = bool(re.search(r"\bpie\b", q))
        got = p.get("chart_type")
        if wanted_pie and got in ("bar", "line") and p.get("route") != "clarification":
            out.append(_finding(
                "silent_wrong_chart_type", "needs_chart_fix", "medium",
                f"Employee asked for a pie chart but got a {got} chart with no "
                f"explanation: “{tr['question'][:80]}”.",
                "Either render a category pie or explain why bar/line fits better "
                "and offer choices — never silently substitute.",
                [tr["id"]],
                suggested_eval={"question": tr["question"],
                                "expect": "pie or explained alternative"},
                self_fixable=True,
            ))
        if p.get("chart_generated") and not got:
            out.append(_finding(
                "malformed_chart_answer", "needs_chart_fix", "medium",
                f"A chart was generated without a type for “{tr['question'][:80]}” "
                "— the client cannot render it.",
                "Fix the chart spec builder for this result shape.",
                [tr["id"]],
                self_fixable=True,
            ))
    return out


def _check_refusal_patterns(traces: list) -> list:
    """Separate correct one-off denials from patterns that mean confusion."""
    out = []
    refusals = [t for t in traces if t["payload"].get("access_decision") == "denied"]
    by_role_area: dict = defaultdict(list)
    for tr in refusals:
        reason = str(tr["payload"].get("denied_reason") or "restricted area")
        area = reason.split("'")[1] if "'" in reason else reason[:40]
        by_role_area[(tr["role"], area)].append(tr)

    for (role, area), items in by_role_area.items():
        if len(items) >= 3:
            employees = {t["employee"] for t in items}
            out.append(_finding(
                "repeated_role_refusals", "needs_access_policy_review", "medium",
                f"{len(items)} refusals for {role} on '{area}' "
                f"({len(employees)} employee(s)) — either the role scope is "
                "unclear in the UI or these employees genuinely need the data.",
                "Show the role's data scope more prominently on the Ask page, "
                "or review whether this role should get read access to this area.",
                [t["id"] for t in items],
            ))
        else:
            out.append(_finding(
                "valid_access_refusal", "valid_access_denial", "info",
                f"{role} was correctly refused on '{area}' — access control "
                "working as designed, not a bug.",
                "No action needed.",
                [t["id"] for t in items],
            ))
    return out


def _check_provider_health(traces: list) -> list:
    out = []
    failures = Counter()
    degraded_ids = []
    failure_ids = []
    for tr in traces:
        p = tr["payload"]
        for f in p.get("provider_failures") or []:
            failures[f.get("model") or "unknown"] += 1
            failure_ids.append(tr["id"])
        if p.get("route") == "degraded_mode":
            degraded_ids.append(tr["id"])
    if degraded_ids:
        out.append(_finding(
            "degraded_mode_answers", "provider_ops", "high",
            f"{len(degraded_ids)} question(s) got degraded-mode answers — every "
            "provider was exhausted at those moments.",
            "Deterministic/SQL/RAG families kept working by design; consider "
            "queueing planner jobs for retry and checking provider quotas.",
            degraded_ids,
        ))
    if failures:
        top = ", ".join(f"{m} ×{c}" for m, c in failures.most_common(3))
        out.append(_finding(
            "provider_failures", "provider_ops", "medium",
            f"Provider failures recorded during answers: {top}.",
            "Expected operational state under free-tier quotas; verify fallback "
            "order and cooldowns absorbed them (answers still completed).",
            failure_ids,
        ))
    return out


def _check_data_gaps(traces: list) -> list:
    """Clusters of unanswerable/no-data questions point at missing tables,
    documents, or glossary entries — a data problem, not an agent problem."""
    out = []
    misses = [t for t in traces
              if t["payload"].get("route") in ("no_data",)
              or (t["payload"].get("route") in ("rag_agent", "rag_only")
                  and not (t["payload"].get("citations") or []))]
    by_topic: dict = defaultdict(list)
    for tr in misses:
        words = [w for w in _norm(tr["question"]).split()
                 if len(w) > 4 and w not in ("about", "what", "which", "there")]
        topic = words[0] if words else "unknown"
        by_topic[topic].append(tr)
    for topic, items in by_topic.items():
        if len(items) >= 3:
            depts = Counter(t["role"] for t in items)
            out.append(_finding(
                "clustered_unanswerable_topic", "data_gap", "high",
                f"{len(items)} questions about “{topic}” could not be answered "
                f"from company data (mostly {depts.most_common(1)[0][0]}).",
                f"The workspace likely needs a document, glossary entry, or table "
                f"covering “{topic}”. Add it to the company folder and rebuild "
                "the brain.",
                [t["id"] for t in items],
            ))
    return out


def _check_volume_and_load(traces: list) -> tuple[list, dict]:
    latencies = sorted([float(t["payload"].get("latency_s") or 0)
                        for t in traces if t["payload"].get("latency_s")])
    stats = {
        "traces": len(traces),
        "employees_active": len({t["employee"] for t in traces}),
        "p50_latency_s": latencies[len(latencies) // 2] if latencies else None,
        "p95_latency_s": latencies[int(len(latencies) * 0.95)] if latencies else None,
    }
    out = []
    by_emp = Counter()
    for t in traces:
        if t["payload"].get("route") in ("clarification",) or \
           t["payload"].get("access_decision") == "denied":
            by_emp[t["employee"]] += 1
    for emp, n in by_emp.most_common(3):
        if n >= 5:
            out.append(_finding(
                "employee_friction", "needs_employee_clarification", "medium",
                f"{emp} hit {n} clarifications/refusals in the window — they may "
                "be trying to do something the workspace doesn't support yet.",
                "Ask the employee what they're trying to accomplish; their goal "
                "may reveal a missing metric, document, or access need.",
                [],
            ))
    return out, stats


# ── The agent ───────────────────────────────────────────────────────────

def run_health_check(company: str, requested_by: str = "admin",
                     window_days: int = 30, llm_summary: bool = False,
                     save: bool = True) -> dict:
    """Analyze the company's traces + feedback and produce a recommendations
    report. Deterministic core; optional LLM executive summary on top."""
    date_from = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    traces = store.list_traces_with_payload(company, date_from=date_from)
    feedback = store.list_feedback(company)
    traces_by_id = {t["id"]: t for t in traces}

    findings: list = []
    findings += _check_wrong_answer_feedback(traces_by_id, feedback)
    findings += _check_suspicious_resolved(traces_by_id, feedback)
    findings += _check_repeat_without_choice(traces)
    findings += _check_clarification_misses(traces)
    findings += _check_misrouting(traces)
    findings += _check_chart_issues(traces)
    findings += _check_refusal_patterns(traces)
    findings += _check_provider_health(traces)
    findings += _check_data_gaps(traces)
    friction, stats = _check_volume_and_load(traces)
    findings += friction

    sev_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings.sort(key=lambda f: sev_rank.get(f["severity"], 9))

    actionable = [f for f in findings if f["severity"] in ("high", "medium")]
    good = [f for f in findings if f["classification"] in
            ("valid_access_denial", "likely_resolved")]
    evals = [f["suggested_eval"] for f in findings if f.get("suggested_eval")]

    routes = Counter(t["payload"].get("route") or "unknown" for t in traces)
    summary_text = (
        f"{stats['traces']} questions from {stats['employees_active']} employees "
        f"in the last {window_days} days. "
        f"{len(actionable)} finding(s) need attention "
        f"({sum(1 for f in actionable if f['severity'] == 'high')} high). "
        f"{len(good)} signal(s) confirm correct behavior. "
        f"Top routes: {', '.join(f'{r} ×{c}' for r, c in routes.most_common(4))}."
    )

    report = {
        "company": company,
        "window_days": window_days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_by": requested_by,
        "stats": {**stats, "feedback": len(feedback),
                  "routes": dict(routes),
                  "refusals": sum(1 for t in traces
                                  if t["payload"].get("access_decision") == "denied"),
                  "clarifications": routes.get("clarification", 0),
                  "degraded": routes.get("degraded_mode", 0)},
        "summary": summary_text,
        "findings": findings,
        "suggested_evals": evals[:20],
        "llm_summary": None,
        "llm_summary_status": "not_requested",
    }

    if llm_summary:
        report["llm_summary"], report["llm_summary_status"] = \
            _executive_summary(report)

    if save:
        report["report_id"] = store.save_health_report(
            company, requested_by, window_days, report)
    return report


def _executive_summary(report: dict) -> tuple[Optional[str], str]:
    """Optional stronger-model narrative. Health checks run rarely, so a
    reasoning model is affordable here; failure degrades honestly."""
    try:
        from config.settings import settings
        from utils.llm_gateway import get_llm_gateway, insert_cerebras_fallback
        from utils.quota_tracker import quota_tracker

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
        models = insert_cerebras_fallback(models, reasoning=True)
        if not models:
            return None, "no_providers_configured"

        top = [
            {k: f[k] for k in ("kind", "classification", "severity", "summary",
                               "recommendation")}
            for f in report["findings"] if f["severity"] in ("high", "medium")
        ][:12]
        prompt = (
            "You are the analyst-platform health reviewer for an internal AI "
            "data analyst. Write a short executive summary (5-8 sentences) for "
            "the company Admin. Use ONLY the facts below; do not invent "
            "numbers or incidents. Prioritize what to fix first and say which "
            "items are working as designed.\n\n"
            f"Stats: {report['stats']}\n\nFindings: {top}\n"
        )
        result = get_llm_gateway().invoke_with_fallback(
            prompt=prompt, models=models, tracker=quota_tracker,
            task="health_check.executive_summary", temperature=0.2,
            metadata={"agent": "health_check"},
            response_validator=lambda c: len(c.strip()) > 50,
        )
        if result.get("success"):
            return str(result["response"]).strip(), f"ok ({result.get('model_used')})"
        return None, "providers_unavailable"
    except Exception as exc:  # pragma: no cover - defensive
        return None, f"error: {str(exc)[:80]}"
