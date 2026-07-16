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


# ── model tiering ────────────────────────────────────────────────────────

def test_heavy_stage_gets_strong_model(monkeypatch):
    monkeypatch.delenv("NEXUSIQ_REPAIR_CLI_MODEL", raising=False)
    monkeypatch.delenv("NEXUSIQ_REPAIR_CLI_CHEAP_MODEL", raising=False)
    assert cli_brain.model_for("health_repair.plan") == "sonnet"
    assert cli_brain.model_for("health_repair.implement") == "sonnet"
    assert cli_brain.model_for("health_repair.predict") == "sonnet"


def test_light_stage_gets_cheap_model(monkeypatch):
    monkeypatch.delenv("NEXUSIQ_REPAIR_CLI_CHEAP_MODEL", raising=False)
    assert cli_brain.model_for("health_repair.critique") == "haiku"
    assert cli_brain.model_for("health_repair.self_review") == "haiku"


def test_model_env_overrides(monkeypatch):
    monkeypatch.setenv("NEXUSIQ_REPAIR_CLI_MODEL", "opus")
    monkeypatch.setenv("NEXUSIQ_REPAIR_CLI_CHEAP_MODEL", "sonnet")
    assert cli_brain.model_for("health_repair.plan") == "opus"
    assert cli_brain.model_for("health_repair.critique") == "sonnet"


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
