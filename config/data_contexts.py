"""Data context for the NexusIQ live app."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_CONTEXT_KEY = "live"


@dataclass(frozen=True)
class DataContext:
    """SQL/RAG evidence boundary used by an app session."""

    key: str
    label: str
    sql_table: str
    sql_scope: str
    date_guidance: str
    document_scope: str
    available_years: tuple[int, ...] = (2024,)
    chroma_directory: Optional[Path] = None
    chroma_collection: str = "nexusiq_docs"
    allow_web: bool = True
    # Platform-mode fields. When database_url is set, SQL agents connect to
    # this per-company database instead of the global settings.database_url.
    # allowed_tables / rag_metadata_filter bake a role's evidence boundary
    # into the agent instance so it cannot be widened per-request.
    database_url: Optional[str] = None
    allowed_tables: Optional[tuple[str, ...]] = None
    rag_metadata_filter: Optional[dict] = None
    company: Optional[str] = None
    role: Optional[str] = None

    @property
    def is_pilot(self) -> bool:
        return False


LIVE_CONTEXT = DataContext(
    key=LIVE_CONTEXT_KEY,
    label="Live Baseline (2024)",
    sql_table="sales_transactions",
    sql_scope="100,000 validated Supabase sales transactions",
    date_guidance=(
        "All SQL transaction data is from year 2024 only (January 1 through December 31, 2024). "
        "When a user mentions Q1-Q4 without a year, use 2024."
    ),
    document_scope="25 indexed business PDFs covering 2024 reports, policies, and strategy",
)


# Registry of platform (company/role) contexts, keyed by context key.
# Registered at startup by platform.contexts.register_company_contexts().
_REGISTERED_CONTEXTS: dict[str, DataContext] = {}


def register_data_context(ctx: DataContext) -> None:
    """Register a platform data context so keyed agent factories can find it."""
    if ctx.key == LIVE_CONTEXT_KEY:
        raise ValueError("Cannot overwrite the live context")
    _REGISTERED_CONTEXTS[ctx.key] = ctx


def get_data_context(key: str = LIVE_CONTEXT_KEY) -> DataContext:
    """Return the live context or a registered platform context."""
    if key == LIVE_CONTEXT_KEY:
        return LIVE_CONTEXT
    if key in _REGISTERED_CONTEXTS:
        return _REGISTERED_CONTEXTS[key]
    raise KeyError(f"Unknown data context: {key!r}")
