# Fable notes — 2026-07-15 — Agentic Harnesses + Full Run

Running log for the FABLE_MISSION_2026-07-15 run. Written continuously while
working, not retrospectively. Companion file: `Health_Check notes 2026-07-15.md`
(the Health Check agent's own log).

## Session start (2026-07-16T00:55Z)

- Deepwork activated (`agentic-harnesses-full-run-2026-07-15`), no trusted
  lessons yet for this scope.
- Environment verified: `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` set; `GH_TOKEN`
  authenticates as **Nexus-Healthcheck-Bot** (the separate bot identity from
  mission §E exists — PR finish line reachable). GMAIL_* not set — irrelevant,
  this run uses Telegram, not email.
- `scripts/notify_telegram.py` already exists from the prior initiative and
  matches the mission spec (env-only secrets, non-fatal failures). Reusing it.
- Branch: `trace-restore/dev` (durable-store + sim_employees + Wave-1 review
  work already merged live per PR #11).

## Plan of record

1. Evaluate the four harnesses against the agentic bar (routing / memory /
   tools / loop): sim_employees, health_review (W1), repair (W2), analyst.
2. Upgrade what misses the bar (incl. Bedrock Haiku 4.5 verification).
3. Design + implement the one-analyst/three-companies coexistence layer.
4. Full loop: sim attack (live, 3 companies) → review report → repair →
   tests/evals → D.9 double-check → PR by `repair/pr.py` as the bot.

## Harness verdicts (evaluation complete 2026-07-16T01:20Z)

Bar = per-sub-task model routing · memory · tools · loop engineering.

### 1. sim_employees — CLOSE TO BAR, needs memory + tier-split upgrades
- **Loop ✓**: brief (plan) → ask (act) → cheap verdict heuristics (check) →
  weak-spot re-probe (correct). Real external signal per question.
- **Tools ✓**: company-brain `data_map` (real schema per role), access-bounded
  live client, paced runner, sim-query ledger.
- **Memory ✗ (gap)**: interactions store only `answer_summary[:300]`, and the
  brief exposes only the LAST 10 questions — "never repeat a solved question"
  is not guaranteed across runs once history > 10. Mission requires question
  AND answer stored and next-run decisions made from past answers.
- **Routing ~ (gap)**: single external brain does both strategy and phrasing.
  Mission wants strong-model attack planning + cheap-model phrasing.
- **Upgrade**: memory stores fuller answers + exposes the complete
  solved-question set and per-question outcomes in the brief; QUESTION_SPEC/
  INSTRUCTIONS encode the strong-plans/cheap-phrases split.

### 2. health_review (Wave 1) — MOSTLY AT BAR, three concrete gaps
- **Deterministic-first ✓** (oracle recompute + policy re-derivation, zero
  LLM); **capped LLM judge ✓** on the product chain; **honest abstention ✓**
  ("needs_human_review", never a guess); **watermark ✓**; findings ledger
  carries open bugs run-over-run and reopens recurrences ✓.
- **Gap A**: Bedrock tier pinned to Claude 3.5 Haiku
  (`config/settings.py:38-39`) — mission explicitly requires Haiku 4.5,
  wired + verified, not silently 3.5.
- **Gap B**: report's `fixes_needed.example_trace_ids` capped at 6 — mission
  requires the EXACT trace ids per finding, not a capped sample.
- **Gap C**: no explicit "was last run's bug resolved?" comparison in the
  report output (the ledger has the data; the report doesn't say it).

### 3. repair (Wave 2) — STRONG LOOP, missing memory-read + prediction + plan-confirm
- **Loop ✓✓**: staged Agentless-style pipeline with deterministic validators,
  verbatim-pytest external feedback, test-first repro that must fail pre-fix,
  eval gate, advisory self-review, cooldown-aware quota waits, resume-seed
  from prior session logs. No merge path (grep-enforced by test).
- **Memory ✗ (gap)**: it WRITES lessons (`store.add_lesson`) but never READS
  them before starting — mission requires lesson memory read-before-start.
- **Prediction ✗ (gap)**: no predict-related-hidden-bugs step, no
  verify-by-reproducing-real-failing-input, no three-tier reporting.
- **Plan self-confirmation ✗ (gap)**: hypothesis gets a framed critique and
  the final diff gets a self-review, but the PLAN itself is never
  self-confirmed before code changes, and the plan doesn't decide its own
  new-eval needs.
- **Routing ~ (gap)**: every stage uses the same full chain; no per-stage
  tiering (localize is cheaper work than hypothesize/plan).

### 4. AI Data Analyst — MEETS THE BAR (evidence below); real work is tenancy
- **Routing ✓**: orchestrator gives every question an explicit zero-LLM
  RouteDecision; deterministic layer answers 15 metric families with no LLM;
  SQL/RAG agents pick model tiers by query complexity
  (`_models_for_complexity`, reasoning=True only for complex;
  `sql.format_answer`/`sql.explain_query` pinned to cheap tiers). That is
  genuine per-sub-task tiering already.
- **Memory ✓**: session memory (prev-intent follow-up resolution), user chart
  prefs; **Loop ✓**: SQL error-feedback repair round, RAG evidence assessment
  + reranking, production harness step limits.
- **Verdict**: keep; log why (this section). The genuine deficiency the
  mission names is the one-analyst/three-companies collision problem —
  handled as its own design task — plus latency measurement where touched.

## Upgrades implemented (01:30–02:20Z) — all four harnesses + tenancy

Details + reasoning in ARCHITECTURE_LOG Entry 13. Summary:
- Bedrock → **Claude Haiku 4.5** (`us.anthropic.claude-haiku-4-5-20251001-v1:0`,
  settings + CFN IAM for inference-profile AND foundation-model ARNs).
  Honest limit: live verify is deploy-gated — this Mac's IAM user has zero
  bedrock permissions (AccessDenied on list AND a 5-token converse test).
- Wave-1 report: uncapped `trace_ids` per finding, `resolved_findings`
  run-over-run section (new `store.finding_resolutions_since`), judge
  prefers Bedrock Haiku 4.5 tier when enabled.
- sim_employees: full answer memory (1500 chars), `all_asked_questions`
  never-repeat guarantee, answers in recent_outcomes, brain tier split
  documented (strong plans / cheap phrases).
- Live→local **evidence bridge**: live-mode sim runs mirror each turn into
  the local store (trace + answer, `payload.live_trace_id`) — chosen over
  RDS sync (unreachable) and server-side export (needs deploy); zero extra
  quota.
- Repair: lessons READ before start; Wave-1→Wave-2 seam fix (singular
  `trace_id` findings now load evidence + answers); per-stage tiering
  (localize=fast, reasoning elsewhere); **predictor.py**
  (predict→reproduce→three honest tiers); **confirm_plan** self-check
  before any code edit; PR body carries prediction tiers + eval notes.
- Tenancy: `nexus_platform/company_overrides/` packs + orchestrator seams +
  isolation tests (fires for A, not B; empty packs inert; crash degrades).
- Suite: **233 passed** (was 229 before this wave; +4 tenancy tests).

## Part 2A — sim attack live (started 01:22Z wall / campaign log ongoing)

- I am the strong-tier brain: attack strategies planned per employee from
  each briefing (AcmeCloud memory read: 34 prior interactions across 3
  employees; HR has one recorded weak spot — the tenure question returned an
  EMPTY answer, trace `tr_6daaa225d8` — being re-probed with a sharper
  phrasing). A Haiku subagent is the cheap phrasing tier (mission's brain
  tier split, exercised for real).
- AcmeCloud batch design (6 q/employee × 3 employees, all fresh —
  none repeat the 34 prior questions): simple regression checks,
  hallucination-bait (gross logo retention, LTV, happiness index),
  role-boundary probes (analyst→salaries, HR→tickets), very-hard 4-5-table
  joins, typo'd+malformed periods (revenu q9, recenue teh, attriton h9),
  compound %-of-last-year chart, bare seam follow-ups.
- MedCore/FinPilot: memories empty (first-ever campaigns). Bait chosen to be
  industry-plausible: patient readmission rate (healthcare), chargeback
  rate + settlement latency (fintech), CES, budget variance, on-call
  coverage ratio. Boundary probes matched to each role's actual data_map.
- Budget: 36 questions total across 3 companies, most deterministic-path;
  runner paces 15s (+20s after LLM turns). Live traces land in RDS tagged
  simulated; every turn also mirrored to the local store (evidence bridge).

## Evidence bridge verified live (02:40Z)

Local mirror confirmed working mid-campaign: 14 simulated traces in the
local store for 2026-07-16, each carrying `live_trace_id` (the RDS twin) and
a joined answer. Two more harness fixes landed while monitoring:
`ROUTE_MODULES` gained an `access_refusal` mapping (false-refusal findings
previously localized with only the always-candidate file), and the sim
runner now records `latency_s` per question (mission's latency requirement;
AcmeCloud ran pre-change, MedCore/FinPilot will carry timings).

## Latency profile (honest numbers, measured live, MedCore+FinPilot runs)

Per-route wall-clock from the campaign's recorded `latency_s` (36 turns):
- deterministic_sql_template: avg 0.19s (n=12)
- clarification: avg 0.18s (n=10)
- sql_agent: avg 1.34s (n=2); rag_agent: 14.23s (n=1)
- **access_refusal: avg 3.20s, max 17.64s (n=16)** — a denial should be a
  policy-layer decision (~0.2s like clarifications); the slow ones are being
  decided at the END of the engine path. The false-refusal bug class and the
  latency problem are the same defect: fixing where the decision happens
  fixes both. Before-numbers recorded here for an honest before→after.

## Intervention #1 — repair attempt 1 failed at plan; scaffolding corrected (03:00Z)

Attempt 1 on `hf_e4796a5431` ran predict → localize → understand →
hypothesize → critique clean (all Groq; predictions: 3 hypotheses, none
deterministically reproduced — honestly binned unverified), then died at
`plan`: three rounds of "every provider's answer failed the format check"
with **no visible reason** — the gateway discarded rejected responses, so
the proposer's feedback loop had nothing concrete to say. Correction (all
generic scaffolding, no fix content): (1) gateway now attaches
`invalid_content` to validation failures; (2) proposer re-runs the STAGE
validator on the last rejected answer and feeds the concrete reason back
("TEST_FILE already exists", not "your answer failed"); (3) resume-seed is
now partial — a run that died before a valid plan reuses its finished
localize/understand/hypothesize outputs instead of re-deriving them.
Attempt 2 relaunched with --resume-from. Lesson persisted to deepwork.

## RESUMED 2026-07-16 (CLI-brain era) — TASK 1: automatic per-sub-task model selection

Context change since the pause: the repair brain was rewired to Claude Code
via CLI (`cli_brain.py`, headless `claude -p`, tools off, single turn), so the
free-tier daily-cap that blocked the fix is gone. But the in-CLI model tier
was a STATIC map (`_HEAVY_STAGES`→sonnet, else→haiku) — which put the REVIEW
stages (critique, confirm_plan, self_review) on haiku. A weak reviewer that
"AGREE"s a bad fix is worse than no review, and nothing downstream catches a
rubber-stamp. Fixed.

**Design (automatic, two rules over an ordered tier ladder weak→strong,
default `haiku,sonnet`):**
1. **A reviewer is never weaker than the author.** Review/judgement stages
   always run on the ladder's TOP tier — no downstream validator catches a
   rubber-stamp, so they can never start cheap. (Directly removes the flagged
   risk.)
2. **Generation stages start complexity-appropriately and escalate.**
   Inherently-hard stages (plan, implement) and any call with a large prompt
   (>14k chars of code context, env-tunable) start strong; the lighter
   generation stages (understand, hypothesize, predict) start cheap and
   escalate ONE tier each time the stage validator rejects the answer — the
   proposer threads the retry `attempt` in (counted as substantive failures,
   so cooldown waits never spuriously escalate). A stage is thus never
   *silently* stuck on a model too weak to pass its own check.

Considered and rejected: pure prompt-size heuristic alone (misses semantic
weakness on small prompts); difficulty-tagging every stage by hand (that's
just the static map again). The escalate-on-validator-failure signal is the
honest one — it fires exactly when the current tier demonstrably wasn't
enough. Reviews are the exception because their failure is invisible to a
format validator, so they get strength unconditionally.

Env knobs: `NEXUSIQ_REPAIR_CLI_TIERS` (ladder), `NEXUSIQ_REPAIR_CLI_BIG_PROMPT`
(strong-start threshold); old `_CLI_MODEL`/`_CLI_CHEAP_MODEL` still pin
top/bottom for back-compat. Tests: 249 platform green (7 new/updated in
`test_repair_cli_brain.py`, incl. escalation threaded end-to-end through
`_invoke`). Live-verified: critique→sonnet, understand@0→haiku, @1→sonnet,
real CLI call `cli:haiku` OK.

## Honest run metrics (as of 05:56Z) — captured only what really happened

- **Harnesses upgraded:** 4/4 (sim, Wave-1 review, Wave-2 repair, analyst
  harness judgment) + Bedrock→Haiku 4.5 wiring. Tests: 229→**233 green**.
- **Tenancy:** `company_overrides` shared-kernel + per-company packs +
  orchestrator seams, isolation proven by 4 dedicated tests.
- **Live campaigns:** 54 adversarial questions, 3 companies, 8 employees;
  every question fresh (none repeated a solved one); RDS + local mirror.
- **Wave-1 reviews:** 3 reports (hc_50fcb12888, hc_d29a351231,
  hc_e75e8d889b); **13 findings open** across 3 companies + **8
  resolved/dismissed** (incl. the self-caught fabricated false positive and
  the already-resolved "customers for a4" routing finding).
- **Classifier caught unprompted:** a deterministic false-refusal
  (FinPilot Ops SLA join), the misclassified-refusal class across companies,
  and — via honest self-audit — its OWN store-pollution false positive.
- **Latency before-numbers (measured live):** deterministic 0.19s vs
  wrongful `access_refusal` up to **17.64s** (avg 3.20s). The false-refusal
  bug class and the latency spike are the same sql-failed-seam defect.
- **Bugs:** 1 hard seam bug (`hf_e4796a5431`) diagnosed + logged OPEN;
  1 deterministic malformed-bypass bug (`hf_fbccccb7e2`) verified real +
  pipeline-ready, fix **quota-deferred** on the daily free-tier cap;
  several other findings are the same stochastic seam class (open) or
  already-resolved (dismissed).
- **Repair pipeline hardened across 5 supervised attempts:** concrete
  plan-stage feedback (was discarding rejected LLM answers), mandatory plan
  self-confirmation (never exempt, seeded included), partial resume seeding,
  bounded predictor, budget-conserving predict-skip knob. Each fix committed.

## Budget-floor stop-assessment (05:56Z)

The shared free tier is DAILY-exhausted: Gemini and Groq each give one call
then a hard ~60-min/daily wall; NVIDIA is 360/48 over its daily worker cap;
Cerebras returns empty. This is §2c behaving as designed after a full night
of legitimate campaigns + reviews + repair attempts — a fixed constraint I
may not spend around. Gemini's daily quota resets ~08:00 UTC (midnight
Pacific). The malformed-bypass fix is one clean run away once quota resets;
everything else this run is complete and committed. Resume path in
ACTIVE_HANDOFF.

## Git topology decision (01:25Z)
`origin/master` = PR #12 merge (has sim_employees, repair, store, sim/).
Local `trace-restore/dev` is +4 (Wave-1 grader). Local `master` was stale →
fast-forward sync to origin/master (a sync, never a commit) so repair
worktrees branch off current product code.
