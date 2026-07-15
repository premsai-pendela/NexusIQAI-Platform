# Plan — Durable Traces + Simulation Employees + Trace Console (Option C)

**Branch:** `trace-restore/dev` (off `health-loop/dev`)
**Started:** 2026-07-15 · autonomous run, Prem unavailable
**Owner while running:** this build session (no sub-agents, per instruction)

## The problem (verified live 2026-07-15)

Logged into the live site (nexusiq-ai.com/platform) as AcmeCloud Admin →
**Review page shows `EMPLOYEE QUERY TRACES · 0` and `EMPLOYEE FEEDBACK · 0`.**
Root cause found in code, not guessed:

- Company business data (orders, customers…) lives on **durable RDS
  Postgres** via `nexus_platform/db.py` (`NEXUSIQ_PLATFORM_PG_URL`).
- **Traces, feedback, health reports, session memory** live in
  `nexus_platform/store.py`, which is **raw `sqlite3` → `data/platform.db`**.
  In Fargate that file sits on the container's ephemeral disk and is
  **wiped on every redeploy.** That is why the history vanished — not a
  display bug, a storage-durability bug.

`save_trace()` is append-only (unique `tr_…` id per call, never overwrites),
so accumulation is fine once storage is durable.

## The goal

1. Make trace/feedback/health/memory storage **durable** (RDS Postgres in
   cloud, SQLite locally) so history survives redeploys and accumulates.
2. Build **simulation employees**: per-(company,role) personas with **private
   persistent memory**, driven by an **external CLI brain** (Claude Code /
   Codex / any — CLI-agnostic), that query the AIDA analyst **directly in the
   backend** (tagged `source="simulated"`), **paced** so free-tier quota
   survives, memory-adaptive day to day.
3. Rebuild the Review trace explorer as **Option C — a 3-pane console** with a
   **Year › Month › Day drill-down** rail, trace list, and a full-detail pane
   that shows the **agent's answer** (missing today), route, SQL, citations,
   trace id, and a **real/simulated** badge.
4. Feed the accumulated history to the **health-check agent** so the
   improvement loop has real traffic to audit — the interview story.

## Decisions locked (from Prem, 2026-07-15)

- Sim-employee traces **redirect to the same durable store** (RDS in cloud) so
  they appear on the live link.
- Sim employees **pace** themselves: a delay between questions, longer after
  any LLM-route question. Most questions are deterministic/zero-LLM so only
  LLM turns really need the breather. Keep the free-tier alive.
- Traces carry a **`source`** value (`real` / `simulated`) — already exists.
- Sim-employee **memory = files** in the sim-employees folder (not RDS):
  inspectable, git-trackable, durable (runs from the Mac, never the throwaway
  container), matches the "folder with employees + their memory" mental model.
- **AcmeCloud first**, prove end to end, then MedCore + FinPilot.
- Sim traces **shown on Review** with an honest "synthetic demo traffic"
  label; internal `source` tag kept for the health agent's real-vs-sim logic.
- Brain split unchanged: **question generation = external CLI** (Prem's
  subscription), **analyst under test = NexusIQ free tier**. No NexusIQ quota
  spent on question generation.

## Autonomy boundary (honest scope)

- **I CAN** build all code and verify it **end to end locally**: SQLite
  always; the **Postgres path for real** against a throwaway local Postgres
  (`pg_ctl`/`psql` present); sim employees writing traces; Option C rendering
  them; the health loop reading them.
- **I CANNOT** from this Mac: reach the locked-down production RDS (not
  publicly accessible — only the ECS security group can), deploy to Fargate,
  or touch AWS secrets. So the **live cutover is a documented handoff step for
  Prem**, not something I will claim done. I will NOT assert the live site is
  fixed unless it actually is.
- "Survives redeploy" is proven locally by the equivalent: dispose the engine
  / reconnect a fresh process against the same Postgres and confirm the rows
  are still there (a redeploy is exactly a new process on the same RDS).

## Phases (each ends green + committed)

### Phase 0 — Setup (this session)
- [x] Branch `trace-restore/dev`.
- [ ] This plan doc + `ACTIVE_HANDOFF.md` updated.
- [ ] Local Postgres verification harness (throwaway instance helper).

### Phase 1 — Durable dual-backend store (foundation; nothing persists without it)
- Add a `platform_engine()` to `nexus_platform/db.py` (SQLAlchemy, same
  dual-backend pattern already used for company data; SQLite default,
  Postgres when `NEXUSIQ_PLATFORM_PG_URL` set).
- Refactor `store.py` from raw `sqlite3` to that engine, **keeping the public
  API identical** so nothing downstream breaks. Handle dialect diffs in one
  place: named params, `AUTOINCREMENT`→identity, `lastrowid`→`RETURNING`,
  `ON CONFLICT` (portable), boolean/int, `INSERT OR REPLACE`.
- Verify: full `tests/platform_mode/` suite green on SQLite; then a real run
  against **local Postgres** (smoke: write traces/feedback/health + read them
  back + append + reconnect-survives). Append-only and cross-reconnect
  persistence proven.
- Checkpoint commit.

### Phase 2 — Simulation employees (folder + memory + CLI brain + pacing)
- New package `nexus_platform/sim_employees/` + inspectable top-level
  `sim_employees/` folder (roster, per-employee memory JSON, `INSTRUCTIONS.md`
  the CLI reads).
- Persona = existing `persona_context` (identity + access policy). Memory =
  per-employee file: past questions, answers, verdicts, weak spots to
  re-probe.
- Question design: adversarial **and** realistic, 4 tiers
  (simple/moderate/hard/very-very-hard = 5–6-table joins forcing the LLM
  path), ~6 questions/employee/run (configurable), **memory-adaptive**
  (re-probe yesterday's weak answers, don't repeat solved ones).
- Brain = external CLI, **CLI-agnostic**: an `INSTRUCTIONS.md` + helper
  functions so "run the simulation employees" works interactively in Claude
  Code *or* Codex with no extra setup; an optional subprocess wrapper
  (`claude -p` / `codex exec`) for unattended/cron.
- Pacing: configurable `--delay` (default e.g. 15s; longer after LLM turns).
- Traces via `query_service.run_query()` in-process, `source="simulated"`,
  store pointed at RDS when the PG url is set (so live), local otherwise.
- Verify locally: small run → traces appear, memory files created/updated,
  pacing observed, second run adapts. Checkpoint commit.

### Phase 3 — Frontend Option C (Review trace console)
- Backend: extend the admin traces endpoint to return `source` + an answer
  summary; add a date-tree (year→month→day counts) endpoint if useful.
- Frontend: rebuild the trace explorer in
  `web/src/app/platform/admin/page.tsx` as 3-pane — Year›Month›Day drill-down
  rail, trace list, detail pane (question + **agent answer** + route +
  confidence + SQL + citations + trace id + real/simulated badge).
- Verify: web locally against local API + seeded sim traces; screenshot;
  click-through. Checkpoint commit.

### Phase 4 — Health-check loop over accumulated history
- Confirm `run_health_check` reads the accumulated real+simulated history;
  expose sim-campaign review honestly. Mostly wiring — much exists.
- Verify locally. Checkpoint commit.

### Phase 5 — Deploy handoff (Prem's action; documented, not done by me)
- Exact steps for Prem: point the store at RDS (same instance as company
  data), tables auto-create (`CREATE TABLE IF NOT EXISTS`), redeploy Fargate;
  then the live Review page fills as traffic/sims run. Update `ACTIVE_HANDOFF`.

## Definition of done (autonomous portion)
- All code built; `tests/platform_mode/` green; Postgres path verified against
  local Postgres; sim employees run locally end to end with memory + pacing;
  Option C renders real traces with answers; health loop reads history;
  everything committed on `trace-restore/dev`; this plan + `ACTIVE_HANDOFF`
  current; deploy handoff written. Live cutover flagged as needing Prem's AWS
  access — never claimed done unless actually deployed.

## Running log
- 2026-07-15: Phase 0 begun. Live-verified empty Review; root-caused to
  ephemeral SQLite in Fargate. Branch + plan created.
