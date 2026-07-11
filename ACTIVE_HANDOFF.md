# ACTIVE HANDOFF — NexusIQAI Platform

## INITIATIVE: Self-Improving Health Check Agent (2026-07-10, in progress)

Mission brief: `docs/platform improvements/CONTEXT.md` (+ model-routing rules
in `docs/platform improvements/CLAUDE.md`). Design journal:
`docs/platform improvements/ARCHITECTURE_LOG.md` (guardrails at top — read
those before resuming). Runs autonomously; Prem unavailable during the run.

- **Objective:** turn `nexus_platform/health_check.py` into a closed loop —
  simulate adversarial employee traffic → classify answers → diagnose real
  findings → fix on a branch with before/after evidence → open a PR on
  `premsai-pendela/NexusIQAI-Platform` (never merge). Six-item goal checklist
  in CONTEXT.md §"The final goal".
- **Branch/worktree:** main checkout on `master` (uncommitted doc edits were
  already present before this initiative — untouched). Fix branches will be
  created in a separate git worktree, named `autofix/<fingerprint>`.
- **Completed milestones:**
  - Step 0 orientation (docs + code + live product). Bug #1 reproduced live
    as AcmeCloud Analyst: repeat → "Analyze with AI" → refusal naming
    nonexistent table `sales_transactions`; live trace `tr_79a32d53e8`.
    Correct-refusal contrast case verified as HR (denial names real table
    `orders`).
  - Step 0.5 guardrails + initial architecture plan written
    (ARCHITECTURE_LOG.md), reconciled with
    `SELF_IMPROVING_HEALTH_CHECK_AGENT_PLAN.md` — adopted with 7 documented
    deviations/decisions (difficulty-tier axis, adversarial families,
    continuous phases, PR-target repo, provisional gold set, CLI trigger,
    agent operational memory).
  - GitHub access verified: `gh auth status` → fine-grained PAT active as
    premsai-pendela (GH_TOKEN env). Token value never written anywhere.
  - Research pass done (BI question shapes; agent-memory failure modes —
    LLM-rewritten memory rejected, cited in ARCHITECTURE_LOG Entry 2).
  - Phase 0 done: `traces.source` tagging (contextvar), real-only read
    defaults, `simulated_query_log` / `health_findings` /
    `health_finding_events` / `sim_pattern_stats` / `agent_lessons` tables.
  - Phase 1 done: `nexus_platform/sim/` (personas, question_gen,
    classifier, runner) + `scripts/run_sim_campaign.py`. 86 candidates ×
    14 families × 4 difficulty tiers; zero-LLM classifier with 38-case
    provisional gold set. Suite 178 passed. Commits on `health-loop/dev`.
  - Shakeout campaign `camp_f688345b32` (no-LLM, 98 turns) ran; classifier
    false-positive found+fixed (leak check now gates on
    access_decision=allowed), false findings dismissed with notes, lesson
    persisted. Real discovery kept: typo'd metric words bypass the
    malformed-period gate and get confident garbage (finding recorded).
  - Campaign `camp_c305c02583` (118 turns) surfaced a REAL exceptional
    finding unprompted: SQL agent fabricated an NPS formula over the 1–5
    CSAT scale and answered "Nps score: -1" for a metric that exists
    nowhere (trace `tr_63dee96201`). Goal item 2 met.
  - Fix built on branch `autofix/unknown-metric-honesty` (worktree
    `../NexusIQAI-autofix`, base master@94892ad): unknown-metric honesty
    gate in `orchestrator.find_clarification` + 6 regression tests.
    Eval gate PASS — before: suite 154 green / repro 3 failed; after:
    suite 154 green, zero new failures / repro 5 passed. Evidence JSON in
    session scratchpad; summary in PR body + ARCHITECTURE_LOG Entry 6.
    Branch **pushed to origin**. Goal item 3 met.
- **Mission v2 correction applied (2026-07-10, this session).** Per
  `docs/platform improvements/HEALTH_CHECK_AGENT_MISSION.md`: the
  `autofix/unknown-metric-honesty` branch was hand-written by Fable — kept
  only as a known-good **reference** to validate the real pipeline against;
  it will not be the PR. Goal item 3 re-opened until the pipeline's own
  code does the diagnose/plan/test/edit work.
  - **Repair pipeline built (stages 3–7 as real code):**
    `nexus_platform/repair/` — `context_pack.py` (evidence + hierarchical
    localization), `proposer.py` (localize → understand → hypothesize +
    framed critique → plan → incremental SEARCH/REPLACE implement →
    self-review, all via `utils/llm_gateway.invoke_with_fallback` on the
    product chain, no Ollama, never Fable), `apply.py` (scope fence +
    plan-allowlist + syntax guardrails), `runner.py` (worktree off master,
    test-first repro, eval gate, local-commit-only), plus
    `scripts/run_repair.py` and `scripts/notify_prem.py`. 20 new
    mocked-LLM tests; platform suite 203 green; anti-merge grep extended.
    Design + research: ARCHITECTURE_LOG Entry 7.
  - **PR opening is pre-authorized in advance** (CONTEXT.md §GitHub
    access) — publish once at the true end via `repair/pr.py`, after
    Phase 2. Merging stays Prem-only, always.
- **Next unfinished milestone:** Phase 1 validation — pipeline attempts
  1–5 on finding `hf_73a86c38bc` (NPS fabrication) each failed for a
  *different, fixed* reason (oversized prompts → provider starvation;
  starved retries + narrating reasoning models; two external
  background-task kills; my own runner deleting the test draft before
  soft-accept). Pipeline reasoning itself is proven: attempt 4 (Cerebras)
  independently planned a metric-existence gate before the SQL agent —
  same architectural shape as the hand-written reference. Iterations
  committed: prompt slicing, tracker-adaptive cooldown waits, format
  discipline, exit-code-1 repro rule, stage-resume from prior session
  logs (`--resume-from`). Attempt 6 will run detached (nohup) with
  `--resume-from data/repair_sessions/hf_73a86c38bc_20260711T040705Z.json`
  once a major provider exits cooldown. Then: email Prem (checkpoint 1)
  → Phase 2 very-very-hard campaign (`--llm-roles Analyst Admin Support
  Ops Finance`) → pipeline on new findings → publish via `repair/pr.py`
  → email Prem (checkpoint 2).
- **Resume command:** re-read `docs/platform improvements/
  HEALTH_CHECK_AGENT_MISSION.md` + `CONTEXT.md` + `ARCHITECTURE_LOG.md`
  guardrails; then `.venv/bin/python scripts/run_repair.py --company
  acmecloud --list` and continue from the milestone above. Tests:
  `.venv/bin/python -m pytest tests/platform_mode/ -q` (dev branch: 203
  green). Campaigns: `.venv/bin/python scripts/run_sim_campaign.py
  --company acmecloud [--no-llm|--dry-run]`.
- **Tests already run this initiative:** platform suite 154→159→178→185
  green at each phase; classifier gold set (39 cases) green; three live
  campaigns vs AcmeCloud (`camp_f688345b32` shakeout, `camp_c1014c02ce`,
  `camp_c305c02583` — reports in health_reports: hc_0973390b75,
  hc_03599fe819, hc_9db69d4870); before/after eval gate on the fix branch.
- **Also real but not this PR:** bug #1 (ghost-table denial mislabel,
  FUTURE_IMPROVEMENTS #1) did not reproduce in 3 campaigns (stochastic
  LLM trigger; every analyze-with-AI turn generated valid SQL locally).
  Its specified fix + mocked repro is designed (ARCHITECTURE_LOG Entry 4
  decision tree) and can be a second PR on request. Two more recorded
  product-quality findings awaiting later fixes: typo'd metric words
  bypass the malformed-period gate (confident A4-paper garbage answer,
  camp_f688345b32), and the deterministic parser silently drops the
  out-of-role half of mixed two-part questions.
- **Needs Prem (non-blocking, flagged per plan):** classifier gold-set
  labels are provisional (labeled by construction/agent, not human) — please
  review `tests/platform_mode/fixtures/classifier_gold/` when it exists.
- **Known failures / repair notes:** none yet.

Historical note: the "DO NOT PUSH to GitHub" line at the bottom of this file
predates this initiative; CONTEXT.md §"GitHub access" explicitly authorizes
pushing this initiative's own fix branches and opening PRs (never merging).
Nothing else gets pushed.


**2026-07-08 (later) — RDS + Bedrock live, task def revision 3.** All 3
companies (acmecloud, medcore, finpilot) fully migrated to AWS RDS Postgres
(`nexusiq-platform-db`, one schema per company, ~468k rows total —
`NEXUSIQ_PLATFORM_PG_URL` secret wired into the task def). AWS Bedrock added
as a 5th LLM fallback tier (`BEDROCK_ENABLED=true` in prod, gated off by
default elsewhere) — IAM policy attached to `nexusiq-ecs-task-role`, code
path unit-tested, and confirmed reachable in principle (never organically
triggered in a live call since Groq/Gemini answer first, which is correct
fallback behavior). RDS locked back down after population: not publicly
accessible, no stray IP rules, only the ECS task security group can reach
port 5432. Live-verified with a real deterministic SQL query executed
against RDS (support ticket count) and a real RAG/LLM query (billing policy
question, answered by Groq → Gemini).

Also this session: retired `mcp_server/` (built for the dead single-tenant
demo, would have misrepresented current data — real Platform-Mode-aware MCP
is future work), rewrote the project README (Platform Mode as the primary
product, Mermaid architecture diagram, real screenshots, honest
limitations), rewrote the personal profile README and portfolio site
(`premsai-pendela.github.io` — was serving the *unmodified default Jekyll
theme* with placeholder Lorem-ipsum text; replaced with a real one-page
site), and produced a verified resume at `~/Dev/resume-2026-07-08/`
(resume.html + resume.pdf, one page, every claim checked against what's
actually live).

**2026-07-08 — Live on AWS.** Backend: ECS Fargate (`nexusiq-cluster` /
`nexusiq-api-service`) behind an ALB at `https://api.nexusiq-ai.com` (ACM
cert, ARM64 task def). Frontend: Next.js SSR on Amplify at
`https://master.d3dp95aawguyfq.amplifyapp.com`, auto-deploys on push to
`master` of the new public repo
[github.com/premsai-pendela/NexusIQAI-Platform](https://github.com/premsai-pendela/NexusIQAI-Platform).
Login → real company workspace → real SQL/RAG query verified end-to-end
through both live URLs. Old EC2 (`nexusiq-ai.com` root domain, `NexusIQ-AI`
repo) is untouched and still live — not yet cut over or decommissioned.
Full build/fix log: `~/Dev/interview/aws_learning_notes.md`. Still open:
cut the root domain over from EC2 once ready, then decommission EC2;
CloudFormation IaC capture of the final architecture.

**2026-07-07 — Agentic Analyst Final Run complete.** Ask Analyst now routes
every question explicitly (clarification gate, repeat-question choices,
deterministic/SQL/RAG/mixed/planner, honest refusals and degraded mode, all
traced); an Admin/CEO Analyst Health Check agent analyzes traces+feedback and
recommends fixes (Review page → Health Check panel); the data layer is
PostgreSQL-scale (35 tables, ~468k rows, 3 company schemas, 18 months) with
SQLite mirrors for offline tests; 390 generated employees + 15k historical
traces back the scale story; a 100-concurrent load test passes with zero LLM
calls; Cerebras is wired as the last cloud fallback tier. Full evidence:
`docs/Current NexusIQ docs/AGENTIC_ANALYST_FINAL_RUN_REPORT.md`.

Regenerate scale artifacts (reproducible): `python -m
nexus_platform.scale.generator` (+ optional NEXUSIQ_PLATFORM_PG_URL),
`python -m nexus_platform.brain_builder`, `python -m
nexus_platform.scale.population`, `python -m nexus_platform.scale.history`.
Load test: `python scripts/load_test.py --n 100` (needs the API running).

This repo is the **NexusIQAI Platform** implementation: a prototype
multi-company AI data analyst built on the NexusIQ recruiter-proof agent
stack. The control workspace with the full plan and milestone history lives
at `~/Dev/NexusIQAI-Website/ACTIVE_HANDOFF.md` — read that first when
resuming; this file covers repo-local facts only.

## What this repo contains

- **Platform Mode** (the only product surface now): `nexus_platform/`,
  `api/routes/platform.py`, `web/src/app/platform/*`,
  `data/demo_companies/`. See `docs/Current NexusIQ docs/PLATFORM_MODE.md` for architecture.

**2026-07-08 — Legacy single-tenant demo retired.** The old recruiter-proof
surface (Streamlit UI, `/api/v1/query`, `/ask` `/context` `/how`
`/reliability` pages, the 52-doc single corpus) was deleted from this repo
ahead of the AWS cloud migration — an identical copy still lives in
`~/Dev/NexusIQ-recruiter-proof`, untouched. This repo is Platform Mode only
from here on. See `~/Dev/interview/aws_learning_notes.md` for the full
cleanup + migration log.

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
See `docs/Current NexusIQ docs/NEXUSIQAI_FULL_BUILD_REPORT.md` and
`docs/Current NexusIQ docs/RECRUITER_PROOF_SUMMARY.md`. Milestone history:
`~/Dev/NexusIQAI-Website/ACTIVE_HANDOFF.md`.

Post-final polish (2026-07-07): fixed the "Q1 to Q4 bar graph" parsing
bug so period ranges render a quarterly series, added Ask Analyst recent
analysis restore in localStorage, and changed "report this answer" to ask
for a user comment while attaching the trace automatically for Admin review.

Second polish pass (2026-07-07): fixed disjoint period selections like
"Q2 and Q4" so Ask Analyst returns both selected periods with the requested
line/bar/table chart instead of collapsing to Q2; correction follow-ups such
as "sorry I mean Q2 and Q4" stay deterministic. Login now warns on empty
email/password. Admin Review now has New reviews, New complaints, Reviewed,
and Resolved queues, plus a "mark new" undo for accidental review clicks.

Third polish pass (2026-07-07): added cross-company name clarification before
any dashboard, repeat, SQL, RAG, or LLM route. If an AcmeCloud user asks for
MedCore/FinPilot data by name, Ask Analyst now returns
`cross_company_scope_clarification`, records a denied/no-data-read trace, and
offers the current-company version instead of silently answering with the
current tenant's data. Ask UI now renders clarification choices for any
payload with `platform.clarification`, including access-boundary
clarifications. Verification: red test reproduced the prior MedCore-as-Acme
answer; fixed test passed; `pytest tests/platform_mode -q` 154 passed;
`pytest tests/ -q` 427 passed + 41 subtests; `npm run lint`; `npm run build`.

DO NOT PUSH to GitHub without Prem's explicit go-ahead.
