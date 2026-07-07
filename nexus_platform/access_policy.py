"""Role-based access policies.

One policy per role: which SQL tables and which document departments the role
may see. Enforced in four layers:
1. SQL generation prompt only describes allowed tables (SQLAgent schema subset)
2. SQL AST validation rejects any query touching a non-allowed table
3. ChromaDB retrieval is always filtered to allowed departments
4. Citations/traces are filtered again before leaving the API

Policies are deny-by-default: an unknown role gets nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Departments used to tag document chunks at brain-build time.
ALL_DEPARTMENTS = ("general", "finance", "hr", "support", "product", "ops")

# Tables every demo company database contains.
ALL_TABLES = (
    "orders",
    "customers",
    "products",
    "invoices",
    "support_tickets",
    "employees_hr",
)


@dataclass(frozen=True)
class RolePolicy:
    role: str
    allowed_tables: tuple[str, ...]
    allowed_departments: tuple[str, ...]
    summary: str
    denied_summary: str


ROLE_POLICIES: dict[str, RolePolicy] = {
    "Admin": RolePolicy(
        role="Admin",
        allowed_tables=ALL_TABLES,
        allowed_departments=ALL_DEPARTMENTS,
        summary="Full access to all company tables and documents, plus data management and review tools.",
        denied_summary="",
    ),
    "CEO": RolePolicy(
        role="CEO",
        allowed_tables=ALL_TABLES,
        allowed_departments=ALL_DEPARTMENTS,
        summary="Full access to all company tables and documents, plus data management and review tools.",
        denied_summary="",
    ),
    "Analyst": RolePolicy(
        role="Analyst",
        allowed_tables=("orders", "customers", "products", "invoices", "support_tickets"),
        allowed_departments=("general", "finance", "product", "support"),
        summary="Revenue, orders, customers, products, invoices, and support metrics; finance/product/support documents.",
        denied_summary="HR workforce data and HR policy documents.",
    ),
    "Finance": RolePolicy(
        role="Finance",
        allowed_tables=("invoices", "orders", "customers", "products"),
        allowed_departments=("general", "finance", "product"),
        summary="Invoices, revenue, payments, orders, and customer spend; finance documents.",
        denied_summary="HR workforce data, support tickets, and HR/support documents.",
    ),
    "HR": RolePolicy(
        role="HR",
        allowed_tables=("employees_hr",),
        allowed_departments=("general", "hr"),
        summary="Headcount, attrition, departments, and HR/compliance policy documents.",
        denied_summary="Revenue, orders, customers, invoices, support tickets, and finance documents.",
    ),
    "Support": RolePolicy(
        role="Support",
        allowed_tables=("support_tickets", "customers", "products"),
        allowed_departments=("general", "support", "product"),
        summary="Support tickets, SLAs, customer issues, and support/product documents.",
        denied_summary="Revenue, invoices, HR data, and finance/HR documents.",
    ),
    "Ops": RolePolicy(
        role="Ops",
        allowed_tables=("orders", "products", "support_tickets"),
        allowed_departments=("general", "ops", "product", "support"),
        summary="Orders, products, incidents, and operations documents.",
        denied_summary="Invoices, customer financials, HR data, and finance/HR documents.",
    ),
}


# Topic keywords per data area, used to detect questions that clearly target
# a restricted area so we can refuse politely BEFORE any retrieval happens.
TABLE_TOPICS: dict[str, tuple[str, ...]] = {
    "orders": ("revenue", "order", "orders", "sales", "aov", "bookings"),
    "customers": ("customer", "customers", "churn", "mrr", "segment", "account"),
    "products": ("product", "products", "catalog", "pricing", "list price"),
    "invoices": ("invoice", "invoices", "billing", "payment", "payments", "overdue", "dso", "collections"),
    "support_tickets": ("ticket", "tickets", "csat", "sla", "support", "resolution time", "escalation"),
    "employees_hr": ("headcount", "attrition", "termination", "terminated", "hired",
                     "hires", "salary", "salaries", "compensation", "workforce",
                     "employee count", "employees were", "how many employees", "staff"),
}

DEPARTMENT_TOPICS: dict[str, tuple[str, ...]] = {
    "hr": ("pto", "paid time off", "parental leave", "vacation days", "salary band",
           "harassment", "hr policy", "performance review", "promotion cycle",
           "compliance training", "onboarding policy"),
    "finance": ("billing policy", "revenue recognition", "discount policy", "net-30",
                "collections target"),
    "support": ("sla", "support playbook", "escalation policy", "csat target"),
    "ops": ("runbook", "incident", "sev1", "sev2", "vendor management", "postmortem"),
}


def classify_restricted_intent(question: str, policy: RolePolicy) -> str | None:
    """Return a short reason when a question clearly targets restricted data.

    Conservative: only fires when restricted-area keywords match and NO
    allowed-area keywords do. Ambiguous questions run through the engine,
    where the AST allowlist and retrieval filters still enforce the boundary.
    """
    q = f" {question.lower()} "

    def matches(topics: tuple[str, ...]) -> bool:
        return any(t in q for t in topics)

    hits_allowed = any(
        matches(TABLE_TOPICS.get(t, ())) for t in policy.allowed_tables
    ) or any(
        matches(DEPARTMENT_TOPICS.get(d, ())) for d in policy.allowed_departments
    )
    if hits_allowed:
        return None

    for table, topics in TABLE_TOPICS.items():
        if table not in policy.allowed_tables and matches(topics):
            return f"the '{table}' data area is outside your role"
    for dept, topics in DEPARTMENT_TOPICS.items():
        if dept not in policy.allowed_departments and matches(topics):
            return f"{dept} documents are outside your role"
    return None


def get_policy(role: str) -> RolePolicy:
    """Deny-by-default: unknown roles get an empty policy."""
    return ROLE_POLICIES.get(role) or RolePolicy(
        role=role, allowed_tables=(), allowed_departments=(),
        summary="No data access configured for this role.",
        denied_summary="All company data.",
    )


def refusal_message(role: str, company_name: str, detail: str = "") -> str:
    policy = get_policy(role)
    msg = (
        f"I can't answer that from your current access level. "
        f"Your {policy.role} role in the {company_name} workspace covers: {policy.summary}"
    )
    if policy.denied_summary:
        msg += f" It does not include: {policy.denied_summary}"
    if detail:
        msg += f" ({detail})"
    msg += " If you need this data, you can submit an access request through Feedback."
    return msg
