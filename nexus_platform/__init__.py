"""NexusIQAI Platform Mode — multi-company, role-aware analyst workspace.

Prototype layer on top of the NexusIQ agent stack:
- demo employee registry + login (not production SSO)
- per-company data folders, brains, and agent contexts
- role-based SQL/RAG access boundaries
- per-employee memory, traces, and feedback

Named nexus_platform (not "platform") to avoid shadowing the stdlib module.
"""
