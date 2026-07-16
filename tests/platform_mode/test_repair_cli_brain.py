"""Deterministic tests for the CLI reasoning brain and its routing.

No real ``claude`` process is ever spawned — ``subprocess.run`` is mocked.
These pin down the two things that must not drift: (a) per-sub-task model
tiering (heavy stages get the strong model, light stages the cheap one), and
(b) the return-dict contract the proposer's retry/feedback loop depends on
(success, model_used, models_tried[*].status/invalid_content).
"""

import subprocess
import types

import pytest

from nexus_platform.repair import cli_brain
from nexus_platform.repair import proposer as proposer_mod


def _proc(returncode=0, stdout="", stderr=""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout,
                                 stderr=stderr)


# ── automatic model selection ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_cli_env(monkeypatch):
    for v in ("NEXUSIQ_REPAIR_CLI_TIERS", "NEXUSIQ_REPAIR_CLI_MODEL",
              "NEXUSIQ_REPAIR_CLI_CHEAP_MODEL", "NEXUSIQ_REPAIR_CLI_BIG_PROMPT"):
        monkeypatch.delenv(v, raising=False)


def test_hard_start_stages_start_strong():
    # plan/implement are inherently hard — first attempt already strong.
    assert cli_brain.model_for("health_repair.plan", attempt=0) == "sonnet"
    assert cli_brain.model_for("health_repair.implement", attempt=0) == "sonnet"


def test_light_generation_starts_cheap_then_escalates():
    # understand/hypothesize/predict start cheap on a small prompt...
    assert cli_brain.model_for("health_repair.understand", attempt=0) == "haiku"
    assert cli_brain.model_for("health_repair.predict", attempt=0) == "haiku"
    # ...and escalate to strong once the stage validator has rejected once.
    assert cli_brain.model_for("health_repair.understand", attempt=1) == "sonnet"
    assert cli_brain.model_for("health_repair.hypothesize", attempt=2) == "sonnet"


def test_review_stages_never_run_cheap():
    # The flagged risk: a cheap reviewer rubber-stamping a bad fix. Review
    # stages ALWAYS get the top tier, on every attempt.
    for stage in ("critique", "confirm_plan", "self_review"):
        assert cli_brain.model_for(f"health_repair.{stage}", attempt=0) == "sonnet"


def test_large_prompt_starts_generation_strong(monkeypatch):
    monkeypatch.setenv("NEXUSIQ_REPAIR_CLI_BIG_PROMPT", "100")
    small = "x" * 50
    big = "x" * 200
    assert cli_brain.model_for("health_repair.understand", prompt=small) == "haiku"
    assert cli_brain.model_for("health_repair.understand", prompt=big) == "sonnet"


def test_three_tier_ladder_and_review_pins_top(monkeypatch):
    monkeypatch.setenv("NEXUSIQ_REPAIR_CLI_TIERS", "haiku,sonnet,opus")
    # generation escalates one tier per attempt, capped at the top
    assert cli_brain.model_for("health_repair.understand", attempt=0) == "haiku"
    assert cli_brain.model_for("health_repair.understand", attempt=1) == "sonnet"
    assert cli_brain.model_for("health_repair.understand", attempt=2) == "opus"
    assert cli_brain.model_for("health_repair.understand", attempt=9) == "opus"
    # reviewers always get the top of whatever ladder is configured
    assert cli_brain.model_for("health_repair.critique") == "opus"


def test_backcompat_single_model_envs(monkeypatch):
    monkeypatch.setenv("NEXUSIQ_REPAIR_CLI_MODEL", "opus")
    monkeypatch.setenv("NEXUSIQ_REPAIR_CLI_CHEAP_MODEL", "sonnet")
    assert cli_brain.model_for("health_repair.plan") == "opus"       # hard→top
    assert cli_brain.model_for("health_repair.critique") == "opus"   # review→top
    assert cli_brain.model_for("health_repair.understand") == "sonnet"  # cheap start


# ── cli_llm return contract ──────────────────────────────────────────────

def test_success_path(monkeypatch):
    monkeypatch.setattr(cli_brain.shutil, "which", lambda _: "/bin/claude")
    monkeypatch.setattr(cli_brain.subprocess, "run",
                        lambda *a, **k: _proc(0, "MECHANISM: ok\n"))
    out = cli_brain.cli_llm("prompt", "health_repair.understand",
                            validator=lambda t: "MECHANISM:" in t)
    assert out["success"] is True
    assert out["response"] == "MECHANISM: ok"
    assert out["model_used"].startswith("cli:")
    assert out["models_tried"][0]["status"] == "OK"


def test_validator_failure_returns_invalid_content(monkeypatch):
    monkeypatch.setattr(cli_brain.shutil, "which", lambda _: "/bin/claude")
    monkeypatch.setattr(cli_brain.subprocess, "run",
                        lambda *a, **k: _proc(0, "garbage answer"))
    out = cli_brain.cli_llm("p", "health_repair.plan",
                            validator=lambda t: "PLAN:" in t)
    assert out["success"] is False
    tried = out["models_tried"][0]
    assert tried["status"] == "INVALID"
    assert tried["invalid_content"] == "garbage answer"


def test_nonzero_exit_is_error(monkeypatch):
    monkeypatch.setattr(cli_brain.shutil, "which", lambda _: "/bin/claude")
    monkeypatch.setattr(cli_brain.subprocess, "run",
                        lambda *a, **k: _proc(1, "", "boom"))
    out = cli_brain.cli_llm("p", "health_repair.plan", validator=None)
    assert out["success"] is False
    assert "ERROR" in out["models_tried"][0]["status"]


def test_timeout_is_error(monkeypatch):
    monkeypatch.setattr(cli_brain.shutil, "which", lambda _: "/bin/claude")

    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(cli_brain.subprocess, "run", _raise)
    out = cli_brain.cli_llm("p", "health_repair.plan", validator=None)
    assert out["success"] is False
    assert "timed out" in out["models_tried"][0]["status"]


def test_missing_binary_is_error(monkeypatch):
    monkeypatch.setattr(cli_brain.shutil, "which", lambda _: None)
    monkeypatch.setattr(cli_brain.os.path, "exists", lambda _: False)
    out = cli_brain.cli_llm("p", "health_repair.plan", validator=None)
    assert out["success"] is False
    assert "not found" in out["models_tried"][0]["status"]


def test_disables_tools_and_single_turn(monkeypatch):
    seen = {}

    def _capture(cmd, **k):
        seen["cmd"] = cmd
        return _proc(0, "ok text")

    monkeypatch.setattr(cli_brain.shutil, "which", lambda _: "/bin/claude")
    monkeypatch.setattr(cli_brain.subprocess, "run", _capture)
    cli_brain.cli_llm("p", "health_repair.understand", validator=None)
    cmd = seen["cmd"]
    assert "--max-turns" in cmd and cmd[cmd.index("--max-turns") + 1] == "1"
    assert "--disallowedTools" in cmd
    assert "Bash" in cmd and "Edit" in cmd and "Write" in cmd


# ── proposer routing: hard→CLI, cheap→gateway, env override ───────────────

def test_default_llm_routes_hard_to_cli(monkeypatch):
    calls = {}
    monkeypatch.setenv("NEXUSIQ_REPAIR_BRAIN", "cli")
    monkeypatch.setattr("nexus_platform.repair.cli_brain.cli_llm",
                        lambda **k: calls.setdefault("cli", k) or {"ok": 1})
    monkeypatch.setattr(proposer_mod, "_gateway_llm",
                        lambda *a, **k: calls.setdefault("gw", k) or {"ok": 0})
    proposer_mod._default_llm("p", "health_repair.plan", None, reasoning=True)
    assert "cli" in calls and "gw" not in calls


def test_default_llm_routes_cheap_to_gateway(monkeypatch):
    calls = {}
    monkeypatch.setenv("NEXUSIQ_REPAIR_BRAIN", "cli")
    monkeypatch.setattr("nexus_platform.repair.cli_brain.cli_llm",
                        lambda **k: calls.setdefault("cli", k))
    monkeypatch.setattr(proposer_mod, "_gateway_llm",
                        lambda *a, **k: calls.setdefault("gw", k))
    proposer_mod._default_llm("p", "health_repair.localize", None,
                              reasoning=False)
    assert "gw" in calls and "cli" not in calls


def test_brain_env_gateway_forces_free_tier(monkeypatch):
    calls = {}
    monkeypatch.setenv("NEXUSIQ_REPAIR_BRAIN", "gateway")
    monkeypatch.setattr("nexus_platform.repair.cli_brain.cli_llm",
                        lambda **k: calls.setdefault("cli", k))
    monkeypatch.setattr(proposer_mod, "_gateway_llm",
                        lambda *a, **k: calls.setdefault("gw", k))
    proposer_mod._default_llm("p", "health_repair.plan", None, reasoning=True)
    assert "gw" in calls and "cli" not in calls


# ── escalation threads end-to-end through the proposer's retry loop ────────

def test_invoke_threads_escalating_attempt_into_llm(monkeypatch):
    """_invoke must pass a rising `attempt` on each substantive failure so a
    generation stage that keeps failing its validator escalates model tiers.
    A single injected llm records the attempt it saw each call."""
    from nexus_platform.repair.context_pack import EvidencePack
    from pathlib import Path

    seen_attempts = []

    def fake_llm(prompt, task, validator, reasoning=True, attempt=0):
        seen_attempts.append(attempt)
        # fail the first two substantive attempts, succeed on the third
        text = "MECHANISM: real" if attempt >= 2 else "nope"
        ok = validator(text) if validator else True
        if ok:
            return {"response": text, "success": True, "model_used": "x",
                    "models_tried": [{"model": "x", "status": "OK"}]}
        return {"response": "", "success": False, "model_used": "x",
                "models_tried": [{"model": "x", "status": "INVALID",
                                  "invalid_content": text}]}

    pack = EvidencePack(finding={"id": "f", "company": "c", "severity": "high",
                                 "summary": "s", "payload": {}},
                        traces=[], company="c", repo_root=Path("."))
    p = proposer_mod.Proposer(pack=pack, llm=fake_llm, delay_seconds=0)
    out = p._invoke("understand", "prompt",
                    lambda t: ("MECHANISM:" in t, "need MECHANISM"))
    assert out == "MECHANISM: real"
    assert seen_attempts == [0, 1, 2]   # escalated on each retry
