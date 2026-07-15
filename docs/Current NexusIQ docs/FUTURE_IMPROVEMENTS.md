# NexusIQAI Future Improvements

## Cross-Company Name Clarification

Live access-control testing confirmed that company isolation is enforced: the
backend resolves company and role from the signed session token, ignores
client-supplied company fields/query params, blocks cross-company traces and
health reports, and rejects tampered tokens.

One UX improvement remains:

- If an employee asks for another company by name, such as "What was MedCore
  revenue?" while logged into AcmeCloud, Ask Analyst currently stays inside the
  employee's own company boundary and answers from AcmeCloud data. This is safe,
  but it can be confusing.

Future behavior should be clearer:

> "I can only access AcmeCloud Analytics from your current session. I can answer
> the AcmeCloud version, or you need to sign into a MedCore account."

Implementation idea:

- Add a cross-company-name detector before deterministic/SQL/RAG routing.
- If the mentioned company does not match the authenticated session company,
  return a clarification/refusal-style response.
- Do not query the mentioned external company.
- Record the route as something like `cross_company_scope_clarification`.
- Add regression tests for AcmeCloud -> MedCore, MedCore -> FinPilot, and
  FinPilot -> AcmeCloud prompts.

## Health Check Report Export And Resolution Memory

The Admin/CEO Health Check agent should become a stronger operational loop, not
only a one-time report view.

Future behavior:

- Every Health Check run should be saved as a durable report with:
  - report id
  - company
  - requested by
  - time window
  - generated timestamp
  - findings
  - evidence trace ids
  - recommended fixes
  - suggested eval cases
  - resolution status per finding
- Admin/CEO should be able to download the report as:
  - PDF for review/sharing
  - JSON for machine-readable evidence
  - CSV/XLSX for finding tables if useful
- Each finding should have a resolution workflow:
  - new
  - reviewed
  - fix planned
  - fixed
  - dismissed as valid behavior
  - needs employee clarification
  - reopened
- After an Admin/CEO resolves or dismisses a finding, the Health Check agent
  should remember that decision and use it in future runs.
- Future Health Check reports should show:
  - new findings
  - repeated findings
  - reopened findings
  - previously resolved findings that appear again
  - findings intentionally dismissed as valid access denial or expected behavior
- The Health Check agent should maintain its own memory/history:
  - prior reports
  - prior finding classifications
  - admin decisions
  - fix notes
  - linked regression tests
  - whether the same issue recurred after a fix

Implementation idea:

- Add `health_reports`, `health_findings`, and `health_finding_events` tables
  if the current schema does not already support this fully.
- Add export endpoints:
  - `GET /platform/admin/health-reports/{id}/pdf`
  - `GET /platform/admin/health-reports/{id}/json`
  - optional CSV/XLSX export for findings
- Add finding status update endpoint:
  - `PATCH /platform/admin/health-findings/{finding_id}`
- Add a Health Check memory layer that compares the new run with prior runs by
  finding fingerprint, trace cluster, route type, question pattern, and fix
  ownership category.
- Add tests proving that resolved findings do not disappear silently: they
  should either stay resolved, recur as reopened, or be marked as expected
  behavior with evidence.

## Knowledge Graph / GraphRAG Layer

Current RAG stack covers hybrid retrieval (ChromaDB + BM25), cross-encoder
reranking, cross-source (SQL vs RAG) grounding, and role/department metadata
filtering — but there is no graph-structured layer over the data. The only
entity/relationship-style artifact today is a flat glossary
(`context/business_context.py`), not a real graph.

This is a real, verified gap against market demand: job-description research
across 104 target roles found meaningful mentions of "knowledge graph" (9)
and "GraphRAG"-style retrieval (3-4), with essentially zero demand for
swapping ChromaDB for pgvector/Pinecone/Weaviate/Qdrant (ChromaDB is in fact
the most-named vector store in that research, ahead of every named
alternative).

Future behavior:

- Build a lightweight knowledge graph per company from existing structured
  sources already on hand: SQL schema (tables/columns/foreign keys), the
  business glossary, and document metadata (department, doc type, entities
  mentioned) — not a new ingestion pipeline, a graph layer over what
  `brain_builder.py` and the SQL catalog already produce.
- Represent entities (metrics, departments, products, policies, people) and
  relationships (defines, supersedes, reports_to, belongs_to, referenced_in)
  as first-class nodes/edges, queryable independent of a single document.
- Add GraphRAG-style retrieval: for questions that need multi-hop reasoning
  ("which policy supersedes the one Engineering cites in their Q4 report?"),
  traverse the graph to assemble the relevant document/entity set before
  handing it to the vector/BM25 retriever, instead of relying on a single
  flat similarity search.
- Keep the role/department access boundary intact — graph traversal must
  respect the same `rag_metadata_filter` boundary the current RAG agent
  enforces, not bypass it.

Implementation idea:

- Add `nexus_platform/knowledge_graph.py`: build nodes/edges from
  `schema_catalog.json`, `doc_inventory.json`, and the business glossary
  already produced per company brain.
- Add a graph store — start with an in-process representation (e.g.
  `networkx`, already a transitive dependency) before reaching for a
  dedicated graph database; only add one (e.g. Neo4j) if traversal needs
  outgrow in-memory.
- Add a `graph_rag` route mode in `nexus_platform/query_service.py`: detect
  multi-hop/relationship questions, traverse the graph for the relevant
  entity/document set, then run existing hybrid retrieval scoped to that set.
- Add tests proving graph traversal never returns entities/documents outside
  the requesting role's department/table allowlist.

## Simulation Employees (the third agent)

NexusIQ now has three agents working together, not one:

1. the **AI data analyst** (answers questions),
2. the **Health Check agent** (audits the analyst and finds/repairs bugs),
3. **simulation employees** (generate company-specific, realistic + adversarial
   traffic that exercises the analyst).

A first version of the harness exists (`sim_employees/`): role-scoped personas,
private per-employee file memory, paced runs, and an external-CLI question
brain (Claude Code / Codex — kept off NexusIQ's own free-tier quota). What
remains is making the employees genuinely company-aware and dual-purpose.

**Why this matters.** For the analyst to be truly *agentic for a specific
company*, it should be exercised by that company's own employees. Before real
employees ever use it, simulation employees of that company query it — so the
Health Check agent can harden the analyst *from that company's perspective*.
The same traffic doubles as demo history on the Review page. One daily run,
two payoffs: **build trace history AND attack the analyst to surface bugs.**

**A simulation employee does not touch the database.** Like a real employee,
it asks in plain English; the analyst is what writes the SQL. But it *must
know the company's data landscape* — the tables, metrics, documents, and
role-scoped access an analyst of that company has — so its questions are
relevant and hit real seams instead of being generic. That knowledge comes
from the **company brain** (schema catalog, business glossary, document
inventory, role access map), never from raw data access.

Future behavior:

- Company-specific questions derived from the company brain, tiered
  simple → very-hard, mixing realistic asks with adversarial families
  (hallucination-bait, role-boundary probes, ambiguous/malformed, seam
  follow-ups, chart mismatches).
- Memory-driven adaptivity: each employee remembers prior questions/answers
  and re-probes weak spots day over day, getting sharper about where to hit.
- Two run targets: `local` (in-process, for dev/eval, works offline) and
  `live` (drives the deployed API over HTTP so traces persist to RDS and show
  on the live Review page — no firewall change needed).
- Roll from AcmeCloud to all three companies.

This is really **two distinct build tasks**, worth tracking separately:

1. **The simulation-employee harness** — personas, private memory, pacing,
   `local`/`live` modes. Partly built (`sim_employees/`).
2. **Company research / question generation** — analyze each company's brain
   (schema, glossary, docs, metrics) to derive what an employee of that
   company/role would realistically *and* adversarially ask. This is the
   "know the company" task that makes the traffic company-specific rather than
   generic, and is the harder, higher-value half.

Implementation idea:

- Enrich the `sim_employees` briefing (`sim_employees/brief.py`) with the
  company brain artifacts (`schema_catalog.json`, `doc_inventory.json`, the
  business glossary) so the CLI brain generates targeted questions.
- Add a `--target live` mode: authenticate via `POST /platform/login` and send
  each question to `POST /platform/query` against `api.nexusiq-ai.com`, so the
  Fargate backend writes the trace to RDS (no direct DB access from the Mac,
  no firewall hole).
- Keep the external-CLI brain and the per-question pacing (protect the shared
  free-tier quota).

## Health Check Agent — company-scoped, ground-truth grading

NexusIQ is multi-company. Each company has its own Admin/CEO, and **each runs
the Health Check agent over their own company's traffic only** — three
companies means three admins running three separate, isolated health checks.
Trace reads are already company-scoped by the signed session token; the next
step is deeper, company-aware *grading*.

**Why.** To truly judge whether an answer is correct — not just heuristics
like "degraded" or "low confidence" — the Health Check agent must compare the
analyst's answer against **ground truth**, which means reading *that company's*
database/brain to recompute the correct value (an "oracle") and comparing.
Grading is the Health Check agent's job; to do it well it needs company-scoped
access to the same data the analyst used. The simulation classifier
(`nexus_platform/sim/`) already does zero-LLM oracle grading for deterministic
questions in-process — the improvement is folding that capability into the
per-company Health Check agent so it grades real *and* simulated traffic the
same way.

Future behavior:

- **Per-company, per-admin isolation.** Each company's Admin/CEO runs (or
  schedules) their own Health Check agent; it only ever sees that company's
  traces, brain, and schema. No cross-company leakage — already enforced for
  traces, extend the guarantee to any brain/DB reads the grader makes.
- **Ground-truth grading.** For deterministic/SQL-answerable questions,
  recompute the correct answer from the company database and compare to what
  the analyst said; flag confident wrong answers with evidence. The
  authoritative "these are the real bugs" verdict is the Health Check agent's,
  not the simulator's light self-note.
- **Clear ownership of the loop:** simulation employees attack → the
  per-company Health Check agent grades and finds → the repair pipeline fixes
  → human-reviewed PR. The three agents each own one stage.

Implementation idea:

- Give the Health Check agent a company-scoped, read-only handle to that
  company's brain/schema (via the existing per-company context) and reuse the
  deterministic oracle from `nexus_platform/sim/` (`compute_oracle`) for
  grading; extend to more question families over time.
- Use the `source` toggle (real | simulated) already on the Review panel so an
  admin can grade organic vs synthetic-demo traffic separately, never mixed.
- Combine with the "Health Check Report Export And Resolution Memory" item
  above so findings persist per company, carry a resolution status, and
  recurrence is detected across runs.
