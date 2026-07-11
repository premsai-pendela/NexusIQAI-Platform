"""Deterministic tests for the repair pipeline's scaffolding.

No LLM is called anywhere here — the proposer takes an injected fake. What
these tests pin down is the part that must never drift: the guardrails
(scope fence, plan allowlist, syntax checks), the lenient-but-strict edit
application, the plan parser, and the feedback-retry loop.
"""

import textwrap
from pathlib import Path

import pytest

from nexus_platform.repair import apply as apply_mod
from nexus_platform.repair import proposer as proposer_mod
from nexus_platform.repair.context_pack import EvidencePack
from nexus_platform.repair.proposer import (BudgetExhausted, Proposer,
                                            StageFailed, _parse_plan)

ROOT = Path(__file__).resolve().parents[2]


# ── edit application ─────────────────────────────────────────────────────

def _block(path, search, replace):
    return (f"FILE: {path}\n<<<<<<< SEARCH\n{search}\n=======\n"
            f"{replace}\n>>>>>>> REPLACE\n")


def test_parse_blocks_roundtrip():
    text = _block("nexus_platform/x.py", "a = 1", "a = 2")
    edits = apply_mod.parse_blocks(text)
    assert len(edits) == 1
    assert edits[0].path == "nexus_platform/x.py"
    assert edits[0].search == "a = 1"
    assert edits[0].replace == "a = 2"


def test_apply_rejects_out_of_scope(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web/app.tsx").write_text("x")
    result = apply_mod.apply_edit(
        tmp_path, apply_mod.Edit("web/app.tsx", "x", "y"), ["web/app.tsx"])
    assert not result.ok
    assert "scope fence" in result.reason


def test_apply_rejects_file_not_in_plan(tmp_path):
    (tmp_path / "nexus_platform").mkdir()
    target = tmp_path / "nexus_platform/mod.py"
    target.write_text("a = 1\n")
    result = apply_mod.apply_edit(
        tmp_path, apply_mod.Edit("nexus_platform/mod.py", "a = 1", "a = 2"),
        ["nexus_platform/other.py"])
    assert not result.ok
    assert "FILES_TOUCHED" in result.reason
    assert target.read_text() == "a = 1\n"  # untouched


def test_apply_exact_and_whitespace_tolerant(tmp_path):
    (tmp_path / "nexus_platform").mkdir()
    target = tmp_path / "nexus_platform/mod.py"
    target.write_text("def f():\n    return 1   \n")
    # Search text has the trailing spaces stripped — still must match.
    result = apply_mod.apply_edit(
        tmp_path,
        apply_mod.Edit("nexus_platform/mod.py",
                       "def f():\n    return 1", "def f():\n    return 2"),
        ["nexus_platform/mod.py"])
    assert result.ok, result.reason
    assert "return 2" in target.read_text()


def test_apply_rolls_back_syntax_errors(tmp_path):
    (tmp_path / "nexus_platform").mkdir()
    target = tmp_path / "nexus_platform/mod.py"
    target.write_text("a = 1\n")
    result = apply_mod.apply_edit(
        tmp_path, apply_mod.Edit("nexus_platform/mod.py", "a = 1",
                                 "def broken(:"),
        ["nexus_platform/mod.py"])
    assert not result.ok
    assert "syntax" in result.reason.lower()
    assert target.read_text() == "a = 1\n"


def test_apply_treats_placeholder_search_as_new_file(tmp_path):
    (tmp_path / "tests/platform_mode").mkdir(parents=True)
    result = apply_mod.apply_edit(
        tmp_path,
        apply_mod.Edit("tests/platform_mode/test_new.py",
                       "```\n(file does not exist yet)\n```",
                       "def test_x():\n    assert True"),
        ["tests/platform_mode/test_new.py"])
    assert result.ok, result.reason
    assert "def test_x" in (tmp_path / "tests/platform_mode/test_new.py").read_text()


def test_apply_new_file_requires_empty_search(tmp_path):
    (tmp_path / "tests/platform_mode").mkdir(parents=True)
    result = apply_mod.apply_edit(
        tmp_path, apply_mod.Edit("tests/platform_mode/test_new.py", "",
                                 "def test_x():\n    assert True"),
        ["tests/platform_mode/test_new.py"])
    assert result.ok, result.reason
    assert (tmp_path / "tests/platform_mode/test_new.py").exists()


def test_apply_rejects_ambiguous_search(tmp_path):
    (tmp_path / "nexus_platform").mkdir()
    (tmp_path / "nexus_platform/mod.py").write_text("x = 1\ny = 2\nx = 1\n")
    result = apply_mod.apply_edit(
        tmp_path, apply_mod.Edit("nexus_platform/mod.py", "x = 1", "x = 3"),
        ["nexus_platform/mod.py"])
    assert not result.ok
    assert "unique" in result.reason


# ── plan parsing + guardrails ────────────────────────────────────────────

GOOD_PLAN = textwrap.dedent("""\
    PLAN:
    1. FILE: tests/platform_mode/test_new_gate.py — create the regression test
    2. FILE: nexus_platform/orchestrator.py — add the narrow check
    FILES_TOUCHED: tests/platform_mode/test_new_gate.py, nexus_platform/orchestrator.py
    TEST_FILE: tests/platform_mode/test_new_gate.py
""")


def test_parse_plan_good():
    plan, problem = _parse_plan(GOOD_PLAN)
    assert problem == ""
    assert len(plan.steps) == 2
    assert plan.test_file == "tests/platform_mode/test_new_gate.py"
    assert [s["file"] for s in plan.code_steps] == \
        ["nexus_platform/orchestrator.py"]


def test_parse_plan_rejects_out_of_scope():
    bad = GOOD_PLAN.replace("nexus_platform/orchestrator.py",
                            "web/src/app/page.tsx")
    plan, problem = _parse_plan(bad)
    assert "scope fence" in problem


def test_parse_plan_requires_test_step():
    bad = textwrap.dedent("""\
        PLAN:
        1. FILE: nexus_platform/orchestrator.py — add the check
        FILES_TOUCHED: nexus_platform/orchestrator.py
        TEST_FILE: tests/platform_mode/test_new_gate.py
    """)
    plan, problem = _parse_plan(bad)
    assert "regression test" in problem or "TEST_FILE" in problem


def test_parse_plan_rejects_code_free_plan():
    bad = textwrap.dedent("""\
        PLAN:
        1. FILE: tests/platform_mode/test_new_gate.py — create the test
        FILES_TOUCHED: tests/platform_mode/test_new_gate.py
        TEST_FILE: tests/platform_mode/test_new_gate.py
    """)
    plan, problem = _parse_plan(bad)
    assert "does not fix anything" in problem


# ── proposer stage mechanics with a fake LLM ─────────────────────────────

def _pack(tmp_path=None) -> EvidencePack:
    root = tmp_path or ROOT
    return EvidencePack(
        finding={"id": "hf_test", "company": "acmecloud",
                 "fingerprint": "cafebabe0000", "severity": "high",
                 "summary": "test finding",
                 "payload": {"kind": "test_kind", "recommendation": "fix it",
                             "evidence": ["tr_x"], "campaign_id": "camp_t"}},
        traces=[{"id": "tr_x", "payload": {
            "question": "What is our X?", "route": "sql_agent",
            "route_reason": "no deterministic family matched",
            "sql": "SELECT 1", "access_decision": "allowed"}}],
        company="acmecloud", repo_root=Path(root))


class FakeLLM:
    """Returns queued responses; records prompts for assertions."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def __call__(self, *, prompt, task, validator):
        self.prompts.append((task, prompt))
        if not self.responses:
            return {"success": False, "response": ""}
        return {"success": True, "response": self.responses.pop(0),
                "model_used": "fake-model"}


def test_invoke_retries_with_feedback_then_succeeds():
    pack = _pack()
    fake = FakeLLM(["garbage with no mechanism",
                    "The function decide_route sends it on. MECHANISM: " +
                    "x" * 300])
    p = Proposer(pack=pack, llm=fake, delay_seconds=0)
    p._code_context = "def decide_route(): ..."
    p._known_symbols = {"decide_route"}
    out = p.understand()
    assert "MECHANISM:" in out
    # Second prompt must carry the concrete rejection reason back.
    assert "REJECTED" in fake.prompts[1][1]
    assert p.calls_made == 2


def test_invoke_gives_up_after_retries():
    pack = _pack()
    fake = FakeLLM(["bad"] * 3)
    p = Proposer(pack=pack, llm=fake, delay_seconds=0)
    p._known_symbols = {"decide_route"}
    with pytest.raises(StageFailed):
        p.understand()


def test_budget_exhaustion_stops_the_attempt():
    pack = _pack()
    fake = FakeLLM(["bad"] * 100)
    p = Proposer(pack=pack, llm=fake, delay_seconds=0, max_calls=2)
    p._known_symbols = {"decide_route"}
    with pytest.raises((BudgetExhausted, StageFailed)):
        p.understand()
        p.understand()
    assert p.calls_made <= 2


def test_localize_validates_files_exist():
    pack = _pack()
    fake = FakeLLM([
        "FILES: nexus_platform/does_not_exist.py\nFUNCTIONS: foo",
        "FILES: nexus_platform/orchestrator.py\nFUNCTIONS: decide_route",
    ])
    p = Proposer(pack=pack, llm=fake, delay_seconds=0)
    located = p.localize()
    assert located["files"] == ["nexus_platform/orchestrator.py"]
    assert "decide_route" in p._known_symbols


def test_implement_step_rejects_edits_to_other_files():
    pack = _pack()
    plan, _ = _parse_plan(GOOD_PLAN)
    stray = _block("nexus_platform/query_service.py", "x", "y")
    good = _block("nexus_platform/orchestrator.py", "x", "y")
    fake = FakeLLM([stray, good])
    p = Proposer(pack=pack, llm=fake, delay_seconds=0)
    out = p.implement_step(plan, plan.code_steps[0])
    assert "orchestrator" in out
    assert "REJECTED" in fake.prompts[1][1]


def test_session_log_records_every_call():
    pack = _pack()
    fake = FakeLLM(["FILES: nexus_platform/orchestrator.py\nFUNCTIONS: f"])
    p = Proposer(pack=pack, llm=fake, delay_seconds=0)
    p.localize()
    assert len(p.log) == 1
    entry = p.log[0]
    assert entry["stage"] == "localize"
    assert entry["model_used"] == "fake-model"
    assert entry["valid"] is True


def test_exhaustion_waits_and_retries_without_feedback_suffix():
    pack = _pack()
    fake = FakeLLM([])  # always returns success=False
    fake.responses = []

    class Exhausted:
        def __init__(self):
            self.prompts = []

        def __call__(self, *, prompt, task, validator):
            self.prompts.append(prompt)
            if len(self.prompts) < 2:
                return {"success": False, "response": ""}
            return {"success": True, "model_used": "fake",
                    "response": "The function decide_route routes it. "
                                "MECHANISM: " + "x" * 300}

    ex = Exhausted()
    p = Proposer(pack=pack, llm=ex, delay_seconds=0, exhaustion_wait=0)
    p._known_symbols = {"decide_route"}
    out = p.understand()
    assert "MECHANISM:" in out
    # The retry after exhaustion must NOT carry a REJECTED suffix — there
    # was nothing wrong with the answer, there was no answer.
    assert "REJECTED" not in ex.prompts[1]


def test_wrong_reason_failure_detection():
    from nexus_platform.repair.runner import _fails_for_wrong_reason
    assert _fails_for_wrong_reason("E   ImportError: cannot import name")
    assert _fails_for_wrong_reason("E   TypeError: f() takes 1 argument")
    assert _fails_for_wrong_reason("ERROR ... fixture 'foo' not found")
    assert not _fails_for_wrong_reason(
        "E   AssertionError: expected honest refusal, got '-1'")
    # A TypeError deep in setup followed by the real assertion counts as
    # an honest assertion failure.
    assert not _fails_for_wrong_reason(
        "E   TypeError: bad\nlater...\nE   AssertionError: nope")


def test_implement_step_slices_large_files():
    pack = _pack()
    plan, _ = _parse_plan(GOOD_PLAN.replace(
        "nexus_platform/orchestrator.py", "agents/sql_agent.py"))
    good = _block("agents/sql_agent.py", "x", "y")
    fake = FakeLLM([good])
    p = Proposer(pack=pack, llm=fake, delay_seconds=0)
    p._located_functions = ["_validate_query"]
    p.implement_step(plan, plan.code_steps[0])
    prompt = fake.prompts[0][1]
    # sql_agent.py is >1200 lines; the prompt must carry a slice, not the
    # whole file (whole-file prompts got 413'd by Groq live).
    assert "only the relevant parts of the file are shown" in prompt
    assert len(prompt) < 30000


def test_resume_seed_reconstructs_from_stage_records(tmp_path):
    from nexus_platform.repair.runner import _load_resume_seed
    session = {
        "finding": "hf_x",
        "stages": [
            {"stage": "localize", "valid": True, "response":
                "FILES: nexus_platform/orchestrator.py\nFUNCTIONS: decide_route"},
            {"stage": "understand", "valid": True, "response":
                "It routes wrong. MECHANISM: because."},
            {"stage": "hypothesize", "valid": True, "response":
                "ROOT_CAUSE: a\nLOCATION: b\nEXPECTED: c"},
            {"stage": "critique", "valid": True, "response":
                "VERDICT: REVISE\nROOT_CAUSE: a2\nLOCATION: b2\nEXPECTED: c2"},
            {"stage": "plan", "valid": True, "response": GOOD_PLAN},
        ],
    }
    p = tmp_path / "s.json"
    p.write_text(__import__("json").dumps(session))
    seed = _load_resume_seed(p, "hf_x")
    assert seed is not None
    assert seed["located"]["files"] == ["nexus_platform/orchestrator.py"]
    assert "ROOT_CAUSE: a2" in seed["hypothesis"]  # critique's revision wins
    assert "FILES_TOUCHED" in seed["plan"]
    # wrong finding → no seed
    assert _load_resume_seed(p, "hf_other") is None


def test_dirty_paths_survives_leading_space_status(tmp_path):
    """`stdout.strip()` on line-oriented `git status` once mangled the
    first ' M <path>' entry and silently dropped a file from a commit —
    the -z parser must not."""
    import subprocess
    from nexus_platform.repair.runner import _dirty_paths
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a_tracked.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=tmp_path, check=True)
    (tmp_path / "a_tracked.py").write_text("x = 2\n")
    (tmp_path / "b_untracked.py").write_text("y = 1\n")
    paths = _dirty_paths(tmp_path)
    assert "a_tracked.py" in paths
    assert "b_untracked.py" in paths


def test_test_step_prompt_carries_the_failing_question():
    pack = _pack()
    plan, _ = _parse_plan(GOOD_PLAN)
    fake = FakeLLM([_block("tests/platform_mode/test_new_gate.py", "",
                           "def test_x():\n    assert True")])
    p = Proposer(pack=pack, llm=fake, delay_seconds=0)
    p._code_context = "def decide_route(): ..."
    p.implement_step(plan, plan.test_steps[0])
    prompt = fake.prompts[0][1]
    # The trace's failing question must be visible to the test writer —
    # attempt-7 lesson: a writer that can't see the failure writes a
    # helper-existence test instead of a repro.
    assert "What is our X?" in prompt
    assert "OBSERVED FAILURE" in prompt


def test_replan_naming_missing_symbol_gets_extended_context():
    from nexus_platform.repair.runner import _implement
    pack = _pack()
    plan, _ = _parse_plan(GOOD_PLAN.replace(
        "nexus_platform/orchestrator.py", "nexus_platform/deterministic.py"))
    fake = FakeLLM([
        "REPLAN: cannot locate `parse_intent` in the provided excerpt",
        _block("nexus_platform/deterministic.py", "x", "y"),
    ])
    p = Proposer(pack=pack, llm=fake, delay_seconds=0)
    p._located_functions = ["execute"]
    out = _implement(p, plan, plan.code_steps[0])
    assert "SEARCH" in out
    assert "parse_intent" in p._located_functions
    # The retry prompt must actually show the requested function.
    assert "def parse_intent" in fake.prompts[1][1]


# ── model chain composition ──────────────────────────────────────────────

def test_build_models_never_includes_ollama_or_frontier():
    models = proposer_mod.build_models()
    types = {m.get("type") for m in models}
    assert "ollama" not in types
    names = " ".join(str(m.get("name", "")).lower() for m in models)
    for forbidden in ("opus", "sonnet", "fable"):
        assert forbidden not in names
