"""Company workspace database access — PostgreSQL or SQLite, one API.

The platform's company-scale data layer targets PostgreSQL (one schema per
company inside the platform database, `NEXUSIQ_PLATFORM_PG_URL`). SQLite
per-company files remain the zero-dependency fallback so tests and offline
development never require a database server. All platform SQL (deterministic
templates, dashboards) goes through here so dialect differences live in
exactly one place.
"""

from __future__ import annotations

import os
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from nexus_platform.contexts import company_db_path

_engines: dict[str, Engine] = {}


def platform_pg_url() -> Optional[str]:
    """The PostgreSQL URL for company-scale data, if configured."""
    return os.getenv("NEXUSIQ_PLATFORM_PG_URL") or None


def company_database_url(slug: str) -> str:
    pg = platform_pg_url()
    if pg:
        # One schema per company keeps isolation structural in PG too:
        # the engine's search_path is pinned to that company's schema.
        sep = "&" if "?" in pg else "?"
        return f"{pg}{sep}options=-csearch_path%3D{slug}"
    return f"sqlite:///{company_db_path(slug)}"


def company_engine(slug: str) -> Engine:
    url = company_database_url(slug)
    eng = _engines.get(url)
    if eng is None:
        kwargs = {"pool_pre_ping": True}
        if url.startswith("postgresql"):
            kwargs.update(pool_size=10, max_overflow=30)
        eng = create_engine(url, **kwargs)
        _engines[url] = eng
    return eng


def reset_engines() -> None:
    """Dispose cached engines (used when the backend env flag changes)."""
    for eng in _engines.values():
        eng.dispose()
    _engines.clear()


def dialect_name(slug: str) -> str:
    return company_engine(slug).dialect.name


def _plain(value):
    """Normalize driver types (Decimal, date) to JSON-friendly Python."""
    import datetime
    from decimal import Decimal

    if isinstance(value, Decimal):
        f = float(value)
        return int(f) if f.is_integer() else f
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def run_rows(slug: str, sql: str) -> list[dict]:
    """Run one read-only statement against the company workspace DB."""
    with company_engine(slug).connect() as conn:
        result = conn.execute(text(sql))
        return [{k: _plain(v) for k, v in r._mapping.items()} for r in result]


def run_script(slug: str, statements: list[str]) -> None:
    with company_engine(slug).begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


# ── Dialect-aware SQL fragments ─────────────────────────────────────────

def month_expr(dialect: str, col: str) -> str:
    if dialect == "postgresql":
        return f"to_char({col}, 'YYYY-MM')"
    return f"strftime('%Y-%m', {col})"


def quarter_expr(dialect: str, col: str) -> str:
    if dialect == "postgresql":
        return f"'Q' || EXTRACT(QUARTER FROM {col})::int"
    return f"'Q' || ((CAST(strftime('%m', {col}) AS INTEGER) + 2) / 3)"
