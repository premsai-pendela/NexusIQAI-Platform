"""Access-policy simulator — dry-run a question against any role's boundary.

Usage:
    python scripts/check_access.py <role> "<question>"
    python scripts/check_access.py --matrix          # full role × probe matrix

Shows what the policy layer would do BEFORE any agent/LLM runs: the role's
tables/departments and whether the restricted-intent gate fires. The engine
still enforces the boundary at AST + retrieval level; this tool is for
debugging and demoing policies cheaply.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexus_platform.access_policy import (ROLE_POLICIES,  # noqa: E402
                                          classify_restricted_intent,
                                          get_policy)

PROBES = [
    "What was total revenue in Q3 2024?",
    "How many overdue invoices do we have?",
    "What is our attrition rate by department?",
    "Average resolution hours by ticket priority",
    "How many PTO days do employees get?",
    "What are the incident severity definitions?",
]


def simulate(role: str, question: str) -> str:
    reason = classify_restricted_intent(question, get_policy(role))
    return f"DENIED ({reason})" if reason else "allowed → engine (AST + retrieval filters still apply)"


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--matrix":
        roles = list(ROLE_POLICIES)
        for q in PROBES:
            print(f"\nQ: {q}")
            for role in roles:
                verdict = simulate(role, q)
                mark = "✗" if verdict.startswith("DENIED") else "✓"
                print(f"  {mark} {role:<8} {verdict}")
        return 0
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    role, question = sys.argv[1], sys.argv[2]
    p = get_policy(role)
    print(f"role:        {role}")
    print(f"tables:      {', '.join(p.allowed_tables) or 'none'}")
    print(f"departments: {', '.join(p.allowed_departments) or 'none'}")
    print(f"verdict:     {simulate(role, question)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
