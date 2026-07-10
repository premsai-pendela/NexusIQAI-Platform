# NexusIQ Demo Guide

How to see what this system actually does — in 5 minutes on the live site, or
15 minutes with the repo. Written for recruiters, hiring managers, and
engineers evaluating the project.

## The product in one paragraph

NexusIQ is a multi-agent business intelligence system: connect a company
database and document corpus, let the system learn the schema and
company-specific business definitions, then ask questions in plain English.
The answer matters — but the bigger point is the system around it: routing,
cross-source validation with confidence scoring, per-call cost accounting,
traces, eval gates in CI, and SQL safety guardrails. The proof that the
answer is right is the product.

---

## 5-minute path (live site, nothing to install)

Open **https://nexusiq-ai.com** → "Ask NexusIQ".

1. **Ask: `What was Q4 2024 total revenue? Validate it against the internal financial reports.`**
   Watch the source routing (SQL + documents in parallel), then the answer
   with a HIGH confidence badge — the SQL total and the PDF-reported figure
   cross-validated with the % difference shown.

2. **Ask: `What was net revenue in Q4 2024?`**
   Under the generated SQL, note "📚 Company definitions applied:
   `net_revenue`" — the system retrieved the company's definition (revenue
   minus refunded returns) and the SQL joins the returns table. Without that
   layer, models silently report gross revenue. This is the known failure
   mode of enterprise text-to-SQL, fixed and measured (2/10 → 10/10,
   [business_context_layer.md](business_context_layer.md)).

3. **Open "🧭 How NexusIQ Ran This Answer"** on any reply: route, validation
   confidence, answer method (deterministic vs LLM synthesis), LLM calls
   made vs avoided, token counts, trace ID.

4. **Ask: `How do MacBook prices compare to our Electronics pricing?`**
   Live competitor pricing fused with internal SQL data.

---

## The product frontend (Next.js, streams live)

The `web/` app is the recruiter-facing product experience — a Next.js +
TypeScript frontend over the same FastAPI backend:

```bash
uvicorn api.main:app --port 8000     # backend (repo root, needs .env)
cd web && npm ci && npm run dev      # http://localhost:3000
```

Open **/ask** and ask `What was net revenue in Q4 2024?`. You'll see the
agents report in live over SSE, then the answer card: confidence pill with
the validation reason, an Evidence panel with the actual generated SQL, the
result rows, and per-document citations (page + reranker score), and a
"How I answered" panel with the route, latency, LLM calls made vs avoided,
and the real sanitized execution trace rendered as a timeline. The **/how**
page's dataset numbers are fetched live from `/api/v1/meta` — nothing on
screen is invented, and the UI says so when the backend is offline.

---

## 15-minute path (repo deep dive)

```bash
git clone https://github.com/premsai-pendela/NexusIQ-AI && cd NexusIQ-AI
pip install -r requirements.txt   # CI proves this works from a cold clone
```

**1. Company onboarding walkthrough** — the product vision in one command:

```bash
python -m scripts.onboarding_demo --offline          # no credentials needed
python -m scripts.onboarding_demo --ask "What was net revenue in Q4 2024?"  # needs .env
```

Live schema scan (tables/columns/row counts), document corpus inventory,
business glossary with per-question definition retrieval, then a real
question with validation confidence, business context, avoided LLM calls,
and a trace ID.

**2. Tests and evals** (also run on every push in CI — see the badge):

```bash
python -m unittest discover -s tests        # 202 unit + contract tests
python -m evals.offline_eval                # 7 validation contracts, no API keys
python -m evals.context_eval --mode both    # business-context before/after (needs keys)
```

**3. The receipts:**

| Claim | Evidence |
|-------|----------|
| LLM cost control, measured | [llm_cost_optimization.md](llm_cost_optimization.md) — 4→1 calls on simple SQL, before/after ledger profiles |
| Text-to-SQL business accuracy | [business_context_layer.md](business_context_layer.md) — 2/10 → 10/10, control questions byte-identical |
| Production debugging maturity | [postmortems.md](postmortems.md) — 4 real incidents with root cause, fixing commit, regression tests |
| SQL safety | [sql_guardrails.md](sql_guardrails.md) — sqlglot AST validation, tests in `tests/test_sql_safety.py` |
| Eval methodology | [evaluation.md](evaluation.md) — unit tests vs offline evals vs live golden evals |
| Observability | [observability.md](observability.md) — traces, LLM task ledger, Langfuse |

---

## Honest boundary: demo mode vs. production onboarding

What you see is a **single demo workspace**: the sample Supabase database and
bundled document corpus are pre-connected. The onboarding walkthrough shows
the real mechanics (live schema introspection, corpus indexing, glossary
retrieval) — but this is not multi-tenant SaaS.

What real customer onboarding adds (deliberately not built — wrong
risk/value for a portfolio project, and the AI engineering is the point):

- **Identity & tenancy**: registration/auth (OIDC), workspace model,
  per-tenant row-level security, tenant-scoped vector collections.
- **Customer secrets**: connection strings in a secrets manager (the app
  already uses AWS Secrets Manager for its own Langfuse keys), never in env
  files; read-only DB roles enforced server-side, not just by SQL parsing.
- **Ingestion pipeline**: upload UI, per-source registry with versioning and
  status, background indexing queue, format support beyond PDF.
- **Per-tenant context**: schema scan + glossary bootstrapped per workspace,
  with admin review before company-wide definitions apply.
- **Isolation guarantees**: per-tenant traces/ledgers, quota budgets, and
  eval baselines.

The current architecture was built so these attach cleanly: schema context is
already discovered at runtime, the glossary is already a swappable JSON store
retrieved per question, and every query already carries trace/cost metadata.

---

## Wave-2 proof path (multi-format RAG + learning loop, ~5 minutes local)

Backend + web app running (`uvicorn api.main:app --port 8000`, `cd web && npm run dev`):

1. **Ask: `What is the electronics return window for Gold members under the current returns policy?`**
   The corpus contains a deliberate freshness conflict: a 2024 PDF policy
   (30 days) and a March 2025 Markdown policy v3 (35 days for Gold/Platinum).
   The answer says **35 days**, cites `returns_refunds_policy_v3.md`, and the
   confidence pill carries a real reason ("retrieval evidence confident …").

2. **Open `/context`** — the live ontology page. Everything is
   provenance-tagged: the 15-term glossary the SQL agent actually uses, the
   introspected Postgres schema, the 52-document inventory across 6 formats,
   and the `supersedes` edge between the two returns policies, read from the
   document's own front matter.

3. **Open `/reliability`** — the learning loop. A real eval miss
   (`lost_sales_estimate`) became a failure record, became repair
   `rp-f1cc2ed098`, was implemented, and re-benchmarked: **98% → 100% Hit@5,
   0 misses**, with the before/after evidence and state history shown. The
   state machine enforces that nothing is "verified" without eval evidence
   and nothing is "adopted" without human approval.

4. **Ask something a JSON ticket answers:
   `Which support ticket reported the tablet screen rotation defect?`**
   The citation is `tickets_2025_q1.json` — RAG over structured ticket
   exports, not just PDFs.
