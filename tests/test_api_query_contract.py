"""Contract tests for the enriched /api/v1/query payloads.

The fusion agent is stubbed — no DB, LLM, or network. These tests pin the
shape the web frontend depends on: evidence, usage, confidence reason, and
the final SSE event.
"""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


FUSION_RESULT = {
    "answer": "Q4 electronics revenue was $31.7M.",
    "source_type": "sql_rag",
    "validation": {
        "confidence": "HIGH",
        "confidence_reason": "SQL and PDF figures match within 0.03%",
    },
    "sql_result": {
        "success": True,
        "query": "SELECT SUM(total_amount) FROM sales_transactions",
        "results": [{"sum": 31742905.12}],
        "row_count": 1,
        "answer_mode": "deterministic",
        "sql_repair": {"attempted": False},
        "time": 1.2,
    },
    "rag_result": {
        "success": True,
        "sources": [
            {"filename": "Q4_2024_Financial_Report.pdf", "content": "Electronics revenue reached $31.7 million." * 20}
        ],
        "time": 2.1,
    },
    "web_result": None,
    "llm_usage": {
        "successful_calls": 2,
        "avoided_calls": 2,
        "avoided_estimated_tokens": 850,
        "estimated_tokens": 2478,
        "actual_tokens": 0,
    },
    "answer_generation_mode": "llm",
    "query_time": 6.812,
    "trace_id": "trace-abc123",
    "sources": [{"type": "rag", "content": "Electronics revenue…", "filename": "Q4_2024_Financial_Report.pdf"}],
}


class _StubFusion:
    def query(self, question, force_source=None, progress_cb=None):
        if progress_cb:
            progress_cb("sql", {"success": True})
            progress_cb("rag", {"success": True})
        return dict(FUSION_RESULT)


def _client():
    from api.main import app
    return TestClient(app)


class QueryContractTests(unittest.TestCase):
    def setUp(self):
        patcher_route = patch("api.routes.query.get_fusion_agent", return_value=_StubFusion())
        patcher_main = patch("api.main.get_fusion_agent", return_value=_StubFusion())
        self.addCleanup(patcher_route.stop)
        self.addCleanup(patcher_main.stop)
        patcher_route.start()
        patcher_main.start()

    def test_query_returns_evidence_usage_and_reason(self):
        with _client() as client:
            resp = client.post("/api/v1/query", json={"question": "What was Q4 electronics revenue?"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()

        self.assertEqual(body["confidence"], "HIGH")
        self.assertIn("0.03%", body["confidence_reason"])
        self.assertEqual(body["route"], "sql_rag")
        self.assertEqual(body["query_time_s"], 6.812)
        self.assertEqual(body["trace_id"], "trace-abc123")

        sql = body["evidence"]["sql"]
        self.assertTrue(sql["success"])
        self.assertIn("SELECT SUM", sql["query"])
        self.assertEqual(sql["row_count"], 1)
        self.assertEqual(sql["result_preview"], [{"sum": 31742905.12}])
        self.assertFalse(sql["repair_attempted"])

        docs = body["evidence"]["documents"]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["filename"], "Q4_2024_Financial_Report.pdf")
        self.assertLessEqual(len(docs[0]["snippet"]), 300)

        usage = body["usage"]
        self.assertEqual(usage["llm_calls"], 2)
        self.assertEqual(usage["avoided_llm_calls"], 2)
        self.assertEqual(usage["estimated_tokens"], 2478)
        self.assertIsNone(usage["actual_tokens"])  # 0 → None (not measured)

    def test_stream_final_event_carries_full_payload(self):
        with _client() as client:
            with client.stream("POST", "/api/v1/query/stream",
                               json={"question": "What was Q4 electronics revenue?"}) as resp:
                self.assertEqual(resp.status_code, 200)
                events = []
                for line in resp.iter_lines():
                    if line.startswith("data: "):
                        events.append(json.loads(line[len("data: "):]))

        steps = [e["step"] for e in events]
        self.assertEqual(steps[0], "received")
        self.assertIn("answer", steps)
        final = next(e for e in events if e["step"] == "answer")
        data = final["data"]
        self.assertTrue(data["done"])
        self.assertEqual(data["confidence"], "HIGH")
        self.assertIn("evidence", data)
        self.assertIn("usage", data)
        self.assertEqual(data["evidence"]["sql"]["row_count"], 1)
        # agent progress events surfaced before the answer
        self.assertIn("sql", steps)
        self.assertIn("rag", steps)

    def test_degraded_result_serializes_honestly(self):
        degraded = {
            "answer": "I don't have data to answer this question.",
            "source_type": "no_data",
            "sql_result": None,
            "rag_result": None,
            "web_result": None,
            "validation": None,
            "query_time": 0.4,
        }

        class _DegradedFusion:
            def query(self, question, force_source=None, progress_cb=None):
                return degraded

        with patch("api.routes.query.get_fusion_agent", return_value=_DegradedFusion()):
            with _client() as client:
                resp = client.post("/api/v1/query", json={"question": "Unanswerable question here"})
        body = resp.json()
        self.assertEqual(body["confidence"], "UNKNOWN")
        self.assertIsNone(body["confidence_reason"])
        self.assertIsNone(body["evidence"]["sql"])
        self.assertEqual(body["evidence"]["documents"], [])
        self.assertEqual(body["evidence"]["web"], [])
        self.assertIsNone(body["usage"])


if __name__ == "__main__":
    unittest.main()
