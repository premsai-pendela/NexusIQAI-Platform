"""Deterministic analyst layer — template SQL for common business questions.

Common analytics families (revenue, orders, customers, invoices, tickets,
HR) are answered WITHOUT any LLM: a keyword/regex intent parser produces an
Intent, role policy is checked, safe template SQL runs against the company
workspace database, and the answer + chart spec are formatted
deterministically. Traces record route `deterministic_sql_template` with
`llm_skipped: true`.

This is the demo-stability backbone: these families keep working when every
model provider is exhausted. Unsupported or genuinely complex questions fall
through to the LLM engine (returning None here).

Safety: user text NEVER enters SQL. Templates are fixed strings; the only
variables are ISO dates derived from a fixed period table and enum values
matched against a fixed vocabulary.
"""

from __future__ import annotations

import calendar
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Optional

from nexus_platform.auth import AccessContext
from nexus_platform.contexts import company_db_path

# ── Periods (fiscal 2024, matching the demo data) ───────────────────────

_QUARTERS = {
    "q1": ("Q1 2024", "2024-01-01", "2024-04-01"),
    "q2": ("Q2 2024", "2024-04-01", "2024-07-01"),
    "q3": ("Q3 2024", "2024-07-01", "2024-10-01"),
    "q4": ("Q4 2024", "2024-10-01", "2025-01-01"),
}

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}


def _month_period(month_i: int) -> tuple[str, str, str]:
    label = f"{calendar.month_name[month_i]} 2024"
    start = f"2024-{month_i:02d}-01"
    if month_i == 12:
        end = "2025-01-01"
    else:
        end = f"2024-{month_i + 1:02d}-01"
    return (label, start, end)


_YEAR = ("FY 2024", "2024-01-01", "2025-01-01")


def _find_periods(q: str) -> list[tuple[str, str, str]]:
    """All periods mentioned, in order of appearance."""
    found: list[tuple[int, tuple[str, str, str]]] = []
    for m in re.finditer(r"\bq([1-4])(?:\s+2024)?\b", q):
        found.append((m.start(), _QUARTERS[f"q{m.group(1)}"]))
    for name, i in _MONTHS.items():
        m = re.search(rf"\b{name}(?:\s+2024)?\b", q)
        if m:
            found.append((m.start(), _month_period(i)))
    if re.search(r"\b(2024|this year|the year|full year|ytd)\b", q):
        m = re.search(r"\b(2024|this year|the year|full year|ytd)\b", q)
        found.append((m.start(), _YEAR))
    found.sort(key=lambda t: t[0])
    out = []
    for _, p in found:
        if p not in out:
            out.append(p)
    return out


# ── Metrics ─────────────────────────────────────────────────────────────
# metric → (tables required, value SQL, date column or None, unit, keywords)

@dataclass(frozen=True)
class MetricDef:
    tables: tuple[str, ...]
    value_sql: str          # aggregate select over the base table(s)
    base_from: str          # FROM clause
    date_col: Optional[str]
    unit: str               # "$" | "" | "hrs" | "/5"
    keywords: tuple[str, ...]
    base_where: str = ""    # always-on filter


METRICS: dict[str, MetricDef] = {
    "revenue": MetricDef(
        tables=("orders",),
        value_sql="ROUND(SUM(o.total_amount), 2)",
        base_from="orders o",
        date_col="o.order_date",
        unit="$",
        keywords=("revenue", "sales", "how much did we sell", "sold"),
        base_where="o.status = 'completed'",
    ),
    "orders": MetricDef(
        tables=("orders",),
        value_sql="COUNT(*)",
        base_from="orders o",
        date_col="o.order_date",
        unit="",
        keywords=("how many orders", "order count", "number of orders", "order volume", "orders"),
        base_where="o.status = 'completed'",
    ),
    "aov": MetricDef(
        tables=("orders",),
        value_sql="ROUND(SUM(o.total_amount) / NULLIF(COUNT(*), 0), 2)",
        base_from="orders o",
        date_col="o.order_date",
        unit="$",
        keywords=("average order value", "aov", "avg order value"),
        base_where="o.status = 'completed'",
    ),
    "customers": MetricDef(
        tables=("customers",),
        value_sql="COUNT(*)",
        base_from="customers c",
        date_col=None,
        unit="",
        keywords=("how many customers", "customer count", "number of customers", "active customers"),
    ),
    "mrr": MetricDef(
        tables=("customers",),
        value_sql="ROUND(SUM(c.mrr), 2)",
        base_from="customers c",
        date_col=None,
        unit="$",
        keywords=("mrr", "monthly recurring revenue", "recurring revenue"),
    ),
    "invoice_amount": MetricDef(
        tables=("invoices",),
        value_sql="ROUND(SUM(i.amount), 2)",
        base_from="invoices i",
        date_col="i.issue_date",
        unit="$",
        keywords=("invoiced amount", "invoice total", "total invoiced", "invoice amount", "billing total"),
    ),
    "invoice_count": MetricDef(
        tables=("invoices",),
        value_sql="COUNT(*)",
        base_from="invoices i",
        date_col="i.issue_date",
        unit="",
        keywords=("how many invoices", "invoice count", "number of invoices"),
    ),
    "overdue_invoices": MetricDef(
        tables=("invoices",),
        value_sql="COUNT(*)",
        base_from="invoices i",
        date_col="i.issue_date",
        unit="",
        keywords=("overdue invoice", "overdue invoices", "past due", "unpaid invoices", "overdue"),
        base_where="i.status = 'overdue'",
    ),
    "tickets": MetricDef(
        tables=("support_tickets",),
        value_sql="COUNT(*)",
        base_from="support_tickets t",
        date_col="t.created_at",
        unit="",
        keywords=("how many tickets", "ticket count", "ticket volume", "support tickets", "tickets"),
    ),
    "csat": MetricDef(
        tables=("support_tickets",),
        value_sql="ROUND(AVG(t.csat), 2)",
        base_from="support_tickets t",
        date_col="t.created_at",
        unit="/5",
        keywords=("csat", "satisfaction score", "customer satisfaction"),
        base_where="t.csat IS NOT NULL",
    ),
    "resolution_hours": MetricDef(
        tables=("support_tickets",),
        value_sql="ROUND(AVG(t.resolution_hours), 1)",
        base_from="support_tickets t",
        date_col="t.created_at",
        unit="hrs",
        keywords=("resolution time", "resolution hours", "time to resolve", "how long to resolve"),
        base_where="t.resolution_hours IS NOT NULL",
    ),
    "headcount": MetricDef(
        tables=("employees_hr",),
        value_sql="COUNT(*)",
        base_from="employees_hr e",
        date_col=None,
        unit="",
        keywords=("headcount", "how many employees", "employee count", "staff count", "number of employees"),
        base_where="e.termination_date IS NULL",
    ),
    "terminations": MetricDef(
        tables=("employees_hr",),
        value_sql="COUNT(*)",
        base_from="employees_hr e",
        date_col="e.termination_date",
        unit="",
        keywords=("terminations", "terminated", "employees left", "how many left", "employees were terminated"),
        base_where="e.termination_date IS NOT NULL",
    ),
    "attrition_rate": MetricDef(
        tables=("employees_hr",),
        value_sql=("ROUND(100.0 * SUM(CASE WHEN e.termination_date IS NOT NULL THEN 1 ELSE 0 END) "
                   "/ NULLIF(COUNT(*), 0), 1)"),
        base_from="employees_hr e",
        date_col=None,
        unit="%",
        keywords=("attrition rate", "attrition", "turnover rate", "churn rate of employees"),
    ),
}

# ── Groupings ───────────────────────────────────────────────────────────
# group key → per-metric-base: (label expr, extra join, required tables)

_GROUPS: dict[str, dict[str, tuple[str, str, tuple[str, ...]]]] = {
    "region": {
        "orders": ("o.region", "", ("orders",)),
        "customers": ("c.region", "", ("customers",)),
        "employees_hr": ("e.region", "", ("employees_hr",)),
    },
    "product": {
        "orders": ("p.name", "JOIN products p ON p.product_id = o.product_id", ("orders", "products")),
    },
    "category": {
        "orders": ("p.category", "JOIN products p ON p.product_id = o.product_id", ("orders", "products")),
        "support_tickets": ("t.category", "", ("support_tickets",)),
    },
    "segment": {
        "customers": ("c.segment", "", ("customers",)),
    },
    "plan": {
        "customers": ("c.plan", "", ("customers",)),
    },
    "department": {
        "employees_hr": ("e.department", "", ("employees_hr",)),
    },
    "priority": {
        "support_tickets": ("t.priority", "", ("support_tickets",)),
    },
    "status": {
        "invoices": ("i.status", "", ("invoices",)),
        "support_tickets": ("t.status", "", ("support_tickets",)),
        "orders": ("o.status", "", ("orders",)),
    },
    "month": {},     # handled via strftime on the metric's date column
    "quarter": {},   # handled via CASE on the metric's date column
}

_GROUP_PATTERNS = [
    ("region", r"\bby region\b|\bper region\b|\bregional\b|\bacross regions\b"),
    ("product", r"\bby product\b|\bper product\b|\bproducts by\b|\bproduct\b.*\b(top|best|bottom|worst)\b|\b(top|best|bottom|worst)\b.*\bproducts?\b"),
    ("category", r"\bby category\b|\bper category\b"),
    ("segment", r"\bby segment\b|\bper segment\b"),
    ("plan", r"\bby plan\b|\bper plan\b"),
    ("department", r"\bby department\b|\bper department\b|\bdepartment breakdown\b|\bacross departments\b"),
    ("priority", r"\bby priority\b|\bper priority\b"),
    ("status", r"\bby status\b|\bper status\b"),
    ("month", r"\bby month\b|\bmonthly\b|\bmonth over month\b|\bper month\b|\bmonthly trend\b"),
    ("quarter", r"\bby quarter\b|\bquarterly\b|\bper quarter\b"),
]


@dataclass
class Intent:
    metric: Optional[str] = None
    period: Optional[tuple] = None       # (label, start, end)
    compare: Optional[tuple] = None
    selected_periods: Optional[list[tuple]] = None
    group_by: Optional[str] = None
    top_n: Optional[int] = None
    top_dir: str = "desc"
    output: str = "auto"                 # auto | bar | line | table | kpi
    followup_kind: Optional[str] = None  # rechart | period_swap | compare_add | None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(raw: Optional[str]) -> Optional["Intent"]:
        if not raw:
            return None
        try:
            d = json.loads(raw)
            for k in ("period", "compare"):
                if d.get(k):
                    d[k] = tuple(d[k])
            if d.get("selected_periods"):
                d["selected_periods"] = [tuple(p) for p in d["selected_periods"]]
            return Intent(**d)
        except Exception:
            return None


_CHART_WORDS = {"bar": "bar", "line": "line", "trend": "line", "plot": "bar",
                "graph": "bar", "chart": "bar", "table": "table"}

_FOLLOWUP_STARTS = ("what about", "how about", "and ", "now ", "same for",
                    "show that", "show it", "make that", "chart that",
                    "plot that", "compare", "as a ", "what's it")


def _parse_output(q: str) -> str:
    if re.search(r"\bline (chart|graph)\b|\btrend\b", q):
        return "line"
    if re.search(r"\bbar (chart|graph)\b", q):
        return "bar"
    if re.search(r"\btable\b", q):
        return "table"
    if re.search(r"\bchart\b|\bgraph\b|\bplot\b|\bvisual", q):
        return "bar"
    return "auto"


def parse_intent(question: str, prev: Optional[Intent] = None) -> Optional[Intent]:
    """Parse a question into an Intent; merge with prev for follow-ups.

    Returns None when the question doesn't fit any deterministic family.
    """
    q = " " + question.lower().strip().rstrip("?.!") + " "

    intent = Intent()

    # metric (longest keyword match wins so "overdue invoices" beats "invoices")
    best: tuple[int, Optional[str]] = (0, None)
    for name, mdef in METRICS.items():
        for kw in mdef.keywords:
            if kw in q and len(kw) > best[0]:
                best = (len(kw), name)
    intent.metric = best[1]

    periods = _find_periods(q)
    explicit_periods = [p for p in periods if p != _YEAR]
    is_comparison = bool(re.search(r"\bcompare\b|\bvs\.?\b|\bversus\b|\bdifference between\b", q))
    is_period_range = bool(
        len(explicit_periods) >= 2
        and re.search(r"\b(q[1-4]|january|february|march|april|may|june|july|august|september|october|november|december)\b\s*(to|through|thru|-|until)\s*\b(q[1-4]|january|february|march|april|may|june|july|august|september|october|november|december)\b", q)
    )
    is_period_selection = bool(
        len(explicit_periods) >= 2
        and not is_period_range
        and not is_comparison
        and re.search(r"\b(q[1-4]|january|february|march|april|may|june|july|august|september|october|november|december)\b\s*(,|and|&)\s*\b(q[1-4]|january|february|march|april|may|june|july|august|september|october|november|december)\b", q)
    )
    if periods:
        intent.period = periods[0]
        if is_period_selection:
            intent.period = None
            intent.selected_periods = explicit_periods
        elif is_period_range and not is_comparison:
            # "revenue from Q1 to Q4 as a bar graph" means a time-series,
            # not the Q1 scalar. Preserve the full-year window and group by
            # the natural period grain for the mentioned range.
            intent.period = _YEAR
            intent.group_by = "quarter" if periods[0][0].startswith("Q") else "month"
        elif len(periods) >= 2 and is_comparison:
            intent.compare = periods[1]

    for key, pattern in _GROUP_PATTERNS:
        if re.search(pattern, q):
            intent.group_by = key
            break

    m = re.search(r"\b(top|best|highest|largest|bottom|worst|lowest)\s*(\d+)?\b", q)
    if m:
        intent.top_n = int(m.group(2)) if m.group(2) else 5
        intent.top_dir = "asc" if m.group(1) in ("bottom", "worst", "lowest") else "desc"

    intent.output = _parse_output(q)

    # ── follow-up resolution against the previous deterministic turn ────
    words = q.split()
    looks_followup = (
        len(words) <= 8
        or any(q.strip().startswith(s) for s in _FOLLOWUP_STARTS)
        or re.search(r"\b(that|it|those|these|both)\b", q) is not None
    )
    if intent.metric is None and prev is not None and prev.metric and looks_followup:
        # "show that as a bar chart" / "as a table" — re-render previous
        if intent.output != "auto" and not periods and intent.group_by is None:
            merged = Intent(**{**asdict(prev)})
            if merged.period:
                merged.period = tuple(merged.period)
            if merged.compare:
                merged.compare = tuple(merged.compare)
            merged.output = intent.output
            merged.followup_kind = "rechart"
            return merged
        # "what about Q4?" — same metric/group, new period
        if periods:
            merged = Intent(metric=prev.metric, group_by=prev.group_by,
                            top_n=prev.top_n, top_dir=prev.top_dir,
                            output=prev.output)
            merged.period = periods[0]
            if is_comparison and prev.period:
                # "compare with Q3" — previous period vs the named one
                merged.period = tuple(prev.period)
                merged.compare = periods[0]
                merged.followup_kind = "compare_add"
            elif is_period_selection:
                merged.period = None
                merged.compare = None
                merged.selected_periods = explicit_periods
                merged.output = intent.output if intent.output != "auto" else prev.output
                merged.followup_kind = "period_swap"
            else:
                merged.followup_kind = "period_swap"
            return merged
        # "by region?" — same metric/period, new grouping
        if intent.group_by:
            merged = Intent(metric=prev.metric, output=prev.output,
                            period=tuple(prev.period) if prev.period else None)
            merged.group_by = intent.group_by
            merged.followup_kind = "period_swap"
            return merged
        return None

    if intent.metric is None:
        return None
    return intent


# ── SQL building (templates only — no user text) ────────────────────────

def _period_where(mdef: MetricDef, period: Optional[tuple]) -> str:
    if not period or not mdef.date_col:
        return ""
    _, start, end = period
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
        return ""
    return f"{mdef.date_col} >= '{start}' AND {mdef.date_col} < '{end}'"


def _where_clause(mdef: MetricDef, period: Optional[tuple]) -> str:
    wheres = [w for w in (mdef.base_where, _period_where(mdef, period)) if w]
    return f" WHERE {' AND '.join(wheres)}" if wheres else ""


def build_sql(intent: Intent) -> Optional[tuple[str, tuple[str, ...], str]]:
    """(sql, tables_required, template_id) or None if unsupported combo."""
    mdef = METRICS.get(intent.metric or "")
    if mdef is None:
        return None
    base_table = mdef.tables[0]
    where = _where_clause(mdef, intent.period)

    if intent.selected_periods:
        if not mdef.date_col:
            return None
        selects = []
        for period in intent.selected_periods:
            label, _, _ = period
            selects.append(
                f"SELECT '{label}' AS period, {mdef.value_sql} AS value "
                f"FROM {mdef.base_from}{_where_clause(mdef, period)}"
            )
        return " UNION ALL ".join(selects), mdef.tables, f"{intent.metric}_by_selected_period"

    if intent.group_by in ("month", "quarter"):
        if not mdef.date_col:
            return None
        if intent.group_by == "month":
            label = f"strftime('%Y-%m', {mdef.date_col})"
        else:
            label = (f"'Q' || ((CAST(strftime('%m', {mdef.date_col}) AS INTEGER) + 2) / 3)")
        sql = (f"SELECT {label} AS {intent.group_by}, {mdef.value_sql} AS value "
               f"FROM {mdef.base_from}{where} GROUP BY {intent.group_by} ORDER BY {intent.group_by}")
        return sql, mdef.tables, f"{intent.metric}_by_{intent.group_by}"

    if intent.group_by:
        group_map = _GROUPS.get(intent.group_by, {})
        entry = group_map.get(base_table)
        if entry is None:
            return None
        label_expr, join, tables = entry
        all_tables = tuple(dict.fromkeys(mdef.tables + tables))
        order = f"ORDER BY value {'ASC' if intent.top_dir == 'asc' else 'DESC'}"
        limit = f" LIMIT {int(intent.top_n)}" if intent.top_n else ""
        sql = (f"SELECT {label_expr} AS {intent.group_by}, {mdef.value_sql} AS value "
               f"FROM {mdef.base_from} {join}{where} GROUP BY {label_expr} {order}{limit}")
        return sql, all_tables, f"{intent.metric}_by_{intent.group_by}"

    sql = f"SELECT {mdef.value_sql} AS value FROM {mdef.base_from}{where}"
    return sql, mdef.tables, f"{intent.metric}_total"


# ── Formatting ──────────────────────────────────────────────────────────

def _fmt(value, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "$":
        return f"${value:,.2f}"
    if unit == "%":
        return f"{value}%"
    if unit == "/5":
        return f"{value} / 5"
    if unit == "hrs":
        return f"{value} hours"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value:,}" if isinstance(value, (int, float)) else str(value)


_METRIC_LABELS = {
    "revenue": "revenue", "orders": "completed orders", "aov": "average order value",
    "customers": "customers", "mrr": "MRR", "invoice_amount": "invoiced amount",
    "invoice_count": "invoices", "overdue_invoices": "overdue invoices",
    "tickets": "support tickets", "csat": "average CSAT",
    "resolution_hours": "average resolution time", "headcount": "headcount",
    "terminations": "terminations", "attrition_rate": "attrition rate",
}


def _period_label(intent: Intent) -> str:
    if intent.selected_periods:
        return " and ".join(p[0] for p in intent.selected_periods)
    return intent.period[0] if intent.period else "FY 2024"


def execute(ctx: AccessContext, intent: Intent) -> Optional[dict]:
    """Run a deterministic intent. Returns None (unsupported), or a dict:
    {denied: bool, denied_tables, answer, rows, sql, tables, template_id,
     chart, compare_rows}
    """
    built = build_sql(intent)
    if built is None:
        return None
    sql, tables, template_id = built

    allowed = set(ctx.policy.allowed_tables)
    if not set(tables) <= allowed:
        return {
            "denied": True,
            "denied_tables": sorted(set(tables) - allowed),
            "tables": list(tables), "template_id": template_id,
            "answer": "", "rows": [], "sql": None, "chart": None,
        }

    conn = sqlite3.connect(str(company_db_path(ctx.company.slug)))
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(sql).fetchall()]
        compare_rows = None
        compare_sql = None
        if intent.compare:
            cmp_intent = Intent(**{**asdict(intent)})
            cmp_intent.period = tuple(intent.compare)
            cmp_intent.compare = None
            cmp_built = build_sql(cmp_intent)
            if cmp_built:
                compare_sql = cmp_built[0]
                compare_rows = [dict(r) for r in conn.execute(compare_sql).fetchall()]
    finally:
        conn.close()

    mdef = METRICS[intent.metric]
    label = _METRIC_LABELS.get(intent.metric, intent.metric)
    period_label = _period_label(intent)
    company = ctx.company.name

    chart = None
    if intent.selected_periods:
        answer = (f"{company} {label} for {period_label}: "
                  f"{', '.join(f'{r['period']} {_fmt(r.get('value'), mdef.unit)}' for r in rows)}.")
        chart_type = "line" if intent.output == "line" else "bar"
        if intent.output == "table":
            chart_type = "table"
        chart = {
            "type": chart_type,
            "title": f"{label} — {period_label}",
            "x": "period", "y": "value",
            "data": rows, "download": {"csv": True},
        }
    elif intent.compare and compare_rows is not None:
        v1 = rows[0]["value"] if rows else None
        v2 = compare_rows[0]["value"] if compare_rows else None
        cmp_label = intent.compare[0]
        # Direction is always stated chronologically: later period vs earlier
        periods = [(intent.period, v1), (intent.compare, v2)]
        periods.sort(key=lambda t: t[0][1])  # by start date
        (early_p, early_v), (late_p, late_v) = periods
        if early_v is not None and late_v not in (None,) and early_v != 0:
            delta = late_v - early_v
            pct = 100.0 * delta / early_v
            direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
            answer = (f"{company} {label}: **{_fmt(early_v, mdef.unit)}** in {early_p[0]} vs "
                      f"**{_fmt(late_v, mdef.unit)}** in {late_p[0]} — {late_p[0]} {direction} "
                      f"{_fmt(abs(delta), mdef.unit)} ({pct:+.1f}%) vs {early_p[0]}.")
        else:
            answer = (f"{company} {label}: {_fmt(v1, mdef.unit)} in {period_label}, "
                      f"{_fmt(v2, mdef.unit)} in {cmp_label}.")
        chart = {
            "type": "bar",
            "title": f"{label} — {early_p[0]} vs {late_p[0]}",
            "x": "period", "y": "value",
            "data": [{"period": early_p[0], "value": early_v},
                     {"period": late_p[0], "value": late_v}],
            "download": {"csv": True},
        }
        sql = f"{sql};\n{compare_sql}"
    elif intent.group_by:
        answer = (f"{company} {label} by {intent.group_by}"
                  f"{f' — {period_label}' if intent.period else ''}: "
                  f"{len(rows)} groups")
        valued = [r for r in rows if r.get("value") is not None]
        if valued:
            # time groupings come back in chronological order — pick the true
            # peak, not the first row
            peak = max(valued, key=lambda r: r["value"])
            low = min(valued, key=lambda r: r["value"])
            if intent.top_dir == "asc":
                answer += (f"; lowest is **{low[intent.group_by]}** at "
                           f"{_fmt(low['value'], mdef.unit)}.")
            else:
                answer += (f"; peak is **{peak[intent.group_by]}** at "
                           f"{_fmt(peak['value'], mdef.unit)}.")
        chart_type = ("line" if intent.group_by in ("month", "quarter") else "bar")
        if intent.output in ("bar", "line"):
            chart_type = intent.output
        if intent.output == "table":
            chart_type = "table"
        chart = {
            "type": chart_type,
            "title": f"{label} by {intent.group_by}"
                     f"{f' — {period_label}' if intent.period else ''}",
            "x": intent.group_by, "y": "value",
            "data": rows[:50], "download": {"csv": True},
        }
    else:
        value = rows[0]["value"] if rows else None
        answer = f"{company} {label} for {period_label}: **{_fmt(value, mdef.unit)}**."
        chart = {
            "type": "kpi", "title": f"{label} — {period_label}",
            "x": None, "y": "value", "data": rows[:1],
            "download": {"csv": True},
        }

    return {
        "denied": False, "denied_tables": [],
        "answer": answer, "rows": rows, "sql": sql,
        "tables": list(tables), "template_id": template_id, "chart": chart,
    }
