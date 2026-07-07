"""Scan + summarize entry points for the learning loop (CLI and API).

Usage:
    python -m learning.service scan              # classify traces, persist failures
    python -m learning.service intake <report>   # ingest RAG eval report misses
    python -m learning.service summary           # print the current loop state
    python -m learning.service recall "<question>"        # failure-memory lookup
    python -m learning.service approve <proposal_id> <by> # human approval gate
    python -m learning.service adopt <proposal_id>        # verified+approved → adopted

Guardrails: scans are idempotent (keyed by failure_id) and capped per run;
state transitions live in learning.records and cannot be skipped from here.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Optional

from learning.classify import failures_from_rag_eval_report, scan_trace_files
from learning.records import (
    FAILURE_STORE,
    REPAIR_STORE,
    failure_store,
    repair_store,
    save_failure,
)


MAX_NEW_RECORDS_PER_SCAN = 25


def scan_and_persist(trace_dir: Optional[Path] = None,
                     store_path: Optional[Path] = None) -> Dict:
    """Classify all traces and persist new failure records (idempotent).

    Capped at MAX_NEW_RECORDS_PER_SCAN per run so a pathological trace
    directory cannot flood the store in one pass.
    """
    store = failure_store(store_path)
    known = store.load()
    found = scan_trace_files(trace_dir)
    added = []
    capped = False
    for record in found:
        if record.failure_id in known:
            continue
        if len(added) >= MAX_NEW_RECORDS_PER_SCAN:
            capped = True
            break
        save_failure(record, store_path)
        added.append(record.failure_id)
    return {"scanned": True, "failures_found": len(found),
            "new_records": added, "capped": capped}


def intake_eval_report(report_path: Path, store_path: Optional[Path] = None) -> Dict:
    """Persist failure records for each miss in a RAG eval JSON report."""
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    store = failure_store(store_path)
    known = store.load()
    added = []
    for record in failures_from_rag_eval_report(report):
        if record.failure_id not in known:
            save_failure(record, store_path)
            added.append(record.failure_id)
    return {"report": str(report_path), "misses": len(report.get("misses", [])), "new_records": added}


def loop_summary(failure_path: Optional[Path] = None,
                 repair_path: Optional[Path] = None) -> Dict:
    """Sanitized snapshot of the learning loop for the API/UI."""
    failures = list(failure_store(failure_path).load().values())
    proposals = list(repair_store(repair_path).load().values())

    by_kind: Dict[str, int] = {}
    for f in failures:
        by_kind[f.get("failure_kind", "unknown")] = by_kind.get(f.get("failure_kind", "unknown"), 0) + 1
    by_status: Dict[str, int] = {}
    for p in proposals:
        by_status[p.get("status", "unknown")] = by_status.get(p.get("status", "unknown"), 0) + 1

    failures.sort(key=lambda f: f.get("detected_at", ""), reverse=True)
    proposals.sort(key=lambda p: p.get("created_at", ""), reverse=True)

    return {
        "governance": {
            "classification": "deterministic rules over sanitized traces and eval reports",
            "verification": "proposals need before/after eval evidence to become verified",
            "adoption": "adoption requires explicit human approval; nothing self-modifies",
        },
        "stats": {
            "failure_records": len(failures),
            "failures_by_kind": by_kind,
            "repair_proposals": len(proposals),
            "proposals_by_status": by_status,
        },
        "failure_records": failures[:50],
        "repair_queue": proposals[:50],
        "stores": {"failures": str(failure_path or FAILURE_STORE), "repairs": str(repair_path or REPAIR_STORE)},
    }


def approve_proposal(proposal_id: str, approved_by: str,
                     repair_path: Optional[Path] = None) -> Dict:
    """Human approval gate: only verified proposals can be approved."""
    from learning.records import load_proposal, save_proposal
    store = repair_store(repair_path)
    records = store.load()
    if proposal_id not in records:
        raise KeyError(f"unknown proposal: {proposal_id}")
    proposal = load_proposal(records[proposal_id])
    proposal.approve(approved_by)
    save_proposal(proposal, repair_path)
    return {"proposal_id": proposal_id, "human_approved": True, "approved_by": approved_by,
            "status": proposal.status}


def adopt_proposal(proposal_id: str, repair_path: Optional[Path] = None) -> Dict:
    """Adopt a verified, human-approved proposal (state machine enforced)."""
    from learning.records import load_proposal, save_proposal
    store = repair_store(repair_path)
    records = store.load()
    if proposal_id not in records:
        raise KeyError(f"unknown proposal: {proposal_id}")
    proposal = load_proposal(records[proposal_id])
    proposal.transition("adopted", note="adopted via learning.service CLI")
    save_proposal(proposal, repair_path)
    return {"proposal_id": proposal_id, "status": proposal.status}


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "summary"
    if command == "scan":
        print(json.dumps(scan_and_persist(), indent=2))
    elif command == "intake":
        if len(sys.argv) < 3:
            raise SystemExit("usage: python -m learning.service intake <rag_eval_report.json>")
        print(json.dumps(intake_eval_report(Path(sys.argv[2])), indent=2))
    elif command == "summary":
        print(json.dumps(loop_summary(), indent=2))
    elif command == "recall":
        if len(sys.argv) < 3:
            raise SystemExit('usage: python -m learning.service recall "<question>"')
        from learning.memory import recall
        print(json.dumps(recall(sys.argv[2]), indent=2))
    elif command == "approve":
        if len(sys.argv) < 4:
            raise SystemExit("usage: python -m learning.service approve <proposal_id> <approved_by>")
        print(json.dumps(approve_proposal(sys.argv[2], sys.argv[3]), indent=2))
    elif command == "adopt":
        if len(sys.argv) < 3:
            raise SystemExit("usage: python -m learning.service adopt <proposal_id>")
        print(json.dumps(adopt_proposal(sys.argv[2]), indent=2))
    else:
        raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    main()
