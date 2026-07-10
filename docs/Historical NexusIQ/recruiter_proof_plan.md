# Recruiter-Proof Upgrade Plan

Branch: `recruiter-proof-upgrade`. Date: 2026-07-05.

## Why (evidence from job-market research)

Aggregated skills-map rows across ~90 role-research files in
`Fabulous-GPT-Job-Strategy/Employer and Job Market Research` show the
recurring, *fixable-by-project* gaps:

| Recurring gap (verbatim themes) | Count/theme | What fixes it here |
|---|---|---|
| "React/Next/TypeScript — not a verified strength; frontend gap", "Full-stack product UI ⚠️ Streamlit/Plotly, not heavy React" | repeated across FDE/product/AI-eng roles | Ship a real Next.js + TypeScript product frontend inside this repo, wired to the live API |
| "Project-scale, not production", "not full company production" | most common ⚠️ | Make production machinery *visible in the product*: live SSE agent progress, trace lookup, honest degraded states, real corpus stats |
| Eval/observability proof exists but is invisible (README-only) | strong differentiator per FDE research | Surface route, latency, token usage, avoided LLM calls, confidence reason, and trace ID in every answer |
| "Believable enterprise use case" / demo theater risk | guardrail | No invented numbers in the UI. Every stat rendered comes from the backend or is explicitly labeled EXAMPLE |

Gaps a project cannot fix (tenure, sponsorship, regulated-industry
experience) are out of scope on purpose.

## What already proves strongly (do not touch)

Multi-agent LangGraph routing, SQL safety (AST gate + bounded repair),
business-context glossary (2/10 → 10/10 eval), RAG evidence loop with honest
abstention, 194-test CI eval gate, post-mortems, cost ledger with avoided-call
accounting, AWS deployment.

## What fails to prove today

1. Frontend engineering (Streamlit UI reads "student demo" — documented in
   `NexusIQ-migration/DECISIONS.md` §1).
2. The production machinery is invisible to a visitor: `/query/stream` drops
   sources, validation reason, SQL text, and usage data on the floor.
3. The designed Next.js frontend (NexusIQ-migration) runs on mock data only.

## Workstreams (each: implement → test → verify live → next)

### WS1 — API evidence enrichment
- `api/models/schemas.py`, `api/routes/query.py`.
- `QueryResponse` and the final SSE `answer` event gain:
  `confidence_reason`, `evidence` (sql query text + row count + result
  preview; document citations w/ filename + snippet; web sources),
  `usage` (llm calls, avoided calls, estimated tokens, answer mode),
  `query_time_s`.
- All data already exists in the fusion result (`sql_result.query`,
  `validation.confidence_reason`, `llm_usage`); this only exposes it.
- Test: new `tests/test_api_query_contract.py` — FastAPI TestClient with the
  fusion agent stubbed; no DB/LLM/keys. Done = suite green.

### WS2 — `GET /api/v1/meta` (real numbers for the frontend)
- New `api/routes/meta.py`: transaction count (live SQL, cached, graceful
  `null` on failure), Chroma chunk + distinct document count, web retailer
  count from config, glossary entry count. Nothing hardcoded that can drift.
- Test: stubbed agents; degraded path returns nulls, not fake numbers.

### WS3 — `GET /api/v1/trace/{trace_id}` (observability made visitable)
- Sanitized read of the local JSONL trace: whitelisted fields only
  (span names, status, latency, token estimates, avoided calls). No prompts,
  no raw SQL args, no env.
- Test: writes a temp trace via `observability.tracer`, reads it back through
  the endpoint; unknown ID → 404.

### WS4 — Next.js frontend lands in this repo (`web/`)
- Import the design-locked app from `~/Dev/NexusIQ-migration/web`
  (3 pages: `/`, `/how`, `/ask`; warm-editorial design system; mascot).
  Migration repo stays untouched.
- Add `web/src/lib/api.ts`: typed client — `query()`, `queryStream()` (SSE
  parser), `meta()`, `health()`. `NEXT_PUBLIC_API_BASE` env.
- Done = `npm run build` green.

### WS5 — `/ask` goes live
- Real SSE: thinking line advances on real events (received → processing →
  per-agent complete → answer).
- Answer block renders the real payload: answer text, confidence pill +
  reason, Evidence accordion (real SQL + citations), "How I answered"
  (route · time · LLM calls · avoided calls · trace ID).
- Backend unreachable → honest offline card ("backend offline — here's how
  to run it"), never a fake answer.
- Seed thread stays only if labeled EXAMPLE.
- Done = live question through local backend renders a real validated answer.

### WS6 — Real stats on `/` and `/how`
- Fetch `/meta`; render real counts; fallback values visibly labeled.
- Done = numbers on screen match the database/Chroma.

### WS7 — Docs
- README: frontend section, run commands, updated architecture sketch.
- `docs/DEMO.md`: add the web-product path.

## Non-goals (guardrails)
No multi-tenant auth, no invented users/revenue, no Streamlit removal (it
stays as the second door), no secrets in the repo, migration repo read-only.

## Demo story (after)
"NexusIQ is a grounded multi-agent answer system — SQL + documents + web,
cross-validated, eval-gated in CI. The product UI is Next.js/TypeScript
calling the FastAPI backend over SSE; every answer ships with its evidence,
cost ledger, and trace ID. Nothing on screen is invented: the UI renders what
the backend proves, and says so when it can't."
