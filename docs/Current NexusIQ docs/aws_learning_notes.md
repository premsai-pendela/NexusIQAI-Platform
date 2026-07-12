# AWS Learning Notes — NexusIQAI Cloud Migration

Format per entry: **What I ran** → **Why this, not the alternative** → **Interview line**.

---

## 1. ECR (Elastic Container Registry)
- What I ran: `aws ecr create-repository --repository-name nexusiq-api --region us-east-1 --image-scanning-configuration scanOnPush=true`
  → repo `630589800012.dkr.ecr.us-east-1.amazonaws.com/nexusiq-api` created.
- Why: private, versioned Docker image store. ECS/Fargate pulls straight from it, IAM-controlled, scans images on push.
- Why not the alternative:
  - **Docker Hub** — public by default, no native IAM tie-in to ECS, extra auth hop, rate limits on free tier.
  - **S3 for tarballs** — not a real registry, no image layers/tags/scanning, ECS can't pull from it directly.
  - **Self-hosted registry** — one more service to patch and secure, no benefit over a managed one for a single-image app.
- Interview line: "I push my backend image to ECR because it's IAM-native and ECS pulls from it directly — no separate registry auth to manage, and scan-on-push catches CVEs before they ship."

## 2. ECS + Fargate
- **Live**: `nexusiq-api-service` running on `nexusiq-cluster`, task def
  `nexusiq-api:2`, reachable at `http://<task-public-ip>:8000` (health
  verified — all agents online, 1065 real chroma chunks, environment=production).
- Real deploy bugs hit + fixed, in order:
  1. **IAM permission walls**: the deploy IAM user (`Nexusiq_AI-Deploy`) only
     had ECR + Secrets Manager access. Had to add ECS/RDS/EC2 managed
     policies plus a scoped `iam:PassRole` inline policy before touching ECS
     at all. Also could not create IAM roles itself — had Prem create
     `nexusiq-ecs-task-execution-role` and `nexusiq-ecs-task-role` directly
     in the console since role creation is a privileged action the deploy
     user correctly can't self-grant.
  2. **AWS Educate/Academy guardrail**: `AmazonRDSFullAccess` /
     `AmazonEC2FullAccess` didn't show up in the normal IAM policy picker at
     first (looked like they didn't exist) — they did exist, just needed a
     narrower search term in the console's fuzzy-substring search box, not a
     missing feature.
  3. **Task execution role could pull the image but not create its own log
     group**: `awslogs-create-group: "true"` in the task def isn't covered
     by the standard `AmazonECSTaskExecutionRolePolicy` (only
     CreateLogStream/PutLogEvents are). Fixed by creating
     `/ecs/nexusiq-api` directly via `aws logs create-log-group` instead of
     widening the execution role's log permissions.
  4. **Wrong CPU architecture**: image was built on an Apple Silicon Mac
     (arm64-only) but Fargate defaults to x86_64 — task failed with
     `CannotPullContainerError: image Manifest does not contain descriptor
     matching platform 'linux/amd64'`. Fixed by adding
     `"runtimePlatform": {"cpuArchitecture": "ARM64", ...}` to the task
     definition instead of rebuilding for a different architecture (ARM64
     Fargate is also usually cheaper).
- What I ran: built `Dockerfile.api` (FastAPI-only, no Streamlit CMD), verified locally with
  `docker build -f Dockerfile.api -t nexusiq-api:local .` then `docker run` + curl against
  `/api/v1/health` and `/api/v1/query` — full SQL+RAG+fusion round trip confirmed working in
  the container before pushing. Pushed to ECR:
  `docker push 630589800012.dkr.ecr.us-east-1.amazonaws.com/nexusiq-api:latest`.
  Fargate task definition itself is the next command still pending.
- Bug hit + fixed: `.env` had `CHROMA_PERSIST_DIRECTORY` pointing to the *old* repo's absolute
  host path (`/Users/.../NexusIQ-AI/data/chroma_db`) — a stale leftover from copying the repo.
  RAG agent reported "degraded" until I pointed it at the relative in-repo path
  (`./data/chroma_db`). Lesson: absolute host paths in env files silently break the moment the
  app runs anywhere else — always use paths relative to the container/repo root.
- Push gotcha: `docker login` kept failing with `The specified item already exists in the
  keychain (-25299)` — a stale/corrupted macOS keychain entry conflicting with the
  `osxkeychain` credential helper. Fixed by using an isolated `DOCKER_CONFIG` dir with the
  ECR bearer token written directly into its `auths` field, bypassing the keychain helper
  entirely for that one push, then deleting the temp config. Didn't touch the real
  `~/.docker/config.json` or keychain.
- Why: run containers without managing servers.
- Why not the alternative:
  - **EC2 (old setup)** — I patch the OS, size the instance, and pay for it 24/7 even idle. Fargate bills per task-second and needs zero OS maintenance.
  - **EKS** — full Kubernetes control plane, built for many services/teams. One backend container doesn't need that complexity or its ~$70+/mo control-plane cost.
  - **Lambda** — cold starts and 15-min max runtime are a bad fit for a long-lived FastAPI process with in-memory model/LLM-gateway state.
- Interview line: "I moved off EC2 to Fargate — same containers, but AWS manages the host, and I stop paying for idle compute between demo sessions."

## 3. RDS (Postgres)
- What I ran: _(pending)_
- Why: replace external Supabase dependency, single-cloud story.
- Why not the alternative:
  - **Keep Supabase** — works, but it's a second cloud vendor outside my AWS billing/IAM boundary; breaks the "one account, one story" narrative and adds a network hop.
  - **DynamoDB** — the app is relational (35 tables, joins, SQL agent generates real SQL) — NoSQL would mean rewriting the whole SQL layer for no benefit.
  - **Self-managed Postgres on EC2** — back to patching/backups by hand; RDS gives automated backups/failover for a small cost delta.
- Interview line: "I migrated off a third-party Postgres host to RDS so the database lives inside the same AWS account as the compute — one bill, one IAM boundary, automated backups."

## 4. Bedrock
- What I ran: _(pending)_
- Why: AWS-native managed LLM API (Claude, Titan, Llama), added as last fallback tier after Cerebras.
- Why not the alternative:
  - **Just keep Gemini/Groq/NVIDIA/Cerebras** — those prove I can integrate any provider's API, but none of them show AWS-specific AI skill, which is what half the JDs I researched actually name-check (Bedrock beat SageMaker 17-to-3 in mentions).
  - **SageMaker endpoints** — built for hosting/training your own model; I'm not training a custom model, so a managed inference API (Bedrock) is the honest fit, not overkill.
  - **Azure OpenAI / Vertex AI** — different cloud, breaks the single-AWS-account story I'm building toward.
- Interview line: "My LLM gateway already has four fallback tiers; Bedrock is the fifth and the AWS-native one — same call pattern as Gemini or Groq, but it proves I can wire a model provider that lives inside the same cloud as my compute and IAM."

## 4.5 Application Load Balancer (stable endpoint over Fargate)
- **Live**: `http://nexusiq-api-alb-1838282443.us-east-1.elb.amazonaws.com`
  → target group `nexusiq-api-tg` (IP target type, required for Fargate
  `awsvpc` networking, not instance targets) → ECS service, health check on
  `/api/v1/health`.
- Why: a bare Fargate task's IP changes every restart/redeploy — anything
  pointing at it (a frontend, a bookmark, DNS) breaks silently. An ALB gives
  a permanent DNS name in front of a fleet that can restart/scale freely.
- Security model: task security group only accepts port 8000 from the ALB's
  security group (not 0.0.0.0/0 anymore) — the ALB is the only public door.
  Task still has `assignPublicIp=ENABLED` for *outbound* internet (pulling
  the ECR image, calling Gemini/Groq/Supabase) since these public subnets
  have no NAT gateway; that public IP is not directly reachable inbound
  because the security group only allows the ALB's SG as a source.
- Real bug hit: first service revision was created with
  `assignPublicIp=DISABLED` (reasoning: "the ALB handles public access
  now"). That's wrong — disabling the public IP in a subnet with no NAT
  gateway kills *outbound* internet too, not just inbound. The task would
  never have been able to pull its own image or reach any external API.
  Caught before the service went live by working through what NAT-less
  public subnets actually give you (nothing, without either a public IP or
  a NAT gateway) rather than assuming "ALB in front" means the task's own
  public IP is now redundant.
- Why not the alternative:
  - **NAT Gateway + fully private task** — the "more correct" enterprise
    pattern (task never has a public IP at all), but costs ~$32/mo alone
    and is unnecessary complexity for a single-service portfolio deploy.
    Public subnet + scoped security group achieves the same real security
    boundary (nothing can reach the task except the ALB) for $0 extra.
  - **Skip the ALB, keep hitting the raw task IP** — free, but the IP
    changes on every deploy; not viable the moment a frontend depends on it.

## 5. Secrets Manager
- What I ran: _(pending)_
- Why: keep API keys/DB creds out of code and env files in prod.
- Why not the alternative:
  - **.env file in the image** — what the local dev setup does today; fine locally, a real leak risk baked into a container that gets pushed to a registry.
  - **SSM Parameter Store** — cheaper, works, but no native automatic rotation and a slightly weaker story for "credential lifecycle" in an interview; Secrets Manager is the more recognized answer to "how do you handle secrets in AWS."
  - **Environment variables set manually per task** — no central audit trail, no rotation, breaks the moment you add a second environment.
- Interview line: "Secrets never touch the container image — Secrets Manager injects them at runtime and I can rotate a key without rebuilding or redeploying."

## 6. CloudWatch
- What I ran: _(pending)_
- Why: centralized logs/metrics for the running containers.
- Why not the alternative:
  - **Just stdout, read via `docker logs`** — fine on one EC2 box you SSH into; gone the moment tasks are ephemeral Fargate containers that restart or scale.
  - **Third-party (Datadog/Grafana Cloud)** — real tools, but a second vendor and bill for a portfolio-scale app; CloudWatch is already free-tier included and IAM-native.
  - **Langfuse only** — I already have Langfuse for LLM-specific traces; CloudWatch covers infra-level logs/metrics Langfuse doesn't (container health, request latency at the ALB/ECS layer).
- Interview line: "Every task ships logs to CloudWatch, so a failed request is traceable end to end even though the container itself is gone by the time I look."

## 7. S3
- What I ran: _(pending)_
- Why: object storage for PDF/document archive.
- Why not the alternative:
  - **Bundle PDFs into the Docker image** — what the old setup did (`COPY . .`); bloats the image, and any doc update means a full rebuild/redeploy.
  - **EFS** — built for shared POSIX filesystem access across tasks; I don't need file-locking or POSIX semantics, just read-mostly blob storage, so S3 is simpler and cheaper.
  - **RDS large objects** — storing PDFs as DB blobs bloats the database and slows every backup; S3 is the standard place for unstructured files.
- Interview line: "Source PDFs live in S3, not in the image, so updating the document corpus doesn't require a redeploy."

## 8. CloudFormation
- What I ran: _(pending)_
- Why: infra as code — the whole stack (ECS, RDS, Secrets, networking) defined in one template, reproducible.
- Why not the alternative:
  - **Click-ops in the console (what I did on EC2 originally)** — not reproducible, no diff/history, easy to forget a setting when rebuilding.
  - **Terraform** — real and more portable across clouds, but adds a second tool/state-backend to manage for a single-cloud AWS project; CloudFormation is native, no extra state file to host.
  - **CDK** — nicer authoring experience (real code, not YAML) but one more abstraction layer; for a single-stack portfolio deploy, plain CloudFormation is easier to explain line-by-line in an interview.
- Interview line: "The whole stack — ECS service, RDS, secrets, networking — is one CloudFormation template, so I can tear it down and rebuild it from a single file instead of clicking through the console again."

## 8.5 ACM + HTTPS listener (fixing mixed content)
- **Live**: `https://api.nexusiq-ai.com` — ACM cert for that subdomain, HTTPS
  (443) listener on the ALB forwarding to the same target group as the HTTP
  listener.
- Real bug hit: after deploying the frontend to Amplify (HTTPS by default),
  login/query calls failed with no visible error in curl checks — browsers
  silently block "mixed content" (an HTTPS page calling an `http://` API)
  that curl doesn't enforce, so this only shows up in a real browser, not in
  server-side checks. Root cause: `NEXT_PUBLIC_API_BASE` was pointed at the
  plain-HTTP ALB DNS name.
- You cannot get an ACM certificate for the raw `*.elb.amazonaws.com` name —
  needed a real subdomain (`api.nexusiq-ai.com`) pointed at the ALB, then a
  cert for that subdomain.
- DNS is on Cloudflare, not Route 53, for this domain — added the ACM
  validation CNAME and the `api` → ALB CNAME directly in the Cloudflare
  dashboard, both set to **DNS only** (not proxied) since Cloudflare's proxy
  in front of an ALB with its own ACM cert needs extra config we don't need
  here.
- Second bug hit: `aws amplify update-app --environment-variables` **replaces
  the entire env var set** rather than merging. Setting only
  `NEXT_PUBLIC_API_BASE` silently deleted `AMPLIFY_MONOREPO_APP_ROOT`, which
  broke the next build (`Cannot read 'next' version in package.json` — Amplify
  needs that env var to find the app in the monorepo *before* it even reads
  the buildSpec's `appRoot` field). Fixed by re-setting all three env vars
  together in one call.

## 9. Amplify Hosting
- **Live**: `https://master.d3dp95aawguyfq.amplifyapp.com` — Next.js SSR app,
  auto-deploys on push to `master` of `github.com/premsai-pendela/NexusIQAI-Platform`.
- What I ran: pushed this workspace to a **new** GitHub repo rather than the
  existing `NexusIQ-AI` one — that old repo has a live `deploy-ec2.yml`
  workflow wired to the still-running EC2 box; pushing this cleaned-up code
  there would have auto-triggered a deploy of the new (Streamlit-free) code
  onto the old EC2 using the old (Streamlit-expecting) Dockerfile and broken
  the live site by accident. New repo = zero risk of that collision.
- Connected Amplify to GitHub via the console's GitHub App flow, not a
  personal access token. A personal `gh auth token` has broad scope (all
  repos, workflow triggers, org read) — handing that to Amplify would give
  AWS a permanent credential far wider than "read this one repo." The
  GitHub App flow scopes access to just the repo you approve.
- Real bug hit: first deploy failed with `Cannot read 'next' version in
  package.json` — the app root wasn't set to `web` (repo root has Python +
  Next.js mixed, a monorepo). Checked "My app is a monorepo," set app root
  to `web`; Amplify then correctly auto-detected Next.js and enabled SSR
  compute (it had shown "Framework: None, SSR: Disabled" before the fix —
  would have deployed as a static-only site and broken the server-side
  `redirect()` in the root page).
- Why: hosts the Next.js frontend in the same AWS account as the backend — single-cloud story.
- Why not the alternative:
  - **Vercel** — the "native" Next.js host, zero-config, genuinely easier — but it's a second cloud vendor, which breaks the single-AWS-account narrative I'm optimizing for on this resume pass.
  - **S3 + CloudFront static hosting** — works for a fully static export, but this Next.js app has server-rendered/platform routes, not a pure static site, so a static bucket alone isn't the right fit.
  - **Serve the frontend from the same Fargate container as the API** — couples frontend and backend deploys/scaling together for no reason; keeping them separate lets each scale and redeploy independently.
- Interview line: "Frontend and backend both run inside AWS — one account, one bill — even though Vercel would've been the easier default for Next.js."

---

## Cleanup pass before the first real push (2026-07-08)
Before wiring Fargate/RDS, did a full sweep of this branched repo for legacy
Streamlit-era traces, since deploying a half-cleaned repo would've meant
rebuild-after-rebuild once things broke on AWS instead of locally.

Removed:
- Streamlit UI: `main.py`, `ui/`, `.streamlit/`, `streamlit_app.py`,
  `wake_up_streamlit.py`. Confirmed identical pages already live in the
  separate `~/Dev/NexusIQ-recruiter-proof` workspace first — nothing lost.
- Legacy single-tenant data: `data/chroma_db` (475 chunks), `data/corpus`,
  `data/pdfs` — fed the old `/api/v1/query` route and its 4 frontend pages
  (`ask`, `context`, `how`, `reliability`), all superseded by Platform Mode.
- Backend routes built only for that legacy surface: `api/routes/query.py`,
  `agents.py`, `meta.py`, `context_map.py`, plus their whole orphaned
  subsystem: `context/entity_map.py`, `database/ingestion_pipeline.py`,
  `database/generate_noise_corpus.py`, `scripts/onboarding_demo.py`, and
  their test files.
- `streamlit`/`streamlit-lottie` from `requirements.txt` — image no longer
  pulls in Streamlit/Altair/pydeck at all.
- Rewrote `api/routes/health.py` to probe a real Platform Mode company
  (acmecloud/Admin) instead of the dead legacy singleton.

Real bugs hit + fixed during this pass (kept for pattern recognition, not
just this repo):
1. **Stale absolute path**: `.env` had `CHROMA_PERSIST_DIRECTORY` pointing
   at the *old* repo's absolute host path — broke the moment it ran anywhere
   else. Fixed to a relative path.
2. **Deleted my own import by accident**: stripped a dead Streamlit-secrets
   hook from `config/settings.py` and took the `import os` line with it —
   `os.getenv` elsewhere in the same file broke at class-definition time.
   Caught it because I run the container and hit the actual route after
   every change, not just after the build succeeds.
3. **Quoted env values silently corrupt in Docker**: `.env` had
   `LANGFUSE_BASE_URL="https://cloud.langfuse.com"` — python-dotenv strips
   the quotes locally, but `docker run --env-file` (and later, ECS task-def
   env vars / Secrets Manager) do **not** strip them. The app received the
   literal string `"https://cloud.langfuse.com"` quote-characters-and-all
   and every trace export failed silently in the logs. Lesson: never quote
   values in `.env` files meant to cross into container/ECS env injection.

Verified after cleanup: `pytest tests/ -q` → 373 passed, 32 subtests passed,
0 failed. Real query against acmecloud's Postgres+Chroma brain through the
rebuilt container returned a correct, real answer (Engineering department,
$237,741,461.13 revenue) with full SQL→routing→answer trace in the logs.

Known loose end, intentionally left alone (not part of the container's boot
path): `mcp_server/server.py` still calls the old "live" singleton
(`get_fusion_agent()` default mode) and would degrade if run standalone,
since its backing data is gone. Not fixed now because it's a separate
optional process never started by `Dockerfile.api` — flagged, not urgent.

## Final verification (2026-07-08, later that day)
- RDS population finished: 3 companies, ~468k rows, took far longer than
  expected — running the generator from a laptop over the public internet
  to RDS means every batch is a real network round trip; the biggest table
  (`usage_events`, 60k rows/company) and `ticket_messages` (~22k rows/company)
  dominated the wall-clock time even though CPU usage stayed near idle the
  whole time. Lesson for next time: run bulk population from *inside* the
  VPC (an EC2 box, or an ECS one-off task) if the row count is large — same
  data, a fraction of the time, since round trips become sub-millisecond.
- After population: reverted the temporary "my laptop's IP" security group
  rule and flipped `PubliclyAccessible` back to `false` on the RDS instance.
  Confirmed this worked because my own `psql` from the laptop timed out
  afterward trying to reach it directly — a good sign, not a bug.
- Verified Bedrock honestly: a real open-ended question was answered by
  Groq → Gemini, never reached Bedrock, because those tiers are healthy and
  come first in the fallback chain. That's correct behavior for a fallback
  tier, not a failure to prove it works. The honest resume/README claim is
  "Bedrock is wired as a fallback tier" (true — IAM-permissioned, code
  path unit-tested, deployed) not "Bedrock is serving production answers"
  (would need forced-failure testing of the earlier tiers to actually see).

## CloudFormation capture (2026-07-08, after domain cutover)
- Wrote `infrastructure/nexusiq-platform-stack.yaml` in the repo: all 18
  resources for the real live stack (ECR, security groups, RDS, IAM roles,
  ECS cluster/task-def/service, ALB+listeners+target group, Amplify app).
- Deliberately did **not** run it against the live account — the named
  resources already exist under these same names from the manual CLI build,
  so `create-stack` would collide (ECR repo name taken, ALB name taken, RDS
  identifier taken, etc.), not adopt them. The point of this artifact for
  interviews is "the whole stack is one file, reproducible in a fresh
  account," not "I ran this today on top of what's already there."
- Couldn't even run the safe, read-only `cloudformation:ValidateTemplate`
  call — the deploy IAM user has zero CloudFormation permissions (never
  granted, and no one was around to add it). Validated structurally instead
  with a local YAML parse (stripped the `!Ref`/`!GetAtt`/`!Sub` intrinsic
  tags first since PyYAML doesn't know custom CFN tags, then confirmed all
  18 resources and 4 outputs parsed). Real semantic validation (does AWS
  actually accept every property) is still unverified — flag that honestly
  in an interview rather than claim it's been deployed from scratch.

## Memory method (why this file exists)
1. One file, updated per milestone, not per docs page.
2. Teach-back: explain each entry out loud in 2 sentences before moving on.
3. Redo, don't read: re-run yesterday's command from memory before starting today's.
4. Note errors + fixes, not just clean success — pain is what sticks.
5. Each entry always answers "why not the obvious alternative" — that's the actual interview question, not just "what did you use."
