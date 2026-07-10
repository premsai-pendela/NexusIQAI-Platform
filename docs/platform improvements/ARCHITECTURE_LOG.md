# ARCHITECTURE_LOG — Self-Improving Health Check Agent

Append-only design journal for the initiative described in
`docs/platform improvements/CONTEXT.md`. Written by the agent (Claude Fable 5,
Claude Code) running the mission autonomously. `ACTIVE_HANDOFF.md` (repo root)
tracks *where things stand*; this file records *why they got that way* —
decisions, alternatives rejected, dead ends, and what changed my mind.
Entries are timestamped and chronological.

---

## Guardrails (written 2026-07-10, before any implementation code — Step 0.5)

These are the rules I hold myself to for the entire run. Prem is not
available; these replace "stop and ask." I re-read this section at the
checkpoints defined below and correct any drift instead of ignoring it.

### Scope fence

**In scope** (a "fix" may only touch these):
- `nexus_platform/` — including the new `sim/` package, store migrations,
  and localized changes to `query_service.py` / `orchestrator.py` /
  `health_check.py` where a diagnosed bug lives.
- `agents/` — only localized changes where a diagnosed bug's root cause
  demonstrably lives (e.g. `sql_agent.py::_validate_query` error labeling),
  never engine rewrites.
- `tests/platform_mode/` — new regression tests, new fixtures.
- `scripts/` — new campaign-runner entry points only.
- `docs/platform improvements/` and `ACTIVE_HANDOFF.md` — logs.

**Out of scope, always, no matter how tempting mid-loop:**
- The product UI/UX (`web/`), except that I may *read* it. No frontend
  changes ride along with a backend fix PR.
- `~/Dev/NexusIQ-recruiter-proof`, `~/Dev/NexusIQ-AI`, or any workspace
  outside this repo.
- Rewriting the fusion engine, the LLM gateway, the deterministic parser's
  architecture, the auth system, or the brain builder. If a diagnosis points
  there, the deliverable is a *narrowly scoped* fix or a documented finding —
  not a rework.
- Secrets, `.env`, credentials, token scopes, GitHub repo settings, AWS
  resources. Read-only on the deployed product (I query it like an employee
  would; I never redeploy it).
- The deployed AWS stack. All campaign/fix work happens against the local
  checkout; the PR is the only artifact that leaves this machine.

### Progress-detection circuit breaker ("stuck" definition)

I am stuck when any of these is true:
1. Three consecutive attempts at the same sub-goal (e.g. making the
   classifier flag a finding, making a repro fail, making a fix pass) with
   no new hypothesis between attempts — retrying is only allowed with a
   changed hypothesis, otherwise it's spinning.
2. A fix attempt fails the after-gate the same way twice in a row.
3. A simulation campaign completes with zero signal twice in a row (no
   findings at all, not even passing-test confirmations — that means the
   harness itself is broken, not that the product is perfect).

When stuck: go *up* the loop (re-research, re-diagnose, read more code or
corpus), not *around* it (more retries). If genuinely no path exists after
one full re-derivation, narrow to a smaller real sub-goal (e.g. "PR fixes
bug #1's mislabeling in `query_service` only" instead of "PR fixes every
`ACCESS_DENIED_TABLE` call site") and log the narrowing here.

### Budget ceilings (no looser than CONTEXT.md §2c; these are my stricter caps)

- `SIMULATED_QUERY_DELAY_SECONDS` ≥ 8s between simulated questions that took
  the LLM path. Deterministic-path questions (`llm_skipped: true`) need no
  delay.
- Hard cap **40 LLM-path calls per campaign**; estimated-token cap 100k per
  campaign. Runner stops issuing LLM-path candidates at the cap and reports
  "partial coverage (budget)".
- Shared `utils/quota_tracker.py` only — no parallel tracker. If the top
  provider is in cooldown from real traffic, simulated LLM-path candidates
  are skipped (recorded as `skipped_budget`), not queued to hammer later.
- Campaign question generation itself uses **zero** LLM calls in campaign #1
  (template/paraphrase banks I design offline). If LLM paraphrase is ever
  added, it is capped at 10 calls per campaign and rides the same tracker.
- My own (Claude-side) spend: browser use against the live product is for
  orientation/verification only, a handful of questions per session, mostly
  deterministic-path; never a load test.

### Fixed non-negotiables (not mine to loosen, restated so they're in one place)

- **Never merge anything.** No `gh pr merge`, no merge API call, no push to
  `master`, ever, in code or by hand. Enforced additionally by a grep test
  over any repair/automation code I write.
- Never touch secrets/`.env`/credentials; never create/rotate/broaden
  tokens; never change GitHub repo security settings; never force-push;
  never delete branches other than my own attempt branches.
- Simulated traffic is always tagged `source: simulated` and never appears
  in real-usage reporting, exports, or admin views by default.
- The §2c rate-limit floor and the shared-brain constraint stay fixed.

### Self-review cadence

- Re-read this Guardrails section: (a) after every completed simulation
  campaign, (b) before creating any branch, (c) before opening any PR,
  (d) whenever the circuit breaker trips. If I find myself outside the
  fence, the next log entry says so and says how I corrected it.

---

## 2026-07-10 — Entry 1: Orientation complete; what I verified and decided

### What I read (Step 0)

Repo-root `CLAUDE.md`, `PLATFORM_MODE.md`, `NEXUSIQAI_FULL_BUILD_REPORT.md`,
`FUTURE_IMPROVEMENTS.md` (whole file), `SELF_IMPROVING_HEALTH_CHECK_AGENT_PLAN.md`
(whole file), and the code the plan cites: `health_check.py` (10 deterministic
analyzers, `_finding()` shape, `CLASSIFICATIONS`), `query_service.py::run_query`
(the single entry point; `_is_access_denied`; the refusal wiring at the
`denied_table` branch), `orchestrator.py::decide_route` +
`find_clarification`, `store.py` (schema, `_MIGRATIONS` mechanism, no
`source` column today), `access_policy.py` (`ROLE_POLICIES`, `TABLE_AREAS` —
the full-schema union the bug-#1 fix needs), `contexts.py::build_context`,
`registry.py`, `agents/sql_agent.py::_validate_query` (lines ~588–604, the
`ACCESS_DENIED_TABLE:<name>` raise), `utils/quota_tracker.py`,
`scripts/platform_smoke.py::ctx_for` (the AccessContext construction pattern
the simulator will reuse).

The plan doc's "current state" claims all checked out against the code. I
found no factual errors in it worth correcting.

### Live product visit (Step 0, item 5)

Logged into `nexusiq-ai.com/platform` as **AcmeCloud Analyst** and
**AcmeCloud HR** (click-to-sign-in demo accounts):

- **Bug #1 reproduced live on the first attempt.** Asked "What was the total
  revenue for Q3 2024?" → deterministic answer $5,340,670.84, HIGH
  confidence. Asked identical question again → repeat-choice card → clicked
  "Analyze with AI" → access-boundary refusal: *"(the 'sales_transactions'
  data area is outside your role)"*. Live trace `tr_79a32d53e8`. The same
  card lists the Analyst's queryable areas — 27 tables, no
  `sales_transactions` anywhere — so the UI visibly contradicts itself, and
  the card even offers "request access to this data" for a table that does
  not exist. An employee following that button would file a nonsense access
  request to their Admin. This is worse than the write-up suggests: it
  pollutes the *human* review loop downstream, not just the one answer.
- **The contrast case that defines the classifier.** As HR, "What was total
  revenue in Q3 2024?" is refused naming `orders` — a *real* table genuinely
  outside HR's role. Same message template, completely different truth
  value. The classifier's `exceptional` bucket is precisely: *denial names a
  table not present in the company's full schema* (`TABLE_AREAS` union /
  live schema catalog). A denial naming a real out-of-role table is
  `correct` (valid_access_denial).
- HR's "What is our attrition rate?" answered deterministically (12.8%,
  no LLM) — the deterministic tier works as documented.
- Product-feel notes for the simulator's phrasing realism: employees ask
  short, mid-formality questions; the UI nudges follow-up chips ("What about
  Q4?", "by region"), so real sessions are heavy on elliptical follow-ups —
  the simulator must include multi-turn chains, not just one-shots.

### Reconciliation with `SELF_IMPROVING_HEALTH_CHECK_AGENT_PLAN.md` (prior art)

I adopt the plan's architecture nearly wholesale. It is code-grounded and
its checked claims held up. Specifically adopted unchanged:

- `sim/` package layout (`personas.py`, `question_gen.py`, `runner.py`,
  `classifier.py`) calling `query_service.run_query()` in-process with an
  `AccessContext` built exactly like `platform_smoke.py::ctx_for` — all four
  access layers apply structurally (§3 of the plan).
- `source` column on `traces` via the existing `_MIGRATIONS` mechanism,
  default `'real'`, with real-only defaults on every read helper (§4.1).
- `simulated_query_log` as a campaign ledger, not a trace mirror (§4.1),
  including `path_expected`, `surfaced_real_failure`, `tokens_estimated`.
- `health_findings` / `health_finding_events` fingerprint + status tables
  (§4.2).
- The classifier's four operational definitions (§7), including the
  deterministic layer as the numeric oracle for LLM-path answers.
- Rate limiting design (§6): delay knob, shared tracker, per-campaign caps,
  off-by-default, never in the request hot path.
- Repair flow with before/after eval gate in a git worktree, PR-only,
  anti-merge grep test (§8).

**Where I deviate or extend, and why:**

1. **Difficulty tiers are a first-class campaign axis** (CONTEXT.md adds
   this beyond the plan): every campaign tracks coverage over
   roles × companies × path_expected × difficulty ∈ {simple, moderate,
   complex, compound}. The plan's coverage matrix (§5.3) only had three
   axes. The generator will emit and record the tier per candidate, and the
   campaign report shows the four-way coverage so "only easy questions" is
   visible as a defect.
2. **Adversarial content strategy** (CONTEXT.md "try to break it"): the
   plan's generation is paraphrase/perturbation of observed patterns; I keep
   that grounding but add deliberate attack shapes as their own pattern
   families — nonexistent-but-plausible table/metric references (bug #1's
   shape generalized), in-role + out-of-role mixed in one sentence,
   malformed periods, contradictory selections, repeat→analyze-with-ai for
   every role/company, multi-answer references ("compare the first and third
   things I asked about").
3. **Phases 1–3 collapse into one continuous run.** The plan staged
   Phase 1 (simulate+classify) → Phase 2 (written proposals) → Phase 3
   (branch+PR) as separately shipped milestones with Prem decisions between
   them. CONTEXT.md §"final goal" explicitly requires the whole loop
   including an opened PR, unattended, now. I keep the plan's *ordering* as
   internal gates (a branch is only created for a high-severity finding with
   a deterministic repro that fails before the fix), but I do not wait for a
   human between stages. This directly answers the plan's open question
   §11.1: **"it-builds-then-you-approve-the-merge."** Rationale: the goal
   text fixes this choice ("A real pull request is open… waiting on Prem's
   review"); the risk the plan worried about (a stream of junk PRs from
   classifier false-positives) is bounded by my guardrail that a PR requires
   a *deterministically reproducible* failure encoded as a failing test
   first — a classifier hunch alone never reaches the branch step.
4. **Plan §11.2 (which repo):** fixed by CONTEXT.md — PRs target
   `premsai-pendela/NexusIQAI-Platform` with the provided fine-grained PAT
   (verified: `gh auth status` shows it active). Note the local checkout's
   `ACTIVE_HANDOFF.md` still says "DO NOT PUSH to GitHub without Prem's
   explicit go-ahead" from an earlier era; CONTEXT.md §GitHub access
   supersedes it for this initiative's own branches/PRs (and only those —
   nothing else gets pushed).
5. **Plan §11.3 (human-labeled gold set):** cannot exist yet — Prem isn't
   here to label. I will build the gold-set harness and seed it with
   clear-cut cases labeled by construction (e.g. a deterministic-oracle
   mismatch is `wrong` by definition; a denial naming a nonexistent table is
   `exceptional` by definition), marked `labeled_by: construction`, plus
   ambiguous cases marked `labeled_by: agent-provisional` for Prem to
   confirm/overrule later. The health report will state the gold set is
   provisional, not human-verified. Flagged in `ACTIVE_HANDOFF.md`.
6. **Plan §11.4 (trigger):** CLI/manual only (`python -m nexus_platform.sim.run_campaign`
   or a script entry point). No scheduler, no admin button in this pass —
   UI is out of my scope fence.
7. **Agent operational memory (CONTEXT.md Step 4) is new** — the plan's
   `health_memory.py` tracks the *product's* findings; this tracks the
   *agent's own* lessons (which question patterns hit, which classifier
   heuristics false-positived, what budget was actually consumed, what to
   do differently). Design pending a short research pass (next entry);
   storage will live in `store.py`'s SQLite alongside everything else unless
   research argues otherwise, because one file (`data/platform.db`) is
   already the platform's single local state store and adding a second
   store adds failure modes without adding capability.

### Two engineering decisions made now (with reasoning)

**Simulator transport: in-process `run_query()`, not browser logins.**
Evaluated per CONTEXT.md §2b. Browser-driving the live site would exercise
the frontend too, but: (a) it spends the *deployed* product's LLM budget,
which serves real demo traffic, and multiplies latency ~10× per question;
(b) the campaign writes traces into the deployed container's store where I
can't run the diagnostic loop or tests; (c) the fix loop needs local
before/after tests anyway, so findings must be reproducible locally
regardless of how they were first surfaced; (d) bug #1 was already verified
by hand in the real browser flow (trace `tr_79a32d53e8`), covering the
"does the seam exist end-to-end in prod" question the browser path would
answer. In-process gets identical access enforcement (the boundary lives in
the `(company, role)` agent instance, not in HTTP). Frontend-only bugs are
explicitly out of my scope fence anyway. Decision: in-process, recorded also
in `ACTIVE_HANDOFF.md`.

**Campaigns run against the local checkout, local brains/SQLite mirrors.**
The local repo is the same code that's deployed (master). Local SQLite
mirrors are the documented offline-test path. This keeps the entire
loop — simulate, classify, diagnose, fix, before/after — on one machine with
zero risk to the deployed stack, and the local `.env`'s provider keys ride
the same shared quota tracker the deployed product's keys do (same free-tier
accounts), so the budget discipline still matters and is enforced as above.

### Next actions

1. Short research pass (§2a question-pattern grounding + Step 4 prior art
   on weak-model agent loops/memory) — logged in the next entry.
2. Phase 0 store plumbing, then `sim/`, then the AcmeCloud campaign.

---

## 2026-07-10 — Entry 2: Research pass — what I found, what I discarded, what it changes

### §2a — what real employees ask BI tools

Searched for query-log studies of NLQ/BI usage; found no published raw query
logs (unsurprising — they're proprietary), so I triangulated from vendor and
practitioner material, read skeptically (these are marketing-adjacent
sources; I used them for *question shapes*, not for any statistics):

- [Yellowfin — what is NLQ](https://www.yellowfinbi.com/blog/what-is-natural-language-query-nlq),
  [TechTarget on NLQ in BI](https://www.techtarget.com/searchbusinessanalytics/feature/4-ways-natural-language-querying-in-BI-tools-can-benefit-users),
  [Querio](https://querio.ai/articles/what-is-natural-language-querying-in-bi):
  most real usage is *quick checks*, not deep analysis — "sales last
  quarter", "how many tickets resolved last week", asked in short, casual
  phrasing. People ask questions far more often than they run reports.
  → Validates keeping a large **simple** tier in every campaign; a simulator
  that only asks clever questions is unrepresentative *and* misses basic
  regressions.
- [NetSuite on ad-hoc reporting](https://www.netsuite.com/portal/resource/articles/data-warehouse/ad-hoc-reporting.shtml),
  [Metabase on ad-hoc requests](https://www.metabase.com/blog/ad-hoc-analysis-tips),
  [Domo](https://www.domo.com/learn/article/what-is-ad-hoc-reporting-and-how-does-it-relate-to-bi):
  department shapes — finance drills variance→cost center→transaction
  (drill-down chains, i.e. multi-turn); HR tracks turnover/attendance/
  engagement; ops investigates delays and bottlenecks ("where are shipping
  delays happening"); support counts/resolution/SLA questions. Real-world
  hard questions are compound-causal: "why did X drop 18% in Q1 vs last
  year, and which segments were hit hardest" — a why + comparison + breakdown
  chained in one sentence.
  → The compound tier should chain cause-question + comparison + grouping,
  and follow-up chains should mimic drill-down (metric → by department →
  single department → trend).

Discarded: BI *interview*-question listicles (dominated the search results;
they're about hiring analysts, not what employees ask tools — irrelevant).

### Step 4 — prior art on weak-model loops, memory, judging, repair

- **[Useful Memories Become Faulty When Continuously Updated by LLMs
  (arXiv:2605.12978)](https://arxiv.org/abs/2605.12978)** — the single most
  design-changing find. Continuously LLM-rewritten textual memory degrades:
  utility rises then falls, sometimes below the no-memory baseline (their
  headline: a frontier model failed 54% of previously-solved problems when
  relying on consolidated memories). Root cause is the *consolidation/rewrite
  step itself*, not the experiences. Recommended: raw episodes as primary
  evidence, explicit gating of consolidation, never destroy episodic records.
  → **I am deliberately not implementing the illustrative compaction scheme
  from CONTEXT.md Step 4** ("periodically summarize older entries into a
  condensed digest") in its LLM-rewriting form — it is precisely the failure
  mode this paper measures, and CONTEXT.md itself says "design something
  better if you find it." Design below.
- **[Memory for Autonomous LLM Agents survey (arXiv:2603.07670)](https://arxiv.org/abs/2603.07670)** —
  names the two central risks for reflective memory: *self-reinforcing
  error* (a wrong lesson prevents ever collecting the evidence that would
  overturn it) and *over-generalization*; recommends confidence scores and
  periodic expiration as quality gates.
  → Lessons carry required evidence links + an expiry horizon; "avoid
  pattern X" lessons may only *deprioritize*, never permanently exclude, a
  pattern family — some budget always goes to re-testing deprioritized
  families so a wrong lesson can be overturned.
- **LLM-as-judge reliability** ([reliability study, arXiv:2412.12509](https://arxiv.org/html/2412.12509v2),
  [Braintrust on judge vs deterministic evals](https://www.braintrust.dev/articles/what-is-llm-as-a-judge)):
  small models are unreliable judges and mostly can't use rubric guidance
  (benefits accrue ≥14B); the emerging norm is hybrid — deterministic checks
  first, LLM judgment only where rules can't reach, with humans on the
  boundary.
  → **The campaign-#1 classifier uses zero LLM calls.** All four labels are
  decidable deterministically here because the platform has an unusual
  advantage: a deterministic oracle (`deterministic.execute`) for numeric
  questions, a full-schema catalog (`TABLE_AREAS`/live schema) for the
  nonexistent-table check, and policy tables for allowed/denied
  ground truth. An LLM judge would add cost and unreliability to gain
  nothing. If a future question class genuinely needs semantic judgment,
  it gets a capped LLM tie-breaker with its verdicts marked LOW-confidence.
- **Eval-gated repair prior art** ([Phoenix, arXiv:2606.20243](https://arxiv.org/html/2606.20243v2);
  [RepairAgent](https://github.com/sola-st/RepairAgent); the SWE-agent /
  AutoCodeRover / Agentless family): the common safety pattern matches the
  plan's §8 design — reproduce first, baseline test run before any change,
  change gated on before/after comparison, PR as the only exit, human merge.
  Phoenix specifically layers "baseline-aware test evaluation" + PR-only
  output; that's independent confirmation the eval-gate design here is the
  field's consensus shape, not an invention to defend.

### Agent operational memory — the design (replaces the illustrative scheme)

Two layers, both in `store.py`'s SQLite (one local state store; no new
storage system):

1. **`sim_pattern_stats` (structured, numeric, the workhorse).** One row per
   (company, pattern_family, difficulty, role): candidates run, passes,
   failures surfaced, findings confirmed, LLM calls spent, last campaign id.
   Updated by aggregation only — compaction is lossless arithmetic, no LLM
   involvement, unbounded history folds into bounded rows. This is what
   "prefer higher hit-rate patterns" reads, and it doubles as the §5
   self-measurement trend data.
2. **`agent_lessons` (episodic, bounded, append-only).** Raw lesson entries:
   campaign id, what was attempted, what happened, evidence (trace/finding
   ids — required, no free-floating beliefs), scope tags, expiry. Never
   LLM-rewritten (per arXiv:2605.12978); bounded by eviction of expired or
   least-referenced entries beyond a cap (~40), with evicted entries retained
   in the row but flagged inactive rather than deleted (episodic record
   preserved). Runner + classifier read active lessons at campaign start —
   they're structured enough that "reading memory" is a cheap SELECT, not an
   LLM summarization pass, which is exactly what a weak-brain loop needs.

What deliberately does *not* persist: narrative self-assessments without
evidence links, and any lesson that would permanently disable a question
family (deprioritize only — see over-generalization risk above).
