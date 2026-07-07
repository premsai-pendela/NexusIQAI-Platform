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

See `~/Dev/NexusIQAI-Website/ACTIVE_HANDOFF.md` → Milestones. Platform
C1-C11 complete; C12 (polish/deploy) in progress.

DO NOT PUSH to GitHub without Prem's explicit go-ahead.
