# NexusIQAI Platform Mode

A prototype **multi-company AI data analyst platform** built on the NexusIQ
multi-agent stack. Synthetic companies have registered demo employees and a
prebuilt connected-data workspace ("company brain"). Employees log in, land in
their company workspace, and query only the data their role can access —
with SQL, citations, charts, memory, traces, and safe refusals.

## Run it

```bash
# backend (agents + platform API)
source .venv/bin/activate
NEXUSIQ_PREWARM_LIVE=false uvicorn api.main:app --port 8000

# frontend
cd web && npm run build && npx next start -p 3000
# open http://localhost:3000/platform
```

Demo accounts are listed on the login page (e.g. `analyst@acmecloud.test` /
`demo-analyst-2026`). Data lives in `data/demo_companies/<slug>/`.

## Architecture

```
web/src/app/platform/*            login · workspace · ask · feedback · admin review
api/routes/platform.py            session-token routes; AccessContext dependency
nexus_platform/
  registry.py                     3 synthetic companies, 9 demo employees
  access_policy.py                deny-by-default role policies + intent gate
  auth.py                         HMAC session tokens (prototype-grade)
  contexts.py                     one DataContext per (company, role)
  brain_builder.py                folder → SQLite catalog + Chroma index + artifacts
  query_service.py                memory → rewrite → agents → filter → trace → chart
  charts.py                       deterministic chart specs from SQL results
  dashboard.py                    "give me a dashboard" → role-filtered KPI/chart
                                  blocks from canned SQL (no LLM in the loop)
  store.py                        SQLite: session memory, feedback, traces
data/demo_companies/<slug>/       company.db · docs/<dept>/*.md · brain/ artifacts
```

The role boundary is baked into each (company, role) agent instance and
enforced at four layers:

1. **SQL prompt** — the generation prompt only describes allowed tables
2. **SQL AST** — sqlglot validation rejects any query touching another table
3. **RAG retrieval** — ChromaDB department filter on vector, hybrid, and BM25
4. **Response filter** — citations/traces re-checked before leaving the API

Clearly out-of-role questions are refused *before* retrieval by a
conservative keyword intent gate; ambiguous ones run and are still caught by
layers 2-3. Session memory is per employee and re-scoped on every request —
follow-ups can never widen access.

## Verification

```bash
python -m pytest tests/platform_mode/          # 46 tests: login routing, isolation,
                                               # AST denial, RAG boundary, memory scope
python scripts/platform_smoke.py               # 7 live LLM scenarios across 3 companies
python scripts/check_access.py --matrix        # policy dry-run matrix
python scripts/inspect_platform_traces.py      # audit saved traces for leaks
```

## Honest limitations

- Demo employee registry with hashed demo passwords — **not** production SSO.
- Synthetic companies and data only — no real customers, revenue, or people.
- Company isolation is enforced inside one app process with per-company
  SQLite/Chroma stores — **not** full enterprise tenant isolation.
- All employee access is read-only; only Admin/CEO can rebuild brains and
  review feedback/traces, scoped to their own company.
- The intent gate is keyword-based; it exists for UX (fast, well-worded
  refusals). Security does not depend on it — the AST and retrieval filters
  are the enforcement layers.
- The NVIDIA NIM fallback tier rides the free API: when it saturates, the
  gateway fails fast and the quota tracker applies a cooldown; answers then
  come from the remaining tiers.
- Deployment story is a local demo (two processes, commands above). The
  legacy recruiter-proof surface has a Dockerfile/EC2 path; platform mode
  has not been cloud-deployed — future work, not hidden breakage.

## Exports

Every chart and dashboard block downloads as **CSV** (client-side),
**XLSX** (server-side via openpyxl, styled workbook), or **PNG** (SVG →
canvas). Dashboards expose their exact SQL under "show the N queries".

## Model routing

Gemini Flash → Groq Llama 3.3 70B → NVIDIA NIM (deepseek-v4-flash,
streaming client) → local Ollama. Quota tracker cooldowns move traffic down
the chain automatically; dashboards bypass LLMs entirely.
