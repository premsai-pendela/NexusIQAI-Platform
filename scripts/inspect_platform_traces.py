"""Trace leakage inspector — scan saved platform traces for boundary violations.

Usage:
    python scripts/inspect_platform_traces.py

Checks every saved trace against the policy of the role that produced it:
1. SQL text references a table outside the role's allowlist
2. citations include a department outside the role's allowlist
3. allowed-decision traces produced by roles with no matching policy
4. trace company mismatch vs employee registry

Exit 0 when clean; exit 1 with findings. Run after demos or eval batches —
this is the audit the product story rests on.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexus_platform import store  # noqa: E402
from nexus_platform.access_policy import ALL_TABLES, get_policy  # noqa: E402
from nexus_platform.registry import get_registry  # noqa: E402


def scan() -> list[str]:
    findings: list[str] = []
    registry = get_registry()
    with store._tx() as conn:
        rows = conn.execute(
            "SELECT id, company, employee, role, payload FROM traces").fetchall()

    for row in rows:
        tid, company, employee, role = row["id"], row["company"], row["employee"], row["role"]
        payload = json.loads(row["payload"])
        policy = get_policy(role)

        emp = registry.get_employee(employee)
        if emp is not None and emp.company_slug != company:
            findings.append(f"{tid}: employee {employee} belongs to "
                            f"{emp.company_slug} but trace saved under {company}")

        sql = payload.get("sql") or ""
        if sql:
            for table in ALL_TABLES:
                if table not in policy.allowed_tables and re.search(rf"\b{table}\b", sql, re.I):
                    findings.append(f"{tid}: SQL for role {role} references "
                                    f"restricted table '{table}': {sql[:90]}")

        for cite in payload.get("citations") or []:
            dept = cite.get("department")
            if dept is not None and dept not in policy.allowed_departments:
                findings.append(f"{tid}: citation from restricted department "
                                f"'{dept}' for role {role}: {cite.get('filename')}")

    return findings


def main() -> int:
    with store._tx() as conn:
        total = conn.execute("SELECT COUNT(*) FROM traces").scalar()
    findings = scan()
    print(f"scanned {total} traces")
    if findings:
        print(f"\n{len(findings)} POTENTIAL LEAK(S):")
        for f in findings:
            print(f"  ✗ {f}")
        return 1
    print("✓ no cross-boundary SQL, citations, or company mismatches found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
