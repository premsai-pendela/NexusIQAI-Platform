"""The simulation-employee roster + per-employee access context.

Reuses the real employee registry and the same access-policy construction the
API uses, so a simulated employee is scoped exactly like the real one — a
simulated Analyst cannot be handed a wider policy than a real Analyst.
"""

from __future__ import annotations

from typing import Optional

from nexus_platform.access_policy import get_policy
from nexus_platform.auth import AccessContext
from nexus_platform.registry import Employee, get_registry


def sim_roster(company: str) -> list[dict]:
    """Curated demo employees for a company (Admin/CEO, an analyst, a
    department role) — the personas that generate this company's traffic."""
    registry = get_registry()
    if registry.get_company(company) is None:
        raise KeyError(f"Unknown company: {company}")
    out = []
    for e in sorted(registry.company_employees(company), key=lambda e: e.email):
        out.append({"email": e.email, "name": e.name, "role": e.role,
                    "title": e.title})
    return out


def context_for(company: str, email: str) -> AccessContext:
    """AccessContext for a specific simulation employee (by email)."""
    registry = get_registry()
    comp = registry.get_company(company)
    if comp is None:
        raise KeyError(f"Unknown company: {company}")
    emp = registry.get_employee(email)
    if emp is None or emp.company_slug != company:
        # fall back to the generated population, then a placeholder
        gen = None
        try:
            from nexus_platform import store
            for r in store.list_generated_employees(company):
                if r["email"] == email.strip().lower():
                    gen = r
                    break
        except Exception:
            gen = None
        if gen is not None:
            emp = Employee(email=email, name=gen["name"], company_slug=company,
                           role=gen["role"], password_hash="", title=gen["title"])
        else:
            raise KeyError(f"Unknown employee {email} for {company}")
    return AccessContext(employee=emp, company=comp,
                         policy=get_policy(emp.role))


def accessible(company: str, email: str) -> dict:
    """What this employee's role can reach — for the CLI brain's briefing."""
    ctx = context_for(company, email)
    pol = ctx.policy
    return {
        "role": ctx.employee.role,
        "allowed_tables": sorted(getattr(pol, "allowed_tables", []) or []),
        "allowed_departments": sorted(getattr(pol, "allowed_departments", []) or []),
    }
