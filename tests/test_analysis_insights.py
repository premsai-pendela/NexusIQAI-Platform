"""Tests: deterministic analyst notes (period parsing, notes, degradation)."""

import unittest
from unittest.mock import MagicMock

from analysis.insights import build_insights, parse_period


class PeriodTests(unittest.TestCase):
    def test_quarter_with_previous(self):
        start, end, label, prev = parse_period("revenue in Q4 2024")
        self.assertEqual((start, end, label), ("2024-10-01", "2024-12-31", "Q4 2024"))
        self.assertEqual(prev[2], "Q3 2024")

    def test_q1_previous_crosses_year(self):
        _, _, _, prev = parse_period("transactions in Q1 2024")
        self.assertEqual(prev[2], "Q4 2023")

    def test_year_with_previous_year(self):
        _, _, label, prev = parse_period("revenue in 2024")
        self.assertEqual(label, "2024")
        self.assertEqual(prev[2], "2023")

    def test_no_period_returns_none(self):
        self.assertIsNone(parse_period("what is total revenue overall"))


def _fake_session(region_rows, category_rows, totals):
    session = MagicMock()
    calls = {"n": 0}
    results = [region_rows, category_rows]

    def execute(sql, params=None):
        result = MagicMock()
        stmt = str(sql)
        if "GROUP BY" in stmt:
            result.fetchall.return_value = results.pop(0)
        else:
            result.fetchone.return_value = (totals.pop(0),)
        return result

    session.execute.side_effect = execute
    return session


class InsightTests(unittest.TestCase):
    def test_revenue_insights_shape_and_notes(self):
        session = _fake_session(
            region_rows=[("West", 400.0), ("East", 300.0), ("North", 200.0), ("South", 100.0)],
            category_rows=[("Electronics", 600.0), ("Clothing", 400.0)],
            totals=[1000.0, 800.0],
        )
        result = build_insights("What was revenue in Q4 2024?", lambda: session)
        self.assertEqual(result["kind"], "revenue")
        self.assertEqual(result["period_label"], "Q4 2024")
        region = result["breakdowns"][0]
        self.assertEqual(region["rows"][0]["label"], "West")
        self.assertAlmostEqual(region["rows"][0]["share"], 0.4)
        self.assertEqual(result["trend"]["previous_label"], "Q3 2024")
        self.assertAlmostEqual(result["trend"]["delta_pct"], 25.0)
        self.assertTrue(any("West led regions" in n for n in result["notes"]))
        self.assertIn("no LLM", result["method"])

    def test_non_aggregate_question_returns_none(self):
        self.assertIsNone(build_insights("What is the return policy?", lambda: MagicMock()))

    def test_db_failure_degrades_to_none(self):
        def broken():
            raise RuntimeError("db down")
        self.assertIsNone(build_insights("revenue in Q4 2024", broken))


if __name__ == "__main__":
    unittest.main()
