# NexusIQAI — Full Build Report

Written 2026-07-07, after final-pass implementation and verification. This is
the codebase-grounded record of what NexusIQAI is, how it got here, and what
each piece proves. Companion docs: `PLATFORM_MODE.md` (architecture
reference), `RECRUITER_PROOF_SUMMARY.md` (interview-ready condensation).

---

## 1. Executive overview

NexusIQAI is a prototype **governed AI data analyst platform**. Three
synthetic companies (AcmeCloud Analytics, MedCore Systems, FinPilot Ops) have
registered demo employees with roles (Admin/CEO, Analyst, HR, Finance,
Support, Ops). An employee logs in, lands in their company's workspace —
whose "brain" (SQLite warehouse + ChromaDB document index + catalogs) is
prebuilt from a local data folder — and asks questions in natural language.

Answers route through three tiers:

1. a **deterministic analyst layer** (template SQL for 15 business-metric
   families — no LLM),
2. a **multi-agent SQL/RAG fusion engine** (inherited from recruiter-proof
   NexusIQ) for open questions,
3. **safe refusals** when the question targets data outside the caller's role.

Every answer carries evidence (SQL, citations), a chart or dashboard when
useful, exports, an access decision, and a saved trace that the company's
Admin/CEO can review. Employees file feedback/access requests linked to
traces; admins triage them. The problem it demonstrates: how to put an LLM
analyst on company data **without** giving up governance, cost control,
auditability, or reliability.

## 2. How the product evolved

- **Recruiter-proof NexusIQ (base repo)** — a single-tenant BI system:
  fusion agent routing across SQL (Supabase), RAG (52-doc Chroma corpus),
  and live web scrapers; LangGraph production harness; evals; cost ledger;
  traces; a polished Next.js front.
- **Platform mode (this repo, waves 1-2)** — copied the base wholesale, then
  added a multi-company layer on top without rewriting the engine: registry,
  sessions, per-(company,role) agent contexts, 4-layer access enforcement,
  brains, memory, feedback, admin trace review, charts, dashboards, exports,
  NVIDIA fallback tier.
- **Final showcase pass (this report's wave)** — deterministic analyst layer,
  structured-intent session memory, provenance exports, route/model
  transparency, correctness fixes found through live QA.

The legacy single-tenant surface still works (same repo, `/` routes,
318-of-347 tests are its suite + shared code) — platform mode did not break it.

## 3. Final architecture

```
web/ (Next.js 16, React 19)
  src/app/platform/            login · workspace · ask · feedback · admin
  src/components/              PlatformShell (session, nav, bot) · Mascot
                               ChartView (SVG, CSV/XLSX/PNG) · DashboardView
  src/lib/platform.ts          API client; token in localStorage; company/role
                               never sent by the client

api/ (FastAPI)
  routes/platform.py           login, workspace, query, brain rebuild (admin),
                               feedback + review, traces, XLSX export
  (legacy routes untouched)

nexus_platform/ (the platform layer)
  registry.py                  3 companies, 9 employees, hashed demo passwords
  auth.py                      HMAC session tokens → AccessContext dependency
  access_policy.py             deny-by-default role policies + intent gate
  contexts.py                  DataContext per (company, role): own SQLite URL,
                               own Chroma collection, table allowlist, dept filter
  deterministic.py             intent parser + template SQL (final pass)
  dashboard.py                 role-filtered KPI/chart boards (no LLM)
  charts.py                    SQL rows → chart specs
  query_service.py             the pipeline (see §4)
  store.py                     SQLite: memory turns, feedback, traces
  brain_builder.py             folder → company.db catalog + Chroma + artifacts
  seed/                        employees.json + synthetic data generator

agents/ (inherited engine, minimally patched)
  sql_agent.py                 + per-context engine, SQLite schema/prompt,
                               AST table allowlist
  rag_agent.py                 + department filter on vector/hybrid/BM25,
                               shared embedding model
  fusion_agent.py              + platform-aware routing prompt, NIM fallback
  production_harness.py        (unchanged) step-traced execution

utils/llm_gateway.py           + NVIDIA NIM streaming client
data/demo_companies/<slug>/    company.db · docs/<dept>/*.md · brain/ (runtime)
data/platform.db               memory/feedback/traces (runtime, gitignored)
```

## 4. End-to-end execution flow

`POST /api/v1/platform/query` with a session token:

1. **AccessContext** resolved server-side from the token (employee → company
   → role policy). Client-supplied company/role is never trusted.
2. **Dashboard check** — "give me a dashboard" → `dashboard.py` runs only the
   canned SQL blocks whose tables are in the role allowlist. No LLM.
3. **Deterministic layer** — recent session turns are loaded; the last stored
   intent (if any) seeds follow-up merging. `parse_intent` extracts metric,
   period(s), comparison, grouping, top-N, output type. If a template
   supports it: role check → template SQL on the company SQLite → formatted
   answer + chart spec. Trace route `deterministic_sql_template`,
   `llm_skipped: true`. Refusal if tables fall outside the role.
4. **LLM engine fallthrough** — for open questions: employee session history
   is seeded into the shared (company, role) fusion agent under a lock,
   the harness resolves follow-ups, routes SQL/RAG, cross-validates, and the
   platform layer re-filters citations by department before returning.
5. **Every path** saves a trace (see §9) and a memory turn, then returns
   answer + evidence + chart/dashboard + platform metadata (trace id, route,
   access decision, model or `llm_skipped`, follow-up suggestions).

## 5. Access control — where each layer lives

| Layer | File | Mechanism |
|---|---|---|
| 1. Prompt | `agents/sql_agent.py::_get_sqlite_schema_info` | generation prompt only describes allowed tables |
| 2. AST | `agents/sql_agent.py::_validate_query` | sqlglot walk; any non-allowlisted table → `ACCESS_DENIED_TABLE` before execution |
| 3. Retrieval | `agents/rag_agent.py` | Chroma `where` department filter on vector + hybrid queries AND at BM25 index build |
| 4. Response | `nexus_platform/query_service.py::_filter_sources` | citations re-checked against allowed departments |
| Deterministic | `nexus_platform/deterministic.py::execute` | required tables ⊆ allowlist or refuse; templates contain no user text |
| Dashboards | `nexus_platform/dashboard.py` | per-block table requirement + regex re-check of canned SQL |
| Stores | `nexus_platform/store.py` | every read requires company (and employee where relevant) — no unscoped path |
| Sessions | `nexus_platform/auth.py` | token carries only email; company/role re-resolved server-side each request |

Company isolation: separate SQLite file + separate Chroma collection per
company; traces/feedback/memory rows all carry company and are only ever
queried through company-scoped helpers.

## 6. Deterministic LLM-call reduction

**Before final pass:** dashboards were deterministic; the base engine already
avoided LLM calls for cached and template-answerable cases (its cost-ledger
work).

**Final pass added** `deterministic.py`: 15 metric families
(revenue/orders/AOV/customers/MRR/invoice amount/count/overdue/tickets/CSAT/
resolution hours/headcount/terminations/attrition) × periods (quarters,
months, FY2024) × groupings (region/product/category/segment/plan/department/
priority/status/month/quarter) × comparisons × top-N. Parsing is
keyword/regex; SQL is template-only (user text never enters SQL — periods
come from a fixed table, groupings from a fixed map).

**Where it shows:** traces record `route: deterministic_sql_template,
llm_skipped: true, template_id`, the UI shows a "deterministic · no LLM"
pill, and `tests/platform_mode/test_deterministic.py` runs a 5-turn session
with the agent factory monkeypatched to throw — proving zero LLM touches.

**Why it matters:** free-tier providers saturate mid-demo (observed live with
NVIDIA NIM: `ResourceExhausted (234/48)`); the demo path no longer depends on
any provider being up, and steady-state cost for common questions is zero.

## 7. Model routing and degraded mode

Chain (per task type, in `sql_agent.py` / `rag_agent.py` / fusion
`_gateway_models`): **Gemini 2.5 Flash → Groq Llama 3.3 70B → NVIDIA NIM
deepseek-v4-flash → local Ollama**. The quota tracker applies per-model
cooldowns on failure; the gateway ledger records every attempt.

NVIDIA specifics: the NIM client (`utils/llm_gateway.py`) uses **streaming**
because the free tier hangs non-stream requests when saturated but streams
error events immediately — turning a 45s stall into a bounded fail-over.
Verified live both ways: a 6.4s successful answer, and a saturation error
that fail-fasted into a 5-minute tracker cooldown.

LLM-path traces now include `model_used` and `provider_failures` (model +
truncated error). Codex/Claude Code are development tools here, not backend
providers. Cerebras/OpenRouter/Mistral/SambaNova were considered per the
final-pass file and deliberately skipped: no keys on hand (signup requires
user input) and the deterministic layer solves demo reliability more
directly.

## 8. Session memory

`memory_turns` (SQLite) per (company, employee, session): question, resolved
question, answer summary, source type, chart type, refused flag, and — from
the final pass — `intent_json` (metric, period, comparison, grouping, top-N,
output, follow-up kind), `sql`, `route`, `tables_json`.

Follow-up handling: deterministic merge first ("what about Q4?" → period
swap; "compare that with Q3" → comparison add; "show that as a bar chart" →
re-render; "by region" → regroup). Policy is re-applied on every merged
intent, so a denied metric stays denied through any follow-up. Open-question
follow-ups still use the engine's LLM rewrite with the employee's history
seeded under a lock and always cleared.

Isolation is structural (keys include company + employee + session) and
tested: same session id across employees or companies inherits nothing.

## 9. Traces, feedback, admin review

Trace payload: employee (+name), company (+name), role, session, timestamps,
question, resolved question, follow-up flag, memory turns used, parsed
intent, access-policy snapshot (tables + departments), access decision,
denial reason, route, template id / model used / `llm_skipped` /
provider_failures, SQL, tables touched, citations (file + department), chart
info, latency, and the engine's step trace on LLM paths.

Employees can open their own traces; Admin/CEO list and open same-company
traces with employee/date filters (cross-company returns 404 — existence is
not revealed). Feedback (5 categories incl. access requests, optional linked
trace, status new/reviewed/resolved) flows to the same-company admin queue;
the refusal card and "report this answer" file it with the trace attached.

`scripts/inspect_platform_traces.py` audits every saved trace for restricted
tables in SQL, restricted departments in citations, and company mismatches —
clean across all runs (last audit: zero findings).

## 10. Dashboards, charts, exports

- `charts.py`: SQL rows → deterministic chart spec (kpi/bar/line/table);
  the frontend renders hand-drawn SVG in the design language.
- `dashboard.py`: role-filtered KPI row + up to 4 charts, canned SQL only,
  "show the N queries" in the UI.
- Exports: CSV (client), PNG (SVG→canvas), XLSX (openpyxl endpoint) — the
  XLSX includes a **Provenance** sheet (question, employee, company, role,
  access scope, trace id, timestamp, role-filter note). Exports serialize
  exactly the rows the answer displayed; refused answers render no chart and
  therefore expose no export surface.

## 11. Frontend and product design

Pages: login (demo accounts listed, honest prototype labels), workspace
(access card, brain status, role-filtered tables/docs, admin rebuild with
visible build log), ask analyst (conversation, pills for confidence and
"deterministic · no LLM", evidence accordion, Access & trace accordion with
route/model, follow-up chips, refusal cards with in-access suggestions and
one-click access request), feedback form, admin review (feedback triage +
trace explorer + trace detail). The Nexus mascot gives page-aware guidance,
cycles tips on click, and is mutable/dismissable. Visual language inherited
from recruiter-proof: cream canvas, forest-green accent, serif display,
mono labels.

Screenshots (all live captures): `Screenshots/platform/` — login, workspace,
ask-chart, ask-denied, admin, trace-detail, dashboard, hr-dashboard-refusal,
det-followup, det-charts, det-compare.

## 12. Verification (final state)

| Check | Result |
|---|---|
| Backend tests | **347 passed** (82 platform + legacy suite), 41 subtests |
| Frontend lint | clean |
| Frontend build | clean (13 static routes) |
| Live LLM smoke | 7/7 across 3 companies (`scripts/platform_smoke.py`) |
| Deterministic flow | 5-turn session with agent path booby-trapped — green |
| Trace leak audit | zero findings across all saved traces |
| Policy matrix | `scripts/check_access.py --matrix` sane for 7 roles × 6 probes |
| Browser QA | login → ask → follow-up → compare → chart → dashboard → refusal → feedback → admin review → trace detail |

## 13. Notable bugs found and fixed (all discovered by verification)

1. **BM25 boundary leak** — keyword index ingested all chunks regardless of
   role; fixed at index build + test asserting restricted text absent.
2. **Platform edits broke 24 legacy contract tests** — tests build bare
   agents via `__new__`; fixed with isinstance/getattr guards.
3. **Hydration redirect regression** — lint-driven useSyncExternalStore
   change made /ask bounce to /workspace on the empty server snapshot;
   caught in headless QA.
4. **Comparison direction read backwards** — "Q3 vs Q4 — down 47%" while Q4
   was higher; sign was computed from mention order. Fixed to chronological
   framing; verified live.
5. **`.env` was a symlink into another repo** — an append corrupted the
   shared file's last line; restored (backup kept) and replaced with a
   repo-local real file.
6. **NIM non-stream hangs** — switched to streaming for bounded fail-over.
7. **Month-trend summary claimed "highest" from the first row** — fixed to
   true peak.

## 14. Magic moments (what to show off)

- Kill every provider (or just demo offline): revenue, comparisons,
  breakdowns, dashboards, follow-ups, refusals all still answer instantly —
  with traces honestly labeled `llm_skipped`.
- Ask the same question as Analyst and HR: mirrored allow/deny with the
  refusal naming the restricted area and offering in-access alternatives.
- Open the XLSX Provenance sheet: the export carries its own audit trail.
- The admin opens the exact trace behind an employee's access request.
- `inspect_platform_traces.py`: one command proving no leak ever reached a
  stored answer.

## 15. Honest limitations (say these out loud)

Demo registry login (hashed demo passwords, not SSO/OIDC); synthetic data
only; company isolation within one app process (separate stores, not
enterprise tenancy); employees read-only; deterministic parser is
keyword-based (UX layer — enforcement is AST + retrieval filters); NIM free
tier is unstable by nature; platform mode runs locally (legacy surface has
the Docker/EC2 story); XLSX only on platform surface.

## 16. Run and verify

```bash
cd ~/Dev/NexusIQAI
source .venv/bin/activate
python -m nexus_platform.brain_builder          # first run only
NEXUSIQ_PREWARM_LIVE=false uvicorn api.main:app --port 8000
cd web && npm install && npm run build && npx next start -p 3000
# http://localhost:3000/platform

python -m pytest tests/ -q                       # 347 tests
python scripts/platform_smoke.py                 # live LLM scenarios
python scripts/inspect_platform_traces.py        # leak audit
python scripts/check_access.py --matrix          # policy dry-run
```

Demo question list (all deterministic — provider-proof):
"What was total revenue in Q3 2024?" · "What about Q4?" · "Compare that with
Q3" · "Show that as a bar chart" · "by region" · "Top 5 products by revenue"
· "monthly revenue trend" · "How many overdue invoices do we have?" ·
"average order value in Q2" · "ticket volume by priority" · "Give me a
dashboard" · (as HR) "What is our attrition rate?" · (as Analyst, refused)
same question.

## 17. Resume interpretation

Safe to claim: everything in `RECRUITER_PROOF_SUMMARY.md` §"Resume-ready
bullets" — each maps to code + tests here. Needs careful wording: "multi-
tenant" (say *multi-company prototype isolation*, not enterprise tenancy);
"production" (the legacy surface is deployed; platform mode is local);
"eval-gated CI" (inherited from the base repo). Do not claim real users,
real data, or SSO.
