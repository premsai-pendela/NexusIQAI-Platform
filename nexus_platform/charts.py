"""Chart spec generation from SQL results.

Deterministic: inspects result rows and produces a JSON chart spec the
frontend renders (no LLM). Spec shape:
{
  "type": "kpi" | "bar" | "line" | "table",
  "title": str,
  "x": str | None,          # column for x axis / labels
  "y": str | None,          # numeric column
  "data": [ {..row..} ],    # capped rows
  "download": {"csv": true}
}
"""

from __future__ import annotations

import re
from typing import Optional

MAX_CHART_ROWS = 50

_DATE_HINTS = ("date", "month", "quarter", "week", "day", "year", "created", "period")
_CHART_WORDS = ("chart", "graph", "plot", "dashboard", "visual", "trend", "bar ", "line ")


def wants_chart(question: str) -> bool:
    q = question.lower()
    return any(w in q for w in _CHART_WORDS)


def _numeric_columns(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    cols = []
    for key, value in rows[0].items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            cols.append(key)
    return cols


def _label_column(rows: list[dict], numeric: list[str]) -> Optional[str]:
    for key in rows[0]:
        if key not in numeric:
            return key
    return None


def _is_time_label(name: str) -> bool:
    return any(h in name.lower() for h in _DATE_HINTS)


def build_chart_spec(question: str, sql_result: Optional[dict],
                     preferred_type: Optional[str] = None) -> Optional[dict]:
    """Build a chart spec from a successful SQL result, or None."""
    if not sql_result or not sql_result.get("success"):
        return None
    rows = [r for r in (sql_result.get("results") or []) if isinstance(r, dict)]
    if not rows:
        return None
    rows = rows[:MAX_CHART_ROWS]
    numeric = _numeric_columns(rows)
    if not numeric:
        return None

    title = question.strip().rstrip("?")
    title = re.sub(r"^(show|plot|graph|chart|give me|display)\s+", "", title, flags=re.I)
    title = title[:80].strip().capitalize() or "Query result"

    # Single row, single numeric value → KPI card
    if len(rows) == 1 and len(rows[0]) <= 2:
        return {
            "type": "kpi", "title": title, "x": None, "y": numeric[0],
            "data": rows, "download": {"csv": True},
        }

    label = _label_column(rows, numeric)
    if label is None:
        return {
            "type": "table", "title": title, "x": None, "y": None,
            "data": rows, "download": {"csv": True},
        }

    chart_type = "line" if _is_time_label(label) else "bar"
    if preferred_type in ("bar", "line") and len(rows) > 1:
        chart_type = preferred_type
    return {
        "type": chart_type, "title": title, "x": label, "y": numeric[0],
        "data": rows, "download": {"csv": True},
    }
