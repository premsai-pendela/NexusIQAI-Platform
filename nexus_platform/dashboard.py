"""Deterministic multi-chart dashboards.

"Give me a dashboard" answers are built from canned, role-filtered SQL run
directly against the company workspace database — no LLM call, so they are
instant, cheap, and can never hallucinate. Each block declares the table it
needs; a block renders only when that table is inside the caller's role
allowlist, so an HR dashboard and an Analyst dashboard differ automatically.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Optional

from nexus_platform.auth import AccessContext
from nexus_platform.contexts import company_db_path

_DASHBOARD_WORDS = ("dashboard", "overview of the business", "business overview",
                    "executive summary view")


def wants_dashboard(question: str) -> bool:
    q = question.lower()
    return any(w in q for w in _DASHBOARD_WORDS)


# Each block: (required_table, kind, title, sql)
# kind: "kpi" (single value) | "bar" | "line"
_BLOCKS: list[tuple[str, str, str, str]] = [
    ("orders", "kpi", "Revenue FY2024",
     "SELECT ROUND(SUM(total_amount),0) AS value FROM orders WHERE status='completed'"),
    ("orders", "kpi", "Completed orders",
     "SELECT COUNT(*) AS value FROM orders WHERE status='completed'"),
    ("customers", "kpi", "Active customers",
     "SELECT COUNT(*) AS value FROM customers"),
    ("invoices", "kpi", "Overdue invoices",
     "SELECT COUNT(*) AS value FROM invoices WHERE status='overdue'"),
    ("support_tickets", "kpi", "Avg CSAT (resolved)",
     "SELECT ROUND(AVG(csat),2) AS value FROM support_tickets WHERE csat IS NOT NULL"),
    ("employees_hr", "kpi", "Headcount",
     "SELECT COUNT(*) AS value FROM employees_hr WHERE termination_date IS NULL"),
    ("employees_hr", "kpi", "2024 attrition",
     "SELECT COUNT(*) AS value FROM employees_hr WHERE termination_date IS NOT NULL"),
    ("orders", "line", "Monthly revenue",
     "SELECT strftime('%Y-%m', order_date) AS month, ROUND(SUM(total_amount),0) AS revenue "
     "FROM orders WHERE status='completed' GROUP BY month ORDER BY month"),
    ("orders", "bar", "Revenue by region",
     "SELECT region, ROUND(SUM(total_amount),0) AS revenue FROM orders "
     "WHERE status='completed' GROUP BY region ORDER BY revenue DESC"),
    ("orders", "bar", "Top products by revenue",
     "SELECT p.name AS product, ROUND(SUM(o.total_amount),0) AS revenue FROM orders o "
     "JOIN products p ON p.product_id=o.product_id WHERE o.status='completed' "
     "GROUP BY p.name ORDER BY revenue DESC LIMIT 5"),
    ("invoices", "line", "Invoiced amount by month",
     "SELECT strftime('%Y-%m', issue_date) AS month, ROUND(SUM(amount),0) AS amount "
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


def build_dashboard(ctx: AccessContext) -> Optional[dict]:
    """Role-scoped dashboard payload, or None when no blocks are allowed."""
    allowed = set(ctx.policy.allowed_tables)
    conn = sqlite3.connect(str(company_db_path(ctx.company.slug)))
    conn.row_factory = sqlite3.Row
    kpis: list[dict] = []
    charts: list[dict] = []
    sql_used: list[str] = []
    try:
        for table, kind, title, sql in _BLOCKS:
            if table not in allowed:
                continue
            # Belt-and-braces: canned SQL must never touch other tables
            referenced = set(re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, re.I))
            if not referenced <= allowed:
                continue
            if kind == "kpi" and len(kpis) >= _MAX_KPIS:
                continue
            if kind != "kpi" and len(charts) >= _MAX_CHARTS:
                continue
            rows = [dict(r) for r in conn.execute(sql).fetchall()]
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
    finally:
        conn.close()

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
