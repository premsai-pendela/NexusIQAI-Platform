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
