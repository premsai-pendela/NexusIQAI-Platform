# Overnight Wave 2 Plan — 95% Recruiter-Proof Upgrade

Branch: `recruiter-proof-upgrade` (worktree). Date: 2026-07-06.
Predecessor: `docs/recruiter_proof_plan.md` (wave 1: API enrichment + Next.js frontend, shipped).

## 1. What NexusIQ currently proves well

- Multi-agent LangGraph routing (SQL / RAG / web / fusion) with cross-validation.
- SQL safety: AST gate, bounded repair loop, deterministic call reduction.
- Business-context glossary lifting SQL eval 2/10 → 10/10.
- RAG: hybrid retrieval (BM25 + vector), HyDE, cross-encoder reranking,
  query decomposition, evidence assessment, honest abstention.
- 202-test CI gate + offline evals; cost ledger with avoided-call accounting.
- Wave 1: Next.js/TypeScript product frontend live-wired over SSE; `/meta`
  real corpus stats; sanitized `/trace/{id}`.

## 2. What NexusIQ fails to prove for hiring

1. **Enterprise data-integration proof** — corpus is PDF-only. Real companies
   bring markdown runbooks, CSV exports, JSON tickets, HTML pages, glossaries,
   contracts. No ingestion adapters beyond PDF.
2. **Business-context/ontology proof** — the glossary exists but is invisible;
   no entity map, no data inventory a visitor can inspect.
3. **The next engineering layer** — traces exist, evals exist, but nothing
   closes the loop: failures are not captured as learning records, repairs are
   not eval-gated, nothing shows "what the system learned."
4. **UI proof density** — /ask shows evidence, but ontology, eval status, and
   reliability story have no surface.

## 3. Repeated job-market skill gaps (pattern scan of ~90 research files)

- "React/Next/TypeScript not a verified strength" — partially closed in wave 1.
- "Project-scale, not production" / "no full-time production ML" — most common.
- Enterprise data integration (Databricks/Snowflake-shaped work, data catalogs,
  metadata) — recurring "not verified".
- Advanced RAG + eval/regression discipline — differentiator when visible.
- Customer/product workflow proof — recurring for FDE-type roles.

## 4. Improvements → gaps map

| This wave builds | Gap it closes |
|---|---|
| Multi-format ingestion adapters + realistic mixed corpus | enterprise data integration |
| Knowledge/context API (entity map, data inventory, glossary) | business-context/ontology + data catalog |
| Learning loop substrate (failure records → eval-gated repair queue) | "next layer beyond loop engineering"; agent reliability |
| /context + /reliability UI pages | UI proof density; product workflow |
| Expanded RAG golden cases over new formats | eval/regression proof |

## 5. Demo → platform evolution

The hardcoded dataset is presented truthfully as **one demo tenant** of a
bring-your-own-data platform. Ingestion adapters + manifest + entity map are
the real platform slice; multi-tenancy stays documented future architecture,
never claimed as implemented.

## 6. Per-agent improvement decisions

- **RAG agent**: already advanced (hybrid, HyDE, rerank, decomposition,
  abstention). Highest-impact truthful upgrade = *corpus realism + format
  coverage + metadata*, not another retrieval trick. Implement now.
- **SQL agent / fusion / web**: strong; no risky rewrites overnight. Leave.
- **Business context**: expose as ontology/entity-map API + UI. Implement now.
- **Evals**: extend RAG golden cases to new formats. Implement now.
- **Traces/observability**: feed the learning loop. Implement now.
- **Learning loop**: new substrate, bounded + honest. Implement now.

## 7. Highest-impact RAG upgrade (decision)

Multi-format ingestion (md, txt, csv, json, html) with per-format loaders,
rich metadata (doc_type, department, format, as_of), realistic synthetic
company files including *conflicting/stale* documents, and golden-case evals
that prove correct citation + abstention across formats.

## 8. Evals / guardrails / traces needed

- Loader unit tests (each format, edge cases).
- New RAG golden cases: per-format retrieval hits + one conflict case.
- Learning-loop tests: classifier, store, state transitions, approval gate.
- No self-modifying code: repair queue is *proposals + eval evidence*, human
  approves; nothing auto-mutates agent behavior.

## 9. Enterprise context-intelligence layers — triage

- **Now**: business glossary (exists → expose), data catalog/inventory
  (manifest → expose), entity map (schema + glossary + corpus), evidence
  provenance (exists → keep), document taxonomy (department/doc_type metadata).
- **Docs-only future**: lineage, data contracts, access control, entity
  resolution across tenants, source freshness SLAs, cross-source
  reconciliation engine.
- **Skip**: anything needing fake customers or unverifiable claims.

## 10. UI experience

Calm cream stays. Add two proof-dense pages (`/context`, `/reliability`) in
the existing design system. No gradients, no clutter; tables + quiet cards.

## 11. In this wave (acceptance criteria at §13)

M1 plan+handoff · M2 multi-format RAG+corpus+evals · M3 learning loop ·
M4 context API · M5 UI pages · M6 docs/README/demo.

## 12. Future architecture (documented, not claimed)

Multi-tenant onboarding, connect-your-database flow, lineage graph, data
contracts, feedback-driven retriever tuning, auto-generated glossary drafts.

## 13. Acceptance criteria

- All Python tests green (202 existing + new).
- `web` build + lint green.
- Live: a question answered from a *non-PDF* source with correct citation.
- Live: /context and /reliability render real backend data.
- Learning loop shows ≥1 real failure record derived from real traces.
- ACTIVE_HANDOFF.md current; commits at green checkpoints; no fabricated claims.
