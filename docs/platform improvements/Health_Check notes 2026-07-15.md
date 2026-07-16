# Health Check notes — 2026-07-15

The Health Check agent's own log for the FABLE_MISSION_2026-07-15 run:
each finding → exact trace ids, each predicted hidden bug and whether it
reproduced, the fix plan, its self-confirmation, before/after test + eval
output, latency numbers, and the PR link.

## Campaign observations (live, AcmeCloud, 2026-07-16 ~01:22Z)

- admin@acmecloud.test (Admin — role that may reach every table):
  - `how many customers do we have total?` → deterministic ✓
  - bait `gross logo retention rate` → clarification ✓ (unknown-metric gate held)
  - **very-hard 5-table join → `access_refusal/denied`** — an Admin denied
    data access is a false-refusal candidate; Wave 1 must grade this.
  - malformed `revenu q9` → clarification ✓
  - compound %-of-last-year by region → deterministic answered
  - **seam follow-up `and how does that split by plan tier?` →
    `access_refusal/denied`** — second false-refusal candidate.

## Wave-1 review results (2026-07-16 ~02:50Z)

- **AcmeCloud** report `hc_50fcb12888` (run #5, incremental since 2026-07-15):
  21 traces graded → 12 correct, 1 correct refusal, 4 n/a, 3 wrong,
  1 needs-human (tr_f7f8f82ca6 — HR tenure re-probe returned an EMPTY answer
  again via sql_agent; the weak spot from yesterday reproduces).
  The 3 "wrong" (tr_777b30cadf, tr_e9641dd4bd, tr_b5ed034cf0 — headcount=125
  vs oracle 109) were exposed as FABRICATED EVIDENCE: a unit test's fake
  client leaked fixture answers into the real store. Finding `hf_baeb9f105d`
  dismissed with a note; traces deleted; the leak fixed at the source
  (test now captures store writes). An honest health check dismisses its own
  false positives loudly.
- **MedCore** report `hc_d29a351231` (run #1): 18 traces → 9 correct,
  5 wrong (traces tr_91fcf57504, tr_31cd3cfc12, tr_3c25578b7e,
  tr_f34174797b, tr_633d8a6837). Pattern: malformed/complex questions
  (expnses quater 5; tikets priorty p9; CSAT-escalation join; seam
  follow-ups) came back `access_refusal/denied` and the judge graded the
  refusals wrong — the misclassified-refusal class.
- **FinPilot** report `hc_e75e8d889b` (run #1): 18 traces → 7 correct,
  2 wrong (tr_ad8661c015 settlement-latency bait denied instead of honest
  "not tracked"; tr_1cfccdfb16 seam follow-up), 1 partly-right
  (tr_7774ff77c5 incidents count), 1 needs-human, and **1 deterministic
  false refusal: tr_cec7f4976d — ops asked the SLA-tier breach/incident
  join; the role's policy allows every table it needs; policy re-derivation
  proves the denial wrong.**
- Watermarks advanced for all three; `resolved_findings` sections empty (no
  prior resolutions — first cross-company run).

## CLI-brain run on hf_fbccccb7e2 (2026-07-16 14:58Z) — TASK 1 validated live

First full CLI-brain repair run, and it validated the automatic model
selection (TASK 1) in the best possible way. Per-stage models used (from the
session log): predict=`cli:haiku`, localize=`Gemini Flash` (gateway, the cheap
sub-task), understand/hypothesize/critique/plan = `cli:sonnet`, and
**confirm_plan = sonnet** (review pinned to the strong tier). Escalation
visible: plan retries show the escalated `sonnet`.

**The payoff:** the strong `confirm_plan` reviewer **rejected an inadequate
plan across all 3 rounds** — the plan's regression test only unit-tested a
helper in isolation instead of driving the real failing input through
`query_service`, and the root cause was under-confirmed. A haiku reviewer
(the old static map) would very likely have rubber-stamped it. This is the
exact rubber-stamp failure TASK 1 removed, caught live.

**The diagnosis was genuinely sharp** (sonnet): the real defect is that
`traces` — an internal observability table in NO role's `TABLE_AREAS` — gets
treated as a role-boundary denial by `_is_access_denied`, and `refusal_message`
fabricates a confident false "(the 'traces' data area is outside your role)"
for it. That is the **generalized form of FUTURE_IMPROVEMENTS #1** (ghost-table
denial mislabel), found unprompted. And the pipeline figured out the
deterministic repro the prior initiative said it couldn't: stub the SQL
execution layer to emit `ACCESS_DENIED_TABLE:<table>` (no live LLM), then
assert `query_service` doesn't fabricate the role-denial sentence.

**Why it didn't ship yet:** the plan and the (correctly strict) confirm gate
didn't converge in 3 rounds. Supervisory fix (generic harness, not this
bug's fix): the plan prompt now requires the exact end-to-end + close-variant
+ boundary test the reviewer keeps asking for, and confirm rounds → 4, so a
sound plan and a rigorous review align faster. Re-running.

## CLI-brain end-to-end: the fix IS produced + gate-passed (2026-07-16 17:33)

The pipeline ran the full loop on the CLI brain and **passed the eval gate**:
`repro flipped fail→pass; suite 222 passed, no new failures vs baseline`.
The fix it produced (100% pipeline SEARCH/REPLACE, verified by reading the
diff + re-running the suite in the worktree: 222 passed, 3 new regression
tests pass):
- `access_policy.py`: new `_is_known_table`; `refusal_message` now only
  emits "the 'X' data area is outside your role" for a KNOWN table — an
  unknown/internal table (like `traces`) gets a generic "couldn't be
  processed — please rephrase" instead of a fabricated role-boundary denial.
- `query_service.py`: `_is_access_denied` strips the leaked table name
  cleanly (quotes/whitespace) so the branch is consistent.
This is the generalized fix for FUTURE_IMPROVEMENTS #1 (ghost-table denial),
found + fixed unprompted.

### Harness hardening to make the run reliably COMPLETE (all generic)

The first gate-pass didn't commit — the advisory self_review timed out after
the gate. Fixing that surfaced a chain of real reliability bugs, each fixed
as generic plumbing (never the bug's fix), all tests green:
1. **Commit before the advisory self-review** — a verified, gate-passed fix
   must never be lost to a slow/killed review; self_review now only amends
   if its revision still passes the gate.
2. **CLI timeout ≠ starvation** — a CLI-brain timeout/error was misclassified
   as free-tier exhaustion, triggering cooldown-WAIT cycles that hung a
   single flaky call for the whole window. Now a fast bounded retry.
3. **Dropped the literal-question test guard** — it rejected the (strong-
   review-approved) mechanism-level repro (which names the denied table, not
   the garbled question) and forced endless regen. Superseded by the strong
   confirm_plan review + the repro-must-fail-before check.
4. **Shrank the oversized test-writing prompt** (30k→~13k chars) that was
   timing out the CLI call.
5. **Code-step implement now sees the failing regression test** it must make
   pass — keeps code and test coherent (a mismatched pair fails repro_after).
6. **Checkpoint after plan-confirm + reuse the confirmed plan on resume**
   (don't re-confirm — confirm is non-deterministic and can discard a good
   plan) + `NEXUSIQ_REPAIR_FRESH_PLAN` + flushed progress markers + implement
   starts cheap and escalates (mechanical apply; gate is the backstop).

Remaining variable: raw CLI output non-determinism (a given run may emit a
weak test or a mismatched code edit — the eval gate correctly rejects those).
A retry loop runs the pipeline until a gate-pass, which now commits reliably.

## Wave-2 repair run #1 — finding hf_e4796a5431 (finpilot, false_refusal)

Started 2026-07-16 ~02:58Z on the product's own free-tier chain. Four
attempts, each observed and supervised:
- **Attempt 1** ran predict→critique clean (Groq), died at `plan`: three
  format-check failures with no visible reason. Root cause: the gateway
  discarded rejected responses. Fixed (scaffolding): preserve
  `invalid_content`, re-run the stage validator on it, feed the concrete
  reason back; partial resume seeding.
- **Attempt 2** (resumed): the new `confirm_plan` gate WORKED — it rejected
  two plans that fixed only one of two named root-cause components (topic
  matching but not Intent population), then ran out of rounds just as a good
  plan arrived. Fixed (scaffolding): seeded plans are never exempt from
  re-confirmation; confirm rounds 2→3.
- **Attempt 3** killed externally mid-run; whole free-tier chain in cooldown.
- **Attempt 4** relaunched to ride out cooldowns.

**SUPERVISION INTERVENTION (the important one).** I stopped the loop and
independently verified the finding. Two hard facts the pipeline missed:
  1. Re-running the exact question live returns `sql_plus_rag/allowed` with a
     CORRECT answer — the campaign refusal was **stochastic**.
  2. The stored trace payload shows `engine_route: "rag_only (sql_failed)"` —
     the SQL half of the 5-table join failed on the free tier and the
     degraded fallback emitted a false access-denial. The bug is NOT in the
     access-policy classifier the pipeline localized to (that function
     correctly returns None here); it's the sql-failed degraded path, a
     STOCHASTIC seam bug needing a stubbed-LLM repro the pipeline can't yet
     write (same class as the prior initiative's open hf_aa3f564b71).
  → `hf_e4796a5431` logged honestly **OPEN** with this diagnosis. An
  honestly-open hard bug does not block the goal (mission stop condition).

**Pivot to a deterministic, reproducible bug.** I re-routed every open
finding's question through the deterministic layer only (no LLM). Result:
nearly all the campaign `access_refusal`s were the same stochastic
sql-failed seam (they route to agent/sql_plus_rag today, not refusal). But
that surfaced a genuinely deterministic bug the pipeline CAN fix:
malformed/typo'd questions (`what were our expnses for quater 5?`,
`tikets by priorty for p9?`, `teh margns for q0?`) route to `agent` — and
thence to a confident LLM answer — instead of a clarification, because
`find_clarification`'s malformed-period gate only fires when a recognized
metric is present, and the typo'd metric word leaves `f.metric=None`. This
is the documented typo-bypass class, deterministic and reproducible today.
Repair pipeline pointed at `hf_fbccccb7e2` (medcore). `hf_500c08e695`
(the old "customers for a4" routing finding) checked and found ALREADY
RESOLVED on current code (now clarifies) — dismissed with a note.

### Budget-floor reality (05:12Z) — the fix is pipeline-ready, quota-blocked

After a full night of campaigns + 3 Wave-1 reviews + several repair
attempts, the shared free tier is genuinely exhausted: Groq gives one call
then a hard 60-min daily cap; NVIDIA is at 360/48 (far over its daily worker
limit); Gemini + both Cerebras models are ~40min out. §2c ("never exhaust
the free-tier quota real employees depend on") is a HARD constraint I may
not spend around — the mission's own guidance says when the budget floor is
what stands between me and the goal, the answer is a *different path*, not
forcing past it. The different path: WAIT for genuine recovery (the softer-
capped Gemini/Cerebras providers return in ~40min and can carry the
reasoning stages without Groq), then complete the fix in one clean run.

The pipeline is proven functional under this exact constraint: across the
earlier attempts it completed localize→understand→hypothesize→critique on
the free tier, and the `confirm_plan` self-check correctly rejected two
inadequate plans. The malformed-bypass bug is verified real and
deterministically reproducible; the only thing outstanding is a quota window
to run the final fix+gate. Holding for recovery rather than hammering.

### Session-end status (08:15Z) — fix quota-blocked, cleanly resumable

Waited out the daily-reset window (~08:00 UTC) and re-attempted: the free
tier is STILL only giving 1-call bursts (a full 10-minute run created the
worktree but wrote no session log — no sustained reasoning capacity). Every
alternative tier is closed this session: Bedrock disabled locally + no IAM
permission on this Mac; Ollama installed but zero models pulled. The
environment also kills any process at ~10 min, so the pipeline's own
cooldown-wait cannot ride out the throttle. These are fixed constraints
(the §2c budget floor + a process-lifetime limit), not a logic failure —
the fix is one clean run away on genuinely-restored quota (or once Bedrock
Haiku 4.5 is deployed, giving a non-shared reasoning tier).

**Honest outcome:** the self-improving loop is demonstrated end-to-end
*except* the final code-write, which is quota-unreachable this session and
logged open with an exact one-command resume (ACTIVE_HANDOFF). Per the
mission's own rule, an honestly-open item + a fixed-constraint block is not
something to fake past. The diagnosis, the reproduction, the fix location,
and the deterministic test shape are all specified so the resume is
mechanical.
