"""Historical trace/feedback corpus — realistic Ask Analyst history at scale.

Generates 90 days of question traffic from the generated employee
population (plus curated accounts): deterministic answers, SQL/RAG routes,
clarifications, correct refusals, repeat-question flows, provider failures,
degraded-mode answers, and linked feedback — including a few "resolved"
items that should look suspicious to the Health Check agent. The corpus is
what makes Admin/CEO health analysis meaningful.

Trace ids are prefixed gen_ (feedback genfb_) so reruns replace cleanly.

Usage:
    python -m nexus_platform.scale.history [slug ...] [--per-company 5000]
"""

from __future__ import annotations

import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from nexus_platform import store
from nexus_platform.access_policy import get_policy
from nexus_platform.registry import get_registry

# Question pools per role — (question, route, chart_type)
DETERMINISTIC_POOL = [
    ("What was total revenue in Q{q} 2024?", "revenue"),
    ("How many orders in Q{q} 2024?", "orders"),
    ("Revenue by region", "revenue"),
    ("Revenue by month", "revenue"),
    ("Top 5 products by revenue", "revenue"),
    ("How many overdue invoices do we have?", "invoices"),
    ("Average order value in Q{q}", "orders"),
    ("Support tickets by priority", "tickets"),
    ("Average CSAT this year", "tickets"),
    ("How many customers do we have?", "customers"),
    ("What is our MRR?", "customers"),
    ("Headcount by department", "hr"),
    ("What is our attrition rate?", "hr"),
]
RAG_POOL = [
    ("What is the discount policy?", "finance", "discount_policy.md"),
    ("Explain the billing policy", "finance", "billing_policy.md"),
    ("What are the SLA targets for urgent tickets?", "support", "sla_policy.md"),
    ("How does the escalation process work?", "support", "escalation_policy.md"),
    ("What is the PTO policy?", "hr", "pto_policy.md"),
    ("Summarize the parental leave policy", "hr", "parental_leave.md"),
    ("What is the procurement policy?", "ops", "procurement_policy.md"),
    ("What changed in the latest release?", "product", "release_notes_2024_12.md"),
]
SQL_AGENT_POOL = [
    "Which customers churned with the highest MRR?",
    "Average payment delay by segment",
    "Total vendor spend by category this year",
    "Usage events per product in November",
    "Lead conversion by channel",
]
PLANNER_POOL = [
    "Why did revenue change in Q4?",
    "What is driving support ticket volume?",
    "Why are enterprise customers churning?",
]
CLARIFY_POOL = [
    ("show market by invoice", "unclear_metric"),
    ("revenue in q1 and q3", "ambiguous_selection"),
    ("total revenue for q2 and a4", "malformed_period"),
    ("pie chart of revenue by month", "pie_unsuitable"),
    ("analyze everything", "overbroad"),
]

# Restricted-area question per role (what this role is NOT allowed to ask)
DENIED_QUESTIONS = {
    "Analyst": ("What is our attrition rate?", "employees_hr"),
    "Finance": ("Support tickets by priority", "support_tickets"),
    "Support": ("What was total revenue in Q4 2024?", "orders"),
    "Ops": ("How many overdue invoices do we have?", "invoices"),
    "HR": ("What was total revenue in Q4 2024?", "orders"),
}

METRIC_TABLES = {"revenue": ["orders"], "orders": ["orders"],
                 "invoices": ["invoices"], "tickets": ["support_tickets"],
                 "customers": ["customers"], "hr": ["employees_hr"]}


def _base_payload(company, emp, question, route, decision, session,
                  confidence="HIGH", **extra):
    policy = get_policy(emp["role"])
    return {
        "employee": emp["email"], "employee_name": emp["name"],
        "company": company, "role": emp["role"], "session_id": session,
        "question": question, "resolved_question": question,
        "followup_rewritten": False, "memory_turns_used": 0,
        "access_policy": {"allowed_tables": list(policy.allowed_tables),
                          "allowed_departments": list(policy.allowed_departments)},
        "access_decision": decision, "route": route,
        "confidence": confidence, "citations": [],
        "llm_skipped": route in ("deterministic_sql_template", "clarification",
                                 "repeat_question_choice", "access_refusal"),
        "generated": True,
        **extra,
    }


def generate_history(slug: str, per_company: int = 5000,
                     days: int = 90, seed: int = 20260707) -> dict:
    rng = random.Random(seed + hash(slug) % 1000)
    registry = get_registry()
    curated = [{"email": e.email, "name": e.name, "role": e.role}
               for e in registry.company_employees(slug)]
    generated = store.list_generated_employees(slug)
    population = generated + curated
    if not population:
        raise RuntimeError("Run scale.population before scale.history")

    now = datetime.now(timezone.utc)
    traces: list[dict] = []
    feedback: list[dict] = []

    def ts_within(days_back_max):
        dt = now - timedelta(days=rng.uniform(0.05, days_back_max),
                             hours=rng.uniform(0, 10))
        return dt.isoformat()

    def add_trace(emp, question, route, decision, payload_extra=None,
                  confidence="HIGH", session=None, ts=None):
        tid = f"gen_{uuid.uuid4().hex[:12]}"
        session = session or f"hist-{uuid.uuid4().hex[:8]}"
        payload = _base_payload(slug, emp, question, route, decision, session,
                                confidence=confidence, **(payload_extra or {}))
        payload["latency_s"] = round({
            "deterministic_sql_template": rng.uniform(0.02, 0.3),
            "clarification": rng.uniform(0.01, 0.05),
            "repeat_question_choice": rng.uniform(0.01, 0.05),
            "access_refusal": rng.uniform(0.01, 0.08),
            "rag_agent": rng.uniform(1.5, 6.0),
            "sql_agent": rng.uniform(2.0, 8.0),
            "llm_planner": rng.uniform(4.0, 15.0),
            "degraded_mode": rng.uniform(3.0, 20.0),
        }.get(route, rng.uniform(0.5, 5.0)), 3)
        traces.append({"id": tid, "company": slug, "employee": emp["email"],
                       "role": emp["role"], "ts": ts or ts_within(days),
                       "question": question, "access_decision": decision,
                       "payload": payload})
        return tid, session

    role_pools = {}
    for emp in population:
        policy = get_policy(emp["role"])
        allowed = [
            (q.replace("{q}", str(rng.randint(1, 4))), m)
            for q, m in DETERMINISTIC_POOL
            if set(METRIC_TABLES[m]) <= set(policy.allowed_tables)
        ]
        role_pools[emp["email"]] = allowed

    n = 0
    while n < per_company:
        emp = rng.choice(population)
        allowed_pool = role_pools[emp["email"]]
        r = rng.random()

        if r < 0.55 and allowed_pool:
            q, metric = rng.choice(allowed_pool)
            q = q.replace("{q}", str(rng.randint(1, 4)))
            chart = rng.choice([None, "kpi", "bar", "line"])
            add_trace(emp, q, "deterministic_sql_template", "allowed",
                      {"template_id": f"{metric}_total",
                       "sql": f"SELECT ... FROM {METRIC_TABLES[metric][0]}",
                       "tables_touched": METRIC_TABLES[metric],
                       "chart_generated": chart is not None,
                       "chart_type": chart, "model_used": None})
        elif r < 0.70:
            q, dept, fname = rng.choice(RAG_POOL)
            policy = get_policy(emp["role"])
            if dept not in policy.allowed_departments:
                continue
            add_trace(emp, q, "rag_agent", "allowed",
                      {"citations": [{"filename": fname, "department": dept}],
                       "model_used": rng.choice(["Gemini Flash", "Groq"]),
                       "chart_generated": False, "chart_type": None},
                      confidence=rng.choice(["HIGH", "MEDIUM"]))
        elif r < 0.78:
            q = rng.choice(SQL_AGENT_POOL)
            chart = rng.choice(["bar", None])
            add_trace(emp, q, "sql_agent", "allowed",
                      {"sql": "SELECT ...", "model_used": "Gemini Flash",
                       "chart_generated": chart is not None,
                       "chart_type": chart},
                      confidence=rng.choice(["HIGH", "MEDIUM"]))
        elif r < 0.86:
            q, kind = rng.choice(CLARIFY_POOL)
            add_trace(emp, q, "clarification", "allowed",
                      {"clarification_kind": kind,
                       "clarification_choices": ["choice a", "choice b"],
                       "chart_generated": False, "chart_type": None,
                       "model_used": None},
                      confidence="N/A")
        elif r < 0.93:
            role_denied = DENIED_QUESTIONS.get(emp["role"])
            if role_denied is None:
                continue
            q, table = role_denied
            add_trace(emp, q, "access_refusal", "denied",
                      {"denied_reason": f"the '{table}' data area is outside your role",
                       "chart_generated": False, "chart_type": None,
                       "model_used": None})
        elif r < 0.955 and allowed_pool:
            # healthy repeat flow: answer → choice card → use_previous
            q, metric = rng.choice(allowed_pool)
            session = f"hist-{uuid.uuid4().hex[:8]}"
            base_ts = now - timedelta(days=rng.uniform(1, days))
            tid, _ = add_trace(emp, q, "deterministic_sql_template", "allowed",
                               {"template_id": f"{metric}_total",
                                "tables_touched": METRIC_TABLES[metric],
                                "chart_generated": False, "chart_type": None,
                                "model_used": None},
                               session=session, ts=base_ts.isoformat())
            add_trace(emp, q, "repeat_question_choice", "allowed",
                      {"previous_trace_id": tid, "chart_generated": False,
                       "chart_type": None, "model_used": None},
                      confidence="N/A", session=session,
                      ts=(base_ts + timedelta(minutes=3)).isoformat())
            n += 1
        elif r < 0.97:
            q = rng.choice(PLANNER_POOL)
            add_trace(emp, q, "llm_planner", "allowed",
                      {"model_used": rng.choice(["Gemini Flash", "Groq",
                                                 "Cerebras llama-3.3-70b"]),
                       "chart_generated": False, "chart_type": None},
                      confidence="MEDIUM")
        else:
            q = rng.choice(PLANNER_POOL)
            add_trace(emp, q, "degraded_mode", "allowed",
                      {"provider_failures": [
                          {"model": "gemini-2.5-flash", "error": "429 quota exceeded"},
                          {"model": "llama-3.3-70b-versatile", "error": "429 rate limit"},
                      ], "model_used": None, "chart_generated": False,
                          "chart_type": None},
                      confidence="LOW")
        n += 1

    # Feedback: ~3% of traces, mixed statuses, some suspicious resolutions.
    answered = [t for t in traces
                if t["payload"]["route"] in ("deterministic_sql_template",
                                             "rag_agent", "sql_agent")]
    refused = [t for t in traces if t["access_decision"] == "denied"]
    degraded = [t for t in traces if t["payload"]["route"] == "degraded_mode"]

    def add_feedback(tr, category, message, status):
        feedback.append({
            "id": f"genfb_{uuid.uuid4().hex[:10]}", "company": slug,
            "employee": tr["employee"], "role": tr["role"],
            "ts": tr["ts"], "category": category, "message": message,
            "page": "ask", "trace_id": tr["id"], "status": status,
        })

    for tr in rng.sample(answered, min(len(answered), int(per_company * 0.02))):
        add_feedback(tr, rng.choice(["wrong_answer", "issue", "confusing_chart"]),
                     rng.choice(["This number looks off vs my export.",
                                 "Chart labels are hard to read.",
                                 "Answer contradicted last month's report."]),
                     rng.choices(["new", "reviewed", "resolved"],
                                 weights=[5, 3, 2])[0])
    for tr in rng.sample(refused, min(len(refused), int(per_company * 0.006))):
        add_feedback(tr, "access_request",
                     "I need this data area for my quarterly report.",
                     rng.choice(["new", "reviewed"]))
    # Suspicious: degraded answers whose complaints were closed as resolved
    for tr in rng.sample(degraded, min(len(degraded), 4)):
        add_feedback(tr, "wrong_answer",
                     "The analyst never answered my question.", "resolved")
    for tr in rng.sample(answered, min(len(answered), int(per_company * 0.008))):
        add_feedback(tr, "improvement",
                     rng.choice(["Would love saved dashboards.",
                                 "Add export to Google Sheets.",
                                 "Weekly digest of key metrics please."]),
                     rng.choices(["new", "reviewed", "resolved"],
                                 weights=[4, 3, 3])[0])

    store.delete_generated_history(slug)
    store.bulk_save_traces(traces)
    store.bulk_save_feedback(feedback)
    return {"company": slug, "traces": len(traces), "feedback": len(feedback)}


if __name__ == "__main__":
    per = 5000
    args = []
    it = iter(sys.argv[1:])
    for a in it:
        if a == "--per-company":
            per = int(next(it))
        elif a.startswith("--per-company="):
            per = int(a.split("=")[1])
        else:
            args.append(a)
    slugs = args or [c.slug for c in get_registry().companies.values()]
    for s in slugs:
        stats = generate_history(s, per_company=per)
        print(f"{s}: {stats['traces']:,} traces, {stats['feedback']} feedback")
