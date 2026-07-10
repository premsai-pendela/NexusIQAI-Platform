"""Regression: unknown business metrics get an honest clarification, never a
fabricated formula.

Found by the Health Check simulation campaign `camp_c305c02583` (2026-07-10),
evidence trace `tr_63dee96201`: as AcmeCloud Admin, "What is our NPS score
for 2024?" routed to the SQL agent, which invented an NPS formula over the
1–5 CSAT scale (every ticket a "detractor" by construction, since NPS
thresholds assume 0–10) and confidently answered "Nps score: **-1**". NPS is
not tracked anywhere in the workspace — schema, metrics, or documents.

The fabricating engine below mirrors that recorded behavior so the repro is
deterministic: the gate must answer honestly BEFORE any engine call.
"""

import uuid

import pytest

from nexus_platform import query_service
from nexus_platform.access_policy import get_policy
from nexus_platform.auth import AccessContext
from nexus_platform.query_service import run_query
from nexus_platform.registry import get_registry


def _sid(tag: str) -> str:
    """Unique session per run — memory persists in the store, and a reused
    session id would trip the repeat-question gate on re-runs."""
    return f"{tag}-{uuid.uuid4().hex[:8]}"


def ctx_for(email: str) -> AccessContext:
    r = get_registry()
    e = r.get_employee(email)
    return AccessContext(employee=e, company=r.get_company(e.company_slug),
                         policy=get_policy(e.role))


class FabricatingAgent:
    """What the live engine did in trace tr_63dee96201: a confident number
    for a metric that does not exist."""

    _history: list = []

    def _resolve_question(self, q):
        return q

    def query(self, q, force_source=None):
        return {
            "answer": "Nps score: **-1**",
            "source_type": "sql_only",
            "sources": [],
            "sql_result": {"success": True, "row_count": 1,
                           "query": "SELECT ... AS nps_score FROM csat_responses ...",
                           "results": [{"nps_score": -1}]},
            "confidence": "HIGH",
        }


@pytest.fixture()
def fabricating_engine(monkeypatch):
    monkeypatch.setattr(query_service, "get_company_fusion_agent",
                        lambda company, role: FabricatingAgent())


def test_nps_ask_is_answered_honestly_not_fabricated(fabricating_engine):
    ctx = ctx_for("admin@acmecloud.test")
    res = run_query(ctx, "What is our NPS score for 2024?", _sid("s-unknown-metric-1"))
    plat = res["platform"]
    assert plat["route"] == "clarification", (
        f"expected the unknown-metric gate, got route={plat['route']!r} "
        f"answer={res['answer']!r}")
    assert plat["llm_skipped"] is True
    clar = plat.get("clarification") or {}
    assert clar.get("kind") == "unknown_metric"
    assert clar.get("choices"), "must offer real alternatives"
    answer = str(res["answer"]).lower()
    assert "nps" in answer
    # The fabricated number never reaches the employee.
    assert "-1" not in str(res["answer"])


def test_unknown_metric_variants_are_gated(fabricating_engine):
    ctx = ctx_for("admin@acmecloud.test")
    for i, q in enumerate(["What's our LTV for 2024?",
                           "What is our market share?",
                           "Show me our runway for 2024"]):
        res = run_query(ctx, q, _sid(f"s-um-v{i}"))
        plat = res["platform"]
        assert plat["route"] == "clarification", f"{q!r} → {plat['route']!r}"
        assert (plat.get("clarification") or {}).get("kind") == "unknown_metric"


def test_documents_escape_hatch_is_offered(fabricating_engine):
    ctx = ctx_for("admin@acmecloud.test")
    res = run_query(ctx, "What is our NPS score for 2024?", _sid("s-unknown-metric-2"))
    choices = (res["platform"].get("clarification") or {}).get("choices") or []
    assert any("document" in c.lower() for c in choices), (
        "a documents-path choice must be offered so a legitimate doc lookup "
        f"is never blocked; got {choices}")


def test_known_metrics_are_not_gated():
    """Guard against over-firing: every deterministic family still answers."""
    ctx = ctx_for("admin@acmecloud.test")
    for i, (q, frag) in enumerate([
            ("What is our MRR?", "mrr"),
            ("What is our attrition rate?", "attrition"),
            ("What was total revenue in Q3 2024?", "revenue"),
            ("What is our headcount?", "headcount"),
            ("What is our CSAT?", "csat")]):
        res = run_query(ctx, q, _sid(f"s-km-{i}"))
        plat = res["platform"]
        assert plat["route"] == "deterministic_sql_template", (
            f"{q!r} → {plat['route']!r}: known metric must not be gated")
        assert not plat["refused"]


def test_insight_and_doc_questions_are_not_gated():
    """Why-questions and policy questions legitimately go to the engine."""
    from nexus_platform.orchestrator import decide_route

    policy = get_policy("Admin")
    for q in ("Why did our conversion collapse in Q3 2024?",
              "What is our vacation policy?"):
        decision = decide_route(q, policy)
        clar = decision.clarification
        assert not (clar and clar.kind == "unknown_metric"), (
            f"{q!r} must not hit the unknown-metric gate")
