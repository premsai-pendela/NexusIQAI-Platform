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

Started 2026-07-16 ~02:58Z on the product's own free-tier chain (Gemini
cooling down; fallbacks in play). Stages: lessons read → predict+verify →
localize → understand → hypothesize+critique → plan → self-confirm → test
first (must fail) → fix → eval gate. Log updates follow as stages complete.
