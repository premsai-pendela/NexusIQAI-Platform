# Mission: Self-Improving Health Check Agent

**Read `HEALTH_CHECK_AGENT_MISSION.md` in this same folder before this
file** — it corrects who performs the diagnose/fix/test/PR steps described
in §2e below (the Health Check Agent's own code, not Fable directly). That
correction supersedes the parts of this file it conflicts with.

Read `CLAUDE.md` in this same folder first — it tells you which model to use
for which kind of task in everything below. Then read this whole file before
doing anything else.

## The final goal, stated explicitly

Turn `nexus_platform/health_check.py` — today a **read-only** report
generator that only analyzes traces/feedback that already exist — into a
closed loop that:

1. generates realistic simulated employee traffic against the AI Data
   Analyst (Platform Mode), across roles and companies,
2. classifies each simulated answer as correct / wrong / vague / exceptional,
3. for real findings, diagnoses the actual cause by reading the relevant code
   and the company's document corpus,
4. implements a fix on a branch, verifies it with before/after tests, and
5. opens a pull request for a human (Prem) to review and merge — never
   merging on its own.

**"Final goal satisfied" means every one of these is true, and you can point
at real evidence for each (a PR link, trace ids, eval output — not a
description of how it would work):**

1. A simulation campaign ran against at least one real company in this
   platform (start with AcmeCloud, since bug #1 below is already confirmed
   there), producing traces tagged `source: simulated`.
2. The Health Check agent's classifier — running on its actual available
   models, not an assumed frontier one — independently flagged bug #1 (or
   whatever real issue actually surfaces first) as an `exceptional` finding,
   *without being told in advance where to look*.
3. A branch was created, a fix implemented, and the existing test suite plus
   a targeted repro were run **before** (showing the failure) and **after**
   (showing the fix, with zero new regressions).
4. A real pull request is open against
   `premsai-pendela/NexusIQAI-Platform`, with the before/after eval evidence
   in the PR body, waiting on Prem's review. (Opening it is the finish line —
   you do not need Prem to actually merge it for the goal to count as met;
   merging is explicitly not your job.)
5. `ACTIVE_HANDOFF.md` and the architecture log (§3 below) both reflect the
   real history of how this was reached, so Prem can review it without
   re-reading every session's transcript.
6. The whole run respected the shared free-tier LLM budget throughout (see
   "The real constraint" section below) — it didn't quietly need a paid or
   assumed-available frontier model to get here.

**This is the self-check you run against yourself, continuously.** If any of
the six is not yet true, that *is* the definition of "goal not met" — don't
wait to be told. Diagnose specifically which one failed and why (a
simulation campaign that produced no signal? a classifier that missed a real
bug or flagged a false one? a fix that didn't hold under the after-tests? a
PR that couldn't be opened?), then loop back into whichever of
research/plan/implement/test that failure implicates, and try again. Log the
attempt and what you learned from it (§3 below) either way — a failed
attempt that teaches you something is not wasted, an unlogged one is.

This is not a one-shot task and it is not a task with scheduled pauses. Work
it as a continuous loop — research → plan → implement → test → diagnose →
retry — across as long as it takes, in one session or many. **Do not stop to
ask permission between iterations, and do not wait for Prem — he is not
available while this runs.** The only thing that actually stops you is the
goal above being fully met. Everything that isn't the goal being met is a
decision you make yourself, inside the guardrails you write for yourself in
Step 0.5 below. Log continuously as you go (§Step 1 and §3) so the work is
auditable and resumable — logging is not the same as stopping, keep moving
after you write the entry.

## Step 0 — Orientation (do this before writing anything)

Read, in this order:

1. Repo-root `CLAUDE.md` — the project's overall operating rules (autonomy,
   honesty/truth rules, definition of done). These apply to everything you do
   here.
2. `docs/Current NexusIQ docs/PLATFORM_MODE.md` and
   `docs/Current NexusIQ docs/NEXUSIQAI_FULL_BUILD_REPORT.md` — how the
   product actually works today: the 4-layer access boundary, the
   deterministic-vs-LLM routing, the model fallback chain, the trace/feedback
   store.
3. `docs/Current NexusIQ docs/FUTURE_IMPROVEMENTS.md` — read the **whole**
   file, especially item **#1** ("Analyze-With-AI Mislabels Hallucinated SQL
   Tables As Access Denials"). This is a real, confirmed, reproduced bug
   already root-caused for you — use it as your first concrete target rather
   than searching blind.
4. `docs/Current NexusIQ docs/SELF_IMPROVING_HEALTH_CHECK_AGENT_PLAN.md` —
   an existing, code-grounded implementation plan for exactly this
   initiative, written by a prior planning pass. **Treat this as strong prior
   art.** Reconcile with it — extend or correct it with reasons, don't ignore
   it or redo it from scratch. If you disagree with something in it, write
   down why in `ACTIVE_HANDOFF.md` before deviating.
5. **Actually visit the live product.** Use the Chrome browser tool
   (claude-in-chrome) to open `https://nexusiq-ai.com/platform`, log in as at
   least two or three different demo roles (see
   `nexus_platform/seed/employees.json` for the real demo accounts — 3
   companies × 3 curated employees each today, plus a larger 100–150
   generated population per company not wired to real login passwords), and
   ask it real questions yourself. Don't just read about the product —
   experience it the way an employee would, including the exact
   repeat-question / "Analyze with AI" flow that produced bug #1.

## Step 0.5 — Write your own guardrails before you write any code

Prem is not available while this runs — that's the whole point of the loop.
Which means the usual "stop and ask" safety net doesn't exist here, and the
one that replaces it is **you writing down, up front, the rules that keep
this from going vague, over-broad, or out of control** — then actually
following them for the rest of the run without needing anyone to enforce
them for you.

Before writing any implementation code, write a "Guardrails" section at the
top of `ARCHITECTURE_LOG.md` (§Step 3) covering at least:

- **Scope fence.** What counts as in-scope for a "fix" (localized changes
  inside `nexus_platform/`, `agents/`, `tests/platform_mode/`, and this
  initiative's own new modules) vs. out-of-scope (rewriting unrelated
  systems, changing the product's UI/UX, touching the legacy
  `NexusIQ-recruiter-proof` or old `NexusIQ-AI` workspaces mentioned in the
  repo-root `CLAUDE.md` — none of that is this initiative's job, ever, no
  matter how tempting a "related" improvement looks mid-loop).
- **A progress-detection circuit breaker.** Define, for yourself, what
  "stuck" looks like — a concrete default, since an uncalibrated "N" tends
  to get set too high in practice: **3 consecutive attempts at the same
  finding with no new hypothesis, or the same fix attempt failing the same
  way twice in a row.** (This is a proposal like everything else — the
  "proposals vs. requirements" note in `HEALTH_CHECK_AGENT_MISSION.md`
  applies here too; tighten or loosen it with a reason, don't just leave it
  undefined.) When you hit it, the correct move is not to keep retrying the
  same approach — it's to go back further up the loop (re-research,
  reconsider the diagnosis, try a genuinely different angle) or, if truly no
  path forward exists after real attempts, narrow scope to a smaller, still-
  real sub-goal you *can* complete rather than spinning indefinitely on an
  unreachable one. Also apply this at the session level, not just per-
  finding: if you've been running for roughly 6 continuous hours without a
  checkpoint, that's itself a "stuck-or-not" question worth stopping to ask
  — not a reason to pause the loop, but a reason to write a real
  `ACTIVE_HANDOFF.md` checkpoint and honestly assess whether the current
  approach is converging before continuing another 6.
- **Budget ceilings**, consistent with and no looser than §2c's rate-limit
  and per-campaign caps — your own guardrails can be stricter than those,
  never more permissive.
- **A short review-your-own-guardrails cadence** — e.g. after every N
  iterations or every completed campaign, re-read what you wrote here and
  confirm you're still inside it; if you're not, that's itself something to
  log and correct, not ignore.

A few things are **not yours to loosen**, no matter what your own guardrails
say — these are fixed, independent of self-governance, because they're
either genuinely irreversible or outside this initiative's remit:
- Never merge anything (see "GitHub access" below — this is structurally
  enforced anyway, but don't try to work around it either).
- Never touch secrets, `.env`, credentials, or attempt to create, rotate, or
  broaden your own GitHub token's scope — use exactly the access already
  provided.
- Never modify GitHub repo security settings (branch protection,
  collaborators, permissions) yourself.
- Never force-push, delete branches other than your own throwaway attempt
  branches, or touch `master` directly.
- The rate-limit/budget floor in §2c and the "shared brain" constraint in
  Step 4 — these protect real employee traffic, not just this initiative,
  and stay fixed regardless of how confident you get that you could safely
  push past them.

Write this section once, early, and actually hold yourself to it — that's
the whole mechanism that replaces "ask Prem" here.

## Step 1 — ACTIVE_HANDOFF.md discipline

The repo already has an `ACTIVE_HANDOFF.md` at its root — this is the
project's established checkpoint file (see repo-root `CLAUDE.md`'s "Active
Handoff" section for the required format: current objective, completed
milestones, next unfinished milestone, exact resume command, tests already
run, known failures). **Use and update that same file** for this initiative
— do not create a second, competing handoff file. Add a clearly-labeled
section for this initiative so it interleaves cleanly with any other work
happening in the repo. Update it after every meaningful milestone, not just
at the end of a session — if you get cut off mid-task, the next session (or
Prem, manually) should be able to read it and continue without re-deriving
what already happened. This is explicitly about saving time and tokens
across sessions, not busywork.

## Step 2 — The mission, phase by phase

### 2a. Research: what do real employees at these kinds of companies ask?

The three synthetic demo companies in this platform are:
- **AcmeCloud Analytics** — B2B SaaS analytics (dashboards, data-pipeline
  subscriptions)
- **MedCore Systems** — healthcare operations (scheduling, claims,
  compliance tooling for outpatient clinics)
- **FinPilot Ops** — fintech payments (merchant onboarding, transaction
  monitoring, settlement reporting)

Before inventing simulated questions, research what real analysts, HR staff,
finance staff, support staff, and ops staff at comparable real companies
actually ask a BI/data-analyst tool (or a human data analyst, where an AI one
doesn't exist) — typical question shapes, typical ambiguity, typical
follow-up patterns. Ground the simulator's question style in that research
rather than guessing what "a natural human question" sounds like. Cite what
you find (industry material, real BI workflow descriptions) in
`ACTIVE_HANDOFF.md` or the plan doc — don't fabricate market research either.

Use this research to inform, not replace, the **query-log-driven generation**
approach already specified in
`SELF_IMPROVING_HEALTH_CHECK_AGENT_PLAN.md` §5 — real historical traces
already in this platform are still the primary source of grounded questions;
your research should shape *how* those get paraphrased/varied so they read
like a real person, not a template.

### The actual goal of every simulated question: try to break it

Read this carefully — it changes what "grounded, realistic" means above.
The simulator's job is **not** to politely ask normal questions and see what
comes back. It is to **actively, deliberately try to break the AI Data
Analyst** — the same way a real adversarial tester would, not the way a
cooperative user would. Realism (§2a above) is about *phrasing* — sounding
like a real employee, not a template. The *content strategy* underneath that
phrasing should be adversarial: every question should be chosen because it's
a plausible way to make the product refuse when it shouldn't, answer wrong
while sounding confident, go vague, hallucinate, or misroute — not just
because it's a question a real employee might casually ask.

**The attack surface is the question itself — not volume or rate.** This
does not relax §2c in any way: never attack via request volume, concurrency,
or anything that would exhaust the shared free-tier quota faster than a
normal question would. The attack is entirely about *what* is asked, not
*how fast* or *how often*.

Cover the full difficulty spectrum, deliberately, for every role/company —
not just easy realistic questions with a few hard ones sprinkled in:

- **Simple / direct** — single metric, single period, single table. E.g.
  "What is revenue?", "How many customers do we have?" These matter too:
  a simulator that only asks hard questions never notices if something this
  basic quietly regresses.
- **Moderate** — a metric plus a comparison, grouping, or top-N. E.g.
  "revenue by region", "compare Q3 to Q4", "top 5 products by revenue this
  year."
- **Complex** — genuinely requires joining or reasoning across multiple
  tables/concepts, not just one template. E.g. "average order value per
  customer segment, broken down by product category," "which customers have
  high usage but low payments," "churn rate by plan tier as a percentage
  trend over the last 4 quarters."
- **Compound / multi-step** — chains several of the above together, or
  crosses into the seams where deterministic and LLM paths meet. E.g.
  "plot revenue and order count together as a percentage of last year, then
  break that down by region" (multiple metrics + chart + percentage + regroup
  in one ask); multi-turn chains that reference several earlier answers at
  once ("compare the first and third things I asked about, as a bar chart");
  the repeat-question / "Analyze with AI" seam that produced bug #1;
  deliberately ambiguous or malformed phrasing; questions that mix an
  in-role and an out-of-role data area in the same sentence; questions that
  reference a plausible-sounding but nonexistent table/column/metric to see
  whether the system hallucinates one rather than saying it doesn't exist
  (exactly bug #1's failure shape, generalized).

Every one of these should map to one of the classifier's four outcomes
(§2d): a genuine bug is one that should have been correct/vague-with-good-
reason but came back wrong, confidently-wrong-but-vague, or exceptional. A
question that correctly gets refused, or correctly answered, is not a
failure to hunt for harder — it's a passing test, log it as such and move
on. The goal is finding real breaks, not manufacturing the appearance of
breaks.

### 2b. Build the simulator employees

- One simulated persona per (company, role) at minimum, matching the roles
  already defined in `nexus_platform/access_policy.py::ROLE_POLICIES`
  (Admin, CEO, Analyst, Finance, HR, Support, Ops).
- The coverage matrix from `SELF_IMPROVING_HEALTH_CHECK_AGENT_PLAN.md` §5
  (roles × companies × path_expected) needs a fourth axis added: **difficulty
  tier** (simple / moderate / complex / compound, per the attack-surface
  section above). A campaign that's balanced on the first three axes but only
  ever asks simple questions isn't actually attacking the product — make
  sure complex/compound questions are a real, tracked fraction of every
  campaign, not an afterthought.
- **The actual question-asking traffic during a simulation run should be
  driven by a cheap model (Haiku or Sonnet), not Fable** — see `CLAUDE.md`'s
  model-routing rule. Fable designs the simulator and reviews its output;
  Fable does not need to be the one generating each individual simulated
  question.
- Reuse the existing employee registry (curated demo accounts) and the
  larger generated population (`store.generated_employees`,
  100–150 synthetic employees per company already in the system) rather than
  inventing a new employee list from scratch.
- **How the simulator actually calls the product (direct backend call vs.
  driving a real browser login) is your engineering decision.** Whichever is
  more efficient — evaluate both, pick one, and write down why in
  `ACTIVE_HANDOFF.md`. The existing plan doc's default (calling
  `query_service.run_query()` directly with a constructed `AccessContext`,
  the same access enforcement as a real request, no HTTP/session overhead)
  is a reasonable efficient starting point, but if you find a concrete reason
  real browser-driven logins are necessary (e.g. to also catch frontend-layer
  bugs, not just backend ones), that's a legitimate call to make — just
  justify it, since it is meaningfully slower and costs more per question.

### 2c. Never exhaust the free-tier LLM quota

The AI Data Analyst and the Health Check agent both run on a chain of free
LLM tiers with automatic fallback: **Gemini 2.5 Flash → Groq Llama 3.3 70B →
NVIDIA NIM (deepseek-v4-flash) → Cerebras → AWS Bedrock (Claude 3.5 Haiku) →
local Ollama** (see `NEXUSIQAI_FULL_BUILD_REPORT.md` §7 and
`utils/quota_tracker.py`). Simulated traffic must never starve real employee
traffic of this budget. Mandatory:

- A deliberate delay between simulated questions that actually take the LLM
  path (deterministic-path questions make zero LLM calls and don't need a
  delay — see `deterministic.py`, `llm_skipped: true`).
- Reuse the existing shared `quota_tracker` rather than a parallel one, and
  back off / skip when a provider is already in cooldown from real traffic.
- A hard cap on LLM calls and estimated tokens per simulation run.

`SELF_IMPROVING_HEALTH_CHECK_AGENT_PLAN.md` §6 already specifies a concrete
version of this (a `SIMULATED_QUERY_DELAY_SECONDS` knob, per-campaign caps,
yield-to-real-traffic behavior) — start from that, adjust if your research
into actual observed rate limits says otherwise.

### 2d. Health Check reviews the simulated traces

The Health Check agent already runs with Admin/CEO-level access (matching
today's real Admin Review page). After a simulation campaign, it should:

- Read the resulting traces (tagged `source: simulated`, never mixed into
  real-usage reporting — this is a hard requirement, not a nice-to-have).
- Classify each answer: correct / wrong / vague-or-under-evidenced /
  exceptional-or-anomalous. The "exceptional" bucket is exactly where bug #1
  belongs — an access-denial message naming a table that doesn't exist
  anywhere in the company's real schema.
- Produce findings in the same shape the current `health_check.py` analyzers
  already use, so the existing report/coalesce/severity pipeline doesn't need
  a parallel system.
- Track its own classifier's accuracy against a small human-labeled gold set
  (Prem will need to hand-label an initial batch — flag this need in
  `ACTIVE_HANDOFF.md` when you get there rather than assuming it exists).

### 2e. Diagnose and fix real findings — an autonomous repair agent whose reasoning brain is Claude Code via CLI

> **REVISION 2026-07-16 (supersedes the earlier "free-tier chain writes the
> fix" rule below).** Prem's decision: weak free-tier models **cannot** do the
> complex reasoning of program repair — diagnosing from traces, predicting
> hidden bugs, planning a fix, writing the code and its regression tests (the
> Karpathy point: match model strength to task difficulty). So the health
> check's **second part — the repair agent — is a CLI connected to Claude
> Code** for this run. Its hard sub-tasks run on **Claude Code invoked via CLI
> as a headless subprocess** (exactly the pattern `sim_employees/` already uses
> for its external CLI question-brain), while **cheap sub-tasks stay on cheap /
> free-tier models** (per-sub-task routing, mandatory, *inside* the CLI health
> check). Everything below that says "the fix must run on the product's own
> free-tier chain / `invoke_with_fallback`" is **superseded** by this banner.
> `nexus_platform/repair/` must be **rewired** from `invoke_with_fallback` to a
> CLI-invocation brain for the hard stages.

**Why this is still autonomous and still honest (the two concerns the old rule
was protecting):**

- **Autonomy.** The worry was "the loop only ever runs when a human starts a
  Claude Code session." That is still avoided: the repair agent invokes Claude
  Code **programmatically / headlessly** (a subprocess it shells out to as a
  tool inside its own loop), not a human hand-running a session per fix. The
  loop is agent-driven end to end.
- **Honesty.** The worry was "Fable secretly does the job by hand and hides it."
  Still enforced: **you (Fable, this interactive session) never hand-write a
  specific finding's diagnosis or fix.** The difference is only *which brain the
  agent's loop uses* — a model strong enough to actually succeed (Claude Code)
  instead of a free-tier model that could not. The honest claim shifts from "the
  product's tiny free-tier models heal themselves" to "**an agentic self-repair
  harness, built on Claude Code / the Agent SDK, audits traces, diagnoses,
  predicts hidden bugs, and opens eval-gated fix PRs**" — which is both true and
  actually works.

**The actual deliverable of this step** is a real, autonomous repair agent
(`nexus_platform/repair/` + `scripts/run_repair.py`) that, given a finding,
routes each sub-task to the right tier — **cheap/free-tier** for reading the
report, localizing files, deterministic checks, and formatting; **Claude Code
via CLI** for the diagnosis, hidden-bug prediction, fix plan, and the code +
regression tests — and produces a candidate fix on a branch on its own, not
Fable doing that reasoning in its place.

Your job across this mission has two layers, and don't conflate them:

- **Build the module.** Design the prompting/retrieval/tooling so the CLI
  (Claude Code) reasoning brain does a credible job — feeding it the right
  slice of code and trace context, structuring the ask so it produces a
  localized diff rather than an open-ended one, giving it the eval/test
  runners as tools, and routing the cheap framing/localization steps to
  cheap models first so the strong CLI stage gets a tight, well-scoped ask.
  This is genuinely hard and is exactly the kind of architecture problem
  Step 4 already told you to research prior art for (don't skip that research
  for this step specifically — "LLM-based automated program repair" /
  "self-healing code" / "agentic code repair (SWE-agent / Agentless)" is real
  prior art to search for here too).
- **Validate it, don't just replace it.** Once the module exists, *use it*
  to actually diagnose and draft the fix for a real finding — run the
  module, inspect what it produces, and only step in with your own direct
  reasoning to refine the module's approach/prompting if its first attempt
  is genuinely unusable (an architecture-level fix to the module, which is
  legitimately Fable-tier work per `CLAUDE.md`), not to quietly hand-write
  the diagnosis yourself and skip exercising the module. The eval gate
  (before/after tests) and Prem's PR review remain the safety net for
  lower-quality output from a weaker model — that's what they're for. It's
  fine, expected even, if the module's first drafts need iteration; what's
  not fine is the module never actually running because it was faster for
  you to just do it yourself.
- **The bright line, stated as a concrete test, because "improve the
  prompt" can quietly become "do the job and hide it in the prompt":** you
  may rewrite the module's prompt *template*, its retrieval logic, its
  self-check step, its structure — the scaffolding. You may never write the
  actual diagnosis of a specific finding, or the actual fix content for a
  specific finding, yourself, and place that text — even paraphrased,
  even "just as an example in the prompt" — into the module's prompt,
  its output, or the branch. A useful check: could this exact prompt
  template be reused unchanged on a *different* finding it hasn't seen
  yet? If yes, it's scaffolding — fair game. If the prompt (or your
  edit to it) only makes sense because you already know what this
  *specific* bug's fix looks like, you've crossed the line, even if it's
  technically "just a prompt edit."

Be honest in `ARCHITECTURE_LOG.md` about how this went — if the module's
free-tier-generated diagnosis was weak and you had to substantially rewrite
it, say so plainly, and treat that as a real finding about the module's
current quality, not something to gloss over. This is the actual hard
engineering challenge of this whole initiative, more than any other single
piece — don't quietly let it default back to "Fable does it every time"
just because that's the path of least resistance in the moment.

For findings that look like genuine bugs (not "the documents are just
missing/ambiguous," which is a data-gap, not a code bug — tell these apart
explicitly), the module (and you, validating/supervising it) should:

1. Read the relevant agent/service code **and** the company's document
   corpus before concluding what's wrong.
2. Think through the fix carefully — don't rush a patch. Write down the
   reasoning.
3. Capture a **before** baseline: run the existing test suite
   (`python -m pytest tests/platform_mode/ -q`) plus a targeted repro of the
   specific failing question(s), and confirm they currently fail.
4. Create a branch off `master` in a git worktree, so the main checkout stays
   untouched. **This branch stays local for now — do not push it, no matter
   how clean the fix ends up looking.**
5. Implement the fix, plus a new permanent regression test that encodes the
   failing case and close variants.
6. Capture an **after** state: re-run the same baseline commands. The fix is
   only acceptable if the originally-failing case now passes **and** nothing
   else regresses. If it regresses, discard the branch, record what was
   tried, and move on — don't force it through.
7. On a clean after-state, **commit it locally and record it as a verified,
   ready-to-publish fix** in `ACTIVE_HANDOFF.md` — but stop there. Do not
   push to origin, do not open a PR yet. Go back to the loop (more
   campaigns, more findings) rather than publishing incrementally.

**Nothing gets pushed to GitHub, and no PR gets opened, until the entire
mission is done** — see the new "Publishing" step below, which replaces the
old per-fix push in §7 above. Every branch, every commit, every worktree
this initiative creates stays entirely local until that point. This applies
even if you find and fix several real bugs over the course of the run —
they all stay local commits until the end, not several incremental pushes.

### 2f. Logging discipline (not a stopping point)

After each simulation campaign, each finding diagnosis, and each PR attempt
(successful or discarded), update `ACTIVE_HANDOFF.md` **and keep going** —
do not treat the update as a natural place to stop and wait. "In a loop
until the final goal is satisfied" means continuous, unattended iteration
with a clear resumable state written down at every step, not a pause for
review at every step. The record exists so that *if* you get cut off
(context limit, crash, session end) or Prem chooses to check in, the state
is legible — not so that you wait for a green light before continuing.

### 2f.1. Email Prem at real checkpoints — he's away from the laptop the whole run

Written logs are for when Prem chooses to check in. He also needs to be
*told* to check in, at a small number of real moments, because he won't be
watching this run live. Send a short email at exactly these points, no
others:

1. **Phase 1 → Phase 2 transition** — the first fix is verified and staged
   locally, and the fresh, harder simulation round (Phase 2 in
   `HEALTH_CHECK_AGENT_MISSION.md`) is starting.
2. **The full goal is met and the loop has stopped** — including that the
   PR is actually open (per the advance authorization above — don't send
   this until the PR genuinely exists).
3. **Anything that's genuinely blocking** per the fixed list in Step 0.5 (a
   real "needs Prem" case) — send the email *and* write the
   `ACTIVE_HANDOFF.md` entry, don't just do one.

Do not email on ordinary progress (a campaign finished, a finding got
classified, a fix attempt failed and got retried) — that's what
`ACTIVE_HANDOFF.md` and `ARCHITECTURE_LOG.md` are for. Three checkpoint
categories, not a running commentary.

**Mechanism — verified working, use exactly this, not Mail.app/AppleScript.**
Mail.app's GUI can pop a blocking error dialog that needs a human click to
resolve, which defeats the purpose entirely for an unattended run. Use
plain SMTP instead: a Python script using `smtplib`, reading `GMAIL_SENDER`
and `GMAIL_APP_PASSWORD` from the environment (already exported in the
session's shell — never hardcode either value, never write the app password
into any file, same rule as the GitHub token), sending to
`pendelanagapremsai@gmail.com`, talking to `smtp.gmail.com:587` with
STARTTLS. This exact approach was tested live and confirmed working before
this initiative started — build a small reusable script for it (e.g.
`scripts/notify_prem.py`) rather than inlining the SMTP call three
different places.

Keep each email short: one or two sentences of what happened, then point at
`ACTIVE_HANDOFF.md` (and `ARCHITECTURE_LOG.md` for the "why") for the real
detail — don't try to cram the full picture into the email body itself.

## Step 3 — The architecture log (required, written in parallel with the work)

At the very start — before writing any implementation code — create a new
file in this same folder: `docs/platform improvements/ARCHITECTURE_LOG.md`.
This is **your own** design journal, separate from both
`SELF_IMPROVING_HEALTH_CHECK_AGENT_PLAN.md` (the prior planning pass you read
in Step 0 — treat it as input, not something to just copy) and
`ACTIVE_HANDOFF.md` (which tracks *where things stand*, not *why they got
that way*). The two files serve different purposes and shouldn't duplicate
each other:

- `ACTIVE_HANDOFF.md` — current state, next step, how to resume. Short,
  operational, overwritten/updated in place.
- `ARCHITECTURE_LOG.md` — the running record of *your reasoning*: what you
  decided, what alternatives you considered and rejected and why, what
  broke, what you changed your mind about and why. Append-only, narrative,
  meant to be read end-to-end later to understand how the system ended up
  the way it did.

Write your initial architecture plan into it first — your own take on how to
build this, after reading the existing plan doc, reconciled with it
explicitly (where you agree, where you deviate, why). Then keep appending to
it **continuously and in parallel with the work itself — not just at
decision points, and not just at the end.** Prem will not be watching this
run live; this file is how he reconstructs what happened afterward, so treat
it like a running narration of your own thinking, not a sparse changelog:

- **While researching:** what you searched for, what you found, what you
  discarded and why, what changed your mind.
- **While planning:** the options you considered for a given piece (not just
  the one you picked), the tradeoffs you weighed, why you ruled the others
  out.
- **While implementing:** what you're building and why this is the right
  shape for it, not just a diff description — the reasoning a reviewer would
  otherwise have to reconstruct by reading the code cold.
- **While testing/diagnosing:** what you expected, what actually happened,
  what that told you, what you're trying next and why.

Think of it less like a sparse commit log and more like the internal
monologue behind a good pull request description, kept running the entire
time rather than written after the fact. It doesn't need to capture literally
every token of reasoning — but if Prem reads only this file end-to-end days
later, with zero other context, he should come away understanding not just
*what* got built but *how you thought your way there*, including the dead
ends. Log entries should be timestamped and roughly chronological so the
narrative reads in order.

## Step 4 — The real constraint: the brain doing all this is not a frontier model, and it's shared

Here is the part that makes this hard, and it is the actual engineering
challenge of this whole initiative, not a footnote:

**The Health Check agent's own reasoning — classification, diagnosis, repair
planning, everything — runs on the exact same shared free-tier LLM fallback
chain the AI Data Analyst depends on** (Gemini 2.5 Flash → Groq Llama 3.3 70B
→ NVIDIA NIM → Cerebras → AWS Bedrock Claude 3.5 Haiku → local Ollama). There
is no separate, always-available, frontier-quality brain reserved for the
Health Check agent. Sometimes the call it makes to reason about a finding
will land on a weaker fallback tier, or get delayed by a cooldown, or (per
§2c) be deliberately throttled so it doesn't starve real employee traffic.
The goal has to be reachable under that constraint — not by assuming a strong
model is always available, and not by spending your way around the problem.

This means the loop needs some form of **persistent memory that lets it not
re-learn the same lessons from scratch on every run**, so scarce/weak-model
reasoning budget gets spent on new problems, not re-deriving old ones. One
illustrative (not prescriptive) shape of this: after each run, the agent
writes down what it did and what it got wrong; before the next run, it reads
that memory first; periodically (e.g. before a 4th lesson would push the file
past a useful size) it compacts older entries into a condensed summary rather
than letting the memory file grow without bound, so reading its own memory
stays cheap even as it accumulates experience.

That specific compaction scheme is just one example to make the shape of the
problem concrete — **it's Prem's rough idea, not a spec. Design something
better if you find it, don't just implement the example as given.** Think
about what actually needs to persist (procedural lessons about how to do
this job well? a running estimate of which question patterns are worth
generating vs. wasted effort — this overlaps with the "prefer higher
real-failure hit rate" tracking already in
`SELF_IMPROVING_HEALTH_CHECK_AGENT_PLAN.md` §5? confidence calibration for
the classifier itself, per §7 of that plan?), what format keeps it cheap to
read on a weak model, and how it stays bounded in size over many runs without
losing anything that actually matters.

**Don't solve this from first principles alone — you have full internet
access, use it.** This exact problem (an agent loop that has to run reliably
on weak/rate-limited models, self-correct from its own failures, and stay
efficient over long horizons) is an active research area, not something you
have to invent unassisted:

- Use `WebSearch` broadly for prior art: agentic memory architectures,
  self-improving/self-correcting agent loops, LLM-as-judge and answer
  classification reliability, cost-aware or rate-limited agent design,
  eval-gated autonomous code repair. Search for both academic work (arXiv,
  research lab publications — Anthropic, DeepMind, OpenAI, academic groups)
  and practical prior art (real GitHub repos implementing similar loops,
  postmortems/blog posts from people who built something comparable).
- Use `WebFetch` to actually read what you find — abstracts, full papers,
  READMEs, design docs. For arXiv or other PDF-hosted papers, `WebFetch` on
  the arXiv `/abs/` page usually gets you the abstract cleanly; for the full
  PDF, either try `WebFetch` directly on the PDF URL, or if that doesn't
  render usefully, open it via the Chrome browser tool
  (`claude-in-chrome` — navigate to the PDF URL, Chrome's built-in viewer
  will render it, then read the page) and extract the sections that matter
  rather than trying to absorb an entire paper. For long papers, skim
  structure first (abstract, method, results) rather than reading linearly.
- **Be skeptical of what you find, the same way you'd want your own
  simulated-employee questions to be grounded, not invented.** Not
  everything that shows up in a search is reliable — some "comparison" blog
  content in this exact space turned out to be SEO filler with fabricated
  or unverifiable statistics when checked earlier in this project's history
  (see the tool-comparison research in this conversation's own precedent, if
  available to you, or just apply the same skepticism generally: verify
  specific claims against a primary source — the actual paper, the actual
  repo — before relying on them, especially for anything with suspiciously
  precise numbers and no clear origin).
- When something you read genuinely informs a design choice, cite it in
  `ARCHITECTURE_LOG.md` (link + what you took from it) — this is exactly the
  kind of "why" the log exists to capture, and it's also just honest: don't
  present a borrowed idea as something you invented from scratch.

This is exactly the kind of decision that belongs in `ARCHITECTURE_LOG.md` —
write down what you tried, what you read that shaped it, what worked, what
didn't, and why, as you go.

One thing this memory is **not**: it is not the same thing as
`health_memory.py`'s finding-resolution tracking (fingerprint → status →
linked PR) from the existing plan doc — that tracks the *product's* bugs and
their resolution state. What's being asked for here is the *agent's own*
operational memory about how to do its job well under a constrained brain.
They may end up sharing storage (e.g. both living in `store.py`'s SQLite) if
that turns out to be the efficient choice — that's your call, document it.

## Step 2g — Publishing: once, at the true end, and by the agent's own code

**This replaces the old "push as soon as one fix is clean" behavior.**
Everything through §2e stays local — every branch, every commit, every
worktree — for the entire run. Publishing happens exactly once, only when
the mission is genuinely finished (all locally-achievable parts of the
six-item goal checklist are true: at least one real finding caught
unprompted, at least one fix verified before/after, everything logged).

**Who does the actual publishing matters, and it isn't "Fable running `git
push` / `gh pr create` by hand."** The whole point of this initiative is
that the *Health Check agent itself* — the system being built, not the
external coding session building it — should be the thing that branches,
fixes, tests, and opens the PR, on an ongoing basis, without an engineer
sitting there doing it manually each time. So: build the actual publish step
as real code (this is what `repair/pr.py` from
`SELF_IMPROVING_HEALTH_CHECK_AGENT_PLAN.md` §8 already specifies — a branch/
push/PR-only module, no merge path), and when the mission is complete,
**invoke that module** to do the pushing and PR-opening, rather than typing
the equivalent commands yourself in the terminal. If several verified local
fixes have accumulated by the time you publish, decide — and log the
reasoning in `ARCHITECTURE_LOG.md` — whether they become one consolidated
PR or several separate ones; either is fine, just be deliberate about it,
don't default to whichever is less code to write.

The existing rule that opening a PR needs Prem's explicit consent typed in
chat (see "GitHub access" below) is unchanged by this — it just now fires
once, at the true end, instead of once per fix.

## GitHub access (read carefully — this is a hard constraint, not a suggestion)

**Status: set up and ready.** A fine-grained GitHub Personal Access Token
exists, under Prem's account (`premsai-pendela`), scoped only to
`premsai-pendela/NexusIQAI-Platform`, with `contents: read/write` and
`pull_requests: read/write` (plus the forced `metadata: read`). Branch
protection is configured on `master`: pull request required before merging,
1 required approval.

**Explicit, standing, advance authorization — read this if you ever hesitate
before opening a PR.** Prem has already authorized, in writing, right here,
in this durable file: once a fix is eval-gated clean (per §2e/§2g/the Phase
2 validation round in `HEALTH_CHECK_AGENT_MISSION.md`), push the branch and
open the PR yourself. Do not pause the loop or wait for a live "yes" in chat
before doing this — that authorization already happened, in advance, right
now, in text, which is the correct and sufficient form of consent for an
autonomous run where Prem is explicitly not available to respond live. Go
all the way through: branch → fix → test → push → open the PR. Prem reviews
and merges afterward, on his own time — that review is what "he'll see it
after that" means, not a live gate before the PR can even open.

One honest caveat, so you're not confused if it happens: the coding
environment this runs in has its own permission layer that has, in the
past, still inserted a one-time live confirmation prompt before an action
like "open a PR against a public repo," even with this kind of advance
written authorization present. If that happens, it is the environment being
appropriately cautious about an externally-visible action, not a failure of
this authorization or something to route around — just answer it (or Prem
will, if he's monitoring via the phone Remote Control session) and continue.
It is a small, one-time nudge, not a resumed wait for repeated permission —
it should not recur for every subsequent PR once handled the first time.

**Important nuance — read this before writing any repair/PR code.**
Fine-grained PATs do not have a separate "can push and open PRs but cannot
merge" permission — `contents: write` technically permits calling the merge
API too. The token scope is *not* what stops an auto-merge here. Two things
actually do:

1. The PR this token opens will be authored by the same GitHub identity as
   Prem (`premsai-pendela`) — since it's a personal token, not a separate bot
   account. **GitHub does not allow an author to approve their own pull
   request.** So the required-approval rule can never be satisfied by the
   agent itself, under any code path.
2. Branch protection's "do not allow bypassing" is **deliberately left
   unchecked** — Prem, as repo admin, needs bypass rights to merge after
   reviewing, precisely because he can't formally "approve" a PR opened under
   his own account. If that box were checked, no PR could ever merge, by
   anyone, including Prem.

The practical effect: the agent can push branches and open PRs freely, but
the only path to `master` is Prem manually clicking merge as admin, after
reading the diff. That is the real gate. Do not weaken it, and do not write
any code that tries to work around it.

Hard rules, enforced structurally, not just by instruction:

- **Never attempt to merge anything, under any circumstances.** No `gh pr
  merge`, no direct push to `master`, no merge API call, anywhere in this
  initiative's code — even though the token's scope would technically allow
  the API call to succeed if attempted, the identity/approval mismatch above
  means it would still be rejected by GitHub. Don't rely on that as your
  safety net; the code itself must never attempt it.
- Add a test that greps any repair/automation code you write for merge
  primitives (`pr merge`, `merges`, `push.*master`) and fails the build if
  any appear — this is the concrete version of "no auto-merge," not a policy
  comment.
- A human (Prem) reviews and merges every PR. Full stop.

**How to get the token into your session:** it will be provided as an
environment variable (`GH_TOKEN`) in the shell/session you're running in —
verify with `gh auth status` before attempting any push. **Never write the
token value into any file in this repository** — not in `ACTIVE_HANDOFF.md`,
not in a `.env` committed to git, not anywhere. If you ever see it echoed
into a file or a command output that might get logged, treat that as a
security incident: stop, note it in `ACTIVE_HANDOFF.md` under "Blocked /
needs Prem," and flag it for rotation rather than continuing.

## The only real stopping condition

Prem is not available while this runs, so there is exactly **one** thing that
stops you: **the goal is fully met** — all six checklist items in "The final
goal, stated explicitly" are true, with real evidence for each.

There is no second "wait for Prem" condition anymore — that's what Step 0.5's
self-written guardrails are for. Anything that would have been a "stop and
ask" case (a scope question, an ambiguous product decision, an unexpected
fork in the road) gets decided by you, inside the guardrails you wrote for
yourself, and logged in `ARCHITECTURE_LOG.md` with your reasoning — not
paused on.

The narrow exception is the small fixed list in Step 0.5 of things that
aren't yours to decide differently regardless of guardrails (merging,
credentials/secrets, repo security settings, destructive git operations, the
rate-limit/budget floor). Those aren't "ask Prem and wait" situations either
— they're just permanently out of scope. If one of them is genuinely what
stands between you and the goal, that's a sign the approach itself is wrong;
find a different path to the same goal rather than reaching for one of
those.

Everything else — a failed simulation campaign, a classifier that missed
something, a fix that didn't hold, a PR attempt that had to be discarded,
even a whole strategy that turns out not to work — is not a stopping
condition. It's a data point. Log it (§Step 3), diagnose it, adjust your
guardrails if the failure revealed they were wrong, and keep going.
