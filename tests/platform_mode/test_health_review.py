"""Wave 1 of the Health Check agent: the 3-tier per-trace grader + report.

Grading logic is tested with controlled inputs (oracle mocked where the real
deterministic layer would need company data), so these run without ambient DB
state or any LLM quota.
"""

import uuid

import nexus_platform.health_review as hr


def _ctx():
    # Registry-only construction (no company data needed).
    return hr._ctx_for("acmecloud", "Analyst", "analyst@acmecloud.test")


def test_cross_company_block_is_a_correct_refusal():
    v = hr._grade_deterministic(
        _ctx(), "What was MedCore revenue in Q1 2024?", "I can only access AcmeCloud.",
        {"access_decision": "denied", "route": "cross_company_scope_clarification"})
    assert v["verdict"] == "correct_refusal" and v["tier"] == "deterministic"


def test_numeric_answer_graded_against_oracle(monkeypatch):
    monkeypatch.setattr(hr, "compute_oracle", lambda ctx, q: [109.0])
    payload = {"access_decision": "allowed", "route": "deterministic_sql_template"}
    ok = hr._grade_deterministic(_ctx(), "headcount?", "Headcount is 109.", payload)
    assert ok["verdict"] == "correct"
    bad = hr._grade_deterministic(_ctx(), "headcount?", "Headcount is 50.", payload)
    assert bad["verdict"] == "wrong"
    assert "109" in bad["expected"] and "50" in bad["reality"]


def test_clarification_is_not_applicable():
    v = hr._grade_deterministic(
        _ctx(), "What is our NPS?", "Did you mean CSAT?",
        {"access_decision": "allowed", "route": "clarification"})
    assert v["verdict"] == "not_applicable"


def test_non_deterministic_answer_escalates(monkeypatch):
    # oracle can't grade -> deterministic returns None (escalate to LLM).
    monkeypatch.setattr(hr, "compute_oracle", lambda ctx, q: None)
    v = hr._grade_deterministic(
        _ctx(), "why did revenue change?", "It rose on enterprise renewals.",
        {"access_decision": "allowed", "route": "llm_planner"})
    assert v is None


def test_llm_tier_falls_through_to_human_when_budget_spent():
    v = hr._llm_judge(_ctx(), "why?", "because", {"remaining": 0})
    assert v["verdict"] == "needs_human_review" and v["tier"] == "human"


def test_incomplete_trace_needs_human_review():
    v = hr.grade_trace("acmecloud", {"id": "tr_x", "payload": {}}, {"remaining": 0})
    assert v["verdict"] == "needs_human_review"


def test_report_structure_on_empty_company():
    co = f"emptyco_{uuid.uuid4().hex[:8]}"
    r = hr.run_health_review(co, window_days=7, source="real", llm_budget=0, save=False)
    assert r["kind"] == "health_review"
    assert r["traces_reviewed"] == 0
    assert r["employees"] == [] and r["fixes_needed"] == []
    for key in ("report_date", "date_from", "date_to", "summary", "narrative"):
        assert key in r


def test_review_watermark_roundtrip():
    from nexus_platform import store
    co = f"wm_{uuid.uuid4().hex[:8]}"
    assert store.get_review_watermark(co) is None
    store.set_review_watermark(co, "2026-07-15T10:00:00")
    wm = store.get_review_watermark(co)
    assert wm["last_ts"] == "2026-07-15T10:00:00" and wm["runs"] == 1
    store.set_review_watermark(co, "2026-07-15T12:00:00")
    wm2 = store.get_review_watermark(co)
    assert wm2["last_ts"] == "2026-07-15T12:00:00" and wm2["runs"] == 2  # counter advances


def test_review_report_has_incremental_memory():
    co = f"emptyco_{uuid.uuid4().hex[:8]}"
    r = hr.run_health_review(co, window_days=7, source="real", llm_budget=0)
    for k in ("incremental", "since", "run_number", "new_traces_reviewed", "open_findings"):
        assert k in r
    assert r["run_number"] == 1 and r["new_traces_reviewed"] == 0
    # a second run advances the run counter (the watermark persisted)
    r2 = hr.run_health_review(co, window_days=7, source="real", llm_budget=0)
    assert r2["run_number"] == 2 and r2["previous_run_at"] is not None


def test_fixes_needed_rolls_up_and_ranks():
    employees = [{
        "name": "X", "traces": [
            {"trace_id": "t1", "verdict": "wrong"},
            {"trace_id": "t2", "verdict": "false_refusal"},
            {"trace_id": "t3", "verdict": "needs_human_review"},
            {"trace_id": "t4", "verdict": "correct"},
        ]}]
    fixes = hr._fixes_needed(employees)
    kinds = [f["issue"] for f in fixes]
    assert "Wrong answers" in kinds and "Wrongly refused questions" in kinds
    assert fixes[0]["severity"] == "high"  # high-severity first
