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
