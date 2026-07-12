"""Regression test for orchestrator metric clarification.

The question “What is our NPS score for 2024?” contains a metric word
(“score”) that is not present in the deterministic METRICS catalog.  The
orchestrator should recognise the missing metric and return a clarification
instead of routing to a deterministic SQL template.

This test ensures that the current implementation (prior to the fix) does
*not* produce a clarification, causing the test to fail, and that after the
planned change the test passes.
"""

import pytest

from nexus_platform.orchestrator import decide_route
from nexus_platform.registry import get_registry
from nexus_platform.access_policy import get_policy


def test_unknown_metric_triggers_clarification():
    """An unrecognised metric should cause a clarification request."""
    reg = get_registry()
    # Use a role that has access to typical tables (Analyst is a common role)
    policy = get_policy("Analyst")

    # No previous intent – this is a fresh question.
    decision = decide_route("What is our NPS score for 2024?", policy, None)

    # The orchestrator must ask for clarification about the metric.
    assert decision.clarification is not None, "Expected a clarification for unknown metric"
    assert decision.clarification.kind == "unclear_metric"
