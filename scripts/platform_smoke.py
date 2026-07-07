"""Live platform smoke: real LLM queries through role-scoped agents.

Usage:
    python scripts/platform_smoke.py            # 4 scenario checks (LLM calls)

Verifies with live behavior (not mocks):
1. Analyst allowed SQL question answers with correct revenue
2. Analyst HR question is refused with access framing
3. HR user gets HR data with a chart
4. Follow-up "What about Q4?" resolves against session memory

Prints PASS/FAIL per scenario and the trace ids for inspection.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.disable(logging.INFO)

from nexus_platform.access_policy import get_policy  # noqa: E402
from nexus_platform.auth import AccessContext  # noqa: E402
from nexus_platform.query_service import run_query  # noqa: E402
from nexus_platform.registry import get_registry  # noqa: E402


def ctx_for(email: str) -> AccessContext:
    r = get_registry()
    e = r.get_employee(email)
    return AccessContext(employee=e, company=r.get_company(e.company_slug),
                         policy=get_policy(e.role))


def main() -> int:
    failures = 0
    analyst = ctx_for("analyst@acmecloud.test")
    hr = ctx_for("hr@acmecloud.test")

    print("1) Analyst — allowed revenue question")
    res = run_query(analyst, "What was total revenue in Q3 2024?", "smoke-a")
    ok = (not res["platform"]["refused"]
          and "1,321,021" in str(res.get("answer", "")).replace("$", ""))
    print(f"   {'PASS' if ok else 'FAIL'} trace={res['platform']['trace_id']}")
    failures += 0 if ok else 1

    print("2) Analyst — restricted HR question refused")
    res = run_query(analyst, "What is our attrition rate by department?", "smoke-a")
    p = res["platform"]
    ok = p["refused"] and p["access_decision"] == "denied" and not res.get("sources")
    print(f"   {'PASS' if ok else 'FAIL'} trace={p['trace_id']}")
    failures += 0 if ok else 1

    print("3) HR — allowed HR question with chart")
    res = run_query(hr, "How many employees were terminated in 2024 by department? "
                        "Show as a bar chart.", "smoke-h")
    p = res["platform"]
    ok = not p["refused"] and (p.get("chart") or {}).get("type") == "bar"
    print(f"   {'PASS' if ok else 'FAIL'} trace={p['trace_id']}")
    failures += 0 if ok else 1

    print("4) Analyst — follow-up resolution")
    run_query(analyst, "What was total revenue in Q3 2024?", "smoke-f")
    res = run_query(analyst, "What about Q4?", "smoke-f")
    p = res["platform"]
    ok = p["followup_rewritten"] and "q4" in p["resolved_question"].lower()
    print(f"   {'PASS' if ok else 'FAIL'} resolved='{p['resolved_question']}' "
          f"trace={p['trace_id']}")
    failures += 0 if ok else 1

    print("5) MedCore Finance — allowed invoice question")
    med_fin = ctx_for("finance@medcore.test")
    res = run_query(med_fin, "How many overdue invoices do we have?", "smoke-m")
    p = res["platform"]
    ok = (not p["refused"]
          and (res.get("sql_result") or {}).get("success")
          and "invoices" in str((res.get("sql_result") or {}).get("query", "")).lower())
    print(f"   {'PASS' if ok else 'FAIL'} trace={p['trace_id']}")
    failures += 0 if ok else 1

    print("6) FinPilot Ops — restricted invoice question refused")
    fin_ops = ctx_for("ops@finpilot.test")
    res = run_query(fin_ops, "How many overdue invoices do we have?", "smoke-o")
    p = res["platform"]
    ok = p["refused"] and p["access_decision"] == "denied"
    print(f"   {'PASS' if ok else 'FAIL'} trace={p['trace_id']}")
    failures += 0 if ok else 1

    print("7) Company isolation — MedCore data differs from AcmeCloud")
    res = run_query(med_fin, "What was total revenue in Q3 2024?", "smoke-m")
    p = res["platform"]
    ok = (not p["refused"]
          and "1,321,021" not in str(res.get("answer", "")).replace("$", ""))
    print(f"   {'PASS' if ok else 'FAIL'} trace={p['trace_id']}")
    failures += 0 if ok else 1

    print(f"\n{7 - failures}/7 scenarios passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
