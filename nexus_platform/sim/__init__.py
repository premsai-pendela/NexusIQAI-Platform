"""Simulated-employee attack traffic for the self-improving Health Check loop.

personas      — (company, role) → AccessContext, same construction as a real
                request; the 4-layer access boundary applies structurally.
question_gen  — grounded, adversarial candidate generation across difficulty
                tiers (simple/moderate/complex/compound).
classifier    — deterministic 4-outcome scoring of each simulated answer:
                correct | wrong | vague | exceptional. Zero LLM calls.
runner        — throttled campaign loop through query_service.run_query with
                the shared quota tracker and hard per-campaign budget caps.

Design record: docs/platform improvements/ARCHITECTURE_LOG.md.
"""
