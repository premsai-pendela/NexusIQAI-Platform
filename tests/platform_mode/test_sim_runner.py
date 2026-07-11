"""Runner mechanics with a stubbed query pipeline: source tagging end-to-end,
budget caps, ledger rows, pattern stats, and report shape — zero LLM calls."""

import uuid

from nexus_platform import store
from nexus_platform.access_policy import get_policy
from nexus_platform.auth import AccessContext
from nexus_platform.registry import Company, Employee
from nexus_platform.sim import runner as sim_runner
from nexus_platform.sim.question_gen import Candidate, Turn


def _fake_persona(company: str, role: str) -> AccessContext:
    return AccessContext(
        employee=Employee(email=f"sim-{role.lower()}@{company}.test",
                          name=f"Sim {role}", company_slug=company, role=role,
                          password_hash="", title=f"Sim {role}"),
        company=Company(slug=company, name=company.title(),
                        domain=f"{company}.test", industry="test",
                        description="test co"),
        policy=get_policy(role),
    )


def _stub_run_query(answer="ok"):
    """Deterministic questions answer via the template route; questions
    starting with 'llm' take the planner route (llm_skipped False)."""
    def run_query(ctx, question, session_id, repeat_action=None):
        llm = question.startswith("llm")
        route = "llm_planner" if llm else "deterministic_sql_template"
        payload = {
            "employee": ctx.employee.email, "company": ctx.company.slug,
            "role": ctx.employee.role, "session_id": session_id,
            "question": question, "resolved_question": question,
            "access_decision": "allowed", "route": route,
            "confidence": "HIGH", "llm_skipped": not llm,
            "citations": [], "tables_touched": [], "latency_s": 0.0,
        }
        tid = store.save_trace(ctx.company.slug, ctx.employee.email,
                               ctx.employee.role, question, "allowed", payload)
        return {"answer": answer, "platform": {"trace_id": tid,
                                               "llm_skipped": not llm,
                                               "route": route}}
    return run_query


def _candidates(company, n_det=3, n_llm=3):
    out = []
    for i in range(n_det):
        out.append(Candidate(company=company, role="Analyst",
                             family="simple_metric", difficulty="simple",
                             path_expected="deterministic",
                             turns=[Turn(f"det question {i}", expect="answer")]))
    for i in range(n_llm):
        out.append(Candidate(company=company, role="Analyst",
                             family="complex_multi", difficulty="complex",
                             path_expected="llm",
                             turns=[Turn(f"llm question {i}", expect="answer")]))
    return out


def test_campaign_tags_ledger_budget_and_stats(monkeypatch):
    company = f"simco_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(sim_runner, "run_query", _stub_run_query())
    monkeypatch.setattr(sim_runner, "generate_candidates",
                        lambda c, roles=None, llm_roles=None: _candidates(c))
    monkeypatch.setattr(sim_runner, "persona_context", _fake_persona)
    monkeypatch.setattr(sim_runner, "_providers_available", lambda: True)

    # cap allows exactly one LLM candidate (3 estimated calls each)
    report = sim_runner.run_campaign(company, max_llm_calls=3,
                                     delay_seconds=0.0, save_report=False)

    # budget: 3 det + 3 llm planned; cap of 3 est calls allows 1 llm candidate
    skipped = [s for s in report["budget"]["skipped"] if s["reason"] == "budget_cap"]
    assert len(skipped) == 2
    assert report["budget"]["llm_turns_used"] == 1
    # every executed turn produced a ledger row with a classification
    sims = store.list_sim_queries(company, report["campaign_id"])
    assert len(sims) == 4
    assert all(s["classification"] for s in sims)
    # every trace the campaign wrote is tagged simulated
    assert store.list_traces_with_payload(company) == []
    sim_traces = store.list_traces_with_payload(company, source="simulated")
    assert len(sim_traces) == 4
    # pattern stats got bumped
    stats = {(s["pattern_family"], s["difficulty"]): s
             for s in store.get_pattern_stats(company)}
    assert stats[("simple_metric", "simple")]["candidates_run"] == 3
    assert stats[("complex_multi", "complex")]["candidates_run"] == 1
    # a campaign lesson was written with the campaign as evidence
    lessons = [l for l in store.list_active_lessons(f"company:{company}")]
    assert lessons and report["campaign_id"] in lessons[0]["evidence"]


def test_no_llm_mode_skips_llm_candidates(monkeypatch):
    company = f"simco_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(sim_runner, "run_query", _stub_run_query())
    monkeypatch.setattr(sim_runner, "generate_candidates",
                        lambda c, roles=None, llm_roles=None: _candidates(c, n_det=2, n_llm=2))
    monkeypatch.setattr(sim_runner, "persona_context", _fake_persona)
    report = sim_runner.run_campaign(company, include_llm=False,
                                     delay_seconds=0.0, save_report=False)
    assert report["budget"]["llm_turns_used"] == 0
    assert {s["reason"] for s in report["budget"]["skipped"]} == {"llm_disabled"}
    assert len(store.list_sim_queries(company)) == 2
