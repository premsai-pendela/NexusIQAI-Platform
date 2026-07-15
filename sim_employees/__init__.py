"""Simulation employees — outside-Nexus synthetic traffic generators.

A simulation employee is a persona for one (company, role) that queries the
AIDA analyst **directly in the backend** (via `query_service.run_query`, the
same 4-layer access boundary a real request goes through) with every trace
tagged `source="simulated"`. Each employee keeps a **private file memory**
(`sim_employees/memory/<company>/<email>.json`) of what it has asked and how
the analyst answered, so day to day it can re-probe weak spots and avoid
repeating solved questions.

The employee's *brain* — deciding what to ask — is an **external CLI agent**
(Claude Code, Codex, or any), not NexusIQ's own free-tier LLM chain. See
`sim_employees/INSTRUCTIONS.md`. NexusIQ's free tier answers the questions
(the thing under test); the CLI brain writes them. The two are kept separate
so simulation never spends the quota real employees depend on.
"""
