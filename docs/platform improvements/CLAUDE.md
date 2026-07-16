# CLAUDE.md — Self-Improving Health Check Initiative

This file governs how work under this initiative gets done — specifically
**which model does which kind of task**. It does not auto-load the way the
repo-root `CLAUDE.md` does (that one loads for any file you touch anywhere in
the repo; this one only applies because `CONTEXT.md` in this same folder
tells you to read it first). Read it once at the start of every session on
this initiative and follow it for the rest of that session.

**Read this distinction first, it matters for everything below:** the
routing rules in this file are about which model *you* (Fable, running this
build session) use for a given task *while you're building and operating
this session*. They are a separate question from what `CONTEXT.md` §2e
requires for the finished system: the actual diagnose-and-fix-a-real-bug
capability must end up as product code that runs on the product's own
shared free-tier LLM chain (Gemini/Groq/NVIDIA NIM/Cerebras/Bedrock/Ollama),
not a capability that only exists because a Fable session was invoked to
perform it by hand. Don't read "diagnosing... is a Fable-tier task" below as
license to permanently do that diagnosis yourself instead of building the
module that does it on the product's own models — see `CONTEXT.md` §2e for
the corrected, precise version of this.

This file does not replace the repo-root `CLAUDE.md` — it adds model-routing
rules on top of it. Every rule in the root `CLAUDE.md` (autonomy, honesty,
truth rules, ACTIVE_HANDOFF discipline, definition of done) still applies in
full.

## Model routing — the core rule

Not every task in this initiative deserves the strongest model. Use
intelligence proportional to the task:

**Use the strongest available model (Fable, or Opus if Fable is unavailable) for:**
- Research (reading docs, reading code, reading the live product, researching
  real-world comparable companies/workflows)
- Architecture and system design decisions (how the simulator, classifier,
  and repair loop fit together; data model choices; what a "good enough"
  question-generation strategy looks like)
- Writing or revising the agentic plan itself (the kind of document already
  at `docs/Current NexusIQ docs/SELF_IMPROVING_HEALTH_CHECK_AGENT_PLAN.md`)
- Designing and building the `repair/proposer.py` module that will do the
  actual diagnosis-and-fix reasoning going forward on the product's own
  models (see the distinction called out above and detailed in
  `CONTEXT.md` §2e) — the module's design is architecture, squarely
  Fable-tier
- Validating the module's output and, only when its first attempt is
  genuinely unusable, fixing the *module's approach* (not silently
  hand-writing the one-off diagnosis yourself instead of running it)
- The final review of a fix before a PR is opened
- Any decision that touches access control, the anti-auto-merge gates, or
  anything security-relevant

**Use a cheaper model (Sonnet, or Haiku for the cheapest/most mechanical work) for:**
- Mechanical implementation once a plan already exists and is not ambiguous
  (e.g., adding a column via the existing migration pattern, wiring a config
  knob, writing a straightforward test once the case is fully specified)
- Running tests/evals and summarizing pass/fail output
- The simulator "employee" persona calls themselves — i.e., the actual
  question-asking traffic sent to the AI Data Analyst during a simulation
  campaign should be driven by a cheap model, not Fable. Fable designs the
  simulator; it does not need to be the one asking each simulated question.
- Formatting, small doc updates, changelog/handoff note-taking
- Simple, well-specified bug fixes with an obvious one-line cause

**Rule of thumb:** if you're deciding *what* to do or *why* something is
broken, use the strong model. If you already know exactly what to do and it's
just a matter of typing it correctly and checking it, use the cheap model.
When genuinely unsure which bucket a task falls in, default to the stronger
model once, then note in `ACTIVE_HANDOFF.md` that the task turned out to be
mechanical — so next time a similar task shows up, route it cheap.

A concrete example, since this comes up directly in `CONTEXT.md` §4:
**designing** the Health Check agent's own memory/lesson system (what to
persist, in what shape, when to compact it) is a strong-model decision — it's
architecture. **Executing** that design once it exists — e.g. periodically
summarizing older memory entries into a shorter digest per an
already-decided policy — is mechanical once the policy is fixed, and belongs
on a cheap model. Don't let the fact that "memory" sounds sophisticated pull
its routine upkeep onto the expensive model by default.

Do not weaken judgment to save cost. Routing a task to a cheaper model is
about matching effort to difficulty, not about minimizing spend at the
expense of correctness — this project already runs its live traffic on free
LLM tiers with fallback chains; do not make that scarcity worse by burning it
on trivial tasks, and do not make quality worse by starving a hard task of
the intelligence it needs.

## Hard rules specific to this initiative

- **No auto-merge, ever.** Not a policy statement — build it as a structural
  gate. The token cannot get a PR it opens approved (GitHub blocks
  self-approval of your own PR, and the token shares Prem's identity), branch
  protection requires that approval before merge, and the repair code must
  never contain a merge code path in the first place. See `CONTEXT.md`'s
  "GitHub access" section for the exact mechanism — read it before writing
  any repair/PR code, the reasoning matters.
- **Simulated traffic is always tagged and never conflated with real usage**
  in any report, export, or admin view.
- **Never exhaust the free-tier LLM quota real employees depend on.** Rate
  limiting for simulated LLM-path calls is mandatory, not optional — see
  `CONTEXT.md` §4.
- **Keep `ACTIVE_HANDOFF.md` (repo root) current at every checkpoint** — see
  `CONTEXT.md` §2. This is how work resumes cheaply across sessions instead
  of re-deriving everything from scratch.
- Do not touch secrets, `.env`, credentials, or any file outside what this
  initiative's scope covers.
- If you hit a decision that is genuinely Prem's to make (scope, credentials,
  which repo to target, anything irreversible) — stop, write it down in
  `ACTIVE_HANDOFF.md`, and wait. Do not guess on anything in that category.
