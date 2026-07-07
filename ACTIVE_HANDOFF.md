# ACTIVE HANDOFF — NexusIQAI Platform

This repo is the **NexusIQAI Platform** implementation: a prototype
multi-company AI data analyst built on the NexusIQ recruiter-proof agent
stack. The control workspace with the full plan and milestone history lives
at `~/Dev/NexusIQAI-Website/ACTIVE_HANDOFF.md` — read that first when
resuming; this file covers repo-local facts only.

## What this repo contains

- Legacy NexusIQ recruiter-proof app (live demo surface): `/` pages, live
  Supabase + 52-doc Chroma corpus, `/api/v1/query`.
- **Platform Mode** (the new product): `nexus_platform/`,
  `api/routes/platform.py`, `web/src/app/platform/*`,
  `data/demo_companies/`. See `docs/PLATFORM_MODE.md` for architecture.

## Run

```bash
source .venv/bin/activate
NEXUSIQ_PREWARM_LIVE=false uvicorn api.main:app --port 8000   # backend
cd web && npm run build && npx next start -p 3000             # frontend
# open http://localhost:3000/platform  (demo accounts on the login page)
```

First run after a fresh clone: build the company brains once —
`python -m nexus_platform.brain_builder` (they are runtime artifacts,
not committed).

## Verify

```bash
.venv/bin/python -m pytest tests/ -q            # full suite
.venv/bin/python scripts/platform_smoke.py      # 7 live LLM scenarios
.venv/bin/python scripts/check_access.py --matrix
.venv/bin/python scripts/inspect_platform_traces.py
cd web && npm run lint && npm run build
```

## Runtime artifacts (never commit)

- `data/platform.db` — traces/feedback/memory store
- `data/demo_companies/*/brain/` — built brains (Chroma + catalogs)
- `data/quota_tracker.json`, `data/web_cache.json` — legacy runtime state

All gitignored. Regenerate demo data with
`python -m nexus_platform.seed.generate_company_data`, brains with
`python -m nexus_platform.brain_builder`.

## Status

Final showcase pass COMPLETE (2026-07-07). 347 tests green, lint/build
green, 7/7 live smoke, trace audit clean, browser QA done. Deterministic
analyst layer answers 15 metric families with zero LLM calls; session
memory resolves follow-ups deterministically; exports carry provenance.
See `docs/NEXUSIQAI_FULL_BUILD_REPORT.md` and
`docs/RECRUITER_PROOF_SUMMARY.md`. Milestone history:
`~/Dev/NexusIQAI-Website/ACTIVE_HANDOFF.md`.

Post-final polish (2026-07-07): fixed the "Q1 to Q4 bar graph" parsing
bug so period ranges render a quarterly series, added Ask Analyst recent
analysis restore in localStorage, and changed "report this answer" to ask
for a user comment while attaching the trace automatically for Admin review.

DO NOT PUSH to GitHub without Prem's explicit go-ahead.
