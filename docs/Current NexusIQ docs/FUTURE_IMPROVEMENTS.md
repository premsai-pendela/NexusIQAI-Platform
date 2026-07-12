# NexusIQAI Future Improvements

## 1. Analyze-With-AI Mislabels Hallucinated SQL Tables As Access Denials

Status: bug, confirmed live, not fixed yet. Found 2026-07-09 by logging in as
the AcmeCloud Analyst (`analyst@acmecloud.test`) at `nexusiq-ai.com/platform`
and reproducing the exact flow reported by Prem.

Repro:

1. As Analyst, ask "What was the total revenue for Q3 2024?" — answers
   correctly: `$5,340,670.84`, tagged `deterministic · no LLM · HIGH
   confidence`.
2. Ask the identical question again — the UI offers "Use previous answer /
   Rerun on current data / Analyze with AI".
3. Click "Analyze with AI" — the response is a refusal: "I can't answer that
   from your current access level... (the 'sales_transactions' data area is
   outside your role)."

This looks like an access-control bug but is not one. AcmeCloud's schema
(visible on the Analyst's own workspace page) has **no table named
`sales_transactions`** — restricted or otherwise. The real table is
`orders`, and `orders` is inside the Analyst's allowlist. What actually
happens:

- "Analyze with AI" forces the question through the LLM SQL/RAG agent
  instead of the deterministic template
  (`nexus_platform/orchestrator.py::decide_route`, the
  `repeat_action == "analyze_with_ai"` branch).
- The LLM generating SQL hallucinates a table name (`sales_transactions`)
  that does not exist anywhere in the schema.
- `agents/sql_agent.py::_validate_query` (around the `ACCESS_DENIED_TABLE`
  raise) only checks `table not in allowed_set` — it cannot distinguish "real
  table, but outside this role" from "table does not exist, the LLM made it
  up." Both produce the identical `ACCESS_DENIED_TABLE:<name>` error.
- `nexus_platform/query_service.py::_is_access_denied` and the refusal-reason
  logic right after it unconditionally turn any `ACCESS_DENIED_TABLE` into
  "the '<name>' data area is outside your role" — so a query-generation
  failure is reported to the employee as a permissions problem. This is
  worse than a plain error: it makes a correctly-functioning access boundary
  look broken or untrustworthy to the employee.

Future behavior:

- Before turning `ACCESS_DENIED_TABLE:<name>` into an access-denial message,
  check whether `<name>` is a real table in the company's full schema (not
  just the role's allowlist).
  - If `<name>` exists in the full schema but outside the role's allowlist →
    current behavior is correct: show the access-denial card.
  - If `<name>` does not exist in the full schema at all → this is a SQL
    generation failure, not an access decision. Do not show "outside your
    role." Instead retry the generation once with an explicit schema
    reminder, or fall back to the deterministic answer if one exists for the
    resolved question, or show an honest "couldn't generate a valid query"
    message.
- Add a regression test: force the SQL agent to hallucinate a nonexistent
  table name (mock or fixture) and assert the resulting message is a
  generation-failure message, not an access-boundary refusal.
- Audit other `ACCESS_DENIED_TABLE` call sites for the same conflation.

Also observed in the same session, not yet root-caused:

- The user reported that asking to plot two prior answers ("plot both of
  those in a bar graph") once produced "a confident wrong answer" instead of
  a correct chart. Live retest with two phrasings ("Plot both Q3 and Q4
  revenue in a bar graph" and "plot both of those in a bar graph") both
  rendered correct charts, so this did not reproduce with those exact
  wordings. Needs the user's exact original phrasing and turn sequence to
  root-cause; may be an intermittent LLM-path issue rather than a
  deterministic-parser bug.

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

## Self-Improving Health Check Agent (Query-Log-Driven Eval Generation + Autonomous Repair Loop)

Status: not built. The Health Check agent shipped today (see above) only reads
existing saved traces and feedback and produces a read-only report with a
tagged finding, an occurrence count, linked trace ids, and a one-line
recommendation (e.g. "Document-routed answer for 'What about Q4?' cites no
documents... Recommendation: check retrieval for this question; if evidence
is genuinely thin, the company corpus has a gap for this topic."). It does
not generate new questions, write code, run tests, or open pull requests.
Everything below is the planned next stage, not current behavior.

The next stage turns the Health Check agent from an auditor of past traces
into the thing that actively tries to break the analyst before a real
employee does, then fixes what it finds — with a human still required to
merge anything.

Future behavior:

- The Health Check agent maintains a growing corpus per company of two
  sources: real historical employee/admin query traces (already collected
  today) and previously-generated simulated queries (new). These are always
  tagged `source: real` vs `source: simulated` and never conflated in
  reporting.
- It mines that corpus for patterns — ambiguous-metric phrasing (the "net
  revenue" vs "gross revenue" case from the business-context work already
  shipped), multi-turn follow-up chains ("what about Q4?", "compare that
  with Q3"), cross-company name confusion, and known weak-evidence question
  shapes already surfaced by today's Health Check findings — and generates
  new candidate questions as paraphrases and edge-case variants of those
  patterns. This is query-log-driven generation grounded in the company's
  own real usage, not open-ended guessing and not literal prediction of any
  specific future employee's behavior.
- It runs those candidate questions through simulated employee personas
  scoped to real company roles, respecting the same 4-layer access boundary
  every real employee is bound by — a simulated query can never see more
  than the role it's impersonating is allowed to see.
- Simulated queries run with a deliberate delay between each call (not
  fired in a burst) because this uses the same free-tier LLM provider APIs
  the rest of the product depends on — the simulation loop has to respect
  the same rate limits and cost budget as real traffic, not exhaust it.
- Each simulated answer is scored the same way a human reviewer scores one
  today: does it look wrong, vague, under-evidenced, or misrouted. Where it
  fails, the agent creates a branch, proposes the code change, adds the
  failing case (plus closely related adversarial variants) as a permanent
  regression test, and re-runs the original failing questions against the
  fixed branch to confirm the fix actually holds before doing anything else.
- Only after that verification does it open a pull request. A human still
  reviews, tests, and merges every PR — this is not optional and there is no
  auto-merge path. The loop changes how many bugs a human only sees after a
  real complaint, not who is allowed to ship a fix.
- The question-simulator itself is a second, separate target for
  improvement: track how often its generated questions actually surface a
  real failure versus reproduce already-known-good behavior, and prefer
  question patterns with a higher real-failure hit rate over time — measured,
  not assumed.
- The Health Check agent's own diagnostic loop is evaluated the same way:
  finding quality and cost/token spend per run, tracked over time, so
  "the loop improves itself" is a number that can go up or down, not a claim
  taken on faith.

Implementation idea:

- Add a `simulated_query_log` table alongside the existing trace/feedback
  tables, with a `source` column (`real` | `simulated`) so synthetic traffic
  is always distinguishable from real employee activity in every report.
- Add a question-generation step that reads `employee query traces` +
  `feedback` (the same data the current Health Check findings are built
  from) and produces candidate questions via templated paraphrase/
  perturbation of observed patterns — not unconstrained open-ended
  generation with no ground truth to anchor it.
- Add a scoped simulation runner that authenticates as existing demo-role
  personas and calls the analyst through the same API path a real employee
  uses, with a configurable delay (e.g. `SIMULATED_QUERY_DELAY_SECONDS`) to
  stay inside free-tier provider rate limits and keep cost bounded.
- Extend the finding → recommendation → resolution-status model already
  planned in "Health Check Report Export And Resolution Memory" above,
  rather than building a parallel reporting system.
- Add a git-branch-and-PR step (e.g. via the GitHub API): create a branch,
  commit the proposed fix and its new regression test, re-run the full test
  suite plus the originally-failing simulated questions, and open a PR only
  if both pass. Require a human-owned GitHub review and merge on every PR —
  no code path should ever be able to merge without one.
- Track and surface cost/token spend and finding-quality per Health Check
  run over time, so the self-improvement claim for both the simulator and
  the Health Check agent itself is backed by a trend line, not an assertion.

## Give The Health Check Agent Its Own GitHub Identity

Status: idea, not built. Raised after merging the first two Health Check
Agent PRs and noticing every commit, comment, and "who did the work" note
attributed the work to Prem's own account — accurate about who *authorized*
it, misleading about who *did* it.

Today, the repair pipeline pushes and opens PRs using a fine-grained PAT
under Prem's own GitHub account (`premsai-pendela`), since that's what was
available when this was first wired up. That has one real, functional
consequence beyond attribution: because the PR's author and Prem's own
reviewing account are the same identity, GitHub structurally refuses to let
Prem formally "approve" the PR — merging so far has required the
branch-protection bypass-rules checkbox (an admin override), not a real
approval.

Future behavior: give the Health Check Agent a separate, genuine GitHub
identity, so future PRs/commits/comments show as authored by that identity,
not Prem personally — and so Prem can review and approve through the normal
flow instead of using the bypass override every time.

Two real ways to do this, in order of effort:

- **Simpler: a second GitHub account as a machine user.** A normal free
  GitHub account (e.g. `nexusiq-healthcheck-bot`), added as a collaborator
  with push + PR permissions only (no merge/admin rights), with its own
  fine-grained PAT used in place of Prem's personal one. This is standard,
  legitimate practice for repo automation — not the same thing as creating
  accounts to evade a provider's rate limits (which was correctly ruled out
  earlier in this project's history for a different reason). Bonus: once
  the PR author is genuinely a different identity than Prem, real approval
  becomes possible again, and branch protection can go back to fully strict
  (no bypass needed).
- **More "official," heavier: a GitHub App.** Shows up as
  `nexusiq-healthcheck[bot]` in commits/PRs, the same pattern as Dependabot.
  More correct long-term, but requires registering an app and using
  installation-token auth instead of a plain PAT — meaningfully more setup
  for a solo project than the machine-user option above.

Implementation idea:

- Whichever option is chosen, update `docs/platform improvements/CONTEXT.md`
  §"GitHub access" to describe the new identity and re-verify the
  self-approval-is-blocked reasoning still applies correctly (it changes
  once the author is a separate account — re-check the branch protection
  design isn't accidentally weakened in the process, not just the token).
- Migrate `nexus_platform/repair/pr.py` to read the new token from a
  differently-named environment variable so it's unambiguous in logs which
  identity is being used.

## CI Is Broken On Any PR, Unrelated To Content

Status: bug, confirmed 2026-07-11 while reviewing PR #1's checks. The
`test-and-eval` GitHub Actions check fails on every PR regardless of what it
changes — verified this is pre-existing, not caused by either of the
Health Check Agent's PRs.

Root cause: `.github/workflows/ci.yml` runs `python -m unittest discover`,
but `requirements.txt` never lists `pytest` — and at least two test files
(`tests/test_bedrock_fallback.py`, `tests/test_cerebras_fallback.py`) import
`pytest` directly. `unittest`'s own discovery tries to load every test
file, hits the missing import, and fails the whole run with 13 collection
errors before anything can even execute. Confirmed unrelated to content:
neither the workflow file nor either failing test file was touched by
either PR — this would fail identically on a PR that changed nothing.

Future behavior: `test-and-eval` should pass on a clean PR.

Implementation idea:

- Add `pytest` to `requirements.txt` (or a `requirements-dev.txt` CI
  installs), or convert `ci.yml` to run `pytest` instead of
  `unittest discover` — the platform test suite already runs via pytest
  locally (`tests/platform_mode/`), so aligning CI to the same runner
  removes the mismatch entirely instead of patching around it.
- Re-run CI on an existing PR afterward to confirm the fix actually holds,
  rather than assuming the config change alone is sufficient.

## Admin Review Page: Trace Cards Don't Open

Status: bug, confirmed live on the deployed site (`nexusiq-ai.com/platform/admin`)
2026-07-11, logged in as Admin.

Repro:

1. As Admin, open Review, look at "Employee Query Traces."
2. Click directly on any trace row (tried several, different questions,
   different `allowed`/`denied` decisions).
3. Nothing happens — no expanded detail card, no error message, no visual
   change of any kind.

Confirmed with direct evidence, not just visual inspection: read the
browser's network log after clicking — **zero requests were ever sent** to
the trace-detail endpoint (`/platform/traces/{id}`), across multiple clicks
on multiple different rows. No console errors either. This means the click
isn't failing at the network or backend level — the click handler itself
never fires a request in whatever is actually running in production.

The relevant frontend code (`web/src/app/platform/admin/page.tsx`) does
contain a wired-up `onClick={() => openTraceById(t.id)}` on each trace row,
calling `fetchTraceDetail`, with both a `TraceCard` render and an error
banner ready to display the result — so the feature exists in the
*repository's current source*. The most likely explanation is that the
deployed build predates this code being added or wired correctly, or there's
a build/bundling issue that dropped it — not that the idea was never
implemented at all.

Future behavior: clicking a trace row should expand to show the full trace
detail — the question, the actual answer given, the access decision, and
the trace ID — matching what the source code already appears to intend.

Implementation idea:

- Verify this same click actually works against a fresh local build from
  current `master`/`health-loop/dev` source (not just `npm run dev`, since
  dev mode can mask a bundling issue that only shows up in a production
  build) before assuming the fix is only a deploy problem.
- If it reproduces even on a fresh local production build, the bug is in
  the current source despite looking correctly wired — check for something
  more subtle (e.g. an event-handling conflict with a parent element, a
  stale closure over `t.id`, or the button element being visually present
  but not actually receiving the click due to overlapping layout).
- Add a Playwright/browser-level test that clicks a real trace row and
  asserts the detail card renders — this exact class of bug (code that
  looks right but silently does nothing in the browser) is precisely what
  unit tests miss and a real click-through test would catch.

## Health Check Agent Should Write Its Own Guardrails Before Touching Code

Status: idea, not built. Raised after watching the repair pipeline's actual
attempts during the Self-Improving Health Check Agent mission.

Today, the repair pipeline's safety net (`nexus_platform/repair/eval_gate.py`,
the scope fence in `apply.py`, the anti-merge test) is **static structure
Fable wrote once**, applied uniformly to every fix attempt — a fixed set of
rules that don't change based on which specific bug is being fixed. That's
real and it works (see the Phase 1/Phase 2 results), but it's not the same
thing as the pipeline reasoning about *this specific finding* and writing
down, for itself, what it will and won't do before it starts.

Future behavior: before touching any code for a given finding, the pipeline
should generate and write down its own bespoke guardrails for that specific
task — not just rely on the fixed, generic rules built in advance. For
example: which files it believes are actually relevant and why, what it is
assuming that it hasn't verified, what would tell it early that its current
theory is wrong, and what it explicitly will not touch for this fix even if
tempted. This is a stronger, more deliberate version of the existing P3
"write a plan" stage — the plan says *what* it intends to change; this adds
*why it's confident that's the right and complete scope*, written before
implementation starts, not inferred after the fact from what it happened to
touch.

The goal is fewer "try it, see what breaks, try again" cycles and more
"reason carefully first, then implement once, correctly" — reducing reliance
on brute-force retries (which is also what burns free-tier quota fastest).

Implementation idea:

- Add a stage between P2 (hypothesis) and P3 (plan) in
  `nexus_platform/repair/proposer.py`: the model writes its own
  finding-specific guardrails as a structured, checkable list, validated
  the same way other stages are (real symbols cited, files that actually
  exist) before the plan stage is allowed to run.
- Track, over time, whether fixes that included this self-written guardrail
  step needed fewer retry rounds than ones that didn't — this claim should
  be measured, not asserted, consistent with how the rest of this
  initiative treats its own effectiveness.
- This is additive to the existing static safety net (eval gate, scope
  fence, anti-merge), not a replacement for it — the fixed structural rules
  stay as the non-negotiable floor regardless of what the agent reasons its
  way into believing for a specific task.

## Metric-Clarification Card Needs An "Answer As Asked" Path

Status: idea, not built. Prompted by live testing after the unknown-metric
honesty gate shipped (see the fix referenced in item #1's history — the
same fix that stops the SQL agent fabricating a number for an untracked
metric like "NPS").

Today, when the system can't recognize the metric an employee asked about,
the clarification card offers 2-3 *suggested alternative* metrics — but
there's no way for the employee to insist on the actual term they used.
Someone who specifically wants to know about "NPS" doesn't want to be
redirected to "revenue by region" instead; they want a real answer about
NPS, even if that answer is "we don't track that."

Future behavior:

- Add a 4th option on the clarification card: **"Run as it is with AI."**
  This tells the system to actually attempt the employee's own wording
  instead of substituting a suggested alternative, and to distinguish two
  different outcomes rather than collapsing them into one generic refusal:
  - **The metric doesn't exist anywhere in the company's data, for any
    role.** Say so plainly ("This metric isn't tracked anywhere in
    [Company]'s data") and point the employee to their admin/CEO — this is
    a real gap in what the company measures, not a permissions problem, and
    the employee should know to raise it with a human, not keep asking the
    AI.
  - **The metric exists somewhere in the company's data, but this
    employee's role can't see it.** Say so as an access limitation ("This
    metric isn't accessible for your role") and surface the existing
    one-click "Request access" flow (already built elsewhere in the
    product) so they can formally ask, with a reason.

Implementation idea:

- Add the 4th button to the clarification-card frontend component.
- **Hard dependency: this needs item #1's fix first, not built
  independently.** Telling "doesn't exist anywhere" apart from "exists but
  restricted for this role" requires checking the metric/table against the
  company's *full* schema, not just the current role's allowlist — which is
  exactly the distinction `agents/sql_agent.py::_validate_query` cannot
  make today (that gap is what caused the original Analyze-With-AI bug).
  Building this button without that fix risks reintroducing the same
  hallucinated-table-as-access-denial failure, just from a new entry point.
- Reuse the unknown-metric honesty gate's pattern for the "doesn't exist at
  all" case, and the existing access-request UI for the "exists but
  restricted" case — don't build either messaging path from scratch.
- Add regression tests for all three real outcomes: metric truly doesn't
  exist for any role, metric exists but is role-restricted, and metric
  exists and resolves to a normal answer (the "Run as it is with AI" button
  should still work correctly for a metric that *was* just phrased
  unusually, not only for the broken cases).

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

## Give The Repair Pipeline A Memory (Failure/Fix Record, Not Re-Derived From Zero Every Run)

Status: idea, not built. Prompted by comparing the repair pipeline's actual
Phase 1/Phase 2 results (one real bug found and fixed correctly, one real bug
honestly reported as beyond the pipeline's current reach) against Andrej
Karpathy's public argument that today's models are capable but not yet
reliable enough to carry heavy agent scaffolding without support, and that
the more durable fix is architectural memory, not more prompting — the same
reasoning he's given for why weak models need external structure (his own
"hippocampus"-style framing) rather than being asked to re-derive everything
from first principles on every call.

Today, every repair run starts from zero. `nexus_platform/repair/proposer.py`
reasons about a finding using only what's in that run's evidence pack — it
has no way to know "a bug shaped like this was seen and fixed three runs
ago" or "this exact hypothesis was tried before and was wrong." A weak model
re-deriving a hard diagnosis from scratch every time is worse than the same
model recalling a close prior case and adapting it — recall is a much lower
bar than fresh multi-step reasoning, and it's the lever available regardless
of which model is running each stage.

Future behavior:

- Persist a durable record per company (and, where the pattern is
  model/architecture-level rather than company-specific data, across
  companies) of: the finding that triggered a repair, the P1/P2 diagnosis
  reached, the plan that followed, whether the fix passed eval and shipped,
  and — just as importantly — hypotheses that were tried and rejected, so
  the same wrong theory isn't re-explored blind next time.
- Before P1 (understand) runs on a new finding, retrieve the record's most
  similar prior cases (same failure shape, same code area, same
  question-pattern family) and include them in the evidence pack as
  precedent, not as a shortcut that skips verification — the pipeline still
  has to confirm a recalled fix actually applies to the current evidence
  before proposing it.
- Track, over time, whether findings with a similar precedent in the record
  get diagnosed correctly more often or in fewer retry rounds than findings
  with no precedent — this is the same "measure it, don't assert it"
  standard the rest of this initiative already holds itself to.

Implementation idea:

- Add a `repair_case_log` table (or extend `nexus_platform/store.py`) keyed
  by company, with columns for the finding signature, diagnosis, plan,
  outcome (shipped / rejected / abandoned), and rejected-hypothesis text.
- Add a retrieval step at the top of `Proposer` (before P1) that looks up
  the log for cases with a similar finding signature — start with simple
  signature matching (same finding `kind`, same code area) before reaching
  for embedding-based similarity; this doesn't need a new ML system to be
  useful on day one.
- This is additive to the existing staged pipeline (P1-P5) and the
  self-written-guardrails idea above — memory changes what evidence a stage
  starts with, not the staged structure or the safety net around it.

## Tier The Repair Pipeline's Reasoning: Strongest Available Model For Diagnosis + Plan, Free-Tier For Implementation

Status: idea, not built. Also prompted by the Karpathy discussion above —
specifically his point that the fix for a weak-model ceiling on a hard
reasoning task isn't more pipeline steps, it's recognizing which steps
actually need the strongest reasoning available and routing accordingly,
rather than treating every stage as interchangeable.

Today, `nexus_platform/repair/proposer.py::build_models()` builds **one**
model list, used identically for every stage (P1 understand, P2 hypothesis,
P3 plan, P4 implement, P5 self-review): Gemini Flash → Groq → NVIDIA NIM →
Cerebras → Bedrock, with Bedrock inserted last, as a pure availability
fallback (`insert_bedrock_fallback`) — it's only ever reached if everything
earlier in the chain is unavailable or rate-limited, never because it's the
stronger model for a specific stage's difficulty.

That's a mismatch with what the stages actually need. P1-P3 (find the bug
across multiple traces, form a hypothesis, write a detailed step-by-step
plan) is exactly the "cognitively demanding, errors compound" reasoning
Karpathy's argument is about — this is where Phase 2's real capability gap
showed up. P4 (implement the plan as a code diff) is comparatively
mechanical once a correct, detailed plan exists — a lower bar, and a
reasonable place to keep using the cheaper free-tier chain.

Future behavior:

- P1, P2, and P3 (diagnosis + plan) deliberately prefer the strongest
  reasoning model available in the chain first, rather than reaching it
  only as a last-resort fallback.
- P4 (implement) and P5 (self-review of the diff) keep using the existing
  free-tier-first chain (Gemini Flash → Groq → NVIDIA NIM → Cerebras),
  since implementing an already-detailed plan is the lower-judgment step.
- This changes *routing priority per stage*, not the safety net: eval gate,
  scope fence, and the anti-merge test all still apply exactly as they do
  today, regardless of which model produced a given stage's output.

Implementation idea:

- **Resolved:** `config/settings.py::bedrock_fast_model`/`bedrock_reasoning_model`
  now point at Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`
  — the cross-region inference profile ID; the bare model ID throws
  `ValidationException: on-demand throughput isn't supported for this
  model`, confirmed live against this AWS account). Bedrock is enabled in
  production (`BEDROCK_ENABLED=true` on the ECS task) with no env override
  for the model fields, so this default is what actually ships.
- **Still unverified, needs a human check:** the ECS task role
  (`nexusiq-ecs-task-role`, inline policy `nexusiq-bedrock-invoke`) has an
  IAM policy scoped to `bedrock:InvokeModel`. Whether it authorizes the new
  inference-profile resource
  (`arn:aws:bedrock:us-east-1:<account>:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0`)
  or is scoped only to the old 3.5 Haiku model ARN could not be confirmed —
  the deploy IAM user used in this session doesn't have `iam:GetRolePolicy`
  permission (deliberately, least-privilege). Check/update that policy's
  resource ARN before relying on this in production; until then, Bedrock is
  the last-resort tier of the chain, so a permission mismatch here degrades
  to "Bedrock unavailable, falls through" rather than an outage.
- Split `build_models()` into two model lists — a diagnosis-tier list
  (Bedrock reasoning model first, existing chain as fallback if Bedrock is
  unavailable/rate-limited) and an implementation-tier list (existing
  free-tier-first chain, unchanged) — and pass the right one into
  `Proposer._invoke()` per stage instead of one shared list for all five.
- Track cost/latency per stage tier separately (extending the existing
  cost/token-spend tracking from the Self-Improving Health Check Agent
  section above) so the tradeoff — better diagnosis accuracy vs. more
  Bedrock usage — is a measured number, not an assumption.
