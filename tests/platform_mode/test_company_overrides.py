"""One analyst, three companies: company-scoped overrides must coexist.

Proves the tenancy design's core guarantee — a company-specific behavior
change (override pack) applies ONLY to that company, and an empty pack
changes nothing. This is the collision test that makes it safe for the
repair pipeline to land AcmeCloud-specific fixes without clobbering
MedCore/FinPilot behavior in shared modules.
"""

import types

import pytest

from nexus_platform import company_overrides
from nexus_platform.access_policy import get_policy
from nexus_platform.orchestrator import Clarification, decide_route


@pytest.fixture()
def fake_acme_pack(monkeypatch):
    """Install a synthetic override pack for acmecloud only."""
    pack = types.ModuleType("fake_acme_pack")
    pack.EXTRA_METRIC_VOCABULARY = ("gizmoscore",)

    def find_clarification(question, features, policy):
        if "quarterly synergy" in question.lower():
            return Clarification(
                kind="company_specific",
                question="AcmeCloud tracks synergy per product line — which one?",
                choices=["Synergy for dashboards", "Synergy for pipelines"])
        return None

    pack.find_clarification = find_clarification
    monkeypatch.setitem(company_overrides._cache, "acmecloud", pack)
    monkeypatch.setitem(company_overrides._cache, "medcore", None)
    monkeypatch.setitem(company_overrides._cache, "finpilot", None)
    return pack


def test_override_clarification_fires_only_for_its_company(fake_acme_pack):
    policy = get_policy("Analyst")
    q = "Show me the quarterly synergy numbers"

    acme = decide_route(q, policy, company="acmecloud")
    assert acme.route == "clarification"
    assert acme.clarification.kind == "company_specific"

    med = decide_route(q, policy, company="medcore")
    assert (med.clarification is None
            or med.clarification.kind != "company_specific")


def test_extra_vocabulary_is_company_scoped(fake_acme_pack):
    policy = get_policy("Analyst")
    # "gizmoscore" is unknown vocabulary everywhere except AcmeCloud's pack:
    # shared behavior is the unknown-metric honesty clarification.
    q = "What is our gizmoscore for 2024?"

    med = decide_route(q, policy, company="medcore")
    assert med.route == "clarification"

    acme = decide_route(q, policy, company="acmecloud")
    # AcmeCloud's vocabulary knows the word, so the unknown-metric gate must
    # NOT fire there (the question routes onward instead).
    assert not (acme.route == "clarification"
                and acme.clarification.kind == "unknown_metric")


def test_empty_packs_change_nothing():
    """With the real (empty) packs, company routing equals no-company
    routing for representative questions — the seam is inert by default."""
    policy = get_policy("Analyst")
    for q in ("What was total revenue in 2024?",
              "What is our NPS score for 2024?",
              "Revenue by region"):
        base = decide_route(q, policy)
        for company in ("acmecloud", "medcore", "finpilot"):
            got = decide_route(q, policy, company=company)
            assert got.route == base.route, (q, company)


def test_override_crash_degrades_to_shared_behavior(monkeypatch):
    pack = types.ModuleType("broken_pack")

    def find_clarification(question, features, policy):
        raise RuntimeError("boom")

    pack.find_clarification = find_clarification
    monkeypatch.setitem(company_overrides._cache, "medcore", pack)
    policy = get_policy("Analyst")
    base = decide_route("What was total revenue in 2024?", policy)
    got = decide_route("What was total revenue in 2024?", policy,
                       company="medcore")
    assert got.route == base.route
