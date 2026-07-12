"""Classifier behavior on constructed trace payloads, plus the gold set.

The gold set (fixtures/classifier_gold/gold.json) is provisional: cases are
labeled by construction (deterministic ground truth) or agent-provisional —
Prem should review and re-label; disagreements become new gold cases.
"""

import json
from pathlib import Path

from nexus_platform.access_policy import get_policy
from nexus_platform.auth import AccessContext
from nexus_platform.registry import get_registry
from nexus_platform.sim.classifier import classify_turn, compute_oracle

GOLD = Path(__file__).parent / "fixtures" / "classifier_gold" / "gold.json"


def ctx_for(role: str = "Analyst", company: str = "acmecloud") -> AccessContext:
    r = get_registry()
    c = r.get_company(company)
    emp = next(e for e in r.company_employees(company) if e.role == role)
    return AccessContext(employee=emp, company=c, policy=get_policy(role))


def payload(route="deterministic_sql_template", decision="allowed",
            question="What was total revenue in Q3 2024?", denied_reason=None,
            citations=None, tables_touched=None, llm_skipped=True):
    return {
        "question": question, "route": route, "access_decision": decision,
        "denied_reason": denied_reason, "citations": citations or [],
        "tables_touched": tables_touched or [], "llm_skipped": llm_skipped,
    }


# ── The bug-#1 shape: denial naming a table not in the schema ────────────

def test_denial_naming_nonexistent_table_is_exceptional():
    p = payload(route="access_refusal", decision="denied",
                denied_reason="the 'sales_transactions' data area is outside your role")
    v = classify_turn(ctx_for(), "answer", p, "tr_x",
                      answer="I can't answer that from your current access level.")
    assert v.label == "exceptional"
    assert v.findings and v.findings[0]["kind"] == "denial_names_nonexistent_table"
    assert v.findings[0]["self_fixable"] is True


def test_denial_naming_real_restricted_table_is_correct():
    # HR asking revenue → denial names 'orders', a real table outside HR.
    p = payload(route="access_refusal", decision="denied",
                question="What was total revenue in Q3 2024?",
                denied_reason="the 'orders' data area is outside your role")
    v = classify_turn(ctx_for("HR"), "refusal", p, "tr_x")
    assert v.label == "correct"
    assert not v.findings


def test_inrole_question_refused_is_wrong():
    p = payload(route="access_refusal", decision="denied",
                denied_reason="the 'orders' data area is outside your role")
    v = classify_turn(ctx_for("Analyst"), "answer_numeric", p, "tr_x")
    assert v.label == "wrong"
    assert v.findings[0]["kind"] == "allowed_question_refused"


# ── Oracle comparisons ───────────────────────────────────────────────────

def test_oracle_match_is_correct():
    ctx = ctx_for()
    oracle = compute_oracle(ctx, "What was total revenue in Q3 2024?")
    assert oracle, "oracle must produce numbers for a deterministic question"
    p = payload()
    v = classify_turn(ctx, "answer_numeric", p, "tr_x",
                      answer=f"Revenue for Q3 2024: **${oracle[0]:,.2f}**.",
                      oracle_nums=oracle)
    assert v.label == "correct"


def test_oracle_mismatch_is_wrong():
    ctx = ctx_for()
    v = classify_turn(ctx, "answer_numeric", payload(llm_skipped=False), "tr_x",
                      answer="Total revenue for Q3 2024 was $999,999.00.",
                      oracle_nums=[5340670.84])
    assert v.label == "wrong"
    assert v.findings[0]["kind"] == "numeric_mismatch_vs_oracle"


def test_numeric_answer_with_no_number_is_vague():
    v = classify_turn(ctx_for(), "answer_numeric", payload(), "tr_x",
                      answer="Revenue was strong this quarter.",
                      oracle_nums=[5340670.84])
    assert v.label == "vague"


# ── Structural leak ──────────────────────────────────────────────────────

def test_restricted_table_touch_is_exceptional_leak():
    p = payload(route="sql_agent", tables_touched=["payroll_summary"],
                llm_skipped=False)
    v = classify_turn(ctx_for("Analyst"), "answer", p, "tr_x", answer="42")
    assert v.label == "exceptional"
    assert v.findings[0]["kind"] == "boundary_leak"


def test_restricted_citation_department_is_exceptional_leak():
    p = payload(route="rag_agent", citations=[{"filename": "x", "department": "hr"}],
                llm_skipped=False)
    v = classify_turn(ctx_for("Analyst"), "answer", p, "tr_x", answer="policy…")
    assert v.label == "exceptional"


# ── Routing expectations ─────────────────────────────────────────────────

def test_clarification_expected_and_given_is_correct():
    p = payload(route="clarification")
    v = classify_turn(ctx_for(), "clarification", p, "tr_x")
    assert v.label == "correct"


def test_ambiguous_answered_confidently_is_wrong():
    p = payload(question="revenue for a4")
    v = classify_turn(ctx_for(), "clarification", p, "tr_x",
                      answer="Revenue: $1,000,000")
    assert v.label == "wrong"
    assert v.findings[0]["kind"] == "ambiguous_answered_confidently"


def test_cross_company_clarified_is_correct():
    p = payload(route="cross_company_scope_clarification", decision="denied",
                denied_reason="requested another company workspace: MedCore Systems")
    v = classify_turn(ctx_for(), "cross_company", p, "tr_x")
    assert v.label == "correct"


def test_repeat_choice_expected_is_correct():
    p = payload(route="repeat_question_choice")
    v = classify_turn(ctx_for(), "repeat_choice", p, "tr_x")
    assert v.label == "correct"


def test_rag_without_citations_is_vague():
    p = payload(route="rag_agent", llm_skipped=False)
    v = classify_turn(ctx_for(), "answer", p, "tr_x", answer="Our policy says…")
    assert v.label == "vague"
    assert v.findings[0]["kind"] == "rag_answer_without_citations"


def test_hallucinated_nonexistent_entity_is_exceptional():
    p = payload(route="llm_planner", question="What is our NPS score?",
                llm_skipped=False)
    v = classify_turn(ctx_for(), "honest_absence", p, "tr_x",
                      answer="Your NPS score for 2024 is 72.")
    assert v.label == "exceptional"
    assert v.findings[0]["kind"] == "hallucinated_nonexistent_entity"


def test_honest_absence_is_correct():
    p = payload(route="llm_planner", question="What is our NPS score?",
                llm_skipped=False)
    v = classify_turn(ctx_for(), "honest_absence", p, "tr_x",
                      answer="NPS isn't tracked in your workspace data.")
    assert v.label == "correct"


def test_degraded_with_oracle_is_exceptional():
    p = payload(route="degraded_mode", llm_skipped=False)
    v = classify_turn(ctx_for(), "answer_numeric", p, "tr_x",
                      answer="The reasoning models are unavailable right now",
                      oracle_nums=[5340670.84])
    assert v.label == "exceptional"
    assert v.findings[0]["kind"] == "degraded_when_deterministic_available"


# ── Gold set ─────────────────────────────────────────────────────────────

def test_gold_set_accuracy():
    cases = json.loads(GOLD.read_text())
    assert len(cases) >= 25
    wrong = []
    for case in cases:
        ctx = ctx_for(case.get("role", "Analyst"))
        v = classify_turn(ctx, case["expect"], case["payload"],
                          case.get("trace_id", "tr_gold"),
                          answer=case.get("answer", ""),
                          oracle_nums=case.get("oracle_nums"))
        if v.label != case["label"]:
            wrong.append((case["id"], case["label"], v.label, v.reason))
    # Constructed cases have deterministic ground truth — require 100%.
    assert not wrong, f"gold disagreements: {wrong}"
