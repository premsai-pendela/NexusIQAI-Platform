"""Simulation-employees module: memory, roster scoping, and the run loop.

The analyst is mocked so these tests are fast, deterministic, and spend no
LLM quota — they verify the sim plumbing (tagging, memory, pacing hook,
weak-spot flagging), not the analyst itself.
"""

import uuid

import pytest

from sim_employees import memory, runner
from sim_employees.roster import accessible, context_for, sim_roster


@pytest.fixture()
def tmp_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEM_DIR", tmp_path / "memory")
    return tmp_path


def test_memory_roundtrip_and_weak_spot(tmp_memory):
    mem = memory.load("acmecloud", "x@acmecloud.test", role="Analyst", name="X")
    memory.append_interaction(
        mem, {"question": "q1", "route": "deterministic_sql_template",
              "access_decision": "allowed", "trace_id": "tr_1"},
        weak=False)
    memory.append_interaction(
        mem, {"question": "q2", "route": "degraded_mode",
              "access_decision": "allowed", "trace_id": "tr_2"},
        weak=True, weak_note="degraded")
    p = memory.save(mem)
    assert p.exists()

    reloaded = memory.load("acmecloud", "x@acmecloud.test")
    assert len(reloaded["interactions"]) == 2
    assert len(reloaded["weak_spots"]) == 1
    summ = memory.brief_summary(reloaded)
    assert summ["recent_questions"] == ["q1", "q2"]
    assert summ["weak_spots"][0]["evidence_trace"] == "tr_2"


def test_roster_and_scope_is_role_bound():
    roster = sim_roster("acmecloud")
    roles = {r["role"] for r in roster}
    assert {"Admin", "Analyst", "HR"} <= roles
    # HR sees only HR tables/departments; construction mirrors the real policy.
    hr = accessible("acmecloud", "hr@acmecloud.test")
    assert hr["role"] == "HR"
    assert "employees_hr" in hr["allowed_tables"]
    assert "finance" not in hr["allowed_departments"]
    ctx = context_for("acmecloud", "hr@acmecloud.test")
    assert ctx.employee.role == "HR"


def test_ask_tags_simulated_updates_memory_and_flags_weak(tmp_memory, monkeypatch):
    company = "acmecloud"
    email = "analyst@acmecloud.test"
    captured = {}

    def fake_run_query(ctx, question, session_id, repeat_action=None):
        # Record the source tag in effect when the analyst is called.
        from nexus_platform import store
        captured["source"] = store._trace_source.get()
        # A degraded answer -> should be flagged as a weak spot to re-probe.
        return {"answer": "partial",
                "platform": {"trace_id": f"tr_{uuid.uuid4().hex[:6]}",
                             "route": "degraded_mode",
                             "access_decision": "allowed",
                             "confidence": "LOW", "llm_skipped": False}}

    monkeypatch.setattr(runner, "run_query", fake_run_query)

    results = runner.ask(company, email,
                         [{"question": "why did revenue move?",
                           "family": "seam", "difficulty": "hard"}],
                         delay=0, llm_extra_delay=0, quiet=True)

    assert captured["source"] == "simulated"          # analyst saw simulated tag
    assert len(results) == 1 and results[0]["weak"] is True
    mem = memory.load(company, email)
    assert mem["interactions"][-1]["route"] == "degraded_mode"
    assert len(mem["weak_spots"]) == 1
