# Deploy handoff — make traces durable + visible on the live site

**This is the one step the autonomous build could not do** (the build machine
can't reach the locked-down production RDS or deploy to Fargate, and won't
touch AWS secrets). Everything else is built, tested, and committed on
`trace-restore/dev`. This is what *you* run to finish the job on AWS.

## What changed (why this fixes the empty Review page)

`nexus_platform/store.py` (traces, feedback, health, sessions, sim ledger) now
uses `db.platform_engine()`, which writes to **RDS Postgres when
`NEXUSIQ_PLATFORM_PG_URL` is set** and SQLite otherwise. In Fargate that env
var is already wired (it's how company data reaches RDS), so **once this code
deploys, traces automatically persist to RDS instead of the throwaway
container SQLite** — they survive every redeploy and accumulate. Tables
auto-create on first connect (`CREATE TABLE IF NOT EXISTS`), in the `public`
schema (company data uses per-company schemas, so no collision).

Proven locally against a real Postgres: `.venv/bin/python
scripts/verify_platform_pg_store.py` (spins up a throwaway PG, writes every
table, disposes the engine, reconnects, confirms all rows survive).

## Steps

1. **Merge / deploy the branch.** Get `trace-restore/dev` into whatever branch
   the Fargate image builds from (review first — this is your call, never
   auto-merged).
2. **Build + push the API image and redeploy the service** (your normal flow),
   e.g.:
   ```bash
   # from repo root, with your AWS creds/region set
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <acct>.dkr.ecr.us-east-1.amazonaws.com
   docker build -t nexusiq-api .            # ARM64 per the task def
   docker tag nexusiq-api:latest <acct>.dkr.ecr.us-east-1.amazonaws.com/nexusiq-api:latest
   docker push <acct>.dkr.ecr.us-east-1.amazonaws.com/nexusiq-api:latest
   aws ecs update-service --cluster nexusiq-cluster --service nexusiq-api-service --force-new-deployment
   ```
   (Exact repo/cluster/service names are in `~/Dev/interview/aws_learning_notes.md`.)
3. **Confirm durability.** After the new task is running, log into the live
   site as an Admin, ask a couple of questions on Ask Analyst, then open
   Review — the traces appear. Redeploy once more and confirm they're *still*
   there (that's the whole fix).
4. **Nothing to migrate.** No data copy is needed — RDS starts empty and fills
   from live traffic + simulation runs.

## Seeding the live Review page with history (optional, for the demo)

The live page fills naturally as people use it, but to show a rich history
immediately, run the simulation employees so their traces land in RDS. The sim
writes to whatever DB its process points at, so it must reach RDS:

- **Option A (simplest, safe):** temporarily add your current IP to the RDS
  security group, run the sim from your Mac with the RDS URL set, then remove
  the rule:
  ```bash
  export NEXUSIQ_PLATFORM_PG_URL='postgresql+psycopg2://…rds…/nexus'   # your real URL
  # then, as the CLI brain (see sim_employees/INSTRUCTIONS.md), for each employee:
  python -m sim_employees.brief --company acmecloud
  echo '[{"question":"What is our headcount?","difficulty":"simple"}, …]' \
    | python -m sim_employees.ask --company acmecloud --employee admin@acmecloud.test
  ```
  Lock the security group back down immediately after — do not leave RDS
  publicly reachable.
- **Option B (no RDS exposure):** run the sim from inside the VPC (a small
  task/box that can reach RDS on 5432).

Either way the traces are tagged `source="simulated"` and show on Review under
the **synthetic demo** badge — never presented as real customers.

## Guardrails (unchanged)

- Merging is yours only. The build never merges or deploys.
- No secrets were touched; `NEXUSIQ_PLATFORM_PG_URL` is read from the
  environment, never written anywhere.
- Simulated traffic stays labelled and is never conflated with real usage.
