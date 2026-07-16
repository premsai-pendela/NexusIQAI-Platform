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

(Wave-1 verdicts and trace ids follow once the full run is graded.)
