"""Health Check agent self-attack suite.

Adversarial trace/feedback fixtures from the final-run spec: the agent must
catch real problems (wrong answers, misroutes, chart lies, suspicious
resolutions, data gaps, provider failures), must NOT flag correct refusals
as bugs, and must classify who owns each fix.
"""

import uuid

import pytest

from nexus_platform import store
from nexus_platform.health_check import run_health_check


def fresh_company() -> str:
    """Isolated company slug so fixtures never touch real demo data."""
    return f"healthco_{uuid.uuid4().hex[:8]}"


def make_trace(company: str, *, employee="emp@healthco.test", role="Analyst",
               question="What was total revenue in Q3 2024?",
               route="deterministic_sql_template", decision="allowed",
               confidence="HIGH", session="s1", chart_type=None,
               chart_generated=False, citations=None, provider_failures=None,
               denied_reason=None, followup_rewritten=False,
               latency_s=0.2) -> str:
    payload = {
        "employee": employee, "role": role, "company": company,
        "session_id": session, "question": question,
        "resolved_question": question, "followup_rewritten": followup_rewritten,
        "route": route, "access_decision": decision, "confidence": confidence,
        "chart_type": chart_type, "chart_generated": chart_generated,
        "citations": citations if citations is not None else [],
        "provider_failures": provider_failures or [],
        "denied_reason": denied_reason, "latency_s": latency_s,
        "llm_skipped": route == "deterministic_sql_template",
    }
    return store.save_trace(company, employee, role, question, decision, payload)


def kinds(report):
    return [f["kind"] for f in report["findings"]]


def by_kind(report, kind):
    return [f for f in report["findings"] if f["kind"] == kind]


# ── Fixture 1: confidently wrong deterministic answer (via feedback) ─────

def test_detects_confident_answer_reported_wrong():
    c = fresh_company()
    tid = make_trace(c, question="What was total revenue in Q3 2024?")
    store.save_feedback(c, "emp@healthco.test", "Analyst", "wrong_answer",
                        "Q3 revenue looks wrong vs the board deck", "ask", tid)
    report = run_health_check(c, save=False)
    hits = by_kind(report, "confident_answer_reported_wrong")
    assert hits and hits[0]["classification"] == "needs_sql_rag_fix"
    assert tid in hits[0]["evidence"]
    assert hits[0]["suggested_eval"]["question"]


# ── Fixture 2: malformed/partial chart answer ────────────────────────────

def test_detects_malformed_chart():
    c = fresh_company()
    make_trace(c, question="revenue by region chart",
               chart_generated=True, chart_type=None)
    report = run_health_check(c, save=False)
    assert by_kind(report, "malformed_chart_answer")


# ── Fixture 3: repeated question re-answered without choices ─────────────

def test_detects_repeat_answered_without_choice():
    c = fresh_company()
    q = "How many orders in Q2 2024?"
    make_trace(c, question=q, session="s9")
    make_trace(c, question=q, session="s9")
    report = run_health_check(c, save=False)
    hits = by_kind(report, "repeat_answered_without_choice")
    assert hits and hits[0]["self_fixable"]


def test_repeat_with_choice_step_is_clean():
    c = fresh_company()
    q = "How many orders in Q2 2024?"
    make_trace(c, question=q, session="s9")
    make_trace(c, question=q, session="s9", route="repeat_question_choice",
               confidence="N/A")
    report = run_health_check(c, save=False)
    assert not by_kind(report, "repeat_answered_without_choice")


# ── Fixture 4/5: refusals — correct one-offs vs confusing patterns ───────

def test_single_refusal_is_valid_not_a_bug():
    c = fresh_company()
    make_trace(c, question="What is our headcount?", route="access_refusal",
               decision="denied", denied_reason="the 'employees_hr' data area is outside your role")
    report = run_health_check(c, save=False)
    valid = by_kind(report, "valid_access_refusal")
    assert valid and valid[0]["classification"] == "valid_access_denial"
    assert not by_kind(report, "repeated_role_refusals")


def test_repeated_refusals_flag_policy_confusion():
    c = fresh_company()
    for i in range(4):
        make_trace(c, employee=f"a{i}@healthco.test",
                   question="attrition rate by department",
                   route="access_refusal", decision="denied",
                   denied_reason="the 'employees_hr' data area is outside your role")
    report = run_health_check(c, save=False)
    hits = by_kind(report, "repeated_role_refusals")
    assert hits and hits[0]["classification"] == "needs_access_policy_review"


# ── Fixture 6: feedback resolved while still suspicious ──────────────────

def test_detects_suspiciously_resolved_feedback():
    c = fresh_company()
    tid = make_trace(c, question="MRR in Q4?", route="degraded_mode",
                     confidence="LOW")
    fid = store.save_feedback(c, "emp@healthco.test", "Analyst",
                              "wrong_answer", "the MRR answer failed", "ask", tid)
    store.update_feedback_status(c, fid, "resolved")
    report = run_health_check(c, save=False)
    hits = by_kind(report, "suspiciously_resolved_feedback")
    assert hits and hits[0]["classification"] == "suspiciously_resolved"


def test_properly_rechecked_feedback_is_likely_resolved():
    c = fresh_company()
    q = "What was total revenue in Q1 2024?"
    tid = make_trace(c, question=q)
    fid = store.save_feedback(c, "emp@healthco.test", "Analyst",
                              "wrong_answer", "check this", "ask", tid)
    make_trace(c, question=q)  # newer recomputation exists
    store.update_feedback_status(c, fid, "resolved")
    report = run_health_check(c, save=False)
    assert not by_kind(report, "suspiciously_resolved_feedback")
    assert by_kind(report, "resolved_feedback")


# ── Fixture 7: policy/RAG answer with weak evidence ──────────────────────

def test_detects_rag_answer_without_citations():
    c = fresh_company()
    make_trace(c, question="What is the discount escalation guideline?",
               route="rag_agent", citations=[])
    report = run_health_check(c, save=False)
    assert by_kind(report, "rag_answer_without_citations")


def test_cited_rag_answer_is_clean():
    c = fresh_company()
    make_trace(c, question="What is the discount escalation guideline?",
               route="rag_agent",
               citations=[{"filename": "finance_policy.md", "department": "finance"}])
    report = run_health_check(c, save=False)
    assert not by_kind(report, "rag_answer_without_citations")


# ── Fixture 8: LLM answer that should have used SQL ──────────────────────

def test_detects_llm_answering_deterministic_question():
    c = fresh_company()
    make_trace(c, question="What was total revenue in Q3 2024?",
               route="rag_agent",
               citations=[{"filename": "board.md", "department": "finance"}])
    report = run_health_check(c, save=False)
    hits = by_kind(report, "llm_answered_deterministic_question")
    assert hits and hits[0]["classification"] == "needs_routing_fix"


# ── Fixture 9: SQL answer that ignored the document half ─────────────────

def test_detects_sql_answer_missing_document_context():
    c = fresh_company()
    make_trace(c, question="discount policy impact on Q4 revenue",
               route="sql_agent")
    report = run_health_check(c, save=False)
    assert by_kind(report, "sql_answer_missing_document_context")


# ── Fixture 10: silent wrong chart type ──────────────────────────────────

def test_detects_silent_wrong_chart():
    c = fresh_company()
    make_trace(c, question="pie chart of revenue by month",
               chart_generated=True, chart_type="line")
    report = run_health_check(c, save=False)
    assert by_kind(report, "silent_wrong_chart_type")


# ── Fixture 11: provider failures / degraded traces ──────────────────────

def test_detects_provider_failures_and_degraded_mode():
    c = fresh_company()
    make_trace(c, question="why did revenue drop?", route="degraded_mode",
               confidence="LOW",
               provider_failures=[{"model": "gemini-2.5-flash", "error": "429 quota"}])
    report = run_health_check(c, save=False)
    assert by_kind(report, "degraded_mode_answers")
    hits = by_kind(report, "provider_failures")
    assert hits and hits[0]["classification"] == "provider_ops"


# ── Fixture 12: clustered unanswerable topic = data gap ──────────────────

def test_detects_data_gap_from_clustered_misses():
    c = fresh_company()
    for i in range(3):
        make_trace(c, employee=f"s{i}@healthco.test", role="Support",
                   question="what is our onboarding checklist for enterprise?",
                   route="rag_agent", citations=[])
    report = run_health_check(c, save=False)
    hits = by_kind(report, "clustered_unanswerable_topic")
    assert hits and hits[0]["classification"] == "data_gap"


# ── Fixture 13: deterministic HIGH answer to an ambiguous question ───────

def test_detects_clarification_miss():
    c = fresh_company()
    make_trace(c, question="revenue in q1 and q3")  # pre-gate historical trace
    report = run_health_check(c, save=False)
    hits = by_kind(report, "deterministic_answered_ambiguous_question")
    assert hits and hits[0]["suggested_eval"]["expect"].startswith("clarification")


def test_clean_deterministic_answer_not_overflagged():
    c = fresh_company()
    make_trace(c, question="What was total revenue in Q3 2024?")
    report = run_health_check(c, save=False)
    assert not by_kind(report, "deterministic_answered_ambiguous_question")
    assert not by_kind(report, "llm_answered_deterministic_question")


# ── Fixture 14: employee friction pattern ────────────────────────────────

def test_detects_high_friction_employee():
    c = fresh_company()
    for i in range(5):
        make_trace(c, question=f"question {i} about payroll",
                   route="access_refusal", decision="denied",
                   denied_reason="the 'employees_hr' data area is outside your role")
    report = run_health_check(c, save=False)
    assert by_kind(report, "employee_friction")


# ── Report mechanics ─────────────────────────────────────────────────────

def test_healthy_history_produces_no_actionable_findings():
    c = fresh_company()
    make_trace(c, question="What was total revenue in Q3 2024?")
    make_trace(c, question="orders by region", chart_generated=True,
               chart_type="bar")
    report = run_health_check(c, save=False)
    assert not [f for f in report["findings"] if f["severity"] in ("high", "medium")]
    assert report["stats"]["traces"] == 2
    assert report["summary"]


def test_report_persists_company_scoped():
    c = fresh_company()
    make_trace(c)
    report = run_health_check(c, requested_by="admin@healthco.test")
    rid = report["report_id"]
    assert store.get_health_report(c, rid) is not None
    assert store.get_health_report("acmecloud", rid) is None  # cross-company blocked


def test_findings_sorted_most_severe_first():
    c = fresh_company()
    make_trace(c, question="What was total revenue in Q3 2024?")  # info-free
    tid = make_trace(c, question="MRR now?", route="degraded_mode", confidence="LOW")
    fid = store.save_feedback(c, "e@h.test", "Analyst", "wrong_answer", "bad", "ask", tid)
    store.update_feedback_status(c, fid, "resolved")
    report = run_health_check(c, save=False)
    sevs = [f["severity"] for f in report["findings"]]
    assert sevs == sorted(sevs, key=lambda s: {"high": 0, "medium": 1, "low": 2, "info": 3}[s])


def test_llm_summary_degrades_honestly(monkeypatch):
    """No providers → llm_summary None with an honest status, report intact."""
    import nexus_platform.health_check as hc

    def dead_summary(report):
        return None, "providers_unavailable"

    monkeypatch.setattr(hc, "_executive_summary", dead_summary)
    c = fresh_company()
    make_trace(c)
    report = run_health_check(c, llm_summary=True, save=False)
    assert report["llm_summary"] is None
    assert report["llm_summary_status"] == "providers_unavailable"
    assert report["summary"]  # deterministic summary always present
