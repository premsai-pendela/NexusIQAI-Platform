"""Simulated employee personas.

A persona is a normal AccessContext for one (company, role) — built exactly
the way `scripts/platform_smoke.py::ctx_for` and the API dependency build
one, so every simulated query passes through the same 4-layer access
boundary as a real request. A simulated Analyst is constructed from
`get_policy("Analyst")` and therefore cannot be handed a wider policy.

Personas reuse the existing employee registry (curated demo accounts) and
the generated population before synthesizing a placeholder identity, per the
mission brief. Simulated traffic is distinguishable everywhere by the trace
`source="simulated"` tag, never by the employee identity.
"""

from __future__ import annotations

from nexus_platform import store
from nexus_platform.access_policy import ROLE_POLICIES, get_policy
from nexus_platform.auth import AccessContext
from nexus_platform.registry import Employee, get_registry


def persona_context(company_slug: str, role: str) -> AccessContext:
    """AccessContext for a simulated employee of this company and role."""
    if role not in ROLE_POLICIES:
        raise KeyError(f"Unknown role: {role}")
    registry = get_registry()
    company = registry.get_company(company_slug)
    if company is None:
        raise KeyError(f"Unknown company: {company_slug}")

    employee = None
    for e in sorted(registry.company_employees(company_slug),
                    key=lambda e: e.email):
        if e.role == role:
            employee = e
            break
    if employee is None:
        for row in store.list_generated_employees(company_slug):
            if row["role"] == role:
                employee = Employee(
                    email=row["email"], name=row["name"],
                    company_slug=company_slug, role=role,
                    password_hash="", title=row["title"],
                )
                break
    if employee is None:
        employee = Employee(
            email=f"sim-{role.lower()}@{company.domain}",
            name=f"Simulated {role}", company_slug=company_slug, role=role,
            password_hash="", title=f"Simulated {role}",
        )
    return AccessContext(employee=employee, company=company,
                         policy=get_policy(role))


def available_roles() -> list[str]:
    return list(ROLE_POLICIES.keys())
