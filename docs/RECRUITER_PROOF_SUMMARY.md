# NexusIQAI — Recruiter / Interview Proof Summary

## One-sentence positioning

> NexusIQAI is a governed multi-company AI data analyst platform: employees log
> in to their company's prebuilt data brain and ask natural-language questions
> that route through role-scoped deterministic SQL templates, a multi-agent
> SQL/RAG engine, and a quota-aware model gateway — every answer carrying its
> SQL, citations, chart, access decision, and a reviewable trace.

## Resume-ready bullet candidates

Pick 3-5; every claim below is backed by code and tests in this repo.

1. Built a multi-tenant AI data analyst platform (FastAPI + Next.js) where
   role-based access is enforced at four layers: SQL prompt schema subsetting,
   sqlglot AST table allowlists, ChromaDB metadata filters (vector, hybrid,
   and BM25 paths), and response-level citation filtering.
2. Designed a deterministic analyst layer that answers 15 business-metric
   families (revenue, orders, invoices, tickets, HR) from template SQL with
   zero LLM calls — keeping the product fully functional when all model
   providers are rate-limited, with traces recording `llm_skipped: true`.
3. Implemented multi-turn session memory with structured intent storage:
   follow-ups like "what about Q4?", "compare that with Q3", and "show that
   as a bar chart" resolve deterministically from stored intent, with access
   policy re-applied every turn so memory can never widen access.
4. Built a quota-aware model gateway routing across Gemini, Groq, and NVIDIA
   NIM (streaming client) with per-model cooldowns, fallback chains, and a
   local Ollama backstop; traces record provider failures and fallback routes.
5. Shipped an enterprise-style audit loop: per-employee traces (question,
   rewrite, route, SQL, citations, access decision, memory turns), company-
   scoped Admin/CEO trace review with employee/date filters, and a feedback
   queue with linked-trace triage.
6. Wrote a trace-leakage auditor and access-policy simulator; audits across
   all saved traces prove zero cross-role SQL, citations, or cross-company
   reads.
7. Delivered role-aware multi-chart dashboards and provenance-stamped exports
   (CSV / styled XLSX with question, role, access scope, trace id / PNG).
8. 347-test pytest suite (including 82 platform tests: AST denial, RAG
   boundary, memory isolation, deterministic families with the LLM path
   booby-trapped), plus live smoke scenarios across three synthetic companies.

## Interview talking points (the hard decisions)

1. **Boundary baked into agent instances, not request filters.** Each
   (company, role) pair gets its own DataContext with its own SQLite engine,
   Chroma collection, table allowlist, and department filter. A request
   cannot widen what the agent instance can see — safer than per-request
   filtering under concurrency.
2. **BM25 leak found and fixed.** The keyword index originally ingested the
   whole collection; restricted chunks would have leaked through hybrid
   search. Fixed by applying the role filter at index build, with a test
   asserting restricted text never enters the Analyst's BM25 corpus.
3. **Deterministic-first routing as a cost/reliability strategy.** Intent
   parsing → template SQL answers common analytics without any model call;
   the LLM is reserved for genuinely open questions. Free-tier providers
   saturate in demos — this is what makes the demo un-killable.
4. **Memory that can't escalate.** Stored intent (metric/period/grouping) is
   re-authorized on every turn; a refused HR question followed by "what
   about Q4?" re-refuses deterministically. Tested cross-employee and
   cross-company.
5. **Streaming as a fail-fast mechanism.** NVIDIA NIM's free tier hangs
   non-stream requests when saturated but streams an error event instantly —
   so the client uses streaming purely to get bounded fallback latency.
6. **Comparison-direction bug caught by looking at the screenshot.**
   "Compare Q3 vs Q4" computed sign from mention order and read backwards;
   fixed to chronological framing. Lesson: verify with live behavior, not
   just green tests.
7. **Hydration regression from a lint fix.** Switching to
   useSyncExternalStore made the auth redirect fire on the empty server
   snapshot, bouncing /ask to /workspace. Caught in headless browser QA.
8. **Honest prototype boundaries as a feature.** Demo registry (not SSO),
   synthetic data, single-app isolation — labeled in the UI and README, which
   is exactly what makes the rest of the claims credible.

## What was built when (do not overclaim)

**Existed before platform mode (recruiter-proof NexusIQ base):**
multi-agent SQL/RAG/web fusion engine, LangGraph production harness, sqlglot
read-only SQL validation, evals + golden cases, cost ledger/quota tracker,
Langfuse-style tracing, ChromaDB pipeline, Next.js design system + mascot.

**Platform implementation added (this project, pre-final-pass):**
multi-company registry + HMAC sessions, per-(company,role) agent contexts,
4-layer access enforcement, company brains + Admin rebuild, per-employee
session memory + LLM follow-up rewrite, charts, role-filtered dashboards,
feedback + admin trace review, CSV/XLSX/PNG exports, NVIDIA NIM fallback
tier, 3 synthetic companies with data generators, audit tooling.

**Improved during final pass:**
deterministic analyst layer (15 metric families, template SQL, LLM skipped),
structured intent memory + deterministic follow-up merging, provenance sheet
in XLSX exports, route/model transparency in the UI, follow-up suggestion
chips, chronological comparison framing, human-readable rewrite labels.

**Verified during final pass:**
347 backend tests, frontend lint + build, 7/7 live LLM smoke across three
companies, trace-leakage audit clean, 5-turn no-LLM follow-up flow with the
agent path booby-trapped, browser QA with screenshots in
`Screenshots/platform/`.

**Still prototype / not claimed:**
production SSO/tenant isolation, real customer data, cloud deployment of
platform mode, XLSX for the legacy surface, NIM free-tier stability.

## Strongest demo script (~3 minutes)

1. `/platform` — click `analyst@acmecloud.test` (demo registry, honest label).
2. Workspace: role access card, tables/documents visibly filtered (no HR).
3. Ask: "What was total revenue in Q3 2024?" → instant, **deterministic ·
   no LLM** pill, KPI card, SQL under Evidence.
4. "What about Q4?" → follow-up chip shows the resolved intent; instant.
5. "Compare that with Q3" → chronological comparison + bar chart; download
   XLSX and show the Provenance sheet.
6. "What is our attrition rate?" → calm refusal naming the restricted area,
   in-access suggestions, one-click access request.
7. "Give me a dashboard" → role-filtered KPI/chart board; "show the N
   queries".
8. Sign in as `admin@acmecloud.test` → Review: the access request with linked
   trace; open it — route, SQL, access policy snapshot, memory turns, denial
   reason.
9. Close with `scripts/inspect_platform_traces.py` — zero leaks across all
   saved traces.

## Stack demonstrated

Python, FastAPI, SQLAlchemy/SQLite, sqlglot AST analysis, ChromaDB +
sentence-transformers, multi-agent orchestration (LangGraph harness),
deterministic NL→SQL templates, model routing/fallback (Gemini/Groq/NVIDIA
NIM/Ollama), RBAC design, session memory, TypeScript/Next.js/React, SVG
charting, openpyxl, pytest (booby-trap and boundary testing), headless
browser QA.
