# ACTIVE HANDOFF — NexusIQ Overnight Wave 2

- **Branch/worktree**: `recruiter-proof-upgrade` at `~/Dev/NexusIQ-recruiter-proof`
- **Objective**: 95% recruiter-proof upgrade per `docs/FABLE_NEXUSIQ_95_CONTEXT.md`
- **Plan**: `docs/overnight_wave2_plan.md`
- **Resume command**: `cd ~/Dev/NexusIQ-recruiter-proof && cat ACTIVE_HANDOFF.md`
- **Python for tests**: `/opt/anaconda3/bin/python3 -m pytest tests/ -q`
- **Web build**: `cd web && npm run build && npm run lint`

## Milestones

- [x] M1 — Plan doc + handoff created (commit 23235fb5)
- [x] M2 — Multi-format RAG ingestion + corpus + evals (commit 327b4f9b)
- [x] M3 — Learning loop + real closed repair, 98%→100% eval (4dac60f3)
- [x] M4 — Context/ontology API + tests (143a5886)
- [x] M5 — UI /context + /reliability live-verified in browser (67edf643)
- [x] M6 — README/DEMO updates + `docs/wave2_report.md` final report

## Next unfinished milestone

None — wave 2 complete + wave 3 hardening (2026-07-06 night):
- fix: corpus routing vocabulary + bounded RAG fallback on empty SQL
  (real live defect: SKU sell-through question → n/a; now HIGH w/ CSV cite)
- learning: misroute classifier, failure-memory recall (+ API + UI widget),
  approve/adopt CLI, scan cap; 2nd real closed repair rp-f74696e598
- context: business entities (32), trust model, staleness flags + UI
- home: 5 proof doors, fresh stats; ask: corpus starter questions
- 258 tests green; web build+lint green; all pages browser-verified
- wave 4 (UI/analyst): /meta full doc inventory (52 = 43 PDF + 9 business
  files) + /how tab; deterministic Analyst Notes on aggregate answers
  (breakdowns + prior-period trend, both /query and stream); markdown
  answer rendering + numbered source cards; natural copy sitewide;
  collapsible glossary; animated pipeline + reveals + count-ups.
  265 tests green; build+lint green; browser-verified.
DO NOT PUSH — local review by Prem first.

## Checks run

- Fresh `.venv` built from requirements.txt (anaconda + main-repo venv both
  have broken fastapi/starlette pairs — always use `.venv/bin/python3`).
- Baseline 202 tests green; after M2: 218 tests green.
- RAG eval: 52 golden queries, 98% hit rate; all 12 new corpus cases pass.
  One pre-existing miss (`lost_sales_estimate`) — PDF ranking, not corpus.
- Live retrieval verified: v3 policy beats stale 2024 PDF on freshness
  conflict question; CSV/JSON/txt/html sources all retrievable.

## Known failures / notes

- LIVE Chroma store = main repo `~/Dev/NexusIQ-AI/data/chroma_db` (via .env
  symlink). Corpus ingested there (475 chunks).
- Worktree `data/chroma_db` rebuilt clean and committed (6ca006b8): 43 PDFs
  + 9 corpus docs = 475 chunks; fresh clones match README.
- `data/quota_tracker.json`, `data/web_cache.json` = runtime artifacts;
  leave out of feature commits.
- Audit 2026-07-06: 242 tests green, tree clean, live boot verified
  (health OK, /context 52 docs, /learning verified proposal, JSON-ticket
  query answered with citation, HIGH confidence). Wave 2 CLOSED.
- Successor project: `~/Dev/NexusIQ-platform` (separate repo).
