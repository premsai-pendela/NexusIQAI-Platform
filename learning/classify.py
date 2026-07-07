"""Deterministic trace → failure classification and eval-miss intake.

No LLM involved: classification reads the sanitized trace files the
observability layer already writes, plus RAG eval reports. Every failure
record carries the evidence that triggered it so a human can audit the
claim against the original trace or eval output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from learning.records import FailureRecord, _utc_now

TRACES_DIR = Path("traces")
LATENCY_BUDGET_S = 20.0

_ABSTAIN_MARKERS = (
    "i don't have enough evidence",
    "not enough evidence",
    "cannot answer this reliably",
    "insufficient evidence",
    "i couldn't find",
)


def _failed_spans(trace: Dict) -> List[Dict]:
    failed = []
    for span in trace.get("spans", []):
        meta = span.get("metadata", {}) or {}
        if span.get("status") not in (None, "ok") or meta.get("failure_kind"):
            failed.append(
                {
                    "span": span.get("name"),
                    "status": span.get("status"),
                    "failure_kind": meta.get("failure_kind"),
                    "task": meta.get("task"),
                    "model": meta.get("model"),
                }
            )
    return failed


def classify_trace(trace: Dict) -> Optional[FailureRecord]:
    """Return a FailureRecord when the trace shows a real failure signal."""
    trace_id = trace.get("trace_id", "unknown")
    question = trace.get("question", "")
    final = trace.get("final", {}) or {}
    validation = final.get("validation") or trace.get("metadata", {}).get("validation") or {}
    confidence = str(validation.get("confidence", "") or "").upper()
    answer_text = str(final.get("answer") or final.get("answer_preview") or "").lower()

    failed_spans = _failed_spans(trace)
    if failed_spans:
        return FailureRecord(
            failure_id=f"fr-trace-{trace_id}-llm",
            detected_at=_utc_now(),
            source="trace",
            failure_kind="llm_failure",
            question=question,
            evidence={"failed_spans": failed_spans[:5]},
            severity="high" if len(failed_spans) > 1 else "medium",
            trace_id=trace_id,
            suggested_repair="Inspect provider fallback order and retry policy for the failing task.",
        )

    if any(marker in answer_text for marker in _ABSTAIN_MARKERS) or confidence == "LOW":
        return FailureRecord(
            failure_id=f"fr-trace-{trace_id}-evidence",
            detected_at=_utc_now(),
            source="trace",
            failure_kind="weak_evidence",
            question=question,
            evidence={
                "confidence": confidence or "N/A",
                "confidence_reason": validation.get("confidence_reason"),
                "abstained": any(m in answer_text for m in _ABSTAIN_MARKERS),
            },
            severity="medium",
            trace_id=trace_id,
            suggested_repair=(
                "Check whether the corpus/database actually covers this question; "
                "if it does, tune retrieval (query rewrite, metadata filter)."
            ),
        )

    # Misroute: a single-source route produced a filler answer (n/a, zero
    # rows analyzed) with no validation at all — the router picked a source
    # that had no data for the question.
    source_type = str(final.get("source_type") or trace.get("metadata", {}).get("source_type") or "")
    filler_markers = ("**n/a**", "transactions analyzed: **0**", "no data to answer")
    if (source_type.endswith("_only") and not confidence
            and any(marker in answer_text for marker in filler_markers)):
        return FailureRecord(
            failure_id=f"fr-trace-{trace_id}-misroute",
            detected_at=_utc_now(),
            source="trace",
            failure_kind="misroute",
            question=question,
            evidence={"source_type": source_type,
                      "answer_excerpt": answer_text[:160]},
            severity="medium",
            trace_id=trace_id,
            suggested_repair=(
                "Check routing vocabulary/inventory for this question class and "
                "add a no-data fallback to another source."
            ),
        )

    duration = trace.get("duration_s") or 0
    if duration > LATENCY_BUDGET_S:
        return FailureRecord(
            failure_id=f"fr-trace-{trace_id}-latency",
            detected_at=_utc_now(),
            source="trace",
            failure_kind="latency_regression",
            question=question,
            evidence={"duration_s": duration, "budget_s": LATENCY_BUDGET_S},
            severity="low",
            trace_id=trace_id,
            suggested_repair="Profile the slowest span; consider caching or a cheaper model tier.",
        )

    return None


def scan_trace_files(trace_dir: Optional[Path] = None) -> List[FailureRecord]:
    """Classify every trace file on disk; unreadable files are skipped."""
    trace_dir = Path(trace_dir or TRACES_DIR)
    records: List[FailureRecord] = []
    if not trace_dir.exists():
        return records
    for path in sorted(trace_dir.glob("trace-*.json")):
        try:
            trace = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        record = classify_trace(trace)
        if record:
            records.append(record)
    return records


def failures_from_rag_eval_report(report: Dict) -> List[FailureRecord]:
    """Convert RAG eval misses into retrieval_miss failure records."""
    records: List[FailureRecord] = []
    results = {r["id"]: r for r in report.get("results", [])}
    for miss_id in report.get("misses", []):
        result = results.get(miss_id, {})
        records.append(
            FailureRecord(
                failure_id=f"fr-rageval-{miss_id}",
                detected_at=_utc_now(),
                source="rag_eval",
                failure_kind="retrieval_miss",
                question=result.get("question", miss_id),
                evidence={
                    "eval_id": miss_id,
                    "expected_sources": result.get("expected_sources"),
                    "top_retrieved": result.get("top_retrieved"),
                    "eval_hit_rate": report.get("hit_rate"),
                    "top_k": report.get("top_k"),
                },
                severity="medium",
                suggested_repair=(
                    "Add or adjust golden-source keywords in retrieval normalization, "
                    "or improve the expected document's chunk text; re-run evals/rag_eval."
                ),
            )
        )
    return records
