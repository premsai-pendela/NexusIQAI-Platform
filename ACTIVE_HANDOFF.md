# ACTIVE HANDOFF — NexusIQAI Platform

_Last updated: 2026-08-27_

## Current state

- **Branch:** `master` (all initiatives below are merged).
- **Tests:** `479 passed` locally (`.venv/bin/python -m pytest tests/ -q`).
  CI runs the same suite via pytest, gated behind a brain-freshness check.
- **Hosted environment:** paused. The Amplify frontend still serves, but the
  API (`api.nexusiq-ai.com` → ALB) is not running, so the live demo cannot
  answer questions. Everything runs locally from this repo; see README
  "Run Locally". Restoring the hosted stack is a deploy task, not a code task
  — steps in `docs/platform improvements/DEPLOY_HANDOFF_traces_to_rds.md`.

## Completed initiatives

1. **Platform Mode** — multi-company workspaces, four-layer role-based access
   (SQL prompt → sqlglot AST allowlist → Chroma department filter → response
   citation check), deterministic zero-LLM analyst layer for 15 metric
   families.
2. **CI gate hardened** (PR #10) — starlette pinned, suite run via pytest so
   the `tests/platform_mode/*` contracts actually execute, demo brains
   committed plus a `brain_builder --check` staleness guard.
3. **Durable traces + simulation employees + trace console** (PRs #11, #12) —
   dual-backend platform store (RDS Postgres in cloud, SQLite locally),
   `sim_employees/` traffic generator with per-persona file memory and an
   external CLI brain, admin trace console with Year › Month › Day drill-down
   and a real/simulated source filter.
4. **Health Check agent + eval-gated repair pipeline** (PRs #1, #2, #13, #14) —
   trace auditing on a deterministic-oracle → capped-LLM-judge → human
   escalation, plus `nexus_platform/repair/` which localizes, plans, writes a
   regression test, writes the fix, and opens a PR. Hard reasoning stages run
   on Claude Code via CLI (`repair/cli_brain.py`); the cheap localization
   stage stays on the product's free-tier gateway. No merge path exists in the
   repair code and `tests/platform_mode/test_repair_no_merge_path.py` enforces
   that structurally.

**Pipeline-authored fixes merged:** PR #1 (unknown-metric honesty, free-tier
brain, ~10 attempts) and PR #13 (fabricated access-denial for a hallucinated
table, Claude Code brain, 5 LLM calls). Both human-reviewed and human-merged.

## Known open items

- **PR #9 is still open** — upgrades the Bedrock fallback to Claude Haiku 4.5
  (newer Anthropic models need the cross-region inference-profile ARN, not the
  bare model ID) and carries `FUTURE_IMPROVEMENTS.md`. Flags an unverified IAM
  question: the deploy user lacks `iam:GetRolePolicy`, so whether the new ARN
  is authorized is unconfirmed. Degrades to earlier fallback tiers if not.
  README links `ROADMAP.md` for the roadmap so nothing depends on that file.
- **Stochastic seam findings stay open** (e.g. `hf_e4796a5431`). A repair must
  be provable by a test that fails before and passes after; a defect that only
  misbehaves on some runs can't be pinned that way yet. Logged open with a
  diagnosis rather than faked past.
- **Private working docs are intentionally not published.** The mission and
  model-routing briefs for the health-check initiative are kept out of the
  public repo; only the agent's own run log
  (`docs/platform improvements/Health_Check notes 2026-07-15.md`) ships, since
  it is the evidence for what the loop actually did.

## Resume

```bash
git checkout master && git pull
.venv/bin/python -m pytest tests/ -q                      # expect 479 passed
.venv/bin/python scripts/run_repair.py --company acmecloud --list
```

Read the README's "The Second Agent" section for how the loop fits together,
and `docs/platform improvements/ARCHITECTURE_LOG.md` for the design history.
