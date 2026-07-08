# AGENTS.md — NexusIQ Build Mode

## Mission

This repo is NexusIQ: Prem's recruiter-facing proof project for agentic BI, RAG, SQL, evals, traces, observability, and production-minded AI engineering.

When working in this repo, optimize for honest, visible proof that a recruiter or hiring manager can inspect in under 60 seconds and still find deep engineering behind it.

## Autonomy

- Do not stop unless truly blocked.
- Execute end to end on your own.
- Make a change, run the relevant verification, inspect the result, fix what breaks, and keep going until the stage is done and green.
- If a stage fails, diagnose from logs/traces/tests before retrying.
- Do not run blind retry loops.
- Commit as you go at meaningful green checkpoints.
- Keep moving toward the highest-impact overnight improvement possible.

## Active Handoff

Maintain `ACTIVE_HANDOFF.md` at the repo root.

Before long work waves, update it with:

- current branch/worktree
- current objective
- completed milestones
- next unfinished milestone
- exact command to resume
- tests/builds/live checks already run
- known failures and repair notes

After every milestone, update it again.

On resume after a session limit, crash, or manual continuation:

1. Read `ACTIVE_HANDOFF.md` first.
2. Continue from the next unfinished milestone.
3. Do not re-derive the full repo or transcript unless the handoff says it is necessary.

## Model Routing

Use the strongest available model for:

- architecture decisions
- product judgment
- AI/agent/RAG design
- eval/guardrail design
- hard debugging
- final quality review

Use cheaper models only for low-risk mechanical work if routing is available:

- summarizing local files
- drafting repetitive docs
- formatting
- simple code search
- small test-output summaries

Do not weaken important judgment just to save tokens.

## Build Your Own Tools

If a goal is blocked because the repo lacks a tool, harness, eval, analyzer, fixture, trace inspector, migration helper, or test utility, build the tool if it is worth the leverage.

Tools are allowed when they:

- make future work faster or safer
- expose hidden failures
- verify agent/RAG behavior
- prevent hallucinated or ungrounded outputs
- improve repeatability
- help Prem demonstrate the system

Every new tool needs a clear purpose, a command/example, and at least one verification path.

## Product Direction

There are three separate NexusIQ tracks. Do not merge them.

1. Current cloud-deployed NexusIQ: the existing Streamlit/live project.
2. Current recruiter-proof Wave 2: this local recruiter-facing upgrade workspace.
3. Future service-provider / multi-tenant NexusIQ: a separate future project folder under `/Users/nagapremsaipendela/Dev`, not part of this current Wave 2 unless Prem explicitly starts it.

For this current Wave 2, focus on making the existing NexusIQ recruiter-proof, smooth, visually impressive, technically defensible, and honest. Do not turn Wave 2 into the full multi-tenant/connect-any-database service-provider project.

Future separate service-provider direction:

- a company connects databases, documents, reports, policies, business glossary, and operational files
- NexusIQ ingests them
- NexusIQ builds business context and an ontology/entity map
- NexusIQ answers business questions with SQL, RAG, citations, confidence, cost/latency traces, and failure recovery

Do not limit future thinking to only "ontology" and "business context." Real enterprise AI/data platforms may need semantic layer, metrics layer, business glossary, data catalog, metadata extraction, entity resolution, lineage, provenance, data contracts, data quality checks, source freshness, access-control awareness, knowledge graph, feedback loops, and audit trails.

For Wave 2, use those ideas only if they directly strengthen the existing demo without expanding scope into the separate multi-tenant platform.

Do not claim real multi-tenant production unless actually implemented. It is acceptable to build a truthful demo/architecture slice that points toward this future.

## Agent Improvement Requirement

Inspect every major agent and workflow for improvement:

- SQL agent
- RAG agent
- fusion/router agent
- web agent
- business context layer
- semantic layer / metrics layer
- data catalog and metadata
- knowledge graph / entity relationships
- evals
- traces
- observability
- UI proof surfaces
- cost and latency ledger
- failure recovery and abstention

The RAG agent must not remain a shallow PDF-only demo if a higher-impact, truthful improvement is possible. Research and implement the strongest practical RAG upgrade for this repo, such as better chunking, metadata, hybrid retrieval, reranking, agentic retrieval, graph/context links, multi-document support, or richer evidence inspection.

If realistic data or documents are needed to verify an upgrade, create synthetic company data locally or use safe public examples. Prefer realistic synthetic business documents over shallow toy files. Verify live with representative questions, citations, traces, and regression checks before calling the RAG/SQL/context feature done.

## Beyond Loop Engineering

Research and reason about the major AI-engineering evolution beyond prompt/context/harness/observability/loop engineering.

Do not add buzzwords for decoration. If implementing the next layer, make it concrete and verifiable.

The likely direction is agents that learn from loop outcomes under eval and verification:

- traces become failure records
- failures become repair proposals
- repairs are tested against evals before adoption
- useful repairs become reusable tools, skills, routing rules, or memory
- risky changes require human approval
- the UI exposes this improvement loop honestly

Possible labels include self-evolving agent engineering, verification-governed agent engineering, learning-loop engineering, experience/memory engineering, or agent reliability engineering. Pick the most honest framing based on research and implementation proof.

## UI Direction

The UI should feel calm, premium, intelligent, and enterprise-grade.

Keep the calm cream visual direction if it works, but do not settle for a basic three-page frontend or a simple chat box.

Avoid:

- loud generic SaaS gradients
- childish cards
- cluttered dashboards
- fake enterprise claims
- decorative visuals that do not prove engineering depth

The UI must show proof:

- agents working
- SQL generated
- documents cited
- evidence used
- confidence and abstention
- cost/latency
- trace timeline
- eval status
- business context/ontology
- why the answer is trustworthy

## Truth Rules

- Do not fabricate users, customers, revenue, production adoption, or company usage.
- Do not touch secrets, credentials, `.env`, AWS CSVs, SSH keys, or private tokens.
- Do not overwrite Prem's original source documents.
- Do not hide limitations.
- Do not make the frontend beautiful while backend proof is weak.
- Do not remove working backend proof without replacing it with better proof.

## Definition Of Done

A milestone is not done until:

- implementation exists
- relevant tests/builds pass
- live behavior is verified where applicable
- failures are documented or repaired
- user-facing proof is visible
- `ACTIVE_HANDOFF.md` is current
