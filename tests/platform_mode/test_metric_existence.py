"""Regression test for metric existence check.

Ensures the helper function correctly identifies known and unknown metrics
in the deterministic METRICS catalog."""
import pytest

from nexus_platform.deterministic import METRICS, metric_exists


def test_known_metric_exists():
    # Pick any metric that is present in the catalog.
    known_metric = next(iter(METRICS))
    assert metric_exists(known_metric) is True


def test_unknown_metric_returns_false():
    # Use a deliberately bogus metric name.
    assert metric_exists("nonexistent_metric_12345") is False
