"""Generate synthetic demo-company data folders.

Usage:
    python -m nexus_platform.seed.generate_company_data [slug ...]

Creates data/demo_companies/<slug>/ with:
- company.db      SQLite: orders, customers, products, invoices,
                  support_tickets, employees_hr (2024 data, deterministic seed)
- docs/<dept>/    markdown documents per department
- sources.json    source registry consumed by the brain builder

All data is synthetic. No real companies, customers, or people.
"""

from __future__ import annotations

import json
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from nexus_platform.contexts import company_dir, company_db_path
from nexus_platform.registry import get_registry

REGIONS = ["East", "West", "North", "South", "Central"]
SEGMENTS = ["Startup", "Mid-Market", "Enterprise"]
TICKET_CATEGORIES = ["billing", "bug", "how-to", "integration", "outage"]
PRIORITIES = ["low", "medium", "high", "urgent"]
DEPARTMENTS_HR = ["Engineering", "Sales", "Marketing", "Support", "Finance", "People"]

COMPANY_PROFILES = {
    "acmecloud": {
        "seed": 42, "n_customers": 220, "n_orders": 4200, "price_mult": 1.0,
        "products": [
            ("Dashboards Pro", "analytics", 299), ("Pipeline Sync", "data-pipeline", 499),
            ("Insight Alerts", "analytics", 149), ("Warehouse Connect", "data-pipeline", 799),
            ("Embedded Charts", "analytics", 399), ("Usage Metering", "platform", 249),
        ],
    },
    "medcore": {
        "seed": 77, "n_customers": 160, "n_orders": 3000, "price_mult": 1.6,
        "products": [
            ("ClinicFlow Scheduler", "scheduling", 449), ("ClaimsBridge", "claims", 899),
            ("ComplianceGuard", "compliance", 649), ("PatientComms", "engagement", 299),
            ("Referral Router", "scheduling", 379),
        ],
    },
    "finpilot": {
        "seed": 91, "n_customers": 260, "n_orders": 5200, "price_mult": 0.8,
        "products": [
            ("Merchant Onboard", "onboarding", 199), ("TxnMonitor", "risk", 599),
            ("Settlement Ledger", "settlement", 749), ("Chargeback Shield", "risk", 349),
            ("Payout Scheduler", "settlement", 279), ("KYC Express", "onboarding", 159),
        ],
    },
}


def _rand_date_2024(rng: random.Random) -> date:
    return date(2024, 1, 1) + timedelta(days=rng.randint(0, 365))


def build_database(slug: str) -> dict:
    profile = COMPANY_PROFILES[slug]
    rng = random.Random(profile["seed"])
    db_path = company_db_path(slug)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE products (
        product_id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
        list_price REAL NOT NULL, launched TEXT NOT NULL
    );
    CREATE TABLE customers (
        customer_id INTEGER PRIMARY KEY, name TEXT NOT NULL, segment TEXT NOT NULL,
        region TEXT NOT NULL, signup_date TEXT NOT NULL, plan TEXT NOT NULL,
        mrr REAL NOT NULL
    );
    CREATE TABLE orders (
        order_id INTEGER PRIMARY KEY, order_date TEXT NOT NULL,
        customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
        product_id INTEGER NOT NULL REFERENCES products(product_id),
        region TEXT NOT NULL, quantity INTEGER NOT NULL, unit_price REAL NOT NULL,
        total_amount REAL NOT NULL, status TEXT NOT NULL
    );
    CREATE TABLE invoices (
        invoice_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL,
        issue_date TEXT NOT NULL, due_date TEXT NOT NULL, amount REAL NOT NULL,
        status TEXT NOT NULL, paid_date TEXT
    );
    CREATE TABLE support_tickets (
        ticket_id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
        customer_id INTEGER NOT NULL, category TEXT NOT NULL, priority TEXT NOT NULL,
        status TEXT NOT NULL, resolution_hours REAL, csat INTEGER
    );
    CREATE TABLE employees_hr (
        emp_id INTEGER PRIMARY KEY, department TEXT NOT NULL, role_title TEXT NOT NULL,
        region TEXT NOT NULL, hire_date TEXT NOT NULL, termination_date TEXT,
        salary_band TEXT NOT NULL
    );
    """)

    mult = profile["price_mult"]
    for i, (name, category, base_price) in enumerate(profile["products"], start=1):
        launched = date(2023, rng.randint(1, 12), rng.randint(1, 28)).isoformat()
        cur.execute("INSERT INTO products VALUES (?,?,?,?,?)",
                    (i, name, category, round(base_price * mult, 2), launched))

    first_words = ["Blue", "Nova", "Cedar", "Quartz", "Harbor", "Summit", "Argon",
                   "Lumen", "Vertex", "Copper", "Aster", "Zephyr", "Onyx", "Delta"]
    second_words = ["Labs", "Retail", "Health", "Logistics", "Media", "Systems",
                    "Foods", "Robotics", "Studios", "Works", "Group", "Partners"]
    for cid in range(1, profile["n_customers"] + 1):
        name = f"{rng.choice(first_words)} {rng.choice(second_words)} {cid}"
        segment = rng.choices(SEGMENTS, weights=[5, 3, 2])[0]
        mrr = {"Startup": rng.uniform(100, 600), "Mid-Market": rng.uniform(600, 2500),
               "Enterprise": rng.uniform(2500, 12000)}[segment] * mult
        signup = date(2023, rng.randint(1, 12), rng.randint(1, 28))
        plan = {"Startup": "Growth", "Mid-Market": "Business", "Enterprise": "Enterprise"}[segment]
        cur.execute("INSERT INTO customers VALUES (?,?,?,?,?,?,?)",
                    (cid, name, segment, rng.choice(REGIONS), signup.isoformat(),
                     plan, round(mrr, 2)))

    n_products = len(profile["products"])
    for oid in range(1, profile["n_orders"] + 1):
        pid = rng.randint(1, n_products)
        cid = rng.randint(1, profile["n_customers"])
        d = _rand_date_2024(rng)
        # Q4 seasonality bump
        if rng.random() < 0.18:
            d = date(2024, rng.randint(10, 12), rng.randint(1, 28))
        qty = rng.randint(1, 8)
        list_price = profile["products"][pid - 1][2] * mult
        unit_price = round(list_price * rng.uniform(0.85, 1.0), 2)
        status = rng.choices(["completed", "refunded", "pending"], weights=[92, 3, 5])[0]
        cur.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)",
                    (oid, d.isoformat(), cid, pid, rng.choice(REGIONS), qty,
                     unit_price, round(qty * unit_price, 2), status))

    inv_id = 1
    for cid in range(1, profile["n_customers"] + 1):
        for month in range(1, 13):
            if rng.random() < 0.7:
                issue = date(2024, month, rng.randint(1, 5))
                amount = round(rng.uniform(200, 9000) * mult, 2)
                status = rng.choices(["paid", "overdue", "open"], weights=[85, 6, 9])[0]
                paid = (issue + timedelta(days=rng.randint(3, 25))).isoformat() if status == "paid" else None
                cur.execute("INSERT INTO invoices VALUES (?,?,?,?,?,?,?)",
                            (inv_id, cid, issue.isoformat(),
                             (issue + timedelta(days=30)).isoformat(), amount, status, paid))
                inv_id += 1

    n_tickets = profile["n_orders"] // 4
    for tid in range(1, n_tickets + 1):
        created = datetime(2024, 1, 1) + timedelta(hours=rng.randint(0, 365 * 24))
        priority = rng.choices(PRIORITIES, weights=[4, 4, 2, 1])[0]
        status = rng.choices(["resolved", "open", "escalated"], weights=[88, 8, 4])[0]
        res_hours = round(rng.uniform(0.5, 72), 1) if status == "resolved" else None
        csat = rng.choices([1, 2, 3, 4, 5], weights=[1, 1, 2, 5, 6])[0] if status == "resolved" else None
        cur.execute("INSERT INTO support_tickets VALUES (?,?,?,?,?,?,?,?)",
                    (tid, created.isoformat(sep=" "), rng.randint(1, profile["n_customers"]),
                     rng.choice(TICKET_CATEGORIES), priority, status, res_hours, csat))

    n_emps = 120 + rng.randint(0, 60)
    for eid in range(1, n_emps + 1):
        dept = rng.choices(DEPARTMENTS_HR, weights=[5, 3, 2, 3, 1, 1])[0]
        hire = date(2019 + rng.randint(0, 5), rng.randint(1, 12), rng.randint(1, 28))
        termination = None
        if rng.random() < 0.14:
            termination = date(2024, rng.randint(1, 12), rng.randint(1, 28)).isoformat()
        band = rng.choices(["B1", "B2", "B3", "B4", "B5"], weights=[3, 4, 3, 2, 1])[0]
        cur.execute("INSERT INTO employees_hr VALUES (?,?,?,?,?,?,?)",
                    (eid, dept, f"{dept} Specialist", rng.choice(REGIONS),
                     hire.isoformat(), termination, band))

    conn.commit()
    stats = {}
    for table in ("products", "customers", "orders", "invoices", "support_tickets", "employees_hr"):
        stats[table] = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return stats


def write_documents(slug: str) -> list[dict]:
    registry = get_registry()
    company = registry.get_company(slug)
    docs_dir = company_dir(slug) / "docs"
    written = []

    def doc(dept: str, filename: str, content: str):
        path = docs_dir / dept / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n")
        written.append({"path": f"docs/{dept}/{filename}", "department": dept})

    name = company.name
    doc("general", "company_overview.md", f"""
# {name} — Company Overview

{company.description}

{name} operates across five sales regions: East, West, North, South, and
Central. All analytics data in this workspace covers fiscal year 2024
(January 1 through December 31, 2024).

## Business model
Subscription products billed monthly per customer, plus one-time orders for
add-ons and expansions. Customer segments: Startup, Mid-Market, Enterprise.

## Fiscal calendar
Q1 = Jan-Mar, Q2 = Apr-Jun, Q3 = Jul-Sep, Q4 = Oct-Dec. The fiscal year
matches the calendar year.
""")
    doc("general", "business_glossary.md", f"""
# {name} — Business Glossary

- **Revenue**: sum of total_amount on completed orders. Refunded and pending
  orders are excluded from revenue.
- **MRR (Monthly Recurring Revenue)**: sum of the customer mrr field for
  active customers.
- **AOV (Average Order Value)**: revenue divided by count of completed orders.
- **Churned customer**: customer with no completed order in the trailing 90 days.
- **Resolution time**: hours between ticket creation and resolution
  (resolution_hours on resolved tickets).
- **CSAT**: post-resolution customer satisfaction score, 1-5 scale.
- **Attrition rate**: terminated employees divided by total employees for the
  period (HR data).
- **Overdue invoice**: invoice past due_date with status 'overdue'.
""")
    doc("general", "data_dictionary.md", f"""
# {name} — Data Dictionary

## orders
order_id, order_date (2024), customer_id, product_id, region, quantity,
unit_price, total_amount, status (completed / refunded / pending).

## customers
customer_id, name, segment (Startup / Mid-Market / Enterprise), region,
signup_date, plan, mrr.

## products
product_id, name, category, list_price, launched.

## invoices
invoice_id, customer_id, issue_date, due_date, amount,
status (paid / overdue / open), paid_date.

## support_tickets
ticket_id, created_at, customer_id, category (billing / bug / how-to /
integration / outage), priority (low / medium / high / urgent),
status (resolved / open / escalated), resolution_hours, csat (1-5).

## employees_hr (restricted: HR and Admin/CEO roles only)
emp_id, department, role_title, region, hire_date, termination_date,
salary_band (B1-B5).
""")
    doc("finance", "billing_policy.md", f"""
# {name} — Billing & Revenue Policy

## Invoicing
Invoices are issued in the first five days of each month with net-30 terms.
An invoice unpaid 1 day past its due date is marked **overdue**. Accounts with
two consecutive overdue invoices are escalated to the finance controller.

## Revenue recognition
Revenue is recognized on order completion. Refunded orders reverse revenue in
the month of the refund. Pending orders are not revenue.

## Discounts
Sales may discount up to 15% off list price without approval. Discounts
beyond 15% require VP approval and are capped at 30%.

## Collections targets (2024)
- Days Sales Outstanding (DSO) target: under 32 days
- Overdue invoice ratio target: under 7% of issued invoices
""")
    doc("finance", "q4_finance_summary.md", f"""
# {name} — Q4 2024 Finance Summary (Internal)

Q4 2024 was the strongest quarter of the year, helped by seasonal expansion
orders in October-December. Finance highlights:

- Q4 order revenue grew versus Q3, consistent with the planned seasonal bump.
- Overdue invoices stayed within the 7% policy target for the year.
- The 2025 plan assumes 12-15% revenue growth with flat headcount in G&A.

For exact figures, query the orders and invoices tables — this summary is
directional narrative only, and numbers in the workspace database are the
source of truth.
""")
    doc("hr", "hr_policy_handbook.md", f"""
# {name} — HR Policy Handbook (Restricted: HR / Admin)

## Paid time off
All full-time employees receive **24 days** of PTO per year, plus 10 company
holidays. Unused PTO up to 5 days rolls over to the next year.

## Parental leave
16 weeks fully paid for primary caregivers, 8 weeks for secondary caregivers.

## Hiring bands
Salary bands B1-B5. Offers above band midpoint require People-team approval.
Band details are confidential to HR and Admin/CEO roles.

## Attrition reporting
People Operations reports monthly attrition by department. 2024 target:
annualized attrition under 15%. Terminations are recorded in employees_hr
with a termination_date.

## Performance cycle
Two review cycles per year (March, September). Promotion decisions happen in
the September cycle.
""")
    doc("hr", "compliance_training.md", f"""
# {name} — Compliance & Training Policy (Restricted: HR / Admin)

- Security-awareness training: required annually for all employees;
  completion tracked by People Operations.
- Anti-harassment training: required within 30 days of hire and every
  two years after.
- Data-access reviews: quarterly; department leads confirm role access.
- Contractor onboarding: same compliance requirements as employees, tracked
  separately.
""")
    doc("support", "support_playbook.md", f"""
# {name} — Support Playbook

## SLA targets (2024)
- Urgent priority: first response within **1 hour**, resolution within 8 hours.
- High priority: first response within 4 hours, resolution within 24 hours.
- Medium priority: first response within 8 business hours.
- Low priority: first response within 2 business days.

## Escalation
Outage-category tickets are paged to the on-call engineer immediately.
Tickets unresolved past 2x their SLA are escalated to the support manager.

## CSAT
Resolved tickets trigger a 1-5 CSAT survey. 2024 target: average CSAT of
4.2 or higher, with fewer than 5% of surveys scoring 1-2.
""")
    doc("product", "product_catalog.md", f"""
# {name} — Product Catalog Notes

Each product belongs to a category and has a list price; actual order
unit_price may include discounts of up to 15% (see billing policy).
Product launch dates are recorded in the products table.

Product strategy for 2024 prioritized expansion revenue from existing
customers over new-logo acquisition, which shows up as multi-quantity orders
from Enterprise-segment customers.
""")
    doc("ops", "operations_runbook.md", f"""
# {name} — Operations Runbook

## Incident severities
SEV1 (customer-facing outage), SEV2 (degraded service), SEV3 (internal only).
SEV1 incidents require a written postmortem within 5 business days.

## Vendor management
Vendors are reviewed twice a year. Contracts auto-renew unless flagged 60
days before the renewal date.

## Order fulfillment
Completed orders sync to billing nightly. Pending orders older than 14 days
are auto-flagged for review.
""")
    return written


def write_sources_json(slug: str, table_stats: dict, docs: list[dict]) -> None:
    payload = {
        "company": slug,
        "generated_at": datetime.now().isoformat(),
        "synthetic": True,
        "structured": {
            "engine": "sqlite",
            "path": "company.db",
            "tables": table_stats,
        },
        "documents": docs,
    }
    (company_dir(slug) / "sources.json").write_text(json.dumps(payload, indent=2) + "\n")


def generate(slug: str) -> dict:
    stats = build_database(slug)
    docs = write_documents(slug)
    write_sources_json(slug, stats, docs)
    return {"tables": stats, "documents": len(docs)}


if __name__ == "__main__":
    slugs = sys.argv[1:] or list(COMPANY_PROFILES)
    for s in slugs:
        result = generate(s)
        print(f"{s}: {result}")
