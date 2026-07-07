"""Per-(company, role) DataContexts and agent access.

Each company+role pair gets its own DataContext with:
- the company's SQLite database
- the company's ChromaDB brain collection
- the role's table allowlist (baked into SQL prompt + AST validation)
- the role's department filter (baked into every RAG retrieval)

Because the boundary lives inside the agent instance, a request cannot widen
it. Agent instances are cached by the existing keyed fusion factory.
"""

from __future__ import annotations

from pathlib import Path

from config.data_contexts import DataContext, register_data_context
from nexus_platform.access_policy import get_policy
from nexus_platform.registry import get_registry

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPANIES_ROOT = REPO_ROOT / "data" / "demo_companies"


def company_dir(slug: str) -> Path:
    return COMPANIES_ROOT / slug


def company_db_path(slug: str) -> Path:
    return company_dir(slug) / "company.db"


def brain_dir(slug: str) -> Path:
    return company_dir(slug) / "brain"


def context_key(slug: str, role: str) -> str:
    return f"company:{slug}:{role.lower()}"


def build_context(slug: str, role: str) -> DataContext:
    # Deferred import: nexus_platform.db imports company_db_path from here.
    from nexus_platform.db import company_database_url

    registry = get_registry()
    company = registry.get_company(slug)
    if company is None:
        raise KeyError(f"Unknown company: {slug}")
    policy = get_policy(role)
    tables_desc = ", ".join(policy.allowed_tables) or "none"
    return DataContext(
        key=context_key(slug, role),
        label=f"{company.name} — {role}",
        sql_table=policy.allowed_tables[0] if policy.allowed_tables else "",
        sql_scope=f"{company.name} workspace tables: {tables_desc}",
        date_guidance=(
            "All company data covers year 2024 only (January 1 through December 31, 2024). "
            "When a user mentions Q1-Q4 without a year, use 2024. Never use CURRENT_DATE."
        ),
        document_scope=(
            f"{company.name} internal documents for departments: "
            f"{', '.join(policy.allowed_departments)}"
        ),
        chroma_directory=brain_dir(slug) / "chroma",
        chroma_collection=f"brain_{slug}",
        allow_web=False,  # company workspaces never mix in live web data
        # PostgreSQL (schema per company) when NEXUSIQ_PLATFORM_PG_URL is
        # set; per-company SQLite otherwise.
        database_url=company_database_url(slug),
        allowed_tables=policy.allowed_tables,
        rag_metadata_filter={"department": {"$in": list(policy.allowed_departments)}},
        company=slug,
        role=role,
    )


_registered: set[str] = set()


def register_company_contexts() -> None:
    """Register a context for every (company, role) present in the registry."""
    registry = get_registry()
    for emp in registry.employees.values():
        key = context_key(emp.company_slug, emp.role)
        if key not in _registered:
            register_data_context(build_context(emp.company_slug, emp.role))
            _registered.add(key)


def get_company_fusion_agent(slug: str, role: str):
    """Fusion agent bound to one company+role evidence boundary."""
    register_company_contexts()
    # Generated employees can carry roles no curated account has for this
    # company — register the exact (company, role) context on demand.
    key = context_key(slug, role)
    if key not in _registered:
        register_data_context(build_context(slug, role))
        _registered.add(key)
    from agents.fusion_agent import get_fusion_agent
    return get_fusion_agent(key)
