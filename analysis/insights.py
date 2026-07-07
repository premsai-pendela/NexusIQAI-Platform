"""Analyst notes: deterministic follow-up analysis for SQL answers.

When a question asks for an aggregate (revenue or transaction volume), a
human analyst would not stop at the number — they would break it down and
compare it to the prior period. This module does exactly that with fixed,
read-only SQL over ``sales_transactions``:

- breakdown by region and product category for the same period
- prior-period comparison (quarter → previous quarter, year → previous year)
- short insight sentences computed from those rows

Guardrails: every query string is a constant template; the only injected
values are ISO dates produced by the period parser (regex-validated years
and fixed quarter boundaries). Amounts are GROSS (SUM of total_amount) and
labeled as such — this is a breakdown layer, not a restatement of governed
net metrics. No LLM anywhere.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text

logger = logging.getLogger(__name__)

_QUARTERS = {"q1": ("01-01", "03-31"), "q2": ("04-01", "06-30"),
             "q3": ("07-01", "09-30"), "q4": ("10-01", "12-31")}

_REVENUE_CUES = ("revenue", "sales")
_VOLUME_CUES = ("transaction", "transactions", "orders", "how many sales")


def parse_period(question: str) -> Optional[Tuple[str, str, str, Optional[Tuple[str, str, str]]]]:
    """Return (start, end, label, previous_period) or None.

    previous_period is (start, end, label) for the immediately prior
    quarter/year, used for the trend comparison.
    """
    q = question.lower()
    year_match = re.search(r"\b(20\d{2})\b", q)
    quarter_match = re.search(r"\b(q[1-4])\b", q)
    if not year_match:
        return None
    year = int(year_match.group(1))
    if quarter_match:
        quarter = quarter_match.group(1)
        start, end = _QUARTERS[quarter]
        number = int(quarter[1])
        if number == 1:
            prev_year, prev_q = year - 1, "q4"
        else:
            prev_year, prev_q = year, f"q{number - 1}"
        prev_start, prev_end = _QUARTERS[prev_q]
        return (
            f"{year}-{start}", f"{year}-{end}", f"{quarter.upper()} {year}",
            (f"{prev_year}-{prev_start}", f"{prev_year}-{prev_end}",
             f"{prev_q.upper()} {prev_year}"),
        )
    return (
        f"{year}-01-01", f"{year}-12-31", str(year),
        (f"{year - 1}-01-01", f"{year - 1}-12-31", str(year - 1)),
    )


def _detect_kind(question: str) -> Optional[str]:
    q = question.lower()
    if any(cue in q for cue in _REVENUE_CUES):
        return "revenue"
    if any(cue in q for cue in _VOLUME_CUES):
        return "transactions"
    return None


_AGG = {"revenue": "SUM(total_amount)", "transactions": "COUNT(*)"}

_BREAKDOWN_SQL = (
    "SELECT {dimension}, {agg} AS value FROM sales_transactions "
    "WHERE transaction_date BETWEEN :start AND :end "
    "GROUP BY {dimension} ORDER BY value DESC"
)
_TOTAL_SQL = (
    "SELECT {agg} FROM sales_transactions "
    "WHERE transaction_date BETWEEN :start AND :end"
)


def _fmt(value: float, kind: str) -> str:
    if kind == "revenue":
        if value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        return f"${value:,.0f}"
    return f"{int(value):,}"


def build_insights(question: str, session_factory) -> Optional[Dict]:
    """Return analyst notes for an aggregate question, or None.

    ``session_factory`` is a callable returning a SQLAlchemy session
    (the SQL agent's). All failures degrade to None — the answer itself is
    never blocked by the analysis layer.
    """
    kind = _detect_kind(question)
    period = parse_period(question)
    if not kind or not period:
        return None
    start, end, label, previous = period

    try:
        session = session_factory()
        agg = _AGG[kind]

        breakdowns: List[Dict] = []
        for dimension in ("region", "product_category"):
            rows = session.execute(
                text(_BREAKDOWN_SQL.format(dimension=dimension, agg=agg)),
                {"start": start, "end": end},
            ).fetchall()
            values = [(str(r[0]), float(r[1] or 0)) for r in rows if r[0] is not None]
            total = sum(v for _, v in values) or 1.0
            breakdowns.append({
                "dimension": dimension,
                "rows": [{"label": name, "value": round(v, 2),
                          "share": round(v / total, 4)} for name, v in values[:6]],
            })

        current_total = float(session.execute(
            text(_TOTAL_SQL.format(agg=agg)), {"start": start, "end": end}
        ).fetchone()[0] or 0)

        trend = None
        if previous:
            prev_start, prev_end, prev_label = previous
            prev_total = float(session.execute(
                text(_TOTAL_SQL.format(agg=agg)), {"start": prev_start, "end": prev_end}
            ).fetchone()[0] or 0)
            if prev_total > 0:
                trend = {
                    "current": round(current_total, 2),
                    "previous": round(prev_total, 2),
                    "previous_label": prev_label,
                    "delta_pct": round((current_total - prev_total) / prev_total * 100, 1),
                }
        session.commit()
    except Exception as exc:
        logger.warning("insights degraded: %s", exc)
        return None

    if current_total <= 0:
        return None

    unit = "gross revenue" if kind == "revenue" else "transactions"
    notes: List[str] = []
    top_region = next((b["rows"][0] for b in breakdowns
                       if b["dimension"] == "region" and b["rows"]), None)
    if top_region:
        notes.append(
            f"{top_region['label']} led regions with "
            f"{_fmt(top_region['value'], kind)} — {top_region['share']:.0%} of {label} {unit}.")
    top_cat = next((b["rows"][0] for b in breakdowns
                    if b["dimension"] == "product_category" and b["rows"]), None)
    if top_cat:
        notes.append(
            f"{top_cat['label']} was the largest category at "
            f"{_fmt(top_cat['value'], kind)} ({top_cat['share']:.0%}).")
    if trend:
        direction = "up" if trend["delta_pct"] >= 0 else "down"
        notes.append(
            f"{label} {unit} came in {direction} {abs(trend['delta_pct']):.1f}% "
            f"vs {trend['previous_label']} ({_fmt(trend['previous'], kind)} → "
            f"{_fmt(trend['current'], kind)}).")

    return {
        "kind": kind,
        "unit": unit,
        "period_label": label,
        "breakdowns": breakdowns,
        "trend": trend,
        "notes": notes,
        "method": ("deterministic follow-up SQL over sales_transactions "
                   "(gross amounts by transaction_date); no LLM"),
    }
