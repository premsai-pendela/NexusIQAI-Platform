# Why this run exists — resume context + honest-metrics rule (for Fable)

This is background, not a task. Read it so you understand **what kind of honest
evidence this run could produce that would matter**, and then only capture what
*actually* happens. **You must never manufacture a metric, or change behavior
just to create a number.** The rule is: run the loop honestly; if real
before→after improvements occur, record the real ones.

## The situation
Prem (the repo owner) is job-hunting for AI/ML engineering roles. NexusIQ is his
flagship project. A real person, **Murta**, reviewed his résumé and left
comments. The single hardest gap Murta raised: the NexusIQ bullets describe
*capabilities* but have **almost no metrics** — and Murta's core rule for a
strong bullet is:

> **Action verb + task + process/strategy + a Result that is a metric.**

Other Murta comments that shape what "good" looks like:
1. The résumé "reads GPT-generated" — write plainly, evidence over adjectives.
2. A bullet dense with four named mechanisms — make sure a skimming recruiter
   still grasps *what the product is* before the mechanisms.
3. "Good point" on the deterministic zero-LLM layer (keep it).
4. No bullet over two lines.
5. "Good point" on the test suite (keep it).
6–8. (RevenueIQ) drop trailing activity-lists; don't let LLM-written output read
   as a gimmick — "how did you stop the LLM hallucinating numbers?" is a fair
   interview question.
9. (Research role) a bullet that ends in a capability list with **no outcome** is
   weak — give it a real result.
10. Every work bullet should be action + task + process + **metric**; 3–5 bullets
    per role; use the real jargon of the role.
11. Skills section is fine, but **prove each claimed skill in a bullet** —
    evidence beats a list.

So the NexusIQ résumé bullets are currently strong on *what it is* (governed,
multi-company AI data analyst; answers carry SQL + citations + traces; a
deterministic zero-LLM layer; a self-auditing Health Check agent that opens
human-reviewed PRs) but thin on **numbers**. The current defensible number is
basically the test count. That is the gap this run can honestly help close.

## What honest evidence this run could produce (capture only if real)
As the Health Check loop actually runs, these are the kinds of *real* metrics
that, if they genuinely occur, would let a NexusIQ bullet satisfy Murta's
"action + process + metric" — measure a **baseline before** the health check
repairs anything, then **after**:
- **Fabrication / wrong-answer rate** on the simulated traces: before → after a
  fix (e.g. "denials naming a nonexistent table: N → 0").
- **Health-review eval pass-rate** lift after fixes.
- **Number of real bugs** the loop caught unprompted, and **predicted-and-verified**
  hidden bugs, and how many were fixed with a passing regression test (and the
  regression rate — fixes that held vs. broke something).
- **Latency** reduction on the analyst paths you touch (accurate *and* faster).
- Attempts-to-fix, and whether a fix **generalized** across companies.

Record these in the two dated notes files as they happen, clearly separating
*surfaced* vs *predicted-and-verified* vs *unverified hypothesis*. These honest
numbers — and only these — are what may later become a résumé bullet. If a
number didn't really happen, it doesn't get written, anywhere.

## NexusIQ, in one paragraph (so you know what's résumé-worthy)
NexusIQ Platform Mode is a governed, multi-company AI data analyst (AcmeCloud,
MedCore, FinPilot). Employees ask plain-English questions and get answers backed
by SQL, citations, confidence, and a full trace; access is role-scoped at four
layers; common questions resolve deterministically with zero LLM calls; and a
second **Health Check agent** audits the analyst's traces and opens
human-reviewed pull requests (never auto-merged) to fix failures it finds. It's
deployed on AWS (ECS Fargate, RDS, Bedrock fallback). The self-auditing repair
loop is the standout, differentiated capability — which is exactly why making it
produce **real, measured** results is worth this run.
