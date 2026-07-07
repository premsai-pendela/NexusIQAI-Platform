"""Company-scale data generator — PostgreSQL + SQLite, 18 months of history.

Builds the full expanded workspace for each demo company:

- 35 structured tables (see scale.schema), ~150k-180k rows per company,
  covering July 2023 through December 2024
- writes to per-company SQLite always (offline tests/dev) and to PostgreSQL
  (schema per company) when NEXUSIQ_PLATFORM_PG_URL is set
- a 150+ file document corpus per company: markdown policies/runbooks,
  monthly finance summary PDFs, board update PDFs, CSV exports generated
  from the actual structured rows, JSON ticket exports, HTML newsletters

Deterministic per-company seeds: rerunning produces identical data.

Usage:
    python -m nexus_platform.scale.generator [slug ...] [--scale 1.0]
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

from nexus_platform.contexts import company_dir, company_db_path
from nexus_platform.db import platform_pg_url
from nexus_platform.registry import get_registry
from nexus_platform.scale.schema import TABLES, create_table_sql, insert_sql

START = date(2023, 7, 1)          # 18 months of business history
END = date(2024, 12, 31)
DAYS = (END - START).days

REGIONS = ["East", "West", "North", "South", "Central"]
SEGMENTS = ["Startup", "Mid-Market", "Enterprise"]
TICKET_CATEGORIES = ["billing", "bug", "how-to", "integration", "outage"]
PRIORITIES = ["low", "medium", "high", "urgent"]
DEPARTMENTS = ["Engineering", "Sales", "Marketing", "Support", "Finance",
               "People", "Operations", "Product"]
EXPENSE_CATEGORIES = ["travel", "software", "cloud", "office", "events",
                      "recruiting", "training"]
CHANNELS = ["webinar", "search", "content", "events", "outbound", "partner"]
VENDOR_CATEGORIES = ["cloud", "software", "office", "legal", "recruiting",
                     "marketing", "logistics"]

PROFILES = {
    "acmecloud": {
        "seed": 1042, "customers": 420, "orders": 12500, "mult": 1.0,
        "products": [
            ("Dashboards Pro", "analytics", 299), ("Pipeline Sync", "data-pipeline", 499),
            ("Insight Alerts", "analytics", 149), ("Warehouse Connect", "data-pipeline", 799),
            ("Embedded Charts", "analytics", 399), ("Usage Metering", "platform", 249),
        ],
    },
    "medcore": {
        "seed": 1077, "customers": 340, "orders": 9500, "mult": 1.6,
        "products": [
            ("ClinicFlow Scheduler", "scheduling", 449), ("ClaimsBridge", "claims", 899),
            ("ComplianceGuard", "compliance", 649), ("PatientComms", "engagement", 299),
            ("Referral Router", "scheduling", 379),
        ],
    },
    "finpilot": {
        "seed": 1091, "customers": 480, "orders": 14500, "mult": 0.8,
        "products": [
            ("Merchant Onboard", "onboarding", 199), ("TxnMonitor", "risk", 599),
            ("Settlement Ledger", "settlement", 749), ("Chargeback Shield", "risk", 349),
            ("Payout Scheduler", "settlement", 279), ("KYC Express", "onboarding", 159),
        ],
    },
}

FIRST = ["Ava", "Liam", "Maya", "Noah", "Zoe", "Kai", "Iris", "Leo", "Nina",
         "Omar", "Priya", "Sam", "Tara", "Yuki", "Diego", "Elena", "Femi",
         "Grace", "Hugo", "Anya", "Ravi", "Sofia", "Mateo", "Lena"]
LAST = ["Chen", "Patel", "Kim", "Garcia", "Okafor", "Novak", "Silva", "Haddad",
        "Larsen", "Mori", "Ivanov", "Dubois", "Nakamura", "Osei", "Reyes",
        "Kowalski", "Berg", "Costa", "Ahmed", "Fischer"]
COMPANY_WORDS_A = ["Blue", "Nova", "Cedar", "Quartz", "Harbor", "Summit",
                   "Argon", "Lumen", "Vertex", "Copper", "Aster", "Zephyr"]
COMPANY_WORDS_B = ["Labs", "Retail", "Health", "Logistics", "Media", "Systems",
                   "Foods", "Robotics", "Studios", "Works", "Group", "Partners"]


def _rand_date(rng, start=START, end=END) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _seasonal_date(rng) -> date:
    """Business dates with mild growth over time and a Q4-2024 bump."""
    if rng.random() < 0.12:
        return date(2024, rng.randint(10, 12), rng.randint(1, 28))
    # growth: later days slightly more likely
    r = rng.random() ** 0.75
    return START + timedelta(days=int(r * DAYS))


class Rows:
    """Accumulates rows per table, then bulk-inserts into any engine."""

    def __init__(self):
        self.data: dict[str, list[dict]] = {t: [] for t in TABLES}

    def add(self, table: str, **row):
        self.data[table].append(row)

    def counts(self) -> dict[str, int]:
        return {t: len(r) for t, r in self.data.items() if r}


# ── Business simulation ─────────────────────────────────────────────────

def simulate(slug: str, scale: float = 1.0) -> Rows:
    profile = PROFILES[slug]
    rng = random.Random(profile["seed"])
    mult = profile["mult"]
    R = Rows()

    def n(x: int) -> int:
        return max(1, int(x * scale))

    # products / plans / price changes
    products = profile["products"]
    for i, (name, category, base) in enumerate(products, start=1):
        R.add("products", product_id=i, name=name, category=category,
              list_price=round(base * mult, 2),
              launched=date(2023, rng.randint(1, 6), rng.randint(1, 28)).isoformat())
    for pid in range(1, len(products) + 1):
        if rng.random() < 0.7:
            old = products[pid - 1][2] * mult
            new = round(old * rng.uniform(1.03, 1.12), 2)
            R.add("price_changes", id=len(R.data["price_changes"]) + 1,
                  product_id=pid, changed_on=_rand_date(rng).isoformat(),
                  old_price=round(old, 2), new_price=new,
                  reason=rng.choice(["annual uplift", "packaging change",
                                     "cost increase pass-through"]))
    plans = [("Growth", 99, 5, "starter"), ("Business", 399, 20, "mid"),
             ("Enterprise", 1499, 100, "top"), ("Enterprise Plus", 2999, 250, "top")]
    for i, (pname, price, seats, tier) in enumerate(plans, start=1):
        R.add("plans", plan_id=i, name=pname, monthly_price=round(price * mult, 2),
              seats_included=seats, tier=tier)

    # customers / contacts / subscriptions / churn
    n_customers = n(profile["customers"])
    for cid in range(1, n_customers + 1):
        segment = rng.choices(SEGMENTS, weights=[5, 3, 2])[0]
        mrr = {"Startup": rng.uniform(100, 600), "Mid-Market": rng.uniform(600, 2500),
               "Enterprise": rng.uniform(2500, 12000)}[segment] * mult
        plan = {"Startup": "Growth", "Mid-Market": "Business",
                "Enterprise": "Enterprise"}[segment]
        signup = _rand_date(rng, date(2023, 1, 1), date(2024, 10, 1))
        R.add("customers", customer_id=cid,
              name=f"{rng.choice(COMPANY_WORDS_A)} {rng.choice(COMPANY_WORDS_B)} {cid}",
              segment=segment, region=rng.choice(REGIONS),
              signup_date=signup.isoformat(), plan=plan, mrr=round(mrr, 2))
        for k in range(rng.randint(1, 4)):
            first, last = rng.choice(FIRST), rng.choice(LAST)
            R.add("contacts", contact_id=len(R.data["contacts"]) + 1,
                  customer_id=cid, name=f"{first} {last}",
                  title=rng.choice(["CTO", "Head of Data", "Ops Manager",
                                    "Finance Lead", "CEO", "Analyst"]),
                  email=f"{first.lower()}.{last.lower()}@customer{cid}.example",
                  is_primary=int(k == 0))
        plan_id = {"Growth": 1, "Business": 2, "Enterprise": 3}[plan]
        canceled = None
        if rng.random() < 0.12:
            canceled = _rand_date(rng, max(signup, START), END)
            R.add("churn_events", id=len(R.data["churn_events"]) + 1,
                  customer_id=cid, event_date=canceled.isoformat(),
                  reason=rng.choice(["price", "competitor", "shut down",
                                     "consolidation", "low usage"]),
                  mrr_lost=round(mrr, 2))
        R.add("subscriptions", subscription_id=cid, customer_id=cid,
              plan_id=plan_id, started_on=signup.isoformat(),
              canceled_on=canceled.isoformat() if canceled else None,
              seats=rng.randint(3, 120), mrr=round(mrr, 2))

    # orders / order_items / refunds
    n_orders = n(profile["orders"])
    for oid in range(1, n_orders + 1):
        d = _seasonal_date(rng)
        cid = rng.randint(1, n_customers)
        n_items = rng.choices([1, 2, 3], weights=[6, 3, 1])[0]
        total = 0.0
        first_pid = None
        first_qty = 0
        first_price = 0.0
        for _ in range(n_items):
            pid = rng.randint(1, len(products))
            qty = rng.randint(1, 8)
            unit = round(products[pid - 1][2] * mult * rng.uniform(0.85, 1.0), 2)
            line = round(qty * unit, 2)
            total += line
            if first_pid is None:
                first_pid, first_qty, first_price = pid, qty, unit
            R.add("order_items", item_id=len(R.data["order_items"]) + 1,
                  order_id=oid, product_id=pid, quantity=qty,
                  unit_price=unit, line_total=line)
        status = rng.choices(["completed", "refunded", "pending"],
                             weights=[92, 3, 5])[0]
        R.add("orders", order_id=oid, order_date=d.isoformat(),
              customer_id=cid, product_id=first_pid, region=rng.choice(REGIONS),
              quantity=first_qty, unit_price=first_price,
              total_amount=round(total, 2), status=status)
        if status == "refunded":
            R.add("refunds", refund_id=len(R.data["refunds"]) + 1, order_id=oid,
                  refunded_on=(d + timedelta(days=rng.randint(2, 30))).isoformat(),
                  amount=round(total, 2),
                  reason=rng.choice(["duplicate charge", "not satisfied",
                                     "billing error", "downgrade"]))

    # invoices / lines / payments / credit notes
    inv_id, line_id, pay_id = 0, 0, 0
    for cid in range(1, n_customers + 1):
        month_cursor = date(START.year, START.month, 1)
        while month_cursor <= END:
            if rng.random() < 0.72:
                inv_id += 1
                issue = month_cursor + timedelta(days=rng.randint(0, 4))
                n_lines = rng.randint(1, 3)
                amount = 0.0
                for _ in range(n_lines):
                    line_id += 1
                    qty = rng.randint(1, 10)
                    unit = round(rng.uniform(80, 2200) * mult, 2)
                    lt = round(qty * unit, 2)
                    amount += lt
                    R.add("invoice_lines", line_id=line_id, invoice_id=inv_id,
                          description=rng.choice(
                              ["subscription", "usage overage", "support plan",
                               "onboarding services", "add-on seats"]),
                          quantity=qty, unit_price=unit, line_total=lt)
                status = rng.choices(["paid", "overdue", "open"],
                                     weights=[85, 6, 9])[0]
                paid_on = None
                if status == "paid":
                    paid_on = issue + timedelta(days=rng.randint(3, 25))
                    pay_id += 1
                    R.add("payments", payment_id=pay_id, invoice_id=inv_id,
                          paid_on=paid_on.isoformat(), amount=round(amount, 2),
                          method=rng.choice(["ach", "card", "wire"]),
                          status="settled")
                R.add("invoices", invoice_id=inv_id, customer_id=cid,
                      issue_date=issue.isoformat(),
                      due_date=(issue + timedelta(days=30)).isoformat(),
                      amount=round(amount, 2), status=status,
                      paid_date=paid_on.isoformat() if paid_on else None)
            month_cursor = (month_cursor + timedelta(days=32)).replace(day=1)
    for i in range(n(int(n_customers * 0.6))):
        R.add("credit_notes", credit_id=i + 1,
              customer_id=rng.randint(1, n_customers),
              issued_on=_rand_date(rng).isoformat(),
              amount=round(rng.uniform(50, 1500) * mult, 2),
              reason=rng.choice(["SLA credit", "billing correction",
                                 "goodwill", "downgrade proration"]))

    # usage events (the big table)
    for eid in range(1, n(60000) + 1):
        d = _seasonal_date(rng)
        R.add("usage_events", event_id=eid,
              customer_id=rng.randint(1, n_customers),
              product_id=rng.randint(1, len(products)),
              event_ts=datetime(d.year, d.month, min(d.day, 28),
                                rng.randint(0, 23), rng.randint(0, 59)).isoformat(sep=" "),
              event_type=rng.choice(["api_call", "report_run", "export",
                                     "login", "dashboard_view", "alert_fired"]),
              units=rng.randint(1, 500))

    # support tickets / messages / csat / escalations / slas
    for i, pr in enumerate(PRIORITIES, start=1):
        R.add("slas", sla_id=i, priority=pr,
              first_response_hours={"low": 24, "medium": 8, "high": 4, "urgent": 1}[pr],
              resolution_hours={"low": 120, "medium": 72, "high": 24, "urgent": 8}[pr])
    n_tickets = n(4500)
    msg_id = 0
    for tid in range(1, n_tickets + 1):
        d = _seasonal_date(rng)
        created = datetime(d.year, d.month, min(d.day, 28),
                           rng.randint(0, 23), rng.randint(0, 59))
        priority = rng.choices(PRIORITIES, weights=[4, 4, 2, 1])[0]
        status = rng.choices(["resolved", "open", "escalated"],
                             weights=[88, 8, 4])[0]
        res_hours = round(rng.uniform(0.5, 72), 1) if status == "resolved" else None
        csat = (rng.choices([1, 2, 3, 4, 5], weights=[1, 1, 2, 5, 6])[0]
                if status == "resolved" and rng.random() < 0.8 else None)
        R.add("support_tickets", ticket_id=tid,
              created_at=created.isoformat(sep=" "),
              customer_id=rng.randint(1, n_customers),
              category=rng.choice(TICKET_CATEGORIES), priority=priority,
              status=status, resolution_hours=res_hours, csat=csat)
        for m in range(rng.randint(2, 8)):
            msg_id += 1
            R.add("ticket_messages", message_id=msg_id, ticket_id=tid,
                  sent_at=(created + timedelta(hours=m * rng.uniform(0.5, 6))
                           ).isoformat(sep=" "),
                  author="customer" if m % 2 == 0 else "support_agent",
                  body=rng.choice(
                      ["Seeing an error on the integration step.",
                       "Thanks — can you share the workspace ID?",
                       "Escalating to the platform team for review.",
                       "That fixed it, thank you!",
                       "The invoice total doesn't match our PO.",
                       "We pushed a fix; please retry the sync.",
                       "Following up — is this still blocking you?"]))
        if csat is not None:
            R.add("csat_responses", response_id=len(R.data["csat_responses"]) + 1,
                  ticket_id=tid,
                  submitted_on=(created + timedelta(hours=(res_hours or 24))).date().isoformat(),
                  score=csat,
                  comment=rng.choice([None, "quick fix", "slow but solved",
                                      "great support", "had to chase twice"]))
        if status == "escalated":
            R.add("escalations", escalation_id=len(R.data["escalations"]) + 1,
                  ticket_id=tid,
                  escalated_on=(created + timedelta(hours=rng.uniform(1, 24))
                                ).isoformat(sep=" "),
                  to_team=rng.choice(["platform", "billing", "security", "data"]),
                  reason=rng.choice(["SLA breach risk", "requires engineering",
                                     "billing dispute", "security question"]))

    # org: departments / teams / employees_hr / payroll
    for i, dept in enumerate(DEPARTMENTS, start=1):
        R.add("departments", department_id=i, name=dept,
              cost_center=f"CC-{100 + i}", head_emp_id=None)
    team_id = 0
    for i, dept in enumerate(DEPARTMENTS, start=1):
        for t in range(rng.randint(2, 4)):
            team_id += 1
            R.add("teams", team_id=team_id, department_id=i,
                  name=f"{dept} Team {t + 1}",
                  manager_emp_id=rng.randint(1, 40))
    n_emps = 100 + rng.randint(0, 50)
    for eid in range(1, n_emps + 1):
        dept = rng.choices(DEPARTMENTS, weights=[5, 3, 2, 3, 1, 1, 2, 2])[0]
        hire = date(2019 + rng.randint(0, 5), rng.randint(1, 12), rng.randint(1, 28))
        termination = None
        if rng.random() < 0.16:
            termination = _rand_date(rng, date(2023, 7, 1), END).isoformat()
        R.add("employees_hr", emp_id=eid, department=dept,
              role_title=f"{dept} {'Manager' if eid % 9 == 0 else 'Specialist'}",
              region=rng.choice(REGIONS), hire_date=hire.isoformat(),
              termination_date=termination,
              salary_band=rng.choices(["B1", "B2", "B3", "B4", "B5"],
                                      weights=[3, 4, 3, 2, 1])[0])
    month_cursor = date(START.year, START.month, 1)
    pr_id = 0
    while month_cursor <= END:
        for dept in DEPARTMENTS[:6]:
            pr_id += 1
            hc = rng.randint(8, 30)
            R.add("payroll_summary", id=pr_id,
                  month=month_cursor.strftime("%Y-%m"), department=dept,
                  headcount=hc, total_payroll=round(hc * rng.uniform(6000, 11000), 2),
                  total_benefits=round(hc * rng.uniform(900, 1800), 2))
        month_cursor = (month_cursor + timedelta(days=32)).replace(day=1)

    # vendors / POs / bills / expenses / saas spend / contracts
    n_vendors = 80
    for vid in range(1, n_vendors + 1):
        R.add("vendors", vendor_id=vid,
              name=f"{rng.choice(COMPANY_WORDS_A)}{rng.choice(['Soft', 'Serve', 'Cloud', 'Supply'])} {vid}",
              category=rng.choice(VENDOR_CATEGORIES),
              country=rng.choice(["US", "DE", "IN", "UK", "CA", "JP"]),
              active=int(rng.random() > 0.1))
    for i in range(1, n(900) + 1):
        vid = rng.randint(1, n_vendors)
        R.add("purchase_orders", po_id=i, vendor_id=vid,
              ordered_on=_rand_date(rng).isoformat(),
              amount=round(rng.uniform(500, 40000), 2),
              status=rng.choices(["fulfilled", "open", "canceled"],
                                 weights=[8, 1.5, 0.5])[0],
              department=rng.choice(DEPARTMENTS))
    for i in range(1, n(1800) + 1):
        billed = _rand_date(rng)
        R.add("bills", bill_id=i, vendor_id=rng.randint(1, n_vendors),
              billed_on=billed.isoformat(),
              due_on=(billed + timedelta(days=30)).isoformat(),
              amount=round(rng.uniform(200, 25000), 2),
              status=rng.choices(["paid", "open", "overdue"],
                                 weights=[8.5, 1, 0.5])[0])
    for i in range(1, n(3000) + 1):
        R.add("expenses", expense_id=i, incurred_on=_rand_date(rng).isoformat(),
              department=rng.choice(DEPARTMENTS),
              category=rng.choice(EXPENSE_CATEGORIES),
              amount=round(rng.uniform(20, 4000), 2),
              description=rng.choice(["conference travel", "team offsite",
                                      "cloud overage", "laptop", "job board",
                                      "client dinner", "training course"]))
    tools = ["CRM Suite", "Design Studio", "CI Runner", "Chat Ops", "HRIS",
             "Data Warehouse", "Observability", "Email Automation",
             "Doc Signing", "Password Vault", "Video Conf", "Board Portal"]
    for i, tool in enumerate(tools * 5, start=1):
        R.add("saas_subscriptions", id=i, tool=f"{tool} {((i - 1) // len(tools)) + 1}",
              owner_department=rng.choice(DEPARTMENTS),
              monthly_cost=round(rng.uniform(50, 4000), 2),
              seats=rng.randint(5, 300),
              renewal_date=_rand_date(rng, date(2024, 6, 1), date(2025, 6, 1)).isoformat())
    for i in range(1, n(250) + 1):
        is_customer = rng.random() < 0.7
        starts = _rand_date(rng, date(2023, 1, 1), date(2024, 6, 1))
        R.add("contracts", contract_id=i,
              customer_id=rng.randint(1, n_customers) if is_customer else None,
              vendor_id=None if is_customer else rng.randint(1, n_vendors),
              kind="customer_msa" if is_customer else "vendor_agreement",
              starts_on=starts.isoformat(),
              ends_on=(starts + timedelta(days=365 * rng.randint(1, 3))).isoformat(),
              annual_value=round(rng.uniform(5000, 250000) * mult, 2),
              status=rng.choices(["active", "expired", "in_renewal"],
                                 weights=[7, 2, 1])[0])

    # incidents / marketing
    for i in range(1, n(120) + 1):
        d = _seasonal_date(rng)
        sev = rng.choices(["sev1", "sev2", "sev3"], weights=[1, 3, 6])[0]
        R.add("incidents", incident_id=i,
              opened_at=datetime(d.year, d.month, min(d.day, 28),
                                 rng.randint(0, 23)).isoformat(sep=" "),
              severity=sev,
              service=rng.choice(["api", "ingest", "dashboard", "billing", "auth"]),
              minutes_to_resolve=rng.randint(10, 900),
              postmortem_file=(f"docs/ops/postmortem_{i}.md" if sev != "sev3" else None))
    for i in range(1, 25):
        R.add("campaigns", campaign_id=i,
              name=f"{rng.choice(['Spring', 'Summer', 'Fall', 'Winter'])} {rng.choice(CHANNELS)} {i}",
              channel=rng.choice(CHANNELS),
              started_on=_rand_date(rng).isoformat(),
              budget=round(rng.uniform(2000, 60000), 2),
              leads_target=rng.randint(50, 800))
    for i in range(1, n(6000) + 1):
        R.add("leads", lead_id=i, campaign_id=rng.randint(1, 24),
              created_on=_seasonal_date(rng).isoformat(),
              source=rng.choice(CHANNELS),
              status=rng.choices(["new", "qualified", "won", "lost"],
                                 weights=[3, 3, 1.5, 2.5])[0],
              est_value=round(rng.uniform(500, 30000) * mult, 2))

    # finance reports / board updates reference the generated docs
    month_cursor = date(START.year, START.month, 1)
    fr_id = 0
    while month_cursor <= END:
        fr_id += 1
        rev = round(rng.uniform(500000, 1600000) * mult, 2)
        exp = round(rev * rng.uniform(0.6, 0.95), 2)
        R.add("finance_reports", report_id=fr_id,
              period=month_cursor.strftime("%Y-%m"), kind="monthly_summary",
              revenue=rev, expenses=exp, net=round(rev - exp, 2),
              file=f"docs/finance/finance_summary_{month_cursor.strftime('%Y_%m')}.pdf")
        month_cursor = (month_cursor + timedelta(days=32)).replace(day=1)
    for i, q in enumerate(["2023-Q3", "2023-Q4", "2024-Q1", "2024-Q2",
                           "2024-Q3", "2024-Q4"], start=1):
        R.add("board_updates", update_id=i, period=q,
              headline=rng.choice(["Growth on plan", "Churn pressure in SMB",
                                   "Enterprise expansion ahead of target",
                                   "Cost discipline quarter", "New product traction",
                                   "Support load stabilizing"]),
              file=f"docs/finance/board_update_{q.replace('-', '_')}.pdf")

    return R


# ── Writing to databases ────────────────────────────────────────────────

def write_sqlite(slug: str, rows: Rows) -> None:
    db_path = company_db_path(slug)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    eng = create_engine(f"sqlite:///{db_path}")
    _write(eng, "sqlite", rows)
    eng.dispose()


def write_postgres(slug: str, rows: Rows) -> bool:
    pg = platform_pg_url()
    if not pg:
        return False
    admin = create_engine(pg, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{slug}" CASCADE'))
        conn.execute(text(f'CREATE SCHEMA "{slug}"'))
    admin.dispose()
    sep = "&" if "?" in pg else "?"
    eng = create_engine(f"{pg}{sep}options=-csearch_path%3D{slug}")
    _write(eng, "postgresql", rows)
    eng.dispose()
    return True


def _write(engine, dialect: str, rows: Rows) -> None:
    with engine.begin() as conn:
        for table in TABLES:
            conn.execute(text(create_table_sql(table, dialect)))
        for table, data in rows.data.items():
            if not data:
                continue
            stmt = text(insert_sql(table))
            for i in range(0, len(data), 5000):
                conn.execute(stmt, data[i:i + 5000])


def generate_company(slug: str, scale: float = 1.0,
                     docs: bool = True) -> dict:
    rows = simulate(slug, scale)
    write_sqlite(slug, rows)
    pg_written = write_postgres(slug, rows)
    doc_count = 0
    if docs:
        from nexus_platform.scale.documents import write_document_corpus
        doc_count = write_document_corpus(slug, rows)
    counts = rows.counts()
    return {
        "company": slug,
        "tables": len(counts),
        "rows": sum(counts.values()),
        "postgres": pg_written,
        "documents": doc_count,
        "row_counts": counts,
    }


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    scale = 1.0
    for a in sys.argv[1:]:
        if a.startswith("--scale"):
            scale = float(a.split("=")[1] if "=" in a else sys.argv[sys.argv.index(a) + 1])
    slugs = args or list(PROFILES)
    for s in slugs:
        stats = generate_company(s, scale=scale)
        print(f"{s}: {stats['tables']} tables, {stats['rows']:,} rows, "
              f"{stats['documents']} docs, postgres={stats['postgres']}")
