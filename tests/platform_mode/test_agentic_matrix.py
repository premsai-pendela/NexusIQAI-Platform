"""Agentic analyst test matrix — clarification gate, repeat-question choices,
route decisions, chart intelligence, range/selection semantics.

Written BEFORE the orchestrator implementation (final-run requirement).
No LLM calls anywhere: deterministic paths are exercised with the agent path
booby-trapped; agent-path routing is asserted with capturing stubs.
"""

import uuid

import pytest

import nexus_platform.query_service as qs
from nexus_platform import store
from nexus_platform.access_policy import get_policy
from nexus_platform.auth import AccessContext
from nexus_platform.registry import get_registry


def ctx_for(email: str) -> AccessContext:
    r = get_registry()
    e = r.get_employee(email)
    return AccessContext(employee=e, company=r.get_company(e.company_slug),
                         policy=get_policy(e.role))


def session() -> str:
    return f"matrix-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def no_llm(monkeypatch):
    """Any touch of the LLM engine fails the test."""
    monkeypatch.setattr(qs, "get_company_fusion_agent",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("LLM path used")))


class CapturingAgent:
    """Records how the platform called the LLM engine."""

    def __init__(self, source_type="rag_only", answer="Stub answer."):
        self._history = []
        self.calls = []
        self.source_type = source_type
        self.answer = answer

    def _resolve_question(self, q):
        return q

    def query(self, q, force_source=None, **kw):
        self.calls.append({"question": q, "force_source": force_source})
        return {"answer": self.answer, "sources": [],
                "source_type": force_source or self.source_type}


@pytest.fixture()
def capture_llm(monkeypatch):
    agent = CapturingAgent()
    monkeypatch.setattr(qs, "get_company_fusion_agent", lambda *a, **k: agent)
    return agent


ANALYST = "analyst@acmecloud.test"
HR = "hr@acmecloud.test"


# ═══════════════════════════════════════════════════════════════════════
# Clarification gate — no confident answers from partial parses
# ═══════════════════════════════════════════════════════════════════════

def test_unclear_metric_asks_clarification(no_llm):
    """'show market by invoice' must not be answered confidently."""
    r = qs.run_query(ctx_for(ANALYST), "show market by invoice", session())
    p = r["platform"]
    assert p["route"] == "clarification"
    assert r.get("confidence") != "HIGH" or not r.get("sql_result")
    clar = p["clarification"]
    assert clar["question"]
    assert 2 <= len(clar["choices"]) <= 3
    # choices must be full askable questions
    assert all(len(c) > 10 for c in clar["choices"])


def test_malformed_period_asks_clarification(no_llm):
    """'q2 and a4' — a4 is not a quarter; do not silently answer Q2 only."""
    r = qs.run_query(ctx_for(ANALYST), "total revenue for q2 and a4", session())
    p = r["platform"]
    assert p["route"] == "clarification"
    assert "a4" in p["clarification"]["question"].lower() or \
           "quarter" in p["clarification"]["question"].lower()


def test_ambiguous_selection_q1_and_q3_asks_only_vs_through(no_llm):
    """Bare non-adjacent 'q1 and q3' is ambiguous: only-those vs Q1-Q3 range."""
    r = qs.run_query(ctx_for(ANALYST), "revenue in q1 and q3", session())
    p = r["platform"]
    assert p["route"] == "clarification"
    joined = " ".join(p["clarification"]["choices"]).lower()
    assert "only" in joined and "through" in joined


def test_explicit_only_selection_answers_directly(no_llm):
    r = qs.run_query(ctx_for(ANALYST), "revenue for only q1 and q3", session())
    p = r["platform"]
    assert p["route"] == "deterministic_sql_template"
    assert not p["refused"]
    data = p["chart"]["data"]
    assert [d["period"] for d in data] == ["Q1 2024", "Q3 2024"]


def test_selection_with_chart_word_answers_directly(no_llm):
    """Observed-good behavior preserved: explicit chart request disambiguates."""
    r = qs.run_query(ctx_for(ANALYST),
                     "line chart of total revenue of q2 and q4 in 2024", session())
    p = r["platform"]
    assert p["route"] == "deterministic_sql_template"
    assert p["chart"]["type"] == "line"
    assert [d["period"] for d in p["chart"]["data"]] == ["Q2 2024", "Q4 2024"]


def test_contradictory_period_request_asks_clarification(no_llm):
    r = qs.run_query(ctx_for(ANALYST),
                     "show only q1 and q3 from q1 to q4 revenue", session())
    assert r["platform"]["route"] == "clarification"


def test_range_q2_through_q4_returns_exactly_three_quarters(no_llm):
    """'q2 through q4' is Q2..Q4 — not full-year, not Q2 scalar."""
    r = qs.run_query(ctx_for(ANALYST), "revenue from q2 through q4", session())
    p = r["platform"]
    assert p["route"] == "deterministic_sql_template"
    labels = [d.get("quarter") or d.get("period") for d in p["chart"]["data"]]
    assert labels == ["Q2", "Q3", "Q4"] or labels == ["Q2 2024", "Q3 2024", "Q4 2024"]


def test_range_q1_to_q4_returns_four_quarters(no_llm):
    r = qs.run_query(ctx_for(ANALYST), "revenue from q1 to q4", session())
    p = r["platform"]
    assert p["route"] == "deterministic_sql_template"
    assert len(p["chart"]["data"]) == 4


def test_typo_salad_question_asks_clarification(no_llm):
    r = qs.run_query(ctx_for(ANALYST),
                     "q1 and q3 related to total invoice and market in on a bar graph",
                     session())
    assert r["platform"]["route"] == "clarification"


def test_vague_followup_asks_clarification(no_llm):
    s = session()
    qs.run_query(ctx_for(ANALYST), "What was total revenue in Q3 2024?", s)
    r = qs.run_query(ctx_for(ANALYST), "make it better", s)
    assert r["platform"]["route"] == "clarification"


def test_overbroad_question_asks_clarification(no_llm):
    r = qs.run_query(ctx_for(ANALYST), "analyze everything", session())
    p = r["platform"]
    assert p["route"] == "clarification"
    assert len(p["clarification"]["choices"]) >= 2


def test_full_parse_still_answers_deterministically(no_llm):
    r = qs.run_query(ctx_for(ANALYST), "What was total revenue in Q3 2024?", session())
    p = r["platform"]
    assert p["route"] == "deterministic_sql_template"
    assert r["confidence"] == "HIGH"
    assert p["llm_skipped"] is True


def test_clarification_choice_click_resolves(no_llm):
    """Clicking a clarification choice (sent as a new question) must answer."""
    s = session()
    r1 = qs.run_query(ctx_for(ANALYST), "revenue in q1 and q3", s)
    choice = r1["platform"]["clarification"]["choices"][0]
    r2 = qs.run_query(ctx_for(ANALYST), choice, s)
    assert r2["platform"]["route"] == "deterministic_sql_template"
    assert not r2["platform"]["refused"]


# ═══════════════════════════════════════════════════════════════════════
# Chart intelligence
# ═══════════════════════════════════════════════════════════════════════

def test_pie_by_region_renders_pie(no_llm):
    r = qs.run_query(ctx_for(ANALYST), "pie chart of revenue by region", session())
    p = r["platform"]
    assert p["route"] == "deterministic_sql_template"
    assert p["chart"]["type"] == "pie"


def test_pie_over_time_is_not_silently_rendered(no_llm):
    """Pie over a monthly time series → explain + offer choices, or clarify."""
    r = qs.run_query(ctx_for(ANALYST), "pie chart of revenue by month", session())
    p = r["platform"]
    assert p["route"] == "clarification"
    joined = " ".join(p["clarification"]["choices"]).lower()
    assert "pie" in joined or "bar" in joined or "line" in joined


def test_bar_chart_request_still_works(no_llm):
    r = qs.run_query(ctx_for(ANALYST), "bar chart of revenue by region", session())
    assert r["platform"]["chart"]["type"] == "bar"


# ═══════════════════════════════════════════════════════════════════════
# Repeated-question behavior
# ═══════════════════════════════════════════════════════════════════════

def test_repeat_question_offers_choice(no_llm):
    s = session()
    q = "What was total revenue in Q3 2024?"
    r1 = qs.run_query(ctx_for(ANALYST), q, s)
    r2 = qs.run_query(ctx_for(ANALYST), q, s)
    p = r2["platform"]
    assert p["route"] == "repeat_question_choice"
    rep = p["repeat"]
    assert set(rep["options"]) == {"use_previous", "rerun", "analyze_with_ai"}
    assert rep["previous"]["trace_id"] == r1["platform"]["trace_id"]


def test_repeat_use_previous_returns_prior_answer(no_llm):
    s = session()
    q = "What was total revenue in Q3 2024?"
    r1 = qs.run_query(ctx_for(ANALYST), q, s)
    r2 = qs.run_query(ctx_for(ANALYST), q, s, repeat_action="use_previous")
    p = r2["platform"]
    assert p["route"] == "repeat_used_previous"
    assert p["previous_trace_id"] == r1["platform"]["trace_id"]
    assert r2["answer"]


def test_repeat_rerun_recomputes(no_llm):
    s = session()
    q = "What was total revenue in Q3 2024?"
    qs.run_query(ctx_for(ANALYST), q, s)
    r2 = qs.run_query(ctx_for(ANALYST), q, s, repeat_action="rerun")
    assert r2["platform"]["route"] == "deterministic_sql_template"
    assert r2["sql_result"]["success"]


def test_repeat_analyze_with_ai_uses_llm_planner(capture_llm):
    s = session()
    q = "What was total revenue in Q3 2024?"
    qs.run_query(ctx_for(ANALYST), q, s)
    r2 = qs.run_query(ctx_for(ANALYST), q, s, repeat_action="analyze_with_ai")
    assert r2["platform"]["route"] == "llm_planner"
    assert capture_llm.calls, "analyze_with_ai must call the LLM engine"


def test_different_question_gets_no_repeat_card(no_llm):
    s = session()
    qs.run_query(ctx_for(ANALYST), "What was total revenue in Q3 2024?", s)
    r2 = qs.run_query(ctx_for(ANALYST), "What was total revenue in Q4 2024?", s)
    assert r2["platform"]["route"] == "deterministic_sql_template"


def test_repeat_of_refused_question_stays_refused(no_llm):
    """Role-blocked repeats must refuse again — never offer 'use previous'."""
    s = session()
    q = "What is our headcount?"
    r1 = qs.run_query(ctx_for(ANALYST), q, s)
    assert r1["platform"]["refused"]
    r2 = qs.run_query(ctx_for(ANALYST), q, s)
    assert r2["platform"]["refused"]
    assert r2["platform"]["route"] != "repeat_question_choice"


def test_role_blocked_followup_stays_refused(no_llm):
    s = session()
    r1 = qs.run_query(ctx_for(ANALYST), "How many employees were terminated in Q3?", s)
    assert r1["platform"]["refused"]
    r2 = qs.run_query(ctx_for(ANALYST), "what about Q4?", s)
    assert r2["platform"]["refused"]


# ═══════════════════════════════════════════════════════════════════════
# Route decisions: SQL / RAG / mixed / insight
# ═══════════════════════════════════════════════════════════════════════

def test_policy_question_routes_to_rag_agent(capture_llm):
    r = qs.run_query(ctx_for(ANALYST), "What is the discount approval policy?", session())
    assert r["platform"]["route"] == "rag_agent"
    assert capture_llm.calls


def test_mixed_policy_plus_numbers_forces_sql_plus_rag(capture_llm):
    r = qs.run_query(ctx_for(ANALYST),
                     "What was the discount policy impact on Q4 revenue?", session())
    assert r["platform"]["route"] == "sql_plus_rag"
    assert capture_llm.calls[-1]["force_source"] == "sql_rag"


def test_insight_question_routes_to_llm_planner(capture_llm):
    r = qs.run_query(ctx_for(ANALYST), "Why did revenue change in Q4?", session())
    assert r["platform"]["route"] == "llm_planner"
    assert capture_llm.calls


def test_insight_question_degrades_honestly_when_providers_down(monkeypatch):
    """Provider exhaustion on the planner path → honest degraded answer."""
    class DeadAgent(CapturingAgent):
        def query(self, q, force_source=None, **kw):
            return {"answer": "", "sources": [], "source_type": "error",
                    "error": "All LLM models failed"}

    monkeypatch.setattr(qs, "get_company_fusion_agent", lambda *a, **k: DeadAgent())
    r = qs.run_query(ctx_for(ANALYST), "Why did revenue change in Q4?", session())
    p = r["platform"]
    assert p["route"] == "degraded_mode"
    assert r.get("confidence") != "HIGH"
    assert "unavailable" in r["answer"].lower() or "try" in r["answer"].lower()


def test_deterministic_families_survive_provider_exhaustion(no_llm):
    """Core analytics must not need any provider at all."""
    for q in ("What was total revenue in Q3 2024?",
              "how many orders in Q2",
              "revenue by region",
              "overdue invoices"):
        r = qs.run_query(ctx_for(ANALYST), q, session())
        assert r["platform"]["route"] == "deterministic_sql_template", q


# ═══════════════════════════════════════════════════════════════════════
# Traces record the route decision
# ═══════════════════════════════════════════════════════════════════════

def test_clarification_trace_recorded(no_llm):
    ctx = ctx_for(ANALYST)
    r = qs.run_query(ctx, "show market by invoice", session())
    t = store.get_trace(ctx.company.slug, r["platform"]["trace_id"])
    assert t is not None
    assert t["payload"]["route"] == "clarification"
    assert t["payload"]["llm_skipped"] is True


def test_repeat_choice_trace_recorded(no_llm):
    ctx = ctx_for(ANALYST)
    s = session()
    q = "What was total revenue in Q3 2024?"
    qs.run_query(ctx, q, s)
    r2 = qs.run_query(ctx, q, s)
    t = store.get_trace(ctx.company.slug, r2["platform"]["trace_id"])
    assert t["payload"]["route"] == "repeat_question_choice"
