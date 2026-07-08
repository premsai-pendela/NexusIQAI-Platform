"""Tests for /api/v1/trace/{id} — stubbed, no DB/LLM/keys."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


def _client():
    from api.main import app
    return TestClient(app)


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        trace = {
            "trace_id": "abc123deadbeef",
            "started_at": "2026-07-05T00:00:00Z",
            "duration_s": 6.8,
            "trace_type": "fusion_query",
            "question": "SECRET-ISH user question",
            "spans": [
                {
                    "name": "agent.sql",
                    "started_at": "2026-07-05T00:00:01Z",
                    "duration_s": 1.2,
                    "status": "ok",
                    "metadata": {
                        "source": "sql",
                        "prompt_preview": "should never leak",
                        "very_long": "x" * 500,
                        "row_count": 1,
                    },
                }
            ],
            "final": {
                "source_type": "sql_rag",
                "routing_model": "rules",
                "from_cache": False,
                "validation": {"confidence": "HIGH", "confidence_reason": "match"},
                "llm_usage": {"successful_calls": 2, "avoided_calls": 2,
                              "estimated_tokens": 2478, "avoided_estimated_tokens": 850},
                "answer_preview": "should never leak either",
            },
        }
        path = Path(self.tmp.name) / "trace-2026-07-05_00-00-00-abc123deadbeef.json"
        path.write_text(json.dumps(trace))
        p_dir = patch("api.routes.trace.tracer._trace_dir", return_value=Path(self.tmp.name))
        p_dir.start()
        self.addCleanup(p_dir.stop)

    def test_trace_returns_sanitized_timeline(self):
        with _client() as client:
            resp = client.get("/api/v1/trace/abc123deadbeef")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["trace_id"], "abc123deadbeef")
        self.assertEqual(len(body["spans"]), 1)
        span = body["spans"][0]
        self.assertEqual(span["name"], "agent.sql")
        self.assertNotIn("prompt_preview", span["metadata"])
        self.assertNotIn("very_long", span["metadata"])
        self.assertEqual(span["metadata"]["row_count"], 1)
        raw = json.dumps(body)
        self.assertNotIn("should never leak", raw)
        self.assertNotIn("SECRET-ISH", raw)
        self.assertEqual(body["final"]["llm_usage"]["successful_calls"], 2)
        self.assertEqual(body["final"]["validation"]["confidence"], "HIGH")

    def test_unknown_trace_404(self):
        with _client() as client:
            self.assertEqual(client.get("/api/v1/trace/nope404nope").status_code, 404)

    def test_bad_trace_id_rejected(self):
        with _client() as client:
            # too short → fails the id regex
            self.assertEqual(client.get("/api/v1/trace/ab").status_code, 400)
            # traversal attempt → rejected (400 by regex or 404 by routing)
            self.assertIn(client.get("/api/v1/trace/..%2Fetc").status_code, (400, 404))


if __name__ == "__main__":
    unittest.main()
