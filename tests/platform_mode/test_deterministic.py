"""Deterministic analyst layer: phrasing families, roles, follow-ups,
memory isolation, degraded mode. No LLM calls anywhere in this file —
several tests booby-trap the agent path to prove it.
"""

import uuid

import pytest

import nexus_platform.query_service as qs
from nexus_platform import store
from nexus_platform.access_policy import get_policy
from nexus_platform.auth import AccessContext
from nexus_platform.deterministic import execute, parse_intent
from nexus_platform.registry import get_registry


def ctx_for(email: str) -> AccessContext:
    r = get_registry()
    e = r.get_employee(email)
    return AccessContext(employee=e, company=r.get_company(e.company_slug),
                         policy=get_policy(e.role))


@pytest.fixture()
def no_llm(monkeypatch):
    """Any touch of the LLM engine fails the test."""
    monkeypatch.setattr(qs, "get_company_fusion_agent",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("LLM path used")))


class _StubAgent:
    """Benign LLM-engine stand-in for tests where fallthrough is expected."""
    _history: list = []

    def _resolve_question(self, q):
        return q

    def query(self, q):
        return {"answer": "I don't have context for that.", "sources": [],
                "source_type": "rag_only"}


@pytest.fixture()
def stub_llm(monkeypatch):
    monkeypatch.setattr(qs, "get_company_fusion_agent", lambda *a, **k: _StubAgent())


def session() -> str:
    return f"det-test-{uuid.uuid4().hex[:8]}"


# ── Phrasing families (not exact strings) ────────────────────────────────

@pytest.mark.parametrize("question,metric", [
    ("What was total revenue in Q3 2024?", "revenue"),
    ("q3 revenue", "revenue"),
    ("How much did we sell in Q3?", "revenue"),
    ("show me sales for Q3 2024", "revenue"),
    ("How many orders did we complete in October?", "orders"),
    ("order volume in Q1", "orders"),
    ("average order value in Q2", "aov"),
    ("how many overdue invoices do we have", "overdue_invoices"),
    ("total invoiced amount in March", "invoice_amount"),
    ("ticket volume by priority", "tickets"),
    ("what's our average csat", "csat"),
    ("how long to resolve tickets by priority", "resolution_hours"),
    ("what is our attrition rate", "attrition_rate"),
    ("headcount by department", "headcount"),
    ("MRR by segment", "mrr"),
])
def test_phrasing_families_parse(question, metric):
    intent = parse_intent(question)
    assert intent is not None and intent.metric == metric, question


def test_unsupported_question_returns_none():
    assert parse_intent("Why did churn increase after the pricing change?") is None
    assert parse_intent("Summarize the billing policy") is None


# ── Correctness against ground truth ─────────────────────────────────────

def test_q3_revenue_matches_ground_truth():
    out = execute(ctx_for("analyst@acmecloud.test"),
                  parse_intent("What was total revenue in Q3 2024?"))
    assert "$1,321,021.33" in out["answer"]
    assert out["template_id"] == "revenue_total"


def test_period_range_bar_graph_becomes_quarter_series():
    intent = parse_intent("mark on bar graph the total revenue of q1 to q4 in 2024")
    assert intent.metric == "revenue"
    assert intent.group_by == "quarter"
    assert intent.output == "bar"
    out = execute(ctx_for("analyst@acmecloud.test"), intent)
    assert out["template_id"] == "revenue_by_quarter"
    assert out["chart"]["type"] == "bar"
    assert out["chart"]["x"] == "quarter"
    assert len(out["rows"]) == 4


def test_company_isolation_different_numbers():
    a = execute(ctx_for("analyst@acmecloud.test"), parse_intent("revenue in Q3 2024"))
    m = execute(ctx_for("finance@medcore.test"), parse_intent("revenue in Q3 2024"))
    assert a["rows"][0]["value"] != m["rows"][0]["value"]


# ── Role boundaries ──────────────────────────────────────────────────────

@pytest.mark.parametrize("email,question,denied", [
    ("analyst@acmecloud.test", "what is our attrition rate", True),
    ("analyst@acmecloud.test", "headcount by department", True),
    ("hr@acmecloud.test", "what is our attrition rate", False),
    ("hr@acmecloud.test", "revenue in Q3", True),
    ("ops@finpilot.test", "how many overdue invoices", True),
    ("ops@finpilot.test", "ticket volume by priority", False),
])
def test_role_boundaries(email, question, denied):
    out = execute(ctx_for(email), parse_intent(question))
    assert out["denied"] is denied
    if denied:
        assert out["sql"] is None and not out["rows"]


# ── Follow-up flow + degraded mode (LLM booby-trapped) ───────────────────

def test_five_turn_followup_flow_without_llm(no_llm):
    ctx = ctx_for("analyst@acmecloud.test")
    s = session()
    r1 = qs.run_query(ctx, "What was total revenue in Q3 2024?", s)
    assert r1["platform"]["llm_skipped"] and "$1,321,021.33" in r1["answer"]

    r2 = qs.run_query(ctx, "What about Q4?", s)
    assert r2["platform"]["followup_rewritten"]
    assert "Q4 2024" in r2["answer"] and "$2,495,120.54" in r2["answer"]

    r3 = qs.run_query(ctx, "Compare that with Q3", s)
    assert "vs" in r3["answer"] and "Q3 2024" in r3["answer"]

    r4 = qs.run_query(ctx, "Show that as a bar chart", s)
    assert (r4["platform"]["chart"] or {}).get("type") == "bar"

    r5 = qs.run_query(ctx, "by region", s)
    assert "region" in r5["answer"]
    assert (r5["platform"]["chart"] or {}).get("x") == "region"

    # every turn was traced as deterministic with llm skipped
    for r in (r1, r2, r3, r4, r5):
        assert r["platform"]["route"] == "deterministic_sql_template"
        trace = store.get_trace("acmecloud", r["platform"]["trace_id"])
        assert trace["payload"]["llm_skipped"] is True
        assert trace["payload"]["route"] == "deterministic_sql_template"


def test_denied_followup_never_widens_access(no_llm):
    """HR context from one employee cannot leak into an Analyst follow-up."""
    ctx = ctx_for("analyst@acmecloud.test")
    s = session()
    r1 = qs.run_query(ctx, "terminations by department", s)
    assert r1["platform"]["refused"]
    # follow-up after refusal must not resurrect the denied metric
    r2 = qs.run_query(ctx, "what about Q4?", s)
    assert r2["platform"]["refused"] or "termination" not in str(r2["answer"]).lower()


def test_memory_does_not_cross_employees(stub_llm):
    s = session()
    a = ctx_for("analyst@acmecloud.test")
    hr = ctx_for("hr@acmecloud.test")
    qs.run_query(a, "revenue in Q3 2024", s)
    # same session id, different employee: no inherited intent
    r = qs.run_query(hr, "What about Q4?", s)
    assert "revenue" not in str(r["answer"]).lower()


def test_memory_does_not_cross_companies(stub_llm):
    s = session()
    qs.run_query(ctx_for("analyst@acmecloud.test"), "revenue in Q3 2024", s)
    r = qs.run_query(ctx_for("analyst@finpilot.test"), "What about Q4?", s)
    # FinPilot analyst gets either nothing inherited or FinPilot numbers —
    # never AcmeCloud's Q4 figure
    assert "2,495,120" not in str(r["answer"])


def test_trace_records_memory_turn_count(no_llm):
    ctx = ctx_for("analyst@acmecloud.test")
    s = session()
    qs.run_query(ctx, "revenue in Q3 2024", s)
    r = qs.run_query(ctx, "What about Q4?", s)
    trace = store.get_trace("acmecloud", r["platform"]["trace_id"])
    assert trace["payload"]["memory_turns_used"] >= 1
    assert trace["payload"]["intent"]["metric"] == "revenue"
