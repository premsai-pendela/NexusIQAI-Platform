"""Deterministic multi-chart dashboards.

"Give me a dashboard" answers are built from canned, role-filtered SQL run
directly against the company workspace database — no LLM call, so they are
instant, cheap, and can never hallucinate. Each block declares the table it
needs; a block renders only when that table is inside the caller's role
allowlist, so an HR dashboard and an Analyst dashboard differ automatically.
"""

from __future__ import annotations

import re
from typing import Optional

from nexus_platform.auth import AccessContext

_DASHBOARD_WORDS = ("dashboard", "overview of the business", "business overview",
                    "executive summary view")


def wants_dashboard(question: str) -> bool:
    q = question.lower()
    return any(w in q for w in _DASHBOARD_WORDS)


# Each block: (required_table, kind, title, sql)
# kind: "kpi" (single value) | "bar" | "line"
_BLOCKS: list[tuple[str, str, str, str]] = [
    ("orders", "kpi", "Revenue FY2024",
     "SELECT ROUND(SUM(total_amount),0) AS value FROM orders "
     "WHERE status='completed' AND order_date >= '2024-01-01'"),
    ("orders", "kpi", "Completed orders FY2024",
     "SELECT COUNT(*) AS value FROM orders "
     "WHERE status='completed' AND order_date >= '2024-01-01'"),
    ("customers", "kpi", "Active customers",
     "SELECT COUNT(*) AS value FROM customers"),
    ("invoices", "kpi", "Overdue invoices",
     "SELECT COUNT(*) AS value FROM invoices WHERE status='overdue'"),
    ("support_tickets", "kpi", "Avg CSAT (resolved)",
     "SELECT ROUND(AVG(csat),2) AS value FROM support_tickets WHERE csat IS NOT NULL"),
    ("employees_hr", "kpi", "Headcount",
     "SELECT COUNT(*) AS value FROM employees_hr WHERE termination_date IS NULL"),
    ("employees_hr", "kpi", "2024 attrition",
     "SELECT COUNT(*) AS value FROM employees_hr "
     "WHERE termination_date >= '2024-01-01'"),
    ("orders", "line", "Monthly revenue",
     "SELECT {month:order_date} AS month, ROUND(SUM(total_amount),0) AS revenue "
     "FROM orders WHERE status='completed' GROUP BY month ORDER BY month"),
    ("orders", "bar", "Revenue by region (FY2024)",
     "SELECT region, ROUND(SUM(total_amount),0) AS revenue FROM orders "
     "WHERE status='completed' AND order_date >= '2024-01-01' "
     "GROUP BY region ORDER BY revenue DESC"),
    ("orders", "bar", "Top products by revenue (FY2024)",
     "SELECT p.name AS product, ROUND(SUM(o.total_amount),0) AS revenue FROM orders o "
     "JOIN products p ON p.product_id=o.product_id WHERE o.status='completed' "
     "AND o.order_date >= '2024-01-01' "
     "GROUP BY p.name ORDER BY revenue DESC LIMIT 5"),
    ("invoices", "line", "Invoiced amount by month",
     "SELECT {month:issue_date} AS month, ROUND(SUM(amount),0) AS amount "
     "FROM invoices GROUP BY month ORDER BY month"),
    ("support_tickets", "bar", "Tickets by category",
     "SELECT category, COUNT(*) AS tickets FROM support_tickets GROUP BY category "
     "ORDER BY tickets DESC"),
    ("support_tickets", "bar", "Avg resolution hours by priority",
     "SELECT priority, ROUND(AVG(resolution_hours),1) AS hours FROM support_tickets "
     "WHERE resolution_hours IS NOT NULL GROUP BY priority ORDER BY hours DESC"),
    ("employees_hr", "bar", "Headcount by department",
     "SELECT department, COUNT(*) AS employees FROM employees_hr "
     "WHERE termination_date IS NULL GROUP BY department ORDER BY employees DESC"),
    ("employees_hr", "bar", "2024 terminations by department",
     "SELECT department, COUNT(*) AS terminated FROM employees_hr "
     "WHERE termination_date IS NOT NULL GROUP BY department ORDER BY terminated DESC"),
]

_MAX_KPIS = 4
_MAX_CHARTS = 4


def _render_sql(sql: str, dialect: str) -> str:
    """Expand `{month:col}` placeholders into dialect-correct SQL."""
    from nexus_platform.db import month_expr

    return re.sub(r"\{month:(\w+)\}",
                  lambda m: month_expr(dialect, m.group(1)), sql)


def build_dashboard(ctx: AccessContext) -> Optional[dict]:
    """Role-scoped dashboard payload, or None when no blocks are allowed."""
    from nexus_platform.db import dialect_name, run_rows

    allowed = set(ctx.policy.allowed_tables)
    dialect = dialect_name(ctx.company.slug)
    kpis: list[dict] = []
    charts: list[dict] = []
    sql_used: list[str] = []
    for table, kind, title, sql in _BLOCKS:
        if table not in allowed:
            continue
        sql = _render_sql(sql, dialect)
        # Belt-and-braces: canned SQL must never touch other tables
        referenced = set(re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, re.I))
        if not referenced <= allowed:
            continue
        if kind == "kpi" and len(kpis) >= _MAX_KPIS:
            continue
        if kind != "kpi" and len(charts) >= _MAX_CHARTS:
            continue
        rows = run_rows(ctx.company.slug, sql)
        if not rows:
            continue
        sql_used.append(sql)
        if kind == "kpi":
            kpis.append({"title": title, "value": rows[0]["value"]})
        else:
            cols = list(rows[0].keys())
            charts.append({
                "type": kind, "title": title, "x": cols[0], "y": cols[1],
                "data": rows, "download": {"csv": True},
            })

    if not kpis and not charts:
        return None
    return {
        "company": ctx.company.name,
        "role": ctx.employee.role,
        "kpis": kpis,
        "charts": charts,
        "sql_used": sql_used,
        "note": (f"Built from the {len(sql_used)} queries your {ctx.employee.role} "
                 f"role can run — deterministic SQL, no model in the loop."),
    }
