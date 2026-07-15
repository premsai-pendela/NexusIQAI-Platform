"""Analyst orchestrator — the top-level route decision for Ask Analyst.

Every question gets an explicit RouteDecision BEFORE anything answers:

    dashboard | repeat_question_choice | clarification | llm_planner |
    sql_plus_rag | deterministic_sql | agent (sql/rag decided downstream)

The decision is cheap (regex/keyword features, no LLM) and is recorded in the
trace so Admin review and the Health Check agent can audit routing. The
guiding rule is the deterministic safety gate: a template answer is allowed
only when the parse is complete and unambiguous — partial understanding must
become a clarification question, never a confident answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from nexus_platform.access_policy import RolePolicy
from nexus_platform.deterministic import (
    Features, Intent, _METRIC_LABELS, _period_index, extract_features,
    parse_intent, metric_exists,
)

# ── Detection vocabularies ──────────────────────────────────────────────

# Words that make a metric reference ambiguous instead of parseable.
_AMBIGUOUS_TERMS = ("market", "related", "divide", "figures", "numbers",
                    "stats", "metrics", "performance")

_INSIGHT_RE = re.compile(
    r"\bwhy\b|\bwhat caused\b|\bwhat drove\b|\breason for\b|\broot cause\b"
    r"|\bexplain (?:the )?(?:drop|increase|change|dip|spike|decline|growth)"
)

_DOC_TERMS_RE = re.compile(
    r"\bpolicy\b|\bpolicies\b|\bplaybook\b|\bguidelines?\b|\bcontract\b"
    r"|\bcompliance\b|\bhandbook\b|\bmemo\b|\brunbook\b|\bslas?\b"
    r"|\bpostmortem\b|\broadmap\b"
)

_OVERBROAD_RE = re.compile(
    r"\banaly[sz]e everything\b|\btell me everything\b|\banaly[sz]e (?:it )?all\b"
    r"|\beverything about\b|\banaly[sz]e the (?:whole|entire) company\b"
)

_VAGUE_RE = re.compile(r"\b(better|improve|improved|fix|nicer|again|redo)\b")

_TABLE_HINT_RE = re.compile(
    r"\binvoice|\brevenue|\border|\bsales\b|\bcustomer|\bticket|\bproduct"
    r"|\bheadcount\b|\bemployee|\bmrr\b|\bcsat\b"
)

# Scalar-metric ask shape ("what is our X …") for the unknown-metric gate.
_SCALAR_ASK_RE = re.compile(
    r"(?:what(?:'s| is| was)|show me|how much is)\s+(?:our|the|my)\s+"
    r"([a-z][a-z0-9 _-]{1,40}?)"
    r"(?=\s+(?:for|in|this|last|over|during|by|per|right now)\b|\s*$)"
)

# Generic measurement suffixes carry no information about *which* metric is
# meant — they are ignored when checking the term against the vocabulary.
_METRIC_SUFFIXES = frozenset(("score", "rate", "ratio", "margin", "index",
                              "value", "number", "numbers", "figure",
                              "figures", "metric", "metrics"))

_metric_vocab_cache: frozenset | None = None


def _metric_vocabulary() -> frozenset:
    """Every word the workspace's metrics, tables, and topic maps know.

    A metric term with no overlap here is one the workspace does not define
    — the SQL path must not invent semantics for it (see the unknown-metric
    clarification below).
    """
    global _metric_vocab_cache
    if _metric_vocab_cache is None:
        from nexus_platform.access_policy import (DEPARTMENT_TOPICS,
                                                  TABLE_AREAS, TABLE_TOPICS)
        from nexus_platform.deterministic import METRICS, _GROUP_PATTERNS
        words: set[str] = set()
        for mdef in METRICS.values():
            for kw in mdef.keywords:
                words.update(kw.split())
        for label in _METRIC_LABELS.values():
            words.update(label.lower().split())
        for area, tables in TABLE_AREAS.items():
            words.add(area)
            for t in tables:
                words.add(t)
                words.update(t.split("_"))
        for topics in (*TABLE_TOPICS.values(), *DEPARTMENT_TOPICS.values()):
            for topic in topics:
                words.update(topic.split())
        words.update(key for key, _ in _GROUP_PATTERNS)
        _metric_vocab_cache = frozenset(w for w in words if len(w) > 2)
    return _metric_vocab_cache


@dataclass
class Clarification:
    kind: str                       # unclear_metric | malformed_period | ...
    question: str                   # the one short question we ask back
    choices: list = field(default_factory=list)  # full askable questions

    def to_payload(self) -> dict:
        return {"kind": self.kind, "question": self.question,
                "choices": list(self.choices)[:3]}


@dataclass
class RouteDecision:
    route: str                      # see module docstring
    intent: Optional[Intent] = None
    clarification: Optional[Clarification] = None
    force_source: Optional[str] = None   # passed to the fusion engine
    insight: bool = False
    reason: str = ""


# ── Choice builders (every choice is a full, parseable question) ────────

def _metric_label(metric: Optional[str]) -> str:
    return _METRIC_LABELS.get(metric or "", metric or "revenue")


def role_metric_choices(policy: RolePolicy) -> list:
    """Role-safe starter questions for unclear/overbroad asks."""
    out = []
    tables = set(policy.allowed_tables)
    if "orders" in tables:
        out += ["What was total revenue in 2024?", "Revenue by region"]
    if "invoices" in tables:
        out.append("How many overdue invoices do we have?")
    if "support_tickets" in tables:
        out.append("Support tickets by priority")
    if "employees_hr" in tables:
        out += ["What is our headcount?", "Headcount by department"]
    return out[:3] or ["Give me a dashboard"]


def _invoice_metric_choices() -> list:
    return ["Total invoiced amount for 2024",
            "How many overdue invoices do we have?",
            "Invoice amount by status"]


def _titled(metric: Optional[str], rest: str) -> str:
    label = _metric_label(metric)
    return f"{label[0].upper()}{label[1:]} {rest}".strip()


# ── Clarification gate ──────────────────────────────────────────────────

def find_clarification(question: str, f: Features, policy: RolePolicy,
                       prev: Optional[Intent]) -> Optional[Clarification]:
    """Return the clarification this question needs, or None if it is safe
    to keep routing. Checks are ordered most-specific first."""
    q = " " + question.lower().strip().rstrip("?.!") + " "

    # 1. Overbroad ("analyze everything")
    if _OVERBROAD_RE.search(q):
        return Clarification(
            kind="overbroad",
            question=("That's broader than one answer. Where should I start? "
                      "Here are areas your role can see:"),
            choices=["Give me a dashboard"] + role_metric_choices(policy),
        )

    # 2. Malformed period tokens ("a4", "q7")
    if f.malformed_tokens and (f.metric or f.explicit_periods):
        tok = f.malformed_tokens[0]
        guess = None
        m = re.fullmatch(r"[a-z]([1-4])", tok)
        if m:
            guess = f"Q{m.group(1)}"
        choices = []
        if guess and f.explicit_periods:
            named = " and ".join(p[0] for p in f.explicit_periods)
            choices.append(_titled(f.metric, f"for only {named} and {guess} 2024"))
        if f.explicit_periods:
            choices.append(_titled(f.metric, f"for {f.explicit_periods[0][0]}"))
        elif guess:
            choices.append(_titled(f.metric, f"for {guess} 2024"))
        choices.append(_titled(f.metric, "for FY 2024"))
        return Clarification(
            kind="malformed_period",
            question=(f"I couldn't read “{tok}” as a time period — "
                      f"quarters are Q1–Q4. Did you mean one of these?"),
            choices=choices,
        )

    # 3. Unclear metric ("show market by invoice")
    if f.metric is None and any(t in q for t in _AMBIGUOUS_TERMS) and (
            f.explicit_periods or f.output != "auto" or _TABLE_HINT_RE.search(q)):
        choices = (_invoice_metric_choices() if "invoice" in q
                   else role_metric_choices(policy))
        return Clarification(
            kind="unclear_metric",
            question=("I can answer this, but I need one detail first: "
                      "which metric do you mean? For example:"),
            choices=choices,
        )

    # 4. Contradictory period request ("only q1 and q3 from q1 to q4")
    if f.selection_marker and f.range_marker and f.has_only:
        sel = [p for p in f.explicit_periods]
        named = " and ".join(p[0] for p in sel[:2]) if sel else "the quarters"
        return Clarification(
            kind="contradictory_periods",
            question=(f"That mixes a specific selection with a range, so I "
                      f"want to be sure: only {named}, or the full range?"),
            choices=[_titled(f.metric, f"for only {named}"),
                     _titled(f.metric, "from Q1 through Q4 2024")],
        )

    # 5. Ambiguous selection ("q1 and q3" — only those, or Q1..Q3?).
    # Metric-less corrections of a previous question ("sorry I mean q2 and
    # q4?") inherit the previous intent instead — the earlier turn already
    # fixed metric and output, so the selection reading is not ambiguous.
    is_correction = f.metric is None and prev is not None and prev.metric
    if (f.is_selection and not f.has_only and f.output == "auto"
            and not is_correction
            and len(f.explicit_periods) == 2):
        a, b = sorted(f.explicit_periods, key=_period_index)
        if _period_index(b) - _period_index(a) > 1:
            return Clarification(
                kind="ambiguous_selection",
                question=(f"For {a[0]} and {b[0]}, do you want only those two "
                          f"periods, or everything from {a[0].split()[0]} "
                          f"through {b[0].split()[0]}?"),
                choices=[_titled(f.metric, f"for only {a[0]} and {b[0]}"),
                         _titled(f.metric,
                                 f"from {a[0].split()[0]} through {b[0].split()[0]} 2024")],
            )

    # 6. Pie chart needs a categorical breakdown — never silently render a
    # KPI/line instead ("pie chart revenue over time", "pie of Q3 revenue").
    _CATEGORICAL = ("region", "product", "category", "segment", "plan",
                    "department", "priority", "status")
    if f.output == "pie" and (f.group_by not in _CATEGORICAL
                              or f.is_selection or f.is_range
                              or re.search(r"\bover time\b", q)):
        choices = []
        if f.metric in (None, "revenue", "orders", "aov"):
            choices = [_titled(f.metric or "revenue", "as a pie chart by region"),
                       _titled(f.metric or "revenue", "as a pie chart by product"),
                       _titled(f.metric or "revenue", "as a line chart by month")]
        else:
            choices = [_titled(f.metric, "as a pie chart by category"),
                       _titled(f.metric, "as a bar chart by month")]
        return Clarification(
            kind="pie_unsuitable",
            question=("Pie charts work best for category breakdowns, not "
                      "time periods. Want a pie by category, or keep time on "
                      "a line/bar chart?"),
            choices=choices,
        )

    # 7. Vague follow-up ("make it better")
    words = [w for w in re.findall(r"[a-z']+", q)]
    if (prev is not None and prev.metric and f.metric is None
            and not f.explicit_periods and f.group_by is None
            and f.output == "auto" and f.top_n is None
            and len(words) <= 5 and _VAGUE_RE.search(q)):
        # Only suggest the previous metric if this role can actually see it —
        # a refused turn's metric must not become the suggestion.
        from nexus_platform.deterministic import METRICS
        prev_def = METRICS.get(prev.metric)
        prev_allowed = (prev_def is not None
                        and set(prev_def.tables) <= set(policy.allowed_tables))
        if prev_allowed:
            label = _metric_label(prev.metric)
            choices = [_titled(prev.metric, "by region"),
                       f"Compare {label} Q3 vs Q4",
                       f"Monthly {label} trend"]
        else:
            choices = role_metric_choices(policy)
        return Clarification(
            kind="vague_followup",
            question=("Happy to go further — what would make it better?"),
            choices=choices,
        )

    # 8. Unknown business metric ("What is our NPS score for 2024?"). The
    # workspace does not define it anywhere the parser knows, so a confident
    # answer could only be fabricated — the SQL agent has been observed
    # inventing an NPS formula over the 1-5 CSAT scale and answering "-1"
    # (health-check campaign camp_c305c02583, trace tr_63dee96201). Honest
    # move: say it isn't tracked, offer the role's real metrics plus an
    # explicit documents path. Conservative: any recognized metric word,
    # insight cue, or document cue → not our case, keep routing.
    if (f.metric is None and f.group_by is None and f.top_n is None
            and not _INSIGHT_RE.search(q) and not _DOC_TERMS_RE.search(q)
            and len(q.split()) <= 12):
        m = _SCALAR_ASK_RE.search(q)
        if m:
            term = m.group(1).strip()
            tokens = [t for t in re.findall(r"[a-z0-9]+", term)
                      if t not in _METRIC_SUFFIXES and len(t) > 1]
            if tokens and len(tokens) <= 4 and not any(
                    t in _metric_vocabulary() for t in tokens):
                return Clarification(
                    kind="unknown_metric",
                    question=(f"\u201c{term}\u201d isn\u2019t a metric tracked in your "
                              "workspace data, so I can\u2019t compute it without "
                              "guessing. I can answer one of these instead, or "
                              "check your documents:"),
                    choices=(role_metric_choices(policy)[:2]
                             + [f"What do our documents say about {term}?"]),
                )

    return None


# ── Route decision ──────────────────────────────────────────────────────

def decide_route(question: str, policy: RolePolicy,
                 prev: Optional[Intent] = None,
                 repeat_action: Optional[str] = None) -> RouteDecision:
    """Decide how one analyst question should be handled.

    Repeat/dashboard handling happens in the query service (they need session
    state); this function owns the language-understanding decision.
    """
    f = extract_features(question)
    q = " " + question.lower().strip().rstrip("?.!") + " "

    # Forced AI reinterpretation of a repeated question
    if repeat_action == "analyze_with_ai":
        return RouteDecision(route="llm_planner", insight=True,
                             reason="user chose 'Analyze with AI' for a repeated question")

    # Insight/why questions need reasoning over tools, not a template scalar.
    if _INSIGHT_RE.search(q):
        return RouteDecision(route="llm_planner", insight=True,
                             reason="insight/why question needs the planner over SQL/RAG tools")

    clar = find_clarification(question, f, policy, prev)
    if clar is not None:
        return RouteDecision(route="clarification", clarification=clar,
                             reason=f"clarification needed: {clar.kind}")

    # If a metric word appears in the question but parsing didn't capture it,
    # ask for clarification.
    if f.metric is None:
        # metric labels are the human‑readable names for known metrics
        _metric_labels = [lbl.lower() for lbl in _METRIC_LABELS.values()]
        if any(lbl in q for lbl in _metric_labels):
            return RouteDecision(
                route="clarification",
                clarification=Clarification(
                    kind="unclear_metric",
                    question=("I couldn't determine which metric you mean. "
                              "Did you mean one of these?"),
                    choices=role_metric_choices(policy),
                ),
                reason="clarification needed: unrecognized metric word"
            )
        # Detect metric‑like tokens that are not in the catalog (e.g., "NPS score").
        # Look for a word preceding common metric nouns such as "score", "rate",
        # "percentage", or "ratio". If found, treat it as an unrecognized metric.
        m = re.search(r"\b(\w+)\s+(score|rate|percentage|ratio)\b", q)
        if m:
            return RouteDecision(
                route="clarification",
                clarification=Clarification(
                    kind="unclear_metric",
                    question=("I couldn't determine which metric you mean. "
                              "Did you mean one of these?"),
                    choices=role_metric_choices(policy),
                ),
                reason="clarification needed: unrecognized metric token"
            )

    # If a metric was identified but doesn't exist in the catalog, clarify.
    if f.metric and not metric_exists(f.metric):
        return RouteDecision(
            route="clarification",
            clarification=Clarification(
                kind="unknown_metric",
                question=(f"I don't have data for '{f.metric}'. "
                          "Did you mean one of these?"),
                choices=role_metric_choices(policy),
            ),
            reason=f"clarification needed: unknown metric '{f.metric}'"
        )

    # Policy + numbers in one question → both evidence sources, cross-checked.
    if _DOC_TERMS_RE.search(q) and (f.metric or f.explicit_periods):
        return RouteDecision(route="sql_plus_rag", force_source="sql_rag",
                             reason="question mixes document policy with metrics")

    intent = parse_intent(question, prev)
    if intent is not None:
        return RouteDecision(route="deterministic_sql", intent=intent,
                             reason="complete deterministic parse")

    return RouteDecision(route="agent",
                         reason="no deterministic family matched; engine routes SQL/RAG")
