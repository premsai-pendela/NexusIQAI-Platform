# Wave-2 Final Report — Overnight 95% Recruiter-Proof Upgrade

Date: 2026-07-06 · Branch/worktree: `recruiter-proof-upgrade` at
`~/Dev/NexusIQ-recruiter-proof` · Plan: `docs/overnight_wave2_plan.md` ·
Handoff: `ACTIVE_HANDOFF.md` (current, all milestones checked).

## What changed (commit trail)

| Commit | What | Skill gap it addresses |
|---|---|---|
| 23235fb5 | Wave-2 plan + handoff + build-mode docs | process/PM proof |
| 327b4f9b | Multi-format RAG ingestion (md/txt/csv/json/html), 8-doc synthetic corpus with a freshness conflict, 12 new golden cases, Chroma path-drift fix | enterprise data integration; advanced RAG |
| 4dac60f3 | Verification-governed learning loop + one real closed repair (eval 98%→100%) | the layer beyond loop engineering; agent reliability; eval discipline |
| 143a5886 | `/api/v1/context` provenance-tagged entity map | business context/ontology; data catalog; semantic layer |
| 67edf643 | `/context` + `/reliability` pages; evidence-derived confidence for rag_only routes | frontend proof; UI proof density; honest confidence |
| (this) | README/DEMO story, this report | GitHub storytelling |

## Verification run

- `pytest tests/` — **242 passed** (was 202) via worktree `.venv`
  (`.venv/bin/python3 -m pytest tests/ -q`).
- `python -m evals.rag_eval` — **55 queries, 100% Hit@5, 0 misses**,
  context recall 0.964, MRR 0.808 (before wave: 43 queries; before repair:
  98.2%).
- `npm run build && npm run lint` in `web/` — green, 6 static routes.
- Live checks: backend booted; `/api/v1/context` and `/api/v1/learning`
  served real data; live query returned the v3-policy answer (35 days) with
  corpus citations and HIGH confidence with a real reason; both new pages
  screenshot-verified in a browser.

## Exact run commands

```bash
# backend (repo root)
.venv/bin/python3 -m uvicorn api.main:app --port 8000
# frontend
cd web && npm run dev        # http://localhost:3000
# tests / evals
.venv/bin/python3 -m pytest tests/ -q
.venv/bin/python3 -m evals.rag_eval
.venv/bin/python3 -m learning.service summary
```

## 30–60s LinkedIn demo script

> "This is NexusIQ — a multi-agent BI system that answers business
> questions from a live database, 52 company documents in six formats, and
> the web — with citations, confidence, cost, and a trace behind every
> answer. Watch: I ask about the electronics return window. There are two
> policies in the corpus — a 2024 PDF and a newer Markdown v3 — and it
> answers from the current one, 35 days, and cites it. The Context page
> shows the ontology it reasons with: the metric glossary, the introspected
> schema, and that supersedence edge — every node provenance-tagged. And
> the Reliability page is my favorite: a real eval miss became a failure
> record, became a repair proposal, and it only counts as verified because
> the 55-query benchmark went from 98% to 100% — and nothing gets adopted
> without human approval. Agents that learn from failures, under evals.
> All of it is in CI: 242 tests and the eval gate."

## GitHub README story (already applied)

Multi-agent BI platform slice: bring-your-own-data architecture proven on
one demo tenant — multi-format ingestion adapters, semantic layer +
provenance-tagged ontology API, hybrid RAG with reranking and honest
abstention, eval-gated CI, cost ledger, sanitized traces, and a
verification-governed learning loop with one real, evidenced, closed
repair. No invented users, no invented numbers.

## What to screenshot / record

1. `/ask` answering the Gold-member return-window question (v3 citation +
   confidence reason).
2. `/context` full page (stats row, glossary, schema, supersedence card).
3. `/reliability` repair card showing 98% → 100% before/after.
4. Terminal: `pytest` 242 green + `rag_eval` "No misses".

## What is still weak (honest)

- The deployed EC2 site still runs the wave-1 build; wave-2 needs a deploy.
- The learning loop has one closed repair and two failure records — real
  but thin; it grows with usage.
- `/context` relationships are deterministic string-derived edges, not a
  full knowledge graph; lineage/data contracts remain docs-only.
- Confidence for `rag_only` is derived from retrieval evidence, not
  cross-source validation (correctly labeled as such in the payload).
- Worktree-local `data/chroma_db` still holds a pre-fix copy (the live
  store is the main repo's; see ACTIVE_HANDOFF known notes).

## Is NexusIQ closer to 95% recruiter-proof?

Yes. It now proves, with inspectable evidence: enterprise data integration
beyond PDFs, a semantic/ontology layer surfaced in product, eval-governed
self-improvement (the layer beyond loop engineering), and a four-page
TypeScript product UI that renders only backend truth. What still blocks
95%: deploying this wave publicly, recording the demo assets, and more
learning-loop history accumulated through real usage.
