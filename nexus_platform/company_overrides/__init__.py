"""Per-company override packs — how one analyst serves three companies
without company-specific fixes clobbering each other.

The problem (and the design): a single AI Data Analyst serves AcmeCloud,
MedCore, and FinPilot. When the Health Check repair pipeline fixes a bug
that is specific to ONE company's vocabulary/data (say, a metric alias only
AcmeCloud uses), editing the shared orchestrator risks colliding with — or
outright clobbering — an earlier fix another company needed in the same
function. Real multi-tenant systems solve this with a shared kernel plus
tenant-scoped extension points: shared logic stays generic, and per-tenant
behavior lives in the tenant's own module/config, consulted at well-defined
seams (see Microsoft's multitenant application patterns and the SaaS
customization-modeling literature; design notes + citations in
docs/platform improvements/ARCHITECTURE_LOG.md).

Rules of the layer:
  - One module per company (`acmecloud.py`, `medcore.py`, `finpilot.py`).
    A company-specific fix belongs in that company's module, NEVER in the
    shared orchestrator/deterministic code.
  - Shared code consults the pack at explicit seams only (metric vocabulary
    extension, clarification override). No override module may import
    another company's module.
  - Isolation is enforced by tests (tests/platform_mode/
    test_company_overrides.py): an override for company A must not change
    company B's behavior.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Optional

_KNOWN = ("acmecloud", "medcore", "finpilot")
_cache: dict = {}


def overrides_for(company: Optional[str]) -> Optional[ModuleType]:
    """The company's override module, or None (no company / no pack)."""
    if not company or company not in _KNOWN:
        return None
    if company not in _cache:
        try:
            _cache[company] = importlib.import_module(
                f"nexus_platform.company_overrides.{company}")
        except ImportError:
            _cache[company] = None
    return _cache[company]


def extra_metric_vocabulary(company: Optional[str]) -> frozenset:
    """Words this company's workspace additionally recognizes as metric
    vocabulary (e.g. a company-specific metric alias). Extends — never
    replaces — the shared vocabulary."""
    mod = overrides_for(company)
    words = getattr(mod, "EXTRA_METRIC_VOCABULARY", ()) if mod else ()
    return frozenset(str(w).lower() for w in words)


def find_clarification_override(company: Optional[str], question: str,
                                features, policy):
    """A company-scoped clarification hook, consulted BEFORE the shared
    rules. Returns a Clarification to use it, the string "pass" to fall
    through to the shared rules explicitly, or None (no opinion — the
    default). Signature of the hook in a company module:

        def find_clarification(question, features, policy) -> Optional[Clarification | "pass"]
    """
    mod = overrides_for(company)
    hook = getattr(mod, "find_clarification", None) if mod else None
    if hook is None:
        return None
    try:
        return hook(question, features, policy)
    except Exception:
        # A broken override must degrade to shared behavior, never crash
        # another company's (or its own) query path.
        return None
