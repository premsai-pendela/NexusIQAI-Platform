"""Expanded company workspace schema — 35 tables, dialect-portable DDL.

Column types are abstract tokens mapped per dialect so one definition builds
both the PostgreSQL schema (showcase scale) and the SQLite mirror (offline
tests). Money is NUMERIC in PG so ROUND(x, 2) works; SQLite stores REAL.

The first six tables are the original core — their columns are frozen
because the deterministic template layer and existing tests depend on them.
"""

from __future__ import annotations

_TYPE_MAP = {
    "postgresql": {"I": "INTEGER", "T": "TEXT", "M": "NUMERIC(14,2)",
                   "R": "DOUBLE PRECISION", "D": "DATE", "TS": "TIMESTAMP"},
    "sqlite": {"I": "INTEGER", "T": "TEXT", "M": "REAL",
               "R": "REAL", "D": "TEXT", "TS": "TEXT"},
}

# table -> [(column, type_token, "PK"|"NULL"|"")]
TABLES: dict[str, list[tuple[str, str, str]]] = {
    # ── Core six (frozen shapes) ────────────────────────────────────────
    "products": [
        ("product_id", "I", "PK"), ("name", "T", ""), ("category", "T", ""),
        ("list_price", "M", ""), ("launched", "D", ""),
    ],
    "customers": [
        ("customer_id", "I", "PK"), ("name", "T", ""), ("segment", "T", ""),
        ("region", "T", ""), ("signup_date", "D", ""), ("plan", "T", ""),
        ("mrr", "M", ""),
    ],
    "orders": [
        ("order_id", "I", "PK"), ("order_date", "D", ""),
        ("customer_id", "I", ""), ("product_id", "I", ""),
        ("region", "T", ""), ("quantity", "I", ""), ("unit_price", "M", ""),
        ("total_amount", "M", ""), ("status", "T", ""),
    ],
    "invoices": [
        ("invoice_id", "I", "PK"), ("customer_id", "I", ""),
        ("issue_date", "D", ""), ("due_date", "D", ""), ("amount", "M", ""),
        ("status", "T", ""), ("paid_date", "D", "NULL"),
    ],
    "support_tickets": [
        ("ticket_id", "I", "PK"), ("created_at", "TS", ""),
        ("customer_id", "I", ""), ("category", "T", ""), ("priority", "T", ""),
        ("status", "T", ""), ("resolution_hours", "R", "NULL"),
        ("csat", "I", "NULL"),
    ],
    "employees_hr": [
        ("emp_id", "I", "PK"), ("department", "T", ""), ("role_title", "T", ""),
        ("region", "T", ""), ("hire_date", "D", ""),
        ("termination_date", "D", "NULL"), ("salary_band", "T", ""),
    ],
    # ── Org ─────────────────────────────────────────────────────────────
    "departments": [
        ("department_id", "I", "PK"), ("name", "T", ""), ("cost_center", "T", ""),
        ("head_emp_id", "I", "NULL"),
    ],
    "teams": [
        ("team_id", "I", "PK"), ("department_id", "I", ""), ("name", "T", ""),
        ("manager_emp_id", "I", ""),
    ],
    "payroll_summary": [
        ("id", "I", "PK"), ("month", "T", ""), ("department", "T", ""),
        ("headcount", "I", ""), ("total_payroll", "M", ""),
        ("total_benefits", "M", ""),
    ],
    # ── Customer graph ──────────────────────────────────────────────────
    "contacts": [
        ("contact_id", "I", "PK"), ("customer_id", "I", ""), ("name", "T", ""),
        ("title", "T", ""), ("email", "T", ""), ("is_primary", "I", ""),
    ],
    "churn_events": [
        ("id", "I", "PK"), ("customer_id", "I", ""), ("event_date", "D", ""),
        ("reason", "T", ""), ("mrr_lost", "M", ""),
    ],
    # ── Product/pricing ─────────────────────────────────────────────────
    "plans": [
        ("plan_id", "I", "PK"), ("name", "T", ""), ("monthly_price", "M", ""),
        ("seats_included", "I", ""), ("tier", "T", ""),
    ],
    "price_changes": [
        ("id", "I", "PK"), ("product_id", "I", ""), ("changed_on", "D", ""),
        ("old_price", "M", ""), ("new_price", "M", ""), ("reason", "T", ""),
    ],
    # ── Sales/usage ─────────────────────────────────────────────────────
    "order_items": [
        ("item_id", "I", "PK"), ("order_id", "I", ""), ("product_id", "I", ""),
        ("quantity", "I", ""), ("unit_price", "M", ""), ("line_total", "M", ""),
    ],
    "subscriptions": [
        ("subscription_id", "I", "PK"), ("customer_id", "I", ""),
        ("plan_id", "I", ""), ("started_on", "D", ""),
        ("canceled_on", "D", "NULL"), ("seats", "I", ""), ("mrr", "M", ""),
    ],
    "usage_events": [
        ("event_id", "I", "PK"), ("customer_id", "I", ""),
        ("product_id", "I", ""), ("event_ts", "TS", ""), ("event_type", "T", ""),
        ("units", "I", ""),
    ],
    # ── Finance ─────────────────────────────────────────────────────────
    "invoice_lines": [
        ("line_id", "I", "PK"), ("invoice_id", "I", ""), ("description", "T", ""),
        ("quantity", "I", ""), ("unit_price", "M", ""), ("line_total", "M", ""),
    ],
    "payments": [
        ("payment_id", "I", "PK"), ("invoice_id", "I", ""), ("paid_on", "D", ""),
        ("amount", "M", ""), ("method", "T", ""), ("status", "T", ""),
    ],
    "refunds": [
        ("refund_id", "I", "PK"), ("order_id", "I", ""), ("refunded_on", "D", ""),
        ("amount", "M", ""), ("reason", "T", ""),
    ],
    "credit_notes": [
        ("credit_id", "I", "PK"), ("customer_id", "I", ""), ("issued_on", "D", ""),
        ("amount", "M", ""), ("reason", "T", ""),
    ],
    "expenses": [
        ("expense_id", "I", "PK"), ("incurred_on", "D", ""),
        ("department", "T", ""), ("category", "T", ""), ("amount", "M", ""),
        ("description", "T", ""),
    ],
    "bills": [
        ("bill_id", "I", "PK"), ("vendor_id", "I", ""), ("billed_on", "D", ""),
        ("due_on", "D", ""), ("amount", "M", ""), ("status", "T", ""),
    ],
    "saas_subscriptions": [
        ("id", "I", "PK"), ("tool", "T", ""), ("owner_department", "T", ""),
        ("monthly_cost", "M", ""), ("seats", "I", ""), ("renewal_date", "D", ""),
    ],
    "vendors": [
        ("vendor_id", "I", "PK"), ("name", "T", ""), ("category", "T", ""),
        ("country", "T", ""), ("active", "I", ""),
    ],
    "purchase_orders": [
        ("po_id", "I", "PK"), ("vendor_id", "I", ""), ("ordered_on", "D", ""),
        ("amount", "M", ""), ("status", "T", ""), ("department", "T", ""),
    ],
    "contracts": [
        ("contract_id", "I", "PK"), ("customer_id", "I", "NULL"),
        ("vendor_id", "I", "NULL"), ("kind", "T", ""), ("starts_on", "D", ""),
        ("ends_on", "D", ""), ("annual_value", "M", ""), ("status", "T", ""),
    ],
    "finance_reports": [
        ("report_id", "I", "PK"), ("period", "T", ""), ("kind", "T", ""),
        ("revenue", "M", ""), ("expenses", "M", ""), ("net", "M", ""),
        ("file", "T", ""),
    ],
    "board_updates": [
        ("update_id", "I", "PK"), ("period", "T", ""), ("headline", "T", ""),
        ("file", "T", ""),
    ],
    # ── Support ─────────────────────────────────────────────────────────
    "ticket_messages": [
        ("message_id", "I", "PK"), ("ticket_id", "I", ""), ("sent_at", "TS", ""),
        ("author", "T", ""), ("body", "T", ""),
    ],
    "slas": [
        ("sla_id", "I", "PK"), ("priority", "T", ""),
        ("first_response_hours", "I", ""), ("resolution_hours", "I", ""),
    ],
    "csat_responses": [
        ("response_id", "I", "PK"), ("ticket_id", "I", ""),
        ("submitted_on", "D", ""), ("score", "I", ""), ("comment", "T", "NULL"),
    ],
    "escalations": [
        ("escalation_id", "I", "PK"), ("ticket_id", "I", ""),
        ("escalated_on", "TS", ""), ("to_team", "T", ""), ("reason", "T", ""),
    ],
    "incidents": [
        ("incident_id", "I", "PK"), ("opened_at", "TS", ""), ("severity", "T", ""),
        ("service", "T", ""), ("minutes_to_resolve", "I", "NULL"),
        ("postmortem_file", "T", "NULL"),
    ],
    # ── Marketing ───────────────────────────────────────────────────────
    "campaigns": [
        ("campaign_id", "I", "PK"), ("name", "T", ""), ("channel", "T", ""),
        ("started_on", "D", ""), ("budget", "M", ""), ("leads_target", "I", ""),
    ],
    "leads": [
        ("lead_id", "I", "PK"), ("campaign_id", "I", ""), ("created_on", "D", ""),
        ("source", "T", ""), ("status", "T", ""), ("est_value", "M", ""),
    ],
}


def create_table_sql(table: str, dialect: str) -> str:
    types = _TYPE_MAP[dialect]
    cols = []
    for name, token, extra in TABLES[table]:
        col = f"{name} {types[token]}"
        if extra == "PK":
            col += " PRIMARY KEY"
        elif extra != "NULL":
            col += " NOT NULL"
        cols.append(col)
    return f"CREATE TABLE {table} ({', '.join(cols)})"


def insert_sql(table: str) -> str:
    cols = [c for c, _, _ in TABLES[table]]
    placeholders = ", ".join(f":{c}" for c in cols)
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
