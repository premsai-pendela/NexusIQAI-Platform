# NexusIQAI — Agentic Analyst Final Run Report

Date: 2026-07-07 · Repo: `/Users/nagapremsaipendela/Dev/NexusIQAI`
Spec: `NexusIQAI-Website/docs/FABLE_NEXUSIQ_AGENTIC_ANALYST_FINAL_RUN.md`

This run turned Ask Analyst from a deterministic answer bot into an agentic,
hard-to-fool analyst; added an Admin/CEO Analyst Health Check agent; and
replaced the toy data footprint with a credible mid-market scale story
(PostgreSQL, generated employees, historical traces, load testing).

---

## 1. Route architecture

Every question now gets an explicit route decision before anything answers
(`nexus_platform/orchestrator.py`, consumed by `query_service.run_query`):

```
dashboard | repeat_question_choice | repeat_used_previous | clarification |
llm_planner | sql_plus_rag | deterministic_sql_template | sql_agent |
rag_agent | access_refusal | degraded_mode | no_data
```

- The decision is cheap (regex/keyword features, zero LLM) and is recorded in
  every trace (`route`, `engine_route`, `route_reason`) for Admin review and
  the Health Check agent.
- The existing LangGraph/production-harness path (`agents/fusion_graph.py`,
  `agents/production_harness.py`) is **preserved** as the executor for
  sql_agent / rag_agent / sql_plus_rag / llm_planner — no parallel
  orchestration layer was invented. Mixed and planner questions are forced
  through it with `force_source="sql_rag"`; insight questions get an analyst
  framing (what happened / drivers / evidence / uncertainty / follow-up,
  never invent numbers).

## 2. Deterministic safety gate + clarification behavior

`find_clarification` (orchestrator) stops every partial parse before it can
become a confident answer. Each clarification returns one short question and
2–3 **full, parseable questions** as choices (clicking a choice resolves):

| Attack | Behavior |
|---|---|
| `show market by invoice` | clarification (unclear metric, invoice-flavored choices) |
| `revenue for q2 and a4` | clarification (malformed period, Q4-typo guess offered) |
| `revenue in q1 and q3` | clarification (only-those vs Q1–Q3 range) |
| `only q1 and q3 from q1 to q4` | clarification (contradictory) |
| `pie chart revenue over time` | clarification (pie needs categories) |
| `make it better` | clarification (role-safe suggestions) |
| `analyze everything` | clarification (role-scoped starting points) |
| typo salad (`q1 and q3 related to total invoice and market…`) | clarification |

Deliberate semantics (documented decisions):
- `q2 through q4` = the Q2..Q4 quarterly series exactly (was full-year before
  this run — fixed); a range phrase is treated as clear, unlike bare "and"
  selections of non-adjacent quarters.
- Metric-less corrections with session context ("sorry I mean q2 and q4?")
  inherit the previous intent instead of re-clarifying.
- Unqualified metrics ("revenue by month") default to FY 2024 — never a
  silent all-time aggregate over the 18-month history.

## 3. Repeated-question behavior

Same normalized question again in one session → `repeat_question_choice`
card (never a silent duplicate): **Use previous answer** (returns stored
answer + chart + prior trace id, zero recomputation), **Rerun on current
data**, **Analyze with AI** (forces the LLM planner). Refused questions are
always re-refused — repeats never offer "use previous" around a boundary.
API: `repeat_action` on `POST /platform/query`. Memory turns now persist
`trace_id` and `chart_json` to make reuse honest.

## 4. Chart intelligence

Bar / line / table / KPI / **pie** (new SVG pie with legend + CSV/XLSX/PNG
export). Pie renders only for categorical breakdowns; pie-over-time or
pie-of-a-scalar becomes a clarification with concrete alternatives. Found by
self-attack: "pie chart revenue over time" previously rendered a silent KPI —
fixed + regression-tested.

## 5. Admin/CEO Analyst Health Check agent

`nexus_platform/health_check.py` — an analyst of the analyst. Deterministic
analyzers over the company's traces + feedback (runs in <0.3s over ~3,000
traces), each finding classified by fix ownership:

`needs_admin · needs_employee_clarification · needs_routing_fix ·
needs_sql_rag_fix · needs_chart_fix · needs_ui_fix ·
needs_access_policy_review · data_gap · provider_ops · likely_resolved ·
suspiciously_resolved · valid_access_denial`

It detects: HIGH-confidence answers reported wrong, suspiciously-resolved
feedback (degraded/refused/never-recomputed answers closed as resolved),
repeats answered without choices, clarification misses (replays the current
gate over history), misrouting in both directions (LLM↔SQL, SQL-only answers
to policy+numbers questions), citation-less RAG answers, silent wrong chart
types, malformed charts, refusal patterns (one-off = explicitly
`valid_access_denial`, clusters = access-policy/UX review), provider
failures/degraded volume, clustered unanswerable topics (= data gaps), and
per-employee friction. Every finding carries evidence trace ids, a concrete
recommendation, and (where applicable) a suggested eval case. Duplicate
findings coalesce with occurrence counts.

Optional AI executive summary uses the reasoning-tier gateway (health checks
run rarely) and degrades honestly (`providers_unavailable`) — verified live
(`ok (Groq)`).

API: `POST /platform/admin/health-check`, `GET /admin/health-reports[/{id}]`
(Admin/CEO-only, company-scoped, 404 across companies — tested). UI: Health
Check panel on the Review page with severity/classification chips,
expandable recommendations, suggested evals, and click-through to trace
detail.

**Health Check self-attack**: 22 adversarial fixture tests
(`tests/platform_mode/test_health_check.py`) covering every fixture family in
the spec — including must-NOT-flag cases (correct refusals, properly
re-verified resolved feedback, healthy repeat flows, clean deterministic
answers). Running it over the generated corpus also caught a **real parser
bug** ("What are the SLA targets for urgent tickets?" would have been
answered as a deterministic ticket count — now routed sql_plus_rag,
regression-tested) — the self-improving loop working as designed.

## 6. Company data expansion + PostgreSQL

- **PostgreSQL 15** (local Homebrew, database `nexusiqai_platform`, one
  schema per company; `NEXUSIQ_PLATFORM_PG_URL` switches the whole platform —
  DataContext/SQL agent, deterministic templates, dashboards — via
  `nexus_platform/db.py`). SQLite mirrors (identical schema/rows) remain the
  zero-dependency fallback so tests run offline.
- **35 tables per company** across org/customers/product/sales/usage/finance/
  procurement/support/ops/marketing; **145k–166k rows per company**
  (468k total), **18 months** of history (Jul 2023–Dec 2024) with growth +
  Q4 seasonality. Verified: `test_postgres_schema_scale` (30+ tables, 100k+
  rows per schema) and `test_postgres_matches_sqlite_answers` (same question,
  same number on both backends).
- Access policy is now **area-based metadata** (`TABLE_AREAS`) covering all
  35 tables; role semantics preserved (HR still sees zero revenue tables —
  tested).
- **Document corpus**: ~171 files and ~1,065 indexed chunks per company —
  markdown policies/runbooks/playbooks/monthly sales+ops+CSAT reports/account
  briefs, real **PDFs** (18 monthly finance summaries + 6 board updates via
  reportlab), CSV exports generated from the same rows, JSON ticket exports,
  HTML newsletters. Brain builder now ingests md/txt/html/json/csv/pdf.
  Documents and SQL tell one consistent story (reports are computed from the
  generated rows).

## 7. Generated employees + curated login

- `nexus_platform/scale/population.py`: **139 / 102 / 149** generated
  employees (acmecloud/medcore/finpilot) with department, team, manager,
  platform role, and salted-hash credentials (deterministic prototype rule
  `gen-<slug>-<n>` so the load test can authenticate; no secrets stored).
  Registry authentication falls through to the generated population;
  generated employees can never be Admin/CEO.
- The login UI shows only the curated demo accounts plus an honest note about
  the generated backend population (screenshot: `login-curated.png`).

## 8. Historical trace/feedback corpus

`nexus_platform/scale/history.py`: **15,000 traces + 522 feedback** rows
across the three companies over 90 days, generated from the employee
population with realistic route mix (deterministic 55%, RAG, SQL-agent,
clarifications, correct refusals, healthy repeat flows, planner, degraded +
provider failures), role-consistent (a generated trace never touches tables
outside its role policy — tested), with linked feedback including
deliberately suspicious resolutions for the Health Check to catch. Rerunnable
(gen_-prefixed ids replace, not duplicate — tested).

## 9. Concurrency/load story

`scripts/load_test.py` — logs in ~100 generated employees across all three
companies and fires **100 simultaneous questions**:

```
success 100/100 (100%) · wall 0.17s · ~600 q/s
latency p50 0.088s · p95 0.149s · max 0.162s
LLM calls used: 0 (deterministic-first by design)
```

The cost story is architectural: core analytics (deterministic/dashboard/
refusal/clarification/repeat) never call a model, so 100 concurrent employees
are a database problem, not a quota problem. Report saved to
`reports/load_test_report.json`. Queue/worker (Redis) and Kubernetes are
documented as the production path only — not claimed.

## 10. Provider fallback + Cerebras

- Gateway order: **Gemini → Groq → NVIDIA NIM → Cerebras → Ollama** (Cerebras
  tier inserted centrally via `insert_cerebras_fallback`; no-op without a
  key, wired into fusion routing/rewrite, SQL-agent complexity tiers, RAG
  reasoning models, and the Health Check summary).
- Cerebras catalog **verified live 2026-07-07**: `zai-glm-4.7`,
  `gemma-4-31b`, `gpt-oss-120b` (the llama models in older docs are gone).
  Defaults: fast=`gemma-4-31b` (live probe returned `CEREBRAS-OK`),
  reasoning=`gpt-oss-120b` (valid; 429 free-tier saturation at probe time —
  the quota tracker cooldown absorbed it, which is the designed behavior).
  Env-overridable; empty env values no longer erase defaults.
- Degraded mode: engine/provider failure → honest low-confidence message with
  role-safe deterministic suggestions, `degraded_mode` route + provider
  failures in the trace; deterministic families keep answering (tested with
  every provider dead).

## 11. Verification evidence

- **Backend**: 423 tests green (`python -m pytest tests/`) — 153 platform
  (30-test agentic matrix written before implementation, 22 Health Check
  self-attack, 9 scale/PG, plus existing suites) + 270 legacy recruiter-proof
  incl. LangGraph/harness. 8 Cerebras wiring tests (mocked).
- **Frontend**: `npm run lint` ✓, `npm run build` ✓.
- **Ask Analyst self-attack**: all 15 attack cases from the spec produce
  clarification/refusal/choice/planner routes — zero confident answers to
  ambiguous input (2 failures found during the loop → fixed → regression
  tests added).
- **Trace leak audit**: `scripts/inspect_platform_traces.py` — 12,158 traces,
  zero cross-boundary findings. Policy matrix (`scripts/check_access.py
  --matrix`) sane.
- **Live smoke** (tiny, quota-safe): 2 deterministic (incl. pie), 1
  clarification, 1 repeat + use_previous, 1 live SQL+RAG mixed answer citing
  `discount_policy.md` from the new corpus, 1 refusal, 1 health check with AI
  summary, 1 Cerebras probe.
- **Browser QA screenshots** (`Screenshots/platform/`): `login-curated.png`,
  `ask-clarification.png`, `ask-clarified-answer.png`, `ask-pie.png`,
  `ask-repeat-choice.png`, `ask-used-previous.png`, `admin-health-check.png`,
  `admin-health-finding.png`.

## 12. Honest remaining limits

- Prototype auth (salted-hash demo registry, not SSO); generated-employee
  passwords follow a documented deterministic rule by design.
- PostgreSQL is local (Homebrew); Docker Compose/Kubernetes remain a
  documented path, not a deployed claim. SQLite mirrors stay authoritative
  for offline tests.
- No async worker queue was added — FastAPI + bounded executor is sufficient
  at the proven load because the hot paths are LLM-free; the queue design is
  documented, not built.
- Cerebras reasoning tier was rate-limited (free tier) at probe time; fast
  tier verified live. Free-tier saturation is treated as a normal
  operational state.
- The Health Check agent recommends fixes and generates eval cases; it does
  not self-modify code.
- Historical corpus is synthetic; its purpose is Health Check pattern
  analysis and scale credibility, not real usage claims.
