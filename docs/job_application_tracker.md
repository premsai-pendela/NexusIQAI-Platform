# NexusIQ Job Application Tracker

This file is the durable memory for the `NexusIQ-fit job scout` automation.

The automation should read this file before every run, preserve manual edits, and avoid recommending roles already marked `Applied`, `Skipped`, or `Rejected` unless there is a meaningful status change.

## Status Values

- `Researched`: verified and scored, but no action taken yet.
- `Apply Now`: high-quality target ready for application.
- `Applied`: application submitted.
- `Cold Email`: better handled through direct outreach.
- `Watchlist`: promising, but blocked by timing, seniority, unclear fit, or missing information.
- `Skipped`: intentionally not pursuing.
- `Rejected`: applied and got a rejection.
- `Closed`: role is no longer accepting applications.

## Tracker

| Company | Role | Status | Apply URL | Last Checked | Applied Date | Fit Score | Verdict | Notes |
|---|---|---:|---|---:|---:|---:|---|---|
| XY.ai | Customer Implementation Engineer | Apply Now | https://www.xy.ai/career/customer-implementation-engineer | 2026-07-07 |  | 9.5/10 | Apply + cold email | Company page is live. Strong agentic workflow, Python/JS, SQL, APIs, guardrails, healthcare workflow implementation fit. Old LinkedIn mirror was closed, so use company page. |
| Doowii | Implementation Engineer | Apply Now | https://remotive.com/remote/jobs/all-others/implementation-engineer-5113285 | 2026-07-07 |  | 9/10 | Apply now | Strong SQL, Python, APIs/ETL, customer implementation fit. Bonus match for LLM evaluation, vector stores, semantic layers. Verify primary company/Gem page if accessible. |
| Worth AI | Implementation Engineer | Apply Now | https://apply.workable.com/worthai/j/6D392C1E4B/ | 2026-07-07 |  | 8/10 | Apply now | Company Workable page confirms open. Fintech AI implementation, SQL, Node, React, demos, onboarding, customer training. |
| Productera | Product Engineer (AI-Driven Fullstack Developer) | Researched | https://productera.io/careers/product-engineer-ai-driven-fullstack-developer | 2026-07-07 |  | 7/10 | Apply if fullstack positioning is strong | Broader product engineering role. Strong AI-assisted development and SQL/product analytics fit, weaker direct implementation-agent fit. Contract role. |
| Hire Hangar | Implementation Engineer, AI & Workflow Platforms | Watchlist | https://jobs.ashbyhq.com/hirehangar/476ff5fe-8aa3-46e3-a594-5ac1cdd1817e | 2026-07-07 |  | 6/10 | Lower priority | Skills fit Python, SQL, AI workflows, but source quality/pay/company clarity are weaker. |
| Kontent.ai | Solutions Engineer (US) | Watchlist | https://www.linkedin.com/jobs/view/4426486388/ | 2026-07-07 |  | 6.5/10 | Apply if customer-facing role desired | Good AI/content operations and API-first SaaS fit, but weaker SQL/Python/NexusIQ data-agent match. Requires valid U.S. work authorization. |
| Zearch client | Associate Solutions Engineer, AI Automation/Orchestration Platform | Researched | https://www.linkedin.com/jobs/view/4432363145/ | 2026-07-07 |  | 8/10 | Apply, but do not over-invest | Associate-level, remote, Python, SQL, YAML, POCs, onboarding. Recruiter/client anonymized. |
| Trek Health | Solution Implementation Engineer | Watchlist | https://bebee.com/us/jobs/solution-implementation-engineer-trek-health-sacramento-county-ca--jooble-2245568363819309268 | 2026-07-07 |  | 7/10 | Cold email/watchlist | Strong healthcare financial intelligence, SQL, AI tools, client onboarding. Blocked by 3+ years and healthcare claims/revenue-cycle domain. |
| OfferFit | Machine Learning Implementation Engineer | Closed | https://jobs.menlovc.com/companies/offerfit/jobs/38764046-machine-learning-implementation-engineer | 2026-07-07 |  | 8/10 | Skip unless reopened | Excellent category fit, but posting says no longer accepting applications. |

## Run Log

| Date | Automation Run | Summary |
|---:|---|---|
| 2026-07-07 | Manual seed | Seeded tracker from initial research: XY.ai, Doowii, Worth AI, Productera, Hire Hangar, Kontent.ai, Zearch, Trek Health, OfferFit. |

## Manual Update Examples

After applying, change:

`| Worth AI | Implementation Engineer | Apply Now | ... | 2026-07-07 |  | ... |`

to:

`| Worth AI | Implementation Engineer | Applied | ... | 2026-07-07 | 2026-07-08 | ... |`

If a role is not worth pursuing, set `Status` to `Skipped` and add the reason in `Notes`.
