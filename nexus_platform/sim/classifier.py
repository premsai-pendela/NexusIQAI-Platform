"""Deterministic 4-outcome classifier for simulated answers.

Labels: correct | wrong | vague | exceptional. Zero LLM calls — per the
LLM-as-judge reliability research (ARCHITECTURE_LOG.md Entry 2), weak models
are unreliable judges, and this platform has something better: a
deterministic oracle (`deterministic.execute`) for numeric questions, the
full schema universe (`access_policy.TABLE_AREAS`) for the
nonexistent-table check, and role policies for allow/deny ground truth.

The `exceptional` bucket is the bug-class one, e.g. an access-denial message
naming a table that does not exist anywhere in the company's schema — a SQL
generation failure mislabeled as a permissions problem (the confirmed
"Analyze with AI" bug's shape, checked generically here, never hard-coded to
a specific table name).

Findings are emitted in health_check's `_finding(...)` shape so the existing
report/coalesce/severity pipeline consumes them without a parallel system.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional

from nexus_platform.access_policy import ALL_TABLES
from nexus_platform.auth import AccessContext
from nexus_platform.deterministic import execute as det_execute, parse_intent
from nexus_platform.health_check import _finding, _norm

LABELS = ("correct", "wrong", "vague", "exceptional")

_ANSWER_ROUTES = ("deterministic_sql_template", "sql_agent", "rag_agent",
                  "sql_plus_rag", "llm_planner", "sql_only", "rag_only")
_CLARIFY_ROUTES = ("clarification",)

# "the 'sales_transactions' data area is outside your role"
_DENIED_TABLE_RE = re.compile(r"the '([A-Za-z0-9_]+)' data area is outside")
# deterministic refusals: "tables outside role: ['payroll_summary']"
_DENIED_LIST_RE = re.compile(r"tables outside role: \[([^\]]*)\]")

_ABSENCE_RE = re.compile(
    r"\bdon'?t have\b|\bno data\b|\bnot (?:available|tracked|found|recorded)\b"
    r"|\bdoes(?:n'?t| not) exist\b|\bcouldn'?t\b|\bcan'?t\b|\bunable\b"
    r"|\bno such\b|\bisn'?t (?:a|any|tracked)\b|\bnot something\b", re.I)


@dataclass
class Verdict:
    label: str
    confidence: str            # HIGH | LOW
    reason: str
    findings: list = field(default_factory=list)


def _fingerprint(kind: str, company: str, key: str) -> str:
    raw = f"{kind}|{company}|{_norm(key)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _numbers(text: str) -> list[float]:
    """Numbers in an answer, excluding year tokens and quarter digits."""
    out = []
    cleaned = re.sub(r"\bq[1-4]\b|\b20(2[0-9])\b", " ", (text or "").lower())
    for m in re.finditer(r"-?\d[\d,]*\.?\d*", cleaned):
        tok = m.group(0).replace(",", "").rstrip(".")
        if not tok or tok == "-":
            continue
        try:
            out.append(float(tok))
        except ValueError:
            continue
    return out


def _num_match(answer_nums: list[float], oracle_nums: list[float]) -> bool:
    for o in oracle_nums:
        tol = max(0.51, abs(o) * 0.005)
        if any(abs(a - o) <= tol for a in answer_nums):
            return True
    return False


def compute_oracle(ctx: AccessContext, oracle_question: Optional[str]) -> Optional[list[float]]:
    """Ground-truth numbers for a deterministic-parseable question, from the
    deterministic layer itself — independent of whatever run_query did."""
    if not oracle_question:
        return None
    intent = parse_intent(oracle_question)
    if intent is None:
        return None
    det = det_execute(ctx, intent)
    if det is None or det.get("denied"):
        return None
    nums = _numbers(det.get("answer") or "")
    return nums or None


def _denied_table_names(payload: dict, answer: str) -> list[str]:
    names = []
    for source in (str(payload.get("denied_reason") or ""), answer or ""):
        names += _DENIED_TABLE_RE.findall(source)
        for m in _DENIED_LIST_RE.finditer(source):
            names += re.findall(r"[A-Za-z0-9_]+", m.group(1))
    return list(dict.fromkeys(names))


def classify_turn(ctx: AccessContext, expect: str, payload: dict,
                  trace_id: str, answer: str = "",
                  oracle_nums: Optional[list[float]] = None) -> Verdict:
    """Classify one simulated turn. `payload` is the saved trace payload."""
    company = ctx.company.slug
    route = str(payload.get("route") or "")
    decision = payload.get("access_decision")
    allowed_tables = set(ctx.policy.allowed_tables)
    allowed_depts = set(ctx.policy.allowed_departments)

    # 1 — structural leak (worst case, checked first, expectation-independent)
    touched = set(t.lower() for t in (payload.get("tables_touched") or []))
    leaked_tables = touched - {t.lower() for t in allowed_tables}
    leaked_depts = {
        (c.get("department") or "") for c in (payload.get("citations") or [])
        if isinstance(c, dict) and c.get("department")
        and c["department"] not in allowed_depts
    }
    if leaked_tables or leaked_depts:
        what = ", ".join(sorted(leaked_tables | leaked_depts))
        f = _finding(
            "boundary_leak", "needs_sql_rag_fix", "high",
            f"Simulated {ctx.employee.role} answer touched restricted "
            f"data ({what}) for “{payload.get('question', '')[:70]}”.",
            "The 4-layer boundary let restricted evidence through — trace the "
            "layer that failed and add the case to the boundary tests.",
            [trace_id],
        )
        f["fingerprint"] = _fingerprint("boundary_leak", company, what)
        return Verdict("exceptional", "HIGH", f"restricted data leaked: {what}", [f])

    # 2 — denials
    if decision == "denied":
        names = _denied_table_names(payload, answer)
        ghost = [n for n in names if n.lower() not in
                 {t.lower() for t in ALL_TABLES}]
        if route == "cross_company_scope_clarification":
            if expect in ("cross_company", "any"):
                return Verdict("correct", "HIGH",
                               "cross-company ask correctly clarified/refused")
            return Verdict("wrong", "LOW",
                           "cross-company clarification fired unexpectedly")
        if ghost:
            f = _finding(
                "denial_names_nonexistent_table", "needs_sql_rag_fix", "high",
                f"Access-denial message names '{ghost[0]}', which does not "
                f"exist anywhere in the company schema — a query-generation "
                f"failure was reported to the employee as a permissions "
                f"problem (question: “{payload.get('question', '')[:70]}”, "
                f"route {route}).",
                "Before labeling ACCESS_DENIED_TABLE as an access denial, "
                "check the name against the full company schema. If it is "
                "not a real table, this is a generation failure: retry with "
                "a schema reminder, fall back to the deterministic answer, "
                "or say honestly that the query could not be generated.",
                [trace_id],
                suggested_eval={"question": payload.get("question", ""),
                                "expect": "generation-failure handling, not an access refusal"},
                self_fixable=True,
            )
            f["fingerprint"] = _fingerprint("denial_names_nonexistent_table",
                                            company, ghost[0])
            return Verdict("exceptional", "HIGH",
                           f"denial names nonexistent table '{ghost[0]}'", [f])
        if expect in ("refusal", "any"):
            return Verdict("correct", "HIGH",
                           "valid role refusal naming a real restricted area")
        f = _finding(
            "allowed_question_refused", "needs_access_policy_review", "high",
            f"{ctx.employee.role} was refused on an in-role question: "
            f"“{payload.get('question', '')[:70]}”.",
            "The question targets data inside this role's policy; find which "
            "layer refused it and why.",
            [trace_id],
            suggested_eval={"question": payload.get("question", ""),
                            "expect": "answered within role"},
        )
        f["fingerprint"] = _fingerprint("allowed_question_refused", company,
                                        payload.get("question", ""))
        return Verdict("wrong", "HIGH", "in-role question was refused", [f])

    # 3 — routing outcomes
    if route in _CLARIFY_ROUTES:
        if expect in ("clarification", "any"):
            return Verdict("correct", "HIGH", "clarified as expected")
        if expect == "answer_numeric":
            f = _finding(
                "clear_question_clarified", "needs_routing_fix", "medium",
                f"A fully-parseable question got a clarification instead of "
                f"an answer: “{payload.get('question', '')[:70]}”.",
                "The deterministic parser handles this phrasing — the "
                "clarification gate is over-triggering on it.",
                [trace_id],
                suggested_eval={"question": payload.get("question", ""),
                                "expect": "deterministic answer"},
                self_fixable=True,
            )
            f["fingerprint"] = _fingerprint("clear_question_clarified", company,
                                            payload.get("question", ""))
            return Verdict("wrong", "LOW", "clear question was clarified", [f])
        return Verdict("vague", "LOW", "clarification where an answer was expected")

    if route == "repeat_question_choice":
        if expect in ("repeat_choice", "any"):
            return Verdict("correct", "HIGH", "repeat gate offered choices")
        f = _finding(
            "repeat_gate_misfire", "needs_routing_fix", "medium",
            f"Repeat-question gate fired on a non-repeat: "
            f"“{payload.get('question', '')[:70]}”.",
            "Check repeat detection normalization.",
            [trace_id], self_fixable=True,
        )
        f["fingerprint"] = _fingerprint("repeat_gate_misfire", company,
                                        payload.get("question", ""))
        return Verdict("wrong", "LOW", "unexpected repeat gate", [f])

    if route == "degraded_mode":
        if oracle_nums:
            f = _finding(
                "degraded_when_deterministic_available", "needs_routing_fix",
                "medium",
                f"Degraded-mode reply for a question the deterministic layer "
                f"can answer: “{payload.get('question', '')[:70]}”.",
                "Fall back to the deterministic template before giving up.",
                [trace_id], self_fixable=True,
            )
            f["fingerprint"] = _fingerprint("degraded_when_deterministic_available",
                                            company, payload.get("question", ""))
            return Verdict("exceptional", "HIGH",
                           "degraded despite deterministic answer existing", [f])
        return Verdict("vague", "HIGH",
                       "providers exhausted; honest degraded reply (not a bug)")

    # 4 — answered
    if expect == "repeat_choice":
        f = _finding(
            "repeat_answered_without_choice", "needs_routing_fix", "medium",
            f"A repeated question was silently re-answered instead of "
            f"offering use-previous / rerun / analyze choices: "
            f"“{payload.get('question', '')[:70]}”.",
            "The repeat-question gate should intercept this; add the "
            "question to the repeat-detection regression tests.",
            [trace_id],
            suggested_eval={"question": payload.get("question", ""),
                            "expect": "repeat_question_choice on second ask"},
            self_fixable=True,
        )
        f["fingerprint"] = _fingerprint("repeat_answered_without_choice",
                                        company, payload.get("question", ""))
        return Verdict("wrong", "HIGH", "repeat re-answered without choices", [f])

    if expect == "refusal":
        f = _finding(
            "should_have_refused_but_answered", "needs_access_policy_review",
            "high",
            f"Out-of-role question was answered instead of refused: "
            f"“{payload.get('question', '')[:70]}” ({ctx.employee.role}).",
            "No structural leak was detected in evidence, but the refusal "
            "path did not engage — verify what data backed this answer.",
            [trace_id],
        )
        f["fingerprint"] = _fingerprint("should_have_refused_but_answered",
                                        company, payload.get("question", ""))
        return Verdict("exceptional", "HIGH", "restricted ask was answered", [f])

    if expect == "cross_company":
        f = _finding(
            "cross_company_not_clarified", "needs_routing_fix", "high",
            f"Question naming another company was answered without the "
            f"cross-company clarification: “{payload.get('question', '')[:70]}”.",
            "The cross-company detector missed this alias/phrasing.",
            [trace_id], self_fixable=True,
        )
        f["fingerprint"] = _fingerprint("cross_company_not_clarified", company,
                                        payload.get("question", ""))
        return Verdict("wrong", "HIGH", "cross-company ask answered silently", [f])

    if expect == "clarification":
        f = _finding(
            "ambiguous_answered_confidently", "needs_routing_fix", "high",
            f"An ambiguous/malformed question got a confident answer instead "
            f"of a clarification: “{payload.get('question', '')[:70]}”.",
            "Partial understanding must become a clarification question, "
            "never a confident answer — add this phrasing to the gate tests.",
            [trace_id],
            suggested_eval={"question": payload.get("question", ""),
                            "expect": "clarification"},
            self_fixable=True,
        )
        f["fingerprint"] = _fingerprint("ambiguous_answered_confidently",
                                        company, payload.get("question", ""))
        return Verdict("wrong", "HIGH", "ambiguous question answered confidently", [f])

    if expect == "honest_absence":
        citations = payload.get("citations") or []
        if _ABSENCE_RE.search(answer or "") or route in ("no_data",):
            return Verdict("correct", "HIGH",
                           "nonexistent entity handled honestly")
        if citations:
            return Verdict("correct", "LOW",
                           "answered from documents — plausible grounding, "
                           "verify the citations actually cover the ask")
        if _numbers(answer):
            f = _finding(
                "hallucinated_nonexistent_entity", "needs_sql_rag_fix", "high",
                f"Confident numeric answer for an entity that does not exist "
                f"in the workspace: “{payload.get('question', '')[:70]}”.",
                "The answer cites no evidence and the entity has no table or "
                "document — the number cannot be grounded. The system should "
                "say the data does not exist.",
                [trace_id],
                suggested_eval={"question": payload.get("question", ""),
                                "expect": "honest 'not tracked here'"},
            )
            f["fingerprint"] = _fingerprint("hallucinated_nonexistent_entity",
                                            company, payload.get("question", ""))
            return Verdict("exceptional", "HIGH",
                           "ungrounded number for nonexistent entity", [f])
        return Verdict("vague", "LOW", "neither honest absence nor grounded answer")

    if expect == "answer_numeric" and oracle_nums:
        ans_nums = _numbers(answer)
        if _num_match(ans_nums, oracle_nums):
            return Verdict("correct", "HIGH", "matches deterministic oracle")
        if ans_nums:
            f = _finding(
                "numeric_mismatch_vs_oracle", "needs_sql_rag_fix", "high",
                f"Answer disagrees with the deterministic oracle for "
                f"“{payload.get('question', '')[:70]}” "
                f"(answered {ans_nums[:3]}, oracle {oracle_nums[:3]}).",
                "Re-run against the template SQL; if the agent answer is "
                "wrong, fix and add a regression eval.",
                [trace_id],
                suggested_eval={"question": payload.get("question", ""),
                                "expect": f"value ≈ {oracle_nums[0]}"},
            )
            f["fingerprint"] = _fingerprint("numeric_mismatch_vs_oracle",
                                            company, payload.get("question", ""))
            return Verdict("wrong", "HIGH", "number contradicts oracle", [f])
        f = _finding(
            "expected_number_missing", "needs_sql_rag_fix", "medium",
            f"A numeric question came back with no number: "
            f"“{payload.get('question', '')[:70]}”.",
            "Check whether the answer degraded to prose or evidence capture "
            "failed.",
            [trace_id],
        )
        f["fingerprint"] = _fingerprint("expected_number_missing", company,
                                        payload.get("question", ""))
        return Verdict("vague", "HIGH", "numeric answer missing its number", [f])

    if route in ("rag_agent", "rag_only") and not (payload.get("citations") or []):
        f = _finding(
            "rag_answer_without_citations", "needs_sql_rag_fix", "high",
            f"Document-routed answer cites no documents: "
            f"“{payload.get('question', '')[:70]}”.",
            "Either evidence was weak (should have abstained/clarified) or "
            "citation capture is broken.",
            [trace_id],
        )
        f["fingerprint"] = _fingerprint("rag_answer_without_citations", company,
                                        payload.get("question", ""))
        return Verdict("vague", "HIGH", "RAG answer without citations", [f])

    if route in _ANSWER_ROUTES or route in ("dashboard", "repeat_used_previous"):
        return Verdict("correct", "HIGH" if payload.get("llm_skipped") else "LOW",
                       f"answered via {route} with no failed checks")
    return Verdict("vague", "LOW", f"unrecognized route {route!r}")
