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
    #
    # kind is "unknown_metric", not "unclear_metric": find_clarification()'s
    # own unknown-scalar-metric check (nexus_platform/orchestrator.py, the
    # unknown-metric honesty gate) fires before decide_route()'s later
    # metric-noun fallback ever runs, since decide_route calls
    # find_clarification() first. Both were built to catch this same "NPS
    # score" shape from the two PRs that shipped together (the honesty gate
    # and this test's originating fix); "unknown_metric" is the one that
    # actually reaches the caller, and three tests in
    # test_unknown_metric_gate.py plus the classifier gold set already
    # depend on that exact label — this assertion was the stale one.
    assert decision.clarification is not None, "Expected a clarification for unknown metric"
    assert decision.clarification.kind == "unknown_metric"
