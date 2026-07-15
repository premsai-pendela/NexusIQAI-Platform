"""The simulation-employee roster + per-employee access context.

Reuses the real employee registry and the same access-policy construction the
API uses, so a simulated employee is scoped exactly like the real one — a
simulated Analyst cannot be handed a wider policy than a real Analyst.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from nexus_platform.access_policy import get_policy
from nexus_platform.auth import AccessContext
from nexus_platform.contexts import brain_dir
from nexus_platform.registry import Employee, get_registry

_SEED = Path(__file__).resolve().parent.parent / "nexus_platform" / "seed" / "employees.json"


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


def company_data_map(company: str, email: str) -> dict:
    """The company's data landscape *as this role sees it* — table columns and
    documents, read from the company brain (schema_catalog + doc_inventory),
    filtered to what the role may access. This is what lets the CLI brain ask
    company-specific questions without any raw database access."""
    ctx = context_for(company, email)
    allowed_tables = set(getattr(ctx.policy, "allowed_tables", []) or [])
    allowed_depts = set(getattr(ctx.policy, "allowed_departments", []) or [])
    bdir = brain_dir(company)

    tables: dict = {}
    cat_path = bdir / "schema_catalog.json"
    if cat_path.exists():
        try:
            catalog = json.loads(cat_path.read_text())
        except (ValueError, OSError):
            catalog = {}
        for tbl, meta in catalog.items():
            if tbl not in allowed_tables or not isinstance(meta, dict):
                continue
            cols = [f"{c.get('name')} ({c.get('type')})"
                    for c in meta.get("columns", []) if isinstance(c, dict)]
            tables[tbl] = {"columns": cols, "row_count": meta.get("row_count")}

    documents: dict = {}
    inv_path = bdir / "doc_inventory.json"
    if inv_path.exists():
        try:
            inventory = json.loads(inv_path.read_text())
        except (ValueError, OSError):
            inventory = []
        for d in inventory:
            dept = d.get("department")
            if dept in allowed_depts:
                documents.setdefault(dept, []).append(d.get("file"))

    return {"tables": tables, "documents": documents,
            "note": "The analyst runs the SQL; you only ask in natural "
                    "language. Use this map to ask company-specific, "
                    "role-appropriate questions and to probe seams "
                    "(joins across related tables, metrics that don't exist)."}


def demo_password(email: str) -> Optional[str]:
    """Plaintext demo password for a curated seed account — needed only for
    `live` mode (HTTP login). Generated-population accounts return None."""
    try:
        seed = json.loads(_SEED.read_text())
    except (ValueError, OSError):
        return None
    for e in seed.get("employees", []):
        if e.get("email", "").strip().lower() == email.strip().lower():
            return e.get("password")
    return None
