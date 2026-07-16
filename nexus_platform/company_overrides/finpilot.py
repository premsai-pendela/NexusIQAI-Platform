"""FinPilot Ops — company-scoped analyst overrides.

Same contract as acmecloud.py: EXTRA_METRIC_VOCABULARY and an optional
find_clarification(question, features, policy) hook. Company-specific fixes
for FinPilot land here, never in shared modules. Currently empty.
"""

EXTRA_METRIC_VOCABULARY: tuple = ()
