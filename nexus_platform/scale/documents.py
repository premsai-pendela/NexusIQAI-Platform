"""Company document corpus generator — ~170 files, 1000+ chunks per company.

Documents are derived from the SAME generated structured rows, so PDFs, CSV
exports, monthly reports, and the SQL tables tell one consistent story.
Layout: docs/<department>/<file> — the brain builder tags each chunk with its
department directory for role-filtered retrieval.

File types: markdown (policies, runbooks, monthly reports, account pages),
PDF (finance summaries, board updates — reportlab), CSV (exports of real
rows), JSON (ticket exports, org chart), HTML (newsletters), TXT (notes).
"""

from __future__ import annotations

import csv
import json
import random
import shutil
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from nexus_platform.contexts import company_dir
from nexus_platform.registry import get_registry


def _months(start: date, end: date) -> list[date]:
    out, cursor = [], date(start.year, start.month, 1)
    while cursor <= end:
        out.append(cursor)
        cursor = (cursor.replace(day=28) + timedelta(days=5)).replace(day=1)
    return out


MONTHS_ALL = _months(date(2023, 7, 1), date(2024, 12, 1))
MONTHS_12 = MONTHS_ALL[-12:]


def _pdf(path: Path, title: str, lines: list[str]) -> None:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER)
    width, height = LETTER
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 72, title)
    c.setFont("Helvetica", 10)
    y = height - 110
    for line in lines:
        if y < 72:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = height - 72
        c.drawString(72, y, line[:100])
        y -= 15
    c.save()


class Corpus:
    def __init__(self, slug: str):
        self.root = company_dir(slug) / "docs"
        self.written: list[str] = []

    def text(self, dept: str, filename: str, content: str):
        path = self.root / dept / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n")
        self.written.append(f"{dept}/{filename}")

    def csv_rows(self, dept: str, filename: str, rows: list[dict]):
        if not rows:
            return
        path = self.root / dept / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        self.written.append(f"{dept}/{filename}")

    def json_doc(self, dept: str, filename: str, payload):
        path = self.root / dept / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=1, default=str))
        self.written.append(f"{dept}/{filename}")

    def pdf(self, dept: str, filename: str, title: str, lines: list[str]):
        _pdf(self.root / dept / filename, title, lines)
        self.written.append(f"{dept}/{filename}")


def _month_key(value) -> str:
    return str(value)[:7]


def write_document_corpus(slug: str, rows) -> int:
    company = get_registry().get_company(slug)
    name = company.name
    rng = random.Random(hash(slug) % 10_000)
    c = Corpus(slug)
    data = rows.data

    if c.root.exists():
        shutil.rmtree(c.root)

    # Pre-aggregate from the actual rows so documents match SQL answers.
    completed = [o for o in data["orders"] if o["status"] == "completed"]
    rev_by_month: dict[str, float] = defaultdict(float)
    rev_by_region_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    rev_by_product_month: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for o in completed:
        m = _month_key(o["order_date"])
        rev_by_month[m] += o["total_amount"]
        rev_by_region_month[m][o["region"]] += o["total_amount"]
        rev_by_product_month[m][o["product_id"]] += o["total_amount"]
    product_names = {p["product_id"]: p["name"] for p in data["products"]}
    tickets_by_month: dict[str, list] = defaultdict(list)
    for t in data["support_tickets"]:
        tickets_by_month[_month_key(t["created_at"])].append(t)
    incidents_by_month: dict[str, list] = defaultdict(list)
    for i in data["incidents"]:
        incidents_by_month[_month_key(i["opened_at"])].append(i)
    expenses_by_month_dept: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for e in data["expenses"]:
        expenses_by_month_dept[_month_key(e["incurred_on"])][e["department"]] += e["amount"]
    orders_by_customer: dict[int, float] = defaultdict(float)
    for o in completed:
        orders_by_customer[o["customer_id"]] += o["total_amount"]
    customers = {cu["customer_id"]: cu for cu in data["customers"]}

    # ── general ──────────────────────────────────────────────────────────
    c.text("general", "company_overview.md", f"""
# {name} — Company Overview

{company.description}

{name} operates across five sales regions: East, West, North, South, and
Central. The analytics workspace covers July 2023 through December 2024;
headline metrics default to fiscal year 2024.

## Fiscal calendar
Q1 = Jan–Mar, Q2 = Apr–Jun, Q3 = Jul–Sep, Q4 = Oct–Dec.

## Data platform
Employees query company data through NexusIQAI with role-scoped access.
Structured data lives in the workspace database ({len([t for t, r in data.items() if r])}
tables); documents are indexed per department for retrieval.
""")
    c.text("general", "business_glossary.md", f"""
# {name} — Business Glossary

- **Revenue**: sum of total_amount on completed orders (refunded/pending excluded).
- **MRR**: sum of customer mrr for active customers.
- **AOV**: revenue divided by completed order count.
- **Churn event**: a subscription cancellation recorded in churn_events.
- **Resolution time**: hours from ticket creation to resolution.
- **CSAT**: 1–5 post-resolution satisfaction score.
- **Attrition rate**: terminated employees / total employees.
- **Overdue invoice**: unpaid invoice past its due date.
- **DSO**: days sales outstanding — average days from invoice issue to payment.
- **SaaS spend**: monthly cost of third-party tools (saas_subscriptions).
- **Pipeline**: open leads weighted by estimated value.
- **Escalation**: a ticket handed to a specialist team (escalations table).
""")
    c.text("general", "data_dictionary.md",
           f"# {name} — Data Dictionary\n\n" + "\n".join(
               f"- **{t}**: {len(r)} rows" for t, r in data.items() if r))
    c.text("general", "employee_handbook.md", f"""
# {name} — Employee Handbook (excerpt)

Working hours are flexible around a 10:00–15:00 collaboration window.
Expenses need manager approval above $500 and Finance approval above $5,000.
All customer data access is role-scoped through the NexusIQAI workspace;
requesting wider access goes through the Feedback → access request flow.
Security training is annual and mandatory; report incidents to the on-call
lead immediately.
""")
    for m in MONTHS_12:
        mk = m.strftime("%Y-%m")
        c.text("general", f"all_hands_notes_{m.strftime('%Y_%m')}.txt",
               f"{name} all-hands — {m.strftime('%B %Y')}\n\n"
               f"Revenue for the month closed at ${rev_by_month.get(mk, 0):,.0f}.\n"
               f"Support handled {len(tickets_by_month.get(mk, []))} tickets.\n"
               f"Wins: {rng.choice(['enterprise expansion', 'faster onboarding', 'support CSAT up', 'new integrations'])}.\n"
               f"Focus: {rng.choice(['churn reduction', 'Q4 pipeline', 'cost discipline', 'platform reliability'])}.\n"
               f"Question of the month: {rng.choice(['pricing changes', 'roadmap timing', 'hiring plan', 'benefits'])}.")
    for m in MONTHS_12[-6:]:
        c.text("general", f"newsletter_{m.strftime('%Y_%m')}.html",
               f"<html><body><h1>{name} internal newsletter — {m.strftime('%B %Y')}</h1>"
               f"<p>Shout-outs to the {rng.choice(['Support', 'Sales', 'Engineering', 'Finance'])} team.</p>"
               f"<p>Metric of the month: {rng.choice(['revenue', 'CSAT', 'uptime', 'pipeline'])}.</p>"
               f"<p>Reminder: role-scoped analytics questions go through Ask Analyst.</p>"
               f"</body></html>")

    # ── finance: policies, monthly PDFs, sales reports, exports ─────────
    c.text("finance", "billing_policy.md", f"""
# {name} — Billing Policy

Invoices are issued monthly on the 1st–5th, net-30 terms. Late invoices move
to `overdue` status after the due date. Disputes pause collection for 15
days. Payment methods: ACH (preferred), card, wire. Credit notes offset the
next invoice and are never paid out as cash.
""")
    c.text("finance", "revenue_recognition.md", f"""
# {name} — Revenue Recognition

Subscription revenue is recognized ratably over the service month. One-time
orders are recognized on completion. Refunded orders reverse recognized
revenue in the refund month. Credit notes offset the next invoice.
""")
    c.text("finance", "discount_policy.md", f"""
# {name} — Discount Policy

Standard discounting authority: AE up to 10%, Sales Manager up to 20%,
VP Sales up to 30%. Anything above 30% needs CFO approval. Discounts are
applied at order line level (unit_price below list_price). Q4 promotional
windows may add up to 5% on Enterprise plans with Finance sign-off.
Discounts interact with revenue: heavier Q4 discounting raises order volume
but lowers average unit price — compare unit_price to list_price to measure.
""")
    c.text("finance", "collections_playbook.md", f"""
# {name} — Collections Playbook

Day 1 overdue: automated reminder. Day 7: AE follow-up. Day 21: Finance
escalation and service-hold warning. Day 45: service suspension review.
SLA credits are issued as credit notes, never cash refunds.
""")
    c.text("finance", "budget_memo_2024.md",
           f"# {name} — 2024 Budget Memo\n\nCloud spend is capped at 18% of "
           "revenue; SaaS tool renewals above $2,000/month require CFO "
           "review. Hiring backfills only in Support and Engineering.")

    for fr in data["finance_reports"]:
        mk = fr["period"]
        dept_exp = expenses_by_month_dept.get(mk, {})
        top_customers = sorted(
            ((cid, amt) for cid, amt in orders_by_customer.items()), key=lambda t: -t[1])[:8]
        lines = [
            f"Period: {mk}",
            f"Recognized revenue: ${fr['revenue']:,.2f}",
            f"Operating expenses: ${fr['expenses']:,.2f}",
            f"Net: ${fr['net']:,.2f}",
            "",
            "Department expense detail (from expenses table):",
        ]
        lines += [f"  {d}: ${v:,.2f}" for d, v in sorted(dept_exp.items())]
        lines += ["", "Largest customers by lifetime completed order value:"]
        lines += [f"  {customers[cid]['name']}: ${amt:,.2f}"
                  for cid, amt in top_customers if cid in customers]
        lines += ["", "Synthetic demo figures generated for the NexusIQAI",
                  "prototype workspace; consistent with the finance_reports table."]
        c.pdf("finance", f"finance_summary_{mk.replace('-', '_')}.pdf",
              f"{name} — Finance Summary {mk}", lines)
    for bu in data["board_updates"]:
        c.pdf("finance", f"board_update_{bu['period'].replace('-', '_')}.pdf",
              f"{name} — Board Update {bu['period']}",
              [f"Headline: {bu['headline']}",
               "Pipeline, churn, and cash runway reviewed with the board.",
               "Full metrics live in the analytics workspace.",
               "Synthetic prototype document."])

    for m in MONTHS_12:
        mk = m.strftime("%Y-%m")
        regions = rev_by_region_month.get(mk, {})
        prods = rev_by_product_month.get(mk, {})
        c.text("finance", f"sales_report_{m.strftime('%Y_%m')}.md",
               f"# {name} — Sales Report {m.strftime('%B %Y')}\n\n"
               f"Total completed-order revenue: ${rev_by_month.get(mk, 0):,.2f}\n\n"
               "## Revenue by region\n" +
               "\n".join(f"- {r}: ${v:,.2f}" for r, v in
                         sorted(regions.items(), key=lambda t: -t[1])) +
               "\n\n## Revenue by product\n" +
               "\n".join(f"- {product_names.get(p, p)}: ${v:,.2f}" for p, v in
                         sorted(prods.items(), key=lambda t: -t[1])) +
               "\n\nNumbers computed from the orders table (status = completed).")

    c.csv_rows("finance", "overdue_invoices_export.csv",
               [r for r in data["invoices"] if r["status"] == "overdue"])
    c.csv_rows("finance", "payments_export.csv", data["payments"][:1500])
    c.csv_rows("finance", "invoice_lines_export.csv", data["invoice_lines"][:1500])
    c.csv_rows("finance", "expenses_export.csv", data["expenses"])
    c.csv_rows("finance", "leads_export.csv", data["leads"][:1500])
    c.csv_rows("finance", "saas_spend_export.csv", data["saas_subscriptions"])
    c.csv_rows("finance", "vendor_bills_export.csv", data["bills"][:800])

    # ── hr ───────────────────────────────────────────────────────────────
    for fname, title, body in [
        ("pto_policy.md", "PTO Policy",
         "25 days annual PTO plus local public holidays. Carry-over max 5 days. "
         "Manager approval required for more than 10 consecutive days."),
        ("parental_leave.md", "Parental Leave",
         "16 weeks fully paid for primary caregivers, 6 weeks for secondary. "
         "Flexible return-to-work ramp over 4 weeks."),
        ("compensation_bands.md", "Compensation Bands",
         "Bands B1–B5 with regional multipliers. Promotions reviewed twice a "
         "year. Band data is HR/Admin restricted."),
        ("performance_reviews.md", "Performance Reviews",
         "Semi-annual cycle: self review, peer input, manager calibration. "
         "Ratings feed the promotion committee."),
        ("onboarding_policy.md", "Onboarding Policy",
         "Structured 30/60/90 plan, buddy assignment, and role-scoped data "
         "access provisioned on day one through the workspace registry."),
        ("compliance_training.md", "Compliance Training",
         "Annual security + privacy training mandatory for all employees; "
         "role-specific modules for Finance and Support."),
        ("remote_work_policy.md", "Remote Work Policy",
         "Remote-first with quarterly team gatherings. Equipment budget $1,200 "
         "per year."),
        ("anti_harassment_policy.md", "Anti-Harassment Policy",
         "Zero tolerance. Reports go to People team or the anonymous hotline; "
         "investigations conclude within 30 days."),
    ]:
        c.text("hr", fname, f"# {name} — {title}\n\n{body}")
    c.csv_rows("hr", "payroll_summary_export.csv", data["payroll_summary"])
    c.json_doc("hr", "org_chart.json", {
        "departments": [d["name"] for d in data["departments"]],
        "teams": [{"team": t["name"], "department_id": t["department_id"]}
                  for t in data["teams"]],
    })

    # ── support ──────────────────────────────────────────────────────────
    c.text("support", "sla_policy.md",
           f"# {name} — SLA Policy\n\n" + "\n".join(
               f"- **{s['priority']}**: first response {s['first_response_hours']}h, "
               f"resolution {s['resolution_hours']}h"
               for s in data["slas"]))
    c.text("support", "escalation_policy.md", f"""
# {name} — Escalation Policy

Escalate to the platform team for engineering defects, billing team for
invoice disputes, security for data questions. Urgent tickets page the
on-call lead. Every escalation is recorded in the escalations table.
""")
    for cat in ["billing", "bug", "how-to", "integration", "outage"]:
        c.text("support", f"playbook_{cat}.md",
               f"# {name} — {cat.title()} Playbook\n\n"
               f"Triage steps for {cat} tickets: confirm scope, check known "
               f"issues, gather workspace ID, then follow the {cat} runbook. "
               "Escalate on SLA-breach risk. Track CSAT after resolution.")
    for m in MONTHS_12:
        mk = m.strftime("%Y-%m")
        month_tickets = tickets_by_month.get(mk, [])
        scored = [t["csat"] for t in month_tickets if t["csat"]]
        avg = round(sum(scored) / len(scored), 2) if scored else "n/a"
        cats = defaultdict(int)
        for t in month_tickets:
            cats[t["category"]] += 1
        c.text("support", f"csat_report_{m.strftime('%Y_%m')}.md",
               f"# CSAT report {m.strftime('%B %Y')}\n\n"
               f"Tickets: {len(month_tickets)}; average CSAT: {avg}.\n\n"
               "## Tickets by category\n" +
               "\n".join(f"- {k}: {v}" for k, v in
                         sorted(cats.items(), key=lambda t: -t[1])))
    c.json_doc("support", "ticket_export_recent.json",
               data["support_tickets"][:800])
    c.csv_rows("support", "csat_responses_export.csv",
               data["csat_responses"][:900])
    c.csv_rows("support", "escalations_export.csv", data["escalations"])

    # ── product: pricing, one-pagers, releases, roadmaps, accounts ──────
    c.text("product", "pricing_guide.md",
           f"# {name} — Pricing Guide\n\n" + "\n".join(
               f"- **{p['name']}** ({p['tier']}): ${p['monthly_price']}/mo, "
               f"{p['seats_included']} seats included"
               for p in data["plans"]) +
           "\n\nPrice changes are tracked in the price_changes table.")
    for p in data["products"]:
        c.text("product", f"one_pager_{p['name'].lower().replace(' ', '_')}.md",
               f"# {p['name']}\n\nCategory: {p['category']}. List price "
               f"${p['list_price']}. Launched {p['launched']}. Positioning, "
               "target segment, and competitive notes for sales enablement.")
    for m in MONTHS_12[-8:]:
        c.text("product", f"release_notes_{m.strftime('%Y_%m')}.md",
               f"# Release notes — {m.strftime('%B %Y')}\n\n"
               f"- {rng.choice(['Faster exports', 'New chart types', 'SSO groundwork', 'Bulk import', 'Audit log filters'])}\n"
               f"- {rng.choice(['Bug fixes in billing sync', 'Improved alert routing', 'Dashboard performance', 'API rate-limit headers'])}\n"
               f"- {rng.choice(['Beta: usage analytics', 'New admin roles', 'Faster search', 'Webhook retries'])}")
    for q in ["2024_Q1", "2024_Q2", "2024_Q3", "2024_Q4"]:
        c.text("product", f"roadmap_{q}.md",
               f"# Roadmap {q.replace('_', ' ')}\n\nThemes: "
               f"{rng.choice(['reliability', 'enterprise readiness', 'analytics depth', 'integrations'])}, "
               f"{rng.choice(['self-serve growth', 'cost efficiency', 'platform APIs', 'mobile'])}.")
    top_accounts = sorted(orders_by_customer.items(), key=lambda t: -t[1])[:20]
    tickets_by_customer = defaultdict(int)
    for t in data["support_tickets"]:
        tickets_by_customer[t["customer_id"]] += 1
    for cid, amount in top_accounts:
        cu = customers.get(cid)
        if not cu:
            continue
        c.text("product", f"account_{cid}.md",
               f"# Account brief — {cu['name']}\n\n"
               f"Segment: {cu['segment']} · Region: {cu['region']} · Plan: {cu['plan']}\n\n"
               f"Lifetime completed-order value: ${amount:,.2f}\n"
               f"MRR: ${cu['mrr']:,.2f}\n"
               f"Support tickets filed: {tickets_by_customer.get(cid, 0)}\n\n"
               "Talking points: renewal posture, expansion candidates, and "
               "open support themes. Numbers come from the orders, customers, "
               "and support_tickets tables.")

    # ── ops ──────────────────────────────────────────────────────────────
    for svc in ["api", "ingest", "dashboard", "billing", "auth"]:
        c.text("ops", f"runbook_{svc}.md",
               f"# Runbook — {svc}\n\nHealth checks, dashboards, rollback "
               f"steps, and paging policy for the {svc} service. Sev1 pages "
               "the on-call immediately; sev2 within 30 minutes.")
    c.text("ops", "vendor_management.md",
           f"# {name} — Vendor Management\n\nNew vendors require security "
           "review and a signed agreement (contracts table). POs above "
           "$10,000 need department head approval.")
    c.text("ops", "procurement_policy.md",
           f"# {name} — Procurement Policy\n\nThree quotes for purchases "
           "above $25,000. Preferred vendors reviewed annually.")
    for inc in [i for i in data["incidents"] if i["postmortem_file"]][:10]:
        c.text("ops", f"postmortem_{inc['incident_id']}.md",
               f"# Postmortem — incident {inc['incident_id']} ({inc['severity']})\n\n"
               f"Service: {inc['service']}. Time to resolve: "
               f"{inc['minutes_to_resolve']} minutes. Root cause, impact, and "
               "follow-up actions documented for the reliability review.")
    for m in MONTHS_12:
        mk = m.strftime("%Y-%m")
        incs = incidents_by_month.get(mk, [])
        sevs = defaultdict(int)
        for i in incs:
            sevs[i["severity"]] += 1
        c.text("ops", f"ops_report_{m.strftime('%Y_%m')}.md",
               f"# Ops report {m.strftime('%B %Y')}\n\n"
               f"Incidents: {len(incs)} ({', '.join(f'{k}: {v}' for k, v in sorted(sevs.items())) or 'none'}).\n"
               f"Tickets: {len(tickets_by_month.get(mk, []))}.\n"
               "Reliability follow-ups tracked in the incidents table.")
    c.csv_rows("ops", "purchase_orders_export.csv", data["purchase_orders"][:600])
    c.csv_rows("ops", "usage_events_sample.csv", data["usage_events"][:2500])

    return len(c.written)
