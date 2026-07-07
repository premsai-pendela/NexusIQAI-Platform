"""Tests for the verification-governed learning loop."""

import json
import tempfile
import unittest
from pathlib import Path

from learning.classify import classify_trace, failures_from_rag_eval_report, scan_trace_files
from learning.records import (
    FailureRecord,
    InvalidTransition,
    RepairProposal,
    failure_store,
    save_failure,
)
from learning.service import intake_eval_report, loop_summary, scan_and_persist


def _make_trace(**overrides):
    trace = {
        "trace_id": "abc123",
        "question": "What was net revenue in Q4 2024?",
        "duration_s": 3.5,
        "spans": [{"name": "llm.call", "status": "ok", "metadata": {"failure_kind": None}}],
        "final": {
            "answer": "Net revenue was $42.9M.",
            "validation": {"confidence": "HIGH", "confidence_reason": "1 validated fact"},
        },
    }
    trace.update(overrides)
    return trace


class TraceClassifierTests(unittest.TestCase):
    def test_healthy_trace_produces_no_record(self):
        self.assertIsNone(classify_trace(_make_trace()))

    def test_failed_span_becomes_llm_failure(self):
        trace = _make_trace(spans=[
            {"name": "llm.call", "status": "error",
             "metadata": {"failure_kind": "timeout", "task": "rag.answer", "model": "m"}},
        ])
        record = classify_trace(trace)
        self.assertEqual(record.failure_kind, "llm_failure")
        self.assertEqual(record.trace_id, "abc123")
        self.assertEqual(record.evidence["failed_spans"][0]["failure_kind"], "timeout")

    def test_low_confidence_becomes_weak_evidence(self):
        trace = _make_trace(final={
            "answer": "Based on limited data...",
            "validation": {"confidence": "LOW", "confidence_reason": "no corroboration"},
        })
        record = classify_trace(trace)
        self.assertEqual(record.failure_kind, "weak_evidence")
        self.assertEqual(record.evidence["confidence"], "LOW")

    def test_abstention_text_becomes_weak_evidence(self):
        trace = _make_trace(final={
            "answer": "I don't have enough evidence to answer this reliably.",
            "validation": {"confidence": "MEDIUM"},
        })
        record = classify_trace(trace)
        self.assertEqual(record.failure_kind, "weak_evidence")
        self.assertTrue(record.evidence["abstained"])

    def test_slow_trace_becomes_latency_regression(self):
        record = classify_trace(_make_trace(duration_s=45.0))
        self.assertEqual(record.failure_kind, "latency_regression")

    def test_scan_skips_unreadable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_dir = Path(tmp)
            (trace_dir / "trace-bad.json").write_text("{not json")
            (trace_dir / "trace-good.json").write_text(json.dumps(_make_trace(duration_s=99)))
            records = scan_trace_files(trace_dir)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].failure_kind, "latency_regression")


class EvalIntakeTests(unittest.TestCase):
    def test_misses_become_retrieval_miss_records(self):
        report = {
            "hit_rate": 0.98,
            "top_k": 5,
            "misses": ["lost_sales_estimate"],
            "results": [{
                "id": "lost_sales_estimate",
                "question": "What was the lost sales estimate?",
                "expected_sources": ["11_Seasonal_Demand_Incident_Report"],
                "top_retrieved": [{"filename": "06_Electronics_Category_Deep_Dive.pdf"}],
            }],
        }
        records = failures_from_rag_eval_report(report)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].failure_kind, "retrieval_miss")
        self.assertEqual(records[0].evidence["eval_id"], "lost_sales_estimate")

    def test_clean_report_produces_no_records(self):
        self.assertEqual(failures_from_rag_eval_report({"misses": [], "results": []}), [])


class RepairStateMachineTests(unittest.TestCase):
    def _proposal(self):
        return RepairProposal(
            proposal_id="rp-test",
            created_at="2026-07-06T00:00:00Z",
            title="Tune incident-report retrieval",
            description="Add lost-sales phrasing to retrieval normalization.",
            repair_type="retrieval_tuning",
            failure_ids=["fr-rageval-lost_sales_estimate"],
        )

    def test_happy_path_requires_evidence_and_approval(self):
        p = self._proposal()
        p.transition("eval_pending")
        with self.assertRaises(InvalidTransition):
            p.transition("verified")  # no eval evidence yet
        p.attach_eval_evidence({"hit_rate": 0.98}, {"hit_rate": 1.0})
        p.transition("verified")
        with self.assertRaises(InvalidTransition):
            p.transition("adopted")  # not human approved
        p.approve("prem")
        p.transition("adopted")
        self.assertEqual(p.status, "adopted")
        self.assertEqual(len(p.history), 3)

    def test_illegal_jump_blocked(self):
        p = self._proposal()
        with self.assertRaises(InvalidTransition):
            p.transition("adopted")

    def test_approval_only_on_verified(self):
        p = self._proposal()
        with self.assertRaises(InvalidTransition):
            p.approve("prem")

    def test_rejected_is_terminal(self):
        p = self._proposal()
        p.transition("eval_pending")
        p.transition("rejected")
        with self.assertRaises(InvalidTransition):
            p.transition("eval_pending")


class ServiceTests(unittest.TestCase):
    def test_scan_and_persist_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_dir = Path(tmp) / "traces"
            trace_dir.mkdir()
            (trace_dir / "trace-x.json").write_text(json.dumps(_make_trace(duration_s=99)))
            store = Path(tmp) / "failures.jsonl"

            first = scan_and_persist(trace_dir, store)
            second = scan_and_persist(trace_dir, store)

        self.assertEqual(len(first["new_records"]), 1)
        self.assertEqual(second["new_records"], [])

    def test_intake_and_summary_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text(json.dumps({
                "hit_rate": 0.98, "top_k": 5,
                "misses": ["m1"],
                "results": [{"id": "m1", "question": "q", "expected_sources": [], "top_retrieved": []}],
            }))
            failures = Path(tmp) / "failures.jsonl"
            repairs = Path(tmp) / "repairs.jsonl"

            intake = intake_eval_report(report_path, failures)
            summary = loop_summary(failures, repairs)

        self.assertEqual(len(intake["new_records"]), 1)
        self.assertEqual(summary["stats"]["failure_records"], 1)
        self.assertEqual(summary["stats"]["failures_by_kind"], {"retrieval_miss": 1})
        self.assertIn("adoption requires explicit human approval", summary["governance"]["adoption"])

    def test_newest_record_wins_in_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "failures.jsonl"
            record = FailureRecord(
                failure_id="fr-1", detected_at="t1", source="trace",
                failure_kind="weak_evidence", question="q", evidence={}, severity="low",
            )
            save_failure(record, store)
            record.severity = "high"
            save_failure(record, store)
            loaded = failure_store(store).load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded["fr-1"]["severity"], "high")


if __name__ == "__main__":
    unittest.main()


class MisrouteClassifierTests(unittest.TestCase):
    def test_filler_sql_answer_without_confidence_is_misroute(self):
        trace = _make_trace(final={
            "source_type": "sql_only",
            "answer_preview": "Result:\n- Sell through rate: **n/a**\n- Transactions analyzed: **0**",
            "validation": None,
        })
        record = classify_trace(trace)
        self.assertEqual(record.failure_kind, "misroute")
        self.assertEqual(record.evidence["source_type"], "sql_only")

    def test_confident_single_source_answer_is_not_misroute(self):
        trace = _make_trace(final={
            "source_type": "rag_only",
            "answer_preview": "The window is 35 days.",
            "validation": {"confidence": "HIGH"},
        })
        self.assertIsNone(classify_trace(trace))


class MemoryRecallTests(unittest.TestCase):
    def test_recall_links_failures_to_repairs(self):
        import json as _json
        from learning.memory import recall
        from learning.records import RepairProposal, save_proposal
        with tempfile.TemporaryDirectory() as tmp:
            failures = Path(tmp) / "failures.jsonl"
            repairs = Path(tmp) / "repairs.jsonl"
            save_failure(FailureRecord(
                failure_id="fr-x", detected_at="t", source="trace",
                failure_kind="misroute",
                question="What is the sell-through rate for SKU FOOD-5001?",
                evidence={}, severity="medium"), failures)
            proposal = RepairProposal(
                proposal_id="rp-x", created_at="t", title="Fix routing",
                description="d", repair_type="routing_rule", failure_ids=["fr-x"])
            save_proposal(proposal, repairs)

            hit = recall("Which SKUs have a high sell-through rate?", failures, repairs)
            miss = recall("What is the weather today?", failures, repairs)

        self.assertEqual(hit["matches"][0]["failure_id"], "fr-x")
        self.assertEqual(hit["matches"][0]["repairs"][0]["proposal_id"], "rp-x")
        self.assertEqual(miss["matches"], [])


class ApprovalCliTests(unittest.TestCase):
    def _seed_verified(self, repairs):
        from learning.records import RepairProposal, save_proposal
        p = RepairProposal(
            proposal_id="rp-cli", created_at="t", title="T", description="d",
            repair_type="routing_rule", failure_ids=["fr-1"])
        p.transition("eval_pending")
        p.attach_eval_evidence({"tests": 1}, {"tests": 2})
        p.transition("verified")
        save_proposal(p, repairs)

    def test_approve_then_adopt(self):
        from learning.service import adopt_proposal, approve_proposal
        with tempfile.TemporaryDirectory() as tmp:
            repairs = Path(tmp) / "repairs.jsonl"
            self._seed_verified(repairs)
            approved = approve_proposal("rp-cli", "prem", repairs)
            adopted = adopt_proposal("rp-cli", repairs)
        self.assertTrue(approved["human_approved"])
        self.assertEqual(adopted["status"], "adopted")

    def test_adopt_without_approval_blocked(self):
        from learning.records import InvalidTransition
        from learning.service import adopt_proposal
        with tempfile.TemporaryDirectory() as tmp:
            repairs = Path(tmp) / "repairs.jsonl"
            self._seed_verified(repairs)
            with self.assertRaises(InvalidTransition):
                adopt_proposal("rp-cli", repairs)


class ScanCapTests(unittest.TestCase):
    def test_scan_caps_new_records_per_run(self):
        from learning import service
        with tempfile.TemporaryDirectory() as tmp:
            trace_dir = Path(tmp) / "traces"
            trace_dir.mkdir()
            for i in range(30):
                (trace_dir / f"trace-{i}.json").write_text(
                    json.dumps(_make_trace(trace_id=f"t{i}", duration_s=99)))
            store = Path(tmp) / "failures.jsonl"
            result = service.scan_and_persist(trace_dir, store)
        self.assertTrue(result["capped"])
        self.assertEqual(len(result["new_records"]), service.MAX_NEW_RECORDS_PER_SCAN)
