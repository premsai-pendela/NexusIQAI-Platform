"""Simulated traffic must never leak into real-usage reads by default.

The hard rule from the self-improving Health Check initiative: traces are
tagged source real|simulated at write time, every read helper defaults to
real-only, and simulated rows appear only on explicit opt-in.
"""

import uuid

import pytest

from nexus_platform import store
from nexus_platform.health_check import run_health_check


def fresh_company() -> str:
    """Isolated company slug so fixtures never touch real demo data
    (same convention as test_health_check.py)."""
    return f"srcco_{uuid.uuid4().hex[:8]}"


def _payload(company: str, question: str,
             route: str = "deterministic_sql_template") -> dict:
    return {
        "employee": "sim@test", "company": company, "role": "Analyst",
        "session_id": "s-src-test", "question": question,
        "resolved_question": question, "access_decision": "allowed",
        "route": route, "confidence": "HIGH", "llm_skipped": True,
        "citations": [], "latency_s": 0.01,
    }


@pytest.fixture()
def tagged_trace_ids():
    company = fresh_company()
    q = f"source-tagging probe {uuid.uuid4().hex[:8]}"
    real_id = store.save_trace(company, "real@test", "Analyst", q,
                               "allowed", _payload(company, q))
    sim_id = store.save_trace(company, "sim@test", "Analyst", q,
                              "allowed", _payload(company, q),
                              source="simulated")
    return company, real_id, sim_id


def test_default_reads_exclude_simulated(tagged_trace_ids):
    company, real_id, sim_id = tagged_trace_ids
    default_ids = {t["id"] for t in store.list_traces_with_payload(company)}
    assert real_id in default_ids
    assert sim_id not in default_ids

    listed = {t["id"] for t in store.list_traces(company, limit=5000)}
    assert real_id in listed
    assert sim_id not in listed


def test_explicit_opt_in_sees_simulated(tagged_trace_ids):
    company, real_id, sim_id = tagged_trace_ids
    sim_only = {t["id"] for t in
                store.list_traces_with_payload(company, source="simulated")}
    assert sim_id in sim_only
    assert real_id not in sim_only

    both = {t["id"] for t in
            store.list_traces_with_payload(company, source=None)}
    assert {real_id, sim_id} <= both


def test_context_manager_tags_saves():
    company = fresh_company()
    q = f"ctx-tag probe {uuid.uuid4().hex[:8]}"
    with store.tagged_trace_source("simulated"):
        tid = store.save_trace(company, "sim@test", "Analyst", q,
                               "allowed", _payload(company, q))
    sim_ids = {t["id"] for t in
               store.list_traces_with_payload(company, source="simulated")}
    assert tid in sim_ids
    # After the context exits, saves are real again.
    tid2 = store.save_trace(company, "real@test", "Analyst", q,
                            "allowed", _payload(company, q))
    assert tid2 in {t["id"] for t in store.list_traces_with_payload(company)}


def test_unknown_source_rejected():
    company = fresh_company()
    with pytest.raises(ValueError):
        store.save_trace(company, "x@test", "Analyst", "q", "allowed",
                         _payload(company, "q"), source="synthetic")
    with pytest.raises(ValueError):
        with store.tagged_trace_source("fake"):
            pass
    with pytest.raises(ValueError):
        store.list_traces_with_payload(company, source="fake")


def test_health_check_defaults_to_real_only(tagged_trace_ids):
    company, real_id, sim_id = tagged_trace_ids
    report = run_health_check(company, window_days=1, save=False)
    assert report["stats"]["traces"] == 1  # the real trace only
    evidence = {e for f in report["findings"] for e in f["evidence"]}
    assert sim_id not in evidence

    sim_report = run_health_check(company, window_days=1, save=False,
                                  source="simulated")
    assert sim_report["stats"]["traces"] == 1  # the simulated trace only
