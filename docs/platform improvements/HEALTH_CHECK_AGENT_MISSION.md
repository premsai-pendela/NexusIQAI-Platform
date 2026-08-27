# Mission v2: Build the Health Check Agent — It Does The Rest, Not You

Read this file **first**, then `CLAUDE.md`, then `CONTEXT.md`, before
anything else. This file corrects a real mistake in how the previous run was
framed. Where this file and `CONTEXT.md` disagree about *who performs a
step*, this file is right and `CONTEXT.md` is wrong — but `CONTEXT.md` is
still the source of truth for everything this file doesn't re-cover (rate
limits, publishing policy, GitHub access, guardrails, logging discipline).
Read all three. This file exists because the correction is important enough
to be unmissable, not to replace the other two wholesale.

**`CLAUDE.md` is unchanged and still fully in effect — it is not forgotten
and nothing here replaces it.** It governs a different, separate concern
from everything else in this file: which model *you* (this build session)
use for *your own* work while designing, building, and validating the
pipeline — hard/ambiguous work to Fable, mechanical well-specified work
delegated to Sonnet or Haiku so you're not burning Fable-tier tokens on
things that don't need it. That routing question is completely orthogonal
to "which model does the *pipeline itself* run on once built" (answered
below — never Fable/Opus/Sonnet/Haiku, always the product's own free-tier
chain). Keep both rules straight: one is about how *you* work efficiently
right now, the other is about what the *finished system* is allowed to run
on forever after.

## Proposals vs. requirements — read this before treating anything below as a script to follow literally

Everything specific in this file and in `CONTEXT.md` — the five-step
implement sequence, the exact "5–6 tables" threshold, the particular
guardrail list, the phrasing of prompts, even the Phase 2 approach — is
Prem's best proposal for *how* to hit the requirement, not a script to
execute literally. This is the same standing already given explicitly for
the memory system in `CONTEXT.md` §4 ("it's Prem's rough idea, not a spec —
design something better if you find it"); it applies everywhere in both
files, not just there, and it wasn't said clearly enough elsewhere, so it's
being said plainly now: **if research, testing, or your own judgment turns
up a better way to satisfy the actual requirement, use the better way. Don't
follow a specific mechanism described here just because it's written down,
if you have a real reason to believe something else works better.**

What's *not* up for revision, because these are the actual requirements, not
proposed mechanisms for meeting them: the one-sentence rule directly below
(who does what), the full goal checklist including Phase 2 (both phases
complete, no stopping early), and the fixed, non-negotiable guardrail list
already in `CONTEXT.md` §0.5 (no merge, no touching secrets/credentials, no
changing repo security settings, no destructive git operations, the
rate-limit floor). Change the *how* as much as good engineering judgment
supports. Don't change the *what*.

One condition on using this freedom: **when you deviate from something
specific written here, say so in `ARCHITECTURE_LOG.md`** — what was
proposed, what you did instead, and why you believe it's better. That's not
a formality; it's what makes "Fable found a better way" distinguishable from
"Fable skipped a requirement," which matters a lot given nobody is watching
this run live.

## The one-sentence rule

**Fable may only ever directly write or edit code that lives inside the
Health Check Agent's own codebase. Fable must never itself diagnose, write,
or submit a fix to the AI Data Analyst / platform codebase. That entire
job — plan the fix, write the tests, edit the code, run the tests, submit
the PR — belongs to the Health Check Agent: a standalone, autonomous system
Fable builds, which then does that work itself, using the product's own
shared free-tier LLM chain, not Fable's own reasoning.**

## What actually happened last run, stated plainly, so it isn't repeated

The simulator and the classifier were built correctly — real code, running
on its own, that found a genuine bug (the fabricated-NPS finding) without
being told where to look. That part was right.

What went wrong: once that finding existed, **Fable itself** read
`orchestrator.py`, decided what was wrong, wrote the fix, wrote the tests,
and pushed a branch toward a PR — using Fable's own reasoning, not a piece
of running Health Check Agent code. That is not what was asked for. The
Health Check Agent, as it exists right now, can *find* problems on its own.
It cannot yet *fix* them on its own. Building the thing that closes that gap
is the actual job of this mission — not standing in for it by hand, however
well that stand-in works.

## What "the Health Check Agent" means now, concretely — the whole pipeline, as real running code

Seven stages. All seven must exist as code that runs using the product's own
shared LLM gateway (`utils/llm_gateway.py::invoke_with_fallback`, the same
Gemini → Groq → NVIDIA NIM → Cerebras → Bedrock → Ollama chain everything
else in this product uses). None of the last five stages get a pass to be
"Fable does it manually this time" — that manual version does not count
toward the goal, no matter how good the output is.

1. **Simulate** — adversarial employee traffic, per role/company, across
   difficulty tiers (see the precise "very very hard" definition below).
   Already built (`nexus_platform/sim/`).
2. **Classify** — read the resulting traces, judge correct / wrong / vague /
   exceptional. Already built, zero-LLM, deterministic-oracle-based. Keep
   it that way where possible — it doesn't need to get *less* cheap to do
   the next stages well.
3. **Plan** — for a real finding, the agent itself calls out to the shared
   LLM chain to read the relevant code and document corpus and decide what
   in the platform codebase needs to change, and writes that plan down.
   This is the stage that was done by Fable last time and needs to become
   real code — this is the actual hard part of the whole mission.
4. **Write its own tests** — the agent generates the regression test(s) that
   encode the failing case, again via the shared LLM chain, not Fable.
5. **Edit the code** — the agent applies its own planned fix, in a branch/
   worktree, again via the shared LLM chain.
6. **Run its own tests** — before/after against the existing suite plus its
   own new test(s). This part can be plain deterministic code (running
   pytest and reading the result needs no LLM at all) — keep it that way.
7. **Submit the PR** — once the eval gate passes, the agent's own code
   (`nexus_platform/repair/pr.py`) pushes the branch and opens the PR. Human
   review/merge afterward is unchanged and still absolute — see
   `CONTEXT.md`'s "GitHub access" section, nothing about that changes here.

## "Very very hard" — precise definition, not vibes

A role's access grants some number of tables (e.g. Analyst at AcmeCloud has
roughly 10–12 in its allowlist). A **very-very-hard** simulated question must
require genuinely joining or reasoning across **5–6 or more of those tables
in one question**, in a way that forces the LLM path (not something the
deterministic template layer could ever answer) — not just naming several
metrics side by side, but a question whose correct answer structurally
requires that many tables' data related to each other. Example shape: "for
customers who filed a support ticket in the last quarter, what's their
average order value compared to customers who didn't, broken down by the
product category they use most and whether they're on an annual or monthly
plan" — that's `customers` + `support_tickets` + `orders`/`order_items` +
`products` + `subscriptions`/`plans`, all genuinely related, in one ask.
This tier exists specifically to find the failure modes that only show up
under real multi-table reasoning load, not the seam-probing or
single-metric-hallucination bugs the easier tiers already cover well.

## What Fable's own session actually does

**Build stages 3–7 above as real code.** Then, to prove it actually works,
**trigger the finished pipeline and watch it run** — e.g. a script that
takes a classified finding and runs it through plan → write-tests → edit →
test → (stop short of PR per the local-only-until-the-end policy in
`CONTEXT.md` §2e/§2g). Fable's role during that triggered run is to
**observe, log, and validate** what the pipeline produces — not to produce
it. If the pipeline's *own code* has a bug that stops it from running at
all (a Python exception, a broken prompt template, a malformed API call),
Fable can and should fix that — that's fixing the Health Check Agent's own
code, which is in-scope. What Fable must not do is read the finding itself,
decide the fix itself, and write that fix into the platform code itself, and
call that "the pipeline's output."

If the pipeline's first attempt at a real diagnosis is weak or wrong — which
is a completely expected outcome given it's running on a comparatively weak
model — the correct response is to **improve the pipeline's design**
(better prompting, better retrieval of relevant code/trace context, maybe
multiple attempts with self-critique before giving up, maybe a narrower
scope of findings it's allowed to attempt) so *it* gets better at the job,
not to quietly do the job for it and move on. Log every iteration of this
honestly in `ARCHITECTURE_LOG.md` — "the pipeline's first attempt produced
X, which was wrong because Y, so I changed the prompting/retrieval to Z" is
exactly the kind of entry that file exists for.

## Work from the traces that already exist — don't re-simulate by default

Three real campaigns already ran and are sitting in the store right now
(`camp_f688345b32`, `camp_c1014c02ce`, `camp_c305c02583` — see
`ACTIVE_HANDOFF.md`), including the real NPS finding. Building and proving
stages 3–7 does not require fresh simulated traffic — it requires reading
what's already there. **Do not trigger a new simulation campaign as a
default first step.** Only run one if you genuinely need a finding of a
different shape than what already exists (e.g. every existing finding gets
resolved by the pipeline and you need a new one to keep validating against),
and if you do, say why in `ARCHITECTURE_LOG.md` rather than doing it out of
habit. Every simulated question costs real free-tier quota shared with real
employees — spend it when it's actually needed, not by default.

## Say the model list out loud, because it's easy to slip on this

The Health Check Agent's own reasoning — stages 3, 4, and 5 above,
specifically — runs **exclusively** on the product's existing fallback
chain: Gemini 2.5 Flash, Groq Llama 3.3 70B, NVIDIA NIM (deepseek-v4-flash),
Cerebras, AWS Bedrock (which does run Claude 3.5 Haiku, via Bedrock — that
one's legitimately in the chain already). **Local Ollama is not available**
for this initiative — Prem's Mac can't run it, so treat the real usable
chain as those five, not six. If you find an Ollama fallback still coded
into the product for other environments, that's fine to leave alone, just
don't rely on it or count on it being reachable during any of this
initiative's local development or testing. **Fable, Opus, and Sonnet are
never the thing performing stages 3–5's actual reasoning, under any
circumstance, at any point, even temporarily, even to "unblock" something.**
Those three (Fable/Opus/Sonnet) are the tools *you* — this build session —
use to design and validate the pipeline. They are categorically not part of
the pipeline itself. If you ever catch yourself about to use your own
reasoning to produce the actual diagnosis or the actual fix content that
ends up in the branch, stop — that's the exact mistake from last run,
happening again.

## Teach the pipeline your method — don't just assign it the task

This is the actual core engineering idea behind the whole "weak brain doing
a frontier task" challenge, so read this carefully. The reason you (Fable)
can do stages 3–5 well and a bare Gemini Flash call probably can't is not
just raw model capability — it's that *you* bring a whole implicit
methodology to the task: you read surrounding code before touching
anything, you look for existing patterns and follow them, you form a
hypothesis and check it against evidence before committing to it, you plan
before you write, you second-guess your own first draft. A weak model given
the same task with none of that structure will just pattern-match to
"generic bug fix" and produce something shallow.

**Your job is to distill that method into the pipeline's own prompts and
scaffolding, so a weak model ends up following a strong process even though
it isn't a strong model.** Not "ask it to fix the bug" — walk it through the
same steps you'd walk through yourself: here's the trace and the specific
evidence of what went wrong; here's the relevant code, read it first; here's
how a similar problem was already solved elsewhere in this codebase, notice
the pattern; state your hypothesis for the root cause before proposing
anything; here's your own hypothesis, check it against the evidence one more
time; now write a plan; now write a small, localized diff that matches the
existing style; now check your own diff against your plan before handing it
off. That's not decoration — that structure *is* how you compensate for a
weaker model, by giving it your process instead of just your goal. Write
this down explicitly in `ARCHITECTURE_LOG.md` as you design it — this is
exactly the kind of architecture decision that file exists to capture, and
it's worth being able to point to later as "here is the methodology we
taught the pipeline, here's why it's shaped this way."

Think of it the way a good professor teaches, not the way a manager
delegates: a manager just assigns the task and expects the result; a
professor teaches the *method* — and a student who actually absorbs the
method can go on to handle problems the professor never showed them, even
surpass them on some of it. That's the actual bar here: not "the pipeline
produced a correct diff once," but "the pipeline has a method it can apply
to a finding it hasn't seen before."

**Concretely, one starting proposal for the shape of that sequence** — a
single "fix this" prompt with no structure is very unlikely to work
reliably on a weak model, so break stages 3–5 into a real sequence, each
stage's output feeding the next, not one big leap from problem to patch.
This five-step breakdown is exactly the kind of thing the "proposals vs.
requirements" note above is about: if you test this and find a different
structure gets more reliable results on the models actually available,
switch to it and log why — the requirement is "reliable output from a weak
model," not "these specific five steps":

1. **Understand first.** Given the finding and its trace, produce a written
   explanation of what's actually happening — not a fix yet, just
   comprehension. If it can't articulate the problem clearly, it isn't
   ready to plan a fix for it.
2. **Reason toward a fix, out loud, iteratively.** Let it work through "how
   could this be fixed" more than once — a first pass, a critique of that
   first pass, a refined answer — rather than accepting whatever it says
   first. This is deliberately slower and burns a couple more free-tier
   calls per finding; that's the right trade for reliability over speed.
3. **Write the plan** — a concrete, ordered description of the change,
   referencing the exact functions/files involved, before any code exists.
4. **Implement from the plan, incrementally — not as one giant diff.** Have
   it work through the plan's steps one at a time (add the gate condition,
   then wire it into the existing flow, then add the test, checking each
   small step rather than generating the whole change in a single shot).
   Small, sequential, checkable steps are far more likely to stay correct
   on a weaker model than one large generated patch — the failure surface
   per step is smaller, and each step can be sanity-checked before the next
   one builds on it.
5. **Guardrail the whole sequence** so it only ever touches what the plan
   from step 3 said it would — nothing "while I'm in here" extra, no
   drive-by edits to unrelated code. If step 4 wants to touch a file that
   wasn't named in step 3's plan, that's a signal to stop and re-plan, not
   to proceed.

This is a slower, more deliberate loop than "generate a diff in one call" —
that's the point. Reliability on a weak model comes from breaking the task
into small, checkable pieces, not from a bigger single prompt.

## Guardrails baked into the pipeline itself, not just checked after the fact

A weak model asked to "write a fix" without structure will happily produce
something generic, oversized, or unrelated to the actual codebase's
patterns — the eval gate (stage 6) catches *broken* output, but it won't
reliably catch output that's technically passing yet badly shaped (a fix
that works but doesn't match how the rest of the codebase does things, or
touches far more than it needed to). **The pipeline needs its own
guardrails written into stages 3–5's own prompting/scaffolding**, not
relying on stage 6 as the only backstop. This is the concrete, checkable
form of "teach it your method" above — at minimum, design the pipeline so
it:

- Is constrained to a **localized diff** — told explicitly what files are
  in play (from the finding's own trace/evidence, not a free choice), not
  given the whole repo and left to wander.
- Is shown **existing, similar code in this codebase** as a pattern to
  follow (e.g. how `deterministic.py` or `access_policy.py` already
  structure a similar check) before generating new code, so its output
  looks like it belongs here, not like generic boilerplate.
- Is required to **state its plan in writing before generating the diff**
  (stage 3's output should be a legible plan, not just "and now here's
  code") — this is both a guardrail and what makes stage 3's output
  auditable in the PR body.
- Has a **self-check step** — asking the same weak model (or a second call)
  to sanity-check its own proposed diff against the plan and the existing
  code style before handing it to stage 6, catching some fraction of bad
  output before burning a full eval-gate cycle on it.

Design this, don't just assume the eval gate alone is enough — a fix that
merely passes tests is a lower bar than a fix that looks like it was written
by someone who understands this codebase.

## Beyond bug-fixing: the traces can also reveal a missing capability, not just a wrong answer

Everything above is about the case where the AI Data Analyst got something
*wrong*. There's a second, real category worth building toward: sometimes
the traces will show the AI Data Analyst *struggling or falling short* not
because of a bug, but because it's missing a capability that would let it
answer better. The Health Check Agent's analysis of traces (stage 3) should
be free to conclude "this isn't a bug to fix, it's a capability gap" and
propose adding something new — a tool, a skill, an integration — not just a
patch to existing logic.

**This is illustrative, not a spec — don't build the specific examples
below, they're here to explain the shape of the idea, not to hand you a
task list:**

- Claude Code without a web-search tool can only answer from what it was
  trained on and guesses when that's stale or missing; with one, it can
  pull in real, current, verifiable information before answering. That
  contrast — "categorically better answers once a missing capability is
  added, not just fewer bugs" — is the pattern to look for in the traces,
  not a suggestion to give the AI Data Analyst internet access.
- If traces showed employees repeatedly asking for something like an
  interactive chart or a build-your-own-dashboard view and the product could
  only offer a static one, that gap — revealed by real trace evidence, not
  guessed — would be a legitimate capability-improvement finding, on the
  same footing as a bug.

If the pipeline identifies something like this from real evidence (not
speculation), it goes through **exactly the same rigorous path** as a bug
fix — no shortcuts because it's a "feature" instead of a "fix": branch,
worktree, its own tests, eval-gated before/after, human-reviewed PR, never
auto-merged. It also has to stay inside the scope fence from `CONTEXT.md`
§0.5 — a real capability gap grounded in trace evidence is in scope; "it
would be cool if it also did X" without evidence behind it is not. Don't let
this turn into a general feature-brainstorming license — it's specifically
"the traces showed a pattern that a new capability would address," logged
and justified the same way a bug diagnosis would be.

## What to do with what already exists (`autofix/unknown-metric-honesty`)

That branch is a hand-written fix — Fable's own diagnosis and code, not the
pipeline's. Don't discard the insight (it's a real, correctly-diagnosed bug,
and the fix approach is probably right), but don't submit it as the final
PR either. Treat it as a **known-good reference** to validate the new
pipeline against: if you run the finished pipeline on that same finding and
it independently arrives at a comparable fix, that's strong evidence the
pipeline works. The PR that eventually gets submitted (per `CONTEXT.md`'s
local-only-until-the-end publishing policy) should be the pipeline's own
output, not Fable's earlier hand-written version — even if they end up
looking similar.

## Phase 2 validation: after the first fixes land, come back with harder questions

This is the real test of whether the pipeline actually works, not just
whether it worked once on data it was basically handed. Once the pipeline
has processed the findings already sitting in the store (built the fix(es),
passed its own eval gate, everything staged locally per the publishing
policy) — **then, and only then**, it's time to genuinely spawn the
simulator again: a fresh campaign, deliberately different and harder
questions than the ones already used (lean into the "very very hard" tier
more than the first round did, and don't repeat the same question shapes
that already found something), specifically still trying to break the
product. Run the full Health Check Agent pipeline — classify, plan, fix,
test — on whatever this new round surfaces.

This is not the same thing as "don't re-simulate by default" above — that
rule was about not wasting quota re-running the simulator *before* you've
even built anything to test with existing data. This is the deliberate,
correct use of a second round: real generalization testing, after the
pipeline exists and has proven itself once. Your role here is explicitly to
**observe and evaluate**, not participate — watch how the pipeline performs
against traffic it hasn't seen shaped in ways it hasn't seen, log what holds
up and what doesn't in `ARCHITECTURE_LOG.md`, and if it reveals the pipeline
was overfit to the first bug's shape, that's a real finding about the
pipeline's own quality, not a reason to quietly step in and fix the new
findings by hand.

## The goal checklist, corrected

`CONTEXT.md`'s six-item checklist still applies, with item 3 tightened:
"a branch was created, a fix implemented, and tests run before/after" now
specifically means **the Health Check Agent's own code did the planning,
test-writing, and code-editing** — not Fable. When you log evidence for this
item, be explicit about *which actor* did the diagnosis and the fix (cite
the actual LLM call / trace / log entry from the pipeline's own run), so
it's checkable, not just asserted.

**The goal is not met until the Phase 2 validation round above has also
run.** Fixing the first known finding and stopping there is not the finish
line — it's the halfway point. The one and only stopping condition (per
`CONTEXT.md`'s "only real stopping condition" section) still applies exactly
as written: keep going, autonomously, inside your own guardrails, until the
*complete* goal — including this second, harder validation round — is
genuinely satisfied. Don't stop at the first fix and call it done.

## Everything else is unchanged — still governed by `CONTEXT.md`

- Rate limits and shared-quota protection (§2c)
- Local-only commits, publish once at the true end (§2e/§2g)
- GitHub access and the anti-auto-merge structural gates (unchanged,
  absolute) — **note the update in `CONTEXT.md`'s "GitHub access" section:**
  opening the PR is pre-authorized in advance, in writing, right there — do
  not pause the loop waiting for a live chat confirmation before pushing and
  opening it. Merging still requires Prem, always, no exceptions.
- Writing your own guardrails before touching code, and holding yourself to
  them (§0.5)
- Continuous narration in `ARCHITECTURE_LOG.md`, checkpoint updates in
  `ACTIVE_HANDOFF.md`
- Researching real prior art before designing — and for this specific
  correction, add "LLM-based automated program repair" / "self-healing
  software" / "agentic code repair on weak models" to what you search for,
  since that's now the central open problem
- The adversarial framing (attack the product, not just query it) and the
  difficulty-tier coverage requirement, sharpened above for the top tier
