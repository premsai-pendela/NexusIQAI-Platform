# FABLE MISSION — 2026-07-15 — Agentic Harnesses + Full Health-Check Run

**This file is THE mission for this run.** The older `CONTEXT.md`,
`HEALTH_CHECK_AGENT_MISSION.md`, and `SELF_IMPROVING_HEALTH_CHECK_AGENT_PLAN.md`
in this folder were the *previous* run's mission — read them only for the
**fixed rules and existing mechanics that still apply** (free-tier budget
floor, the structural no-auto-merge gate, the GitHub setup, the staged-repair
design). **Where they conflict with this file, this file wins** — including
where they say "wait for Prem" or "never edit the analyst" (both changed below).

## Autonomy — read this first
- **Run start to finish without stopping.** There are **no human confirmation
  gates** in this run. The only thing that stops you is the **final goal being
  fully met** (see Stop condition). No excuses, no exceptions.
- **The confirmations in this run are the agents confirming their *own* work,
  not asking a human.** Specifically, the Health Check must **self-review and
  confirm its own fix plan (and its own guardrails/evals) before it changes any
  code** — a self-check step, not a pause for Prem.
- **`ACTIVE_HANDOFF.md` is your resume anchor.** Update it continuously at every
  milestone. If you are ever cut off (context limit, crash), you resume by
  reading `ACTIVE_HANDOFF.md` and continuing — never by re-deriving the whole
  context. This is how "never stop" survives interruptions.
- **Telegram glance on every handoff update.** Each time you update
  `ACTIVE_HANDOFF.md`, also send Prem a **2–3 line plain-language glance** of that
  update (what the update was about — what just changed, what's next) via a
  Telegram bot. Build one small reusable `scripts/notify_telegram.py` that reads
  `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from the environment (never hardcode
  either — same rule as the GitHub token) and POSTs to the Telegram Bot API. Keep
  it short; this replaces the old email checkpoints. If the env vars aren't set,
  log that and keep going — a missing notifier is never a stop condition.
- Run under **`/deepwork`** (scratchpad + honestly-scored lessons).
- You decide everything inside the guardrails; make your own plan to reach the
  goal. The work below is the required outcome and its proof, not a script.

## Read first
1. `CONTEXT.md` + `CLAUDE.md` (this folder) — fixed rules + model-routing rules.
2. `RESUME_CONTEXT_FOR_METRICS.md` (this folder) — **why this run exists**: the
   resume reviewer's (Murta's) comments, the honest-metrics intent, and enough
   NexusIQ context to know what evidence would actually help. Read it fully.
3. The code you will evaluate and run: `sim_employees/*` + its `INSTRUCTIONS.md`;
   `nexus_platform/sim/*` (the *other* sim — see below); the Wave-1 grader
   (`nexus_platform/health_review.py` is the current per-trace grader with the
   downloadable report; `nexus_platform/health_check.py` is its older sibling —
   evaluate both, treat `health_review.py` as Wave 1); `nexus_platform/repair/*`
   (Wave 2); and the AI Data Analyst path (`query_service.run_query` →
   `orchestrator` → `deterministic.py` / `agents/*`).

## CRITICAL — two sims; use the agentic one
- **USE `sim_employees/`** — the agentic CLI sim where **you are the brain**:
  `python -m sim_employees.brief` gives each employee's role, real schema
  `data_map`, past questions and weak spots; you author 5–10 adaptive adversarial
  questions per employee; `python -m sim_employees.ask --target live` drives the
  deployed API so traces land in **RDS** and show on the **live Review page**,
  tagged `source="simulated"`.
- **DO NOT USE** `scripts/run_sim_campaign.py` / `nexus_platform/sim/` for this
  run (deterministic template campaign — leave it as-is).

---

## PART 1 — Make the four harnesses genuinely agentic (evaluate → upgrade)
Four harnesses: (1) sim employees, (2) health review (Wave 1), (3) health check
/ repair (Wave 2), (4) **the AI Data Analyst itself** (the most important).

For **each**, read its present harness and judge it against this bar:
- **Per-sub-task model routing — deliberate tiering, not one model for the whole
  harness.** A cheap model for cheap/simple sub-tasks (phrasing a question,
  formatting, summarizing, reading a report, localizing a file); a **strong**
  tier for genuine reasoning (diagnosis, fix design, hidden-bug prediction,
  writing the code + regression tests). **For the health check / repair (Wave 2)
  the strong tier is Claude Code invoked via CLI** — a headless subprocess the
  agent shells out to, exactly like the sim-employee CLI brain — because weak
  free-tier models cannot do complex program repair (this is the corrected §2e;
  the old "free-tier chain writes the fix" rule is superseded — see below). The
  harness should **decide the tier per sub-task automatically and run it**, and
  keep cheap work on cheap models even inside the CLI health check.
- **Memory** — the working memory (live scratchpad) *and* the persistent memory
  each harness needs, at the right scope (see each harness's specifics below).
- **Tools** — the tools that sub-task actually needs (schema/data map, code
  access, trace access, eval/test runners); add external tools/skills if they
  genuinely help.
- **Loop engineering** — a real loop (plan → act → check against a concrete
  external signal → correct on feedback), not a single shot. Weak free-tier
  models need external correction signals between steps.

If a harness meets the bar → keep it, log **why** (with evidence). If not →
**research prior art (internet), plan, and implement** the upgrade. You decide
and proceed (log the decision in `ACTIVE_HANDOFF.md` + your notes) — **no human
gate.**

**Harness-edit boundary (resolves the old contradiction):** you (Fable) may edit
the **harness** — the routing, memory, loop, and tool *plumbing* of any of the
four, including the AI Data Analyst's harness. You may **never hand-write, in
this interactive session, the code *inside* it that fixes a specific product
bug** — that always goes through the **repair agent's own autonomous loop, whose
reasoning brain is Claude Code invoked via CLI** (the corrected §2e). The agent
does the diagnosing and fixing autonomously (it shells out to Claude Code
headlessly for the hard sub-tasks); you never hand-patch the fix in chat.

### Per-harness specifics
1. **Sim employees.** Memory must **store each question AND the analyst's
   answer**, per employee per company (`sim_employees/memory/<company>/<email>.json`),
   so the next run reads it, **never repeats a solved question**, and **decides
   what to ask next from those past answers** (re-probe weak spots harder). Empty
   memory → all fresh. Split the brain by tier: strong model plans each
   employee's attack strategy; cheap model phrases the questions.
2. **Health review (Wave 1).** **Deterministic-first** (recompute ground truth /
   re-derive refusal correctness — milliseconds, no LLM). Only when a trace is
   *not* deterministically decidable, escalate to an LLM reviewer (**AWS Bedrock
   Claude Haiku 4.5** on the product's chain — deliberate: Haiku 4.5 is the newer
  model, so wire it in / verify it is available in the account, do not silently
  stay on 3.5). If the LLM still cannot be sure,
   it must **say so explicitly ("cannot be sure on this trace — needs human
   review")**, never guess. Memory: a **watermark** of the last trace reviewed
   so the next run starts from there, and it must **read its own past reports**
   and compare bugs run-over-run (was a past bug resolved or not?). Output: a
   **downloadable report** listing, per finding, the bug, severity, plain-English
   explanation, and the **exact trace ids** (not a capped sample).
3. **Health check / repair (Wave 2).** Its own **lesson memory** ("this bug →
   fixed this way"), read before starting so it doesn't re-derive solved lessons.
   Reads the review's report **and past reports** and its lessons to see which
   bugs are already solved vs open. **Company-scoped** — a health check for one
   company works only that company's findings/brain/traces. Full flow per bug:
   understand → **predict related hidden bugs and verify each by reproducing a
   real failing input** → write a careful agentic fix plan **plus its own
   guardrails/evals** (decide what new evals a code change needs and write them)
   → **self-confirm the plan** → fix → recreate every bug as a regression test →
   run tests + evals; on failure, go back, re-plan, re-fix (**always plan before
   changing code**).
   **Model routing inside this CLI health check (corrected §2e):** the hard
   sub-tasks — diagnose from traces, predict hidden bugs, write the fix plan,
   write the code + regression tests, final pre-PR review — run on **Claude Code
   via CLI** (a headless subprocess the runner invokes, like the sim-employee
   brain); the cheap sub-tasks — reading the report, localizing files,
   deterministic grading, formatting notes — route to **cheap/free-tier**
   models. **Never** run the code-writing on the weak free-tier chain: that was
   the old rule and it demonstrably could not do complex repair (and got
   quota-blocked). The rewiring of `nexus_platform/repair/` from
   `utils/llm_gateway.invoke_with_fallback` to a CLI-invocation brain for the
   hard stages is part of this harness upgrade.
4. **AI Data Analyst.** Judge its routing (is it genuinely per-sub-task?),
   memory, and loop/self-correction. Upgrade its **harness** as needed (see the
   boundary above).

### The one-analyst / three-companies bottleneck (research + solve)
One AI Data Analyst serves all three companies. A fix for AcmeCloud in a file
can clobber or collide with a fix for MedCore in the same file → new bugs.
**Research how real production systems handle one service across many tenants**
(multi-tenancy, per-tenant config/logic, scoped modules, feature flags — verify
claims against primary sources, not SEO filler), then **reason, plan, and
implement** a design that lets company-specific fixes coexist without clobbering
each other. This is genuinely hard and is yours to design.

---

## PART 2 — Run the full loop end-to-end, then open a PR

**A. Sim employees attack the analyst (you are the brain).**
Drive `sim_employees/` `--target live`, company by company (AcmeCloud → MedCore →
FinPilot), covering the curated demo logins (a few roles per company across all
three). Traces land in **RDS** (shown on the live site) tagged
`source="simulated"`; per-employee answer-memory updated; pacing respects the
budget floor. **Evidence plumbing (yours to solve):** the traces must be in RDS
for the live display, *and* the local repair pipeline must be able to read the
evidence it needs (it reads the local store today, and this machine can't reach
prod RDS). Design the bridge — a local mirror of the same run, an RDS→local
sync, or a server-side review that exports report/findings you pull local —
minimizing extra quota. Log the choice and why.

**B. Health review → downloadable report (Wave 1).** Run it over the resulting
traces (deterministic-first, Haiku-4.5 fallback, honest "cannot be sure"),
producing the downloadable report + updating the watermark, comparing against
past reports.

**C. Health check — understand, predict, plan (Wave 2).** Per the harness spec
above: read report + past reports + lessons, company-scoped, understand each
bug, predict-and-verify hidden bugs, write the plan + own evals, self-confirm.

**D. Fix + tests + evals.** Implement the fix; every bug (surfaced +
verified-predicted) becomes a deterministic regression test that fails before /
passes after; run the new evals; zero regressions; a regression → discard the
branch, log, move on.

**D.9 Final double-check before any PR (both agents, in order).** Nothing is
pushed until two checks pass: (1) the **Health Check re-verifies its own
completed work end-to-end** — every fix still holds, every regression test and
new eval passes, nothing regressed; then (2) **you (Fable) independently verify**
the same. Only after both pass does the PR step run.

**E. Open the PR under the Health-Check bot identity (never merge).** The agent's
own `repair/pr.py` pushes and opens the PR with before/after evidence + the
report referenced. The PR is opened under a **separate Health-Check bot GitHub
account, not Prem's** — so the PR reads as the bot's work, not Prem opening his
own PR. `repair/pr.py` authenticates with the bot account's token (`GH_TOKEN` =
the bot's fine-grained PAT, provided via the environment — never hardcoded).
Prem, as a *different* identity, reviews and merges — which also keeps the
human-review gate clean (the bot is the PR author and cannot approve its own PR).
Opening the PR is the finish line; merging is never yours (never attempt, no
merge code path).

> **SETUP REQUIRED (Prem, one-time, before this step):** create the bot's GitHub
> account, generate a fine-grained PAT scoped to `premsai-pendela/NexusIQAI-Platform`
> (`contents: read/write`, `pull_requests: read/write`), add the bot as a
> collaborator with write access, and export that PAT as `GH_TOKEN` in the run's
> shell. Until that exists, the loop runs fully but stops short of the push/PR
> step and logs the fix as "verified, ready to publish."

---

## Truthfulness AND latency
The analyst runs on free-tier credits; complex queries can be slow or land a
wrong answer. The bar is **accurate *and* low-latency** — not "accurate even if
slow." Keep answers truthful, and where the health check touches the analyst's
harness, **measure where latency is spent and reduce it** without sacrificing
accuracy. Log latency before/after.

## Metrics — honest, opportunistic (not manufactured)
Do **not** manufacture metrics or change behavior just to produce a number. As
the loop runs, **notice whether real before→after improvements naturally occur**
(a bug's fabrication gone, an eval pass-rate lift, a latency drop, N bugs caught
and fixed) and record the real ones. `RESUME_CONTEXT_FOR_METRICS.md` explains
what kind of honest evidence would let the reviewer's (Murta's) "action +
process + **metric**" point be satisfied — understand those comments and the
NexusIQ context so you know what's worth capturing, then only capture what
truly happened.

## Working memory + logging
- **Scratchpad:** run under `/deepwork` (live notes + scored lessons).
- **Dated notes files, written continuously while you work and while you monitor
  the agents** (not retrospectively):
  - `docs/platform improvements/fable notes 2026-07-15.md` — Fable's own running
    log: harness verdicts + reasons, decisions, what each agent is doing, where
    one went vague and how you corrected it, the honest run numbers.
  - `docs/platform improvements/Health_Check notes 2026-07-15.md` — the Health
    Check's own log: each finding→traces, each prediction and whether it
    reproduced, the plan, its self-confirmation, before/after test + eval output,
    latency numbers, the PR link.
- Keep `ACTIVE_HANDOFF.md` (resume state) and `ARCHITECTURE_LOG.md` (design
  reasoning) current and separate.

## Monitor and intervene
You (Fable) monitor every harness while it runs. If the sim employees, health
review, or health check **goes vague, broad, or off-target**, stop that agent
immediately, make the specific correction, and resume/restart it — don't let it
spin. Log the intervention.

**Supervise the repair quality — re-loop the Health Check if the fix is not
genuinely done.** After the Health Check repairs a bug, you verify it was fixed
*properly* — not merely that a test went green, but that the fix truly addresses
the **class** of failure, is in the right scope, and introduced no regression. If
it's inadequate (superficial, wrong scope, the class isn't actually fixed, or it
regressed something), **send the Health Check back to change its fix plan and
re-implement** — loop it (re-plan → re-fix → re-test) until the fix is genuinely
correct, or until it's honestly logged as currently unreachable. You supervise;
the Health Check's own autonomous loop still does the diagnosing and fixing —
its reasoning brain is Claude Code via CLI (corrected §2e). You never hand-write
the fix yourself in this session; the agent invokes the CLI to do it.

## Fixed constraints (not yours to loosen)
- Never merge; never touch secrets/`.env`/tokens; never change repo security
  settings; never force-push or touch `master`.
- Simulated traffic is always `source="simulated"`, never mixed into real
  reporting.
- Never exhaust the shared free-tier quota — the §2c caps are a floor.
- Predicted bugs count only if they reproduce; report three tiers separately
  (surfaced / predicted-and-verified / predicted-unverified hypothesis);
  prediction prompts stay generic (never encode a specific bug's fix).

## Stop condition
The only thing that stops you is the goal being fully met, with real evidence:
the PR is open; every surfaced + verified-predicted bug is fixed with a passing
regression test and any needed new eval — or, for a genuinely hard bug that survives real
re-plan/re-fix loops, honestly logged as open/unreachable (an honestly-open bug
does not block the goal); the downloadable report exists; the
one-analyst/three-companies design is implemented; and both dated notes files +
`ACTIVE_HANDOFF.md` are complete. Everything else — a failed campaign, a
non-reproducing prediction, a regressing fix — is a data point: log it, adjust,
keep going.

**On stop, send the final Telegram message.** The moment you actually stop
(goal met), send one last Telegram message via `scripts/notify_telegram.py`:
start it with **"✅ Run done — stopped."** then a 2–3 line summary — bugs fixed
(surfaced + verified-predicted), the PR link, and the key honest numbers
(before→after). This is the one message that tells Prem the whole run is over.
