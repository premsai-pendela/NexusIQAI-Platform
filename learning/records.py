"""Failure records and the eval-gated repair queue.

State machine for a repair proposal:

    proposed -> eval_pending -> verified -> adopted
                             -> rejected

Guardrails (enforced, not aspirational):
- a proposal cannot reach ``verified`` without before/after eval evidence
- a proposal cannot reach ``adopted`` without ``human_approved=True``
- transitions outside the state machine raise ``InvalidTransition``

Stores are append-friendly JSONL files under ``data/learning/`` keyed by id;
the last line for an id wins, so history stays inspectable.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

LEARNING_DIR = Path("data/learning")
FAILURE_STORE = LEARNING_DIR / "failure_records.jsonl"
REPAIR_STORE = LEARNING_DIR / "repair_queue.jsonl"

FAILURE_KINDS = (
    "weak_evidence",      # low confidence / abstention on a real question
    "llm_failure",        # provider error, timeout, malformed output
    "retrieval_miss",     # eval says expected source not retrieved
    "misroute",           # router sent the question to a source with no data
    "sql_repair_loop",    # SQL needed bounded repair to pass the gate
    "latency_regression", # answer exceeded the latency budget
    "validation_conflict",# sources disagreed and fusion flagged it
)

REPAIR_STATES = ("proposed", "eval_pending", "verified", "rejected", "adopted")

_TRANSITIONS = {
    "proposed": {"eval_pending"},
    "eval_pending": {"verified", "rejected"},
    "verified": {"adopted", "rejected"},
    "rejected": set(),
    "adopted": set(),
}


class InvalidTransition(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class FailureRecord:
    failure_id: str
    detected_at: str
    source: str                 # "trace" | "rag_eval" | "offline_eval"
    failure_kind: str
    question: str
    evidence: Dict              # sanitized: span names, statuses, eval ids — no prompts
    severity: str = "medium"    # low | medium | high
    trace_id: Optional[str] = None
    suggested_repair: Optional[str] = None

    def __post_init__(self):
        if self.failure_kind not in FAILURE_KINDS:
            raise ValueError(f"Unknown failure kind: {self.failure_kind}")


@dataclass
class RepairProposal:
    proposal_id: str
    created_at: str
    title: str
    description: str
    repair_type: str            # retrieval_tuning | routing_rule | prompt_change | data_fix | tool_addition
    failure_ids: List[str]
    status: str = "proposed"
    eval_before: Optional[Dict] = None
    eval_after: Optional[Dict] = None
    human_approved: bool = False
    approved_by: Optional[str] = None
    history: List[Dict] = field(default_factory=list)

    def transition(self, new_status: str, note: str = "") -> None:
        if new_status not in REPAIR_STATES:
            raise InvalidTransition(f"Unknown state: {new_status}")
        if new_status not in _TRANSITIONS[self.status]:
            raise InvalidTransition(f"{self.status} -> {new_status} is not allowed")
        if new_status == "verified" and not (self.eval_before and self.eval_after):
            raise InvalidTransition(
                "verified requires eval_before and eval_after evidence"
            )
        if new_status == "adopted" and not self.human_approved:
            raise InvalidTransition("adopted requires human approval")
        self.history.append(
            {"at": _utc_now(), "from": self.status, "to": new_status, "note": note}
        )
        self.status = new_status

    def attach_eval_evidence(self, before: Dict, after: Dict) -> None:
        self.eval_before = before
        self.eval_after = after

    def approve(self, approved_by: str) -> None:
        if self.status != "verified":
            raise InvalidTransition("approval only applies to verified proposals")
        self.human_approved = True
        self.approved_by = approved_by


class JsonlKeyedStore:
    """Append-only JSONL where the newest line per key wins."""

    def __init__(self, path: Path, key: str):
        self.path = Path(path)
        self.key = key

    def append(self, record: Dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load(self) -> Dict[str, Dict]:
        if not self.path.exists():
            return {}
        merged: Dict[str, Dict] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = record.get(self.key)
            if key:
                merged[key] = record
        return merged


def failure_store(path: Optional[Path] = None) -> JsonlKeyedStore:
    return JsonlKeyedStore(path or FAILURE_STORE, key="failure_id")


def repair_store(path: Optional[Path] = None) -> JsonlKeyedStore:
    return JsonlKeyedStore(path or REPAIR_STORE, key="proposal_id")


def save_failure(record: FailureRecord, path: Optional[Path] = None) -> None:
    failure_store(path).append(asdict(record))


def save_proposal(proposal: RepairProposal, path: Optional[Path] = None) -> None:
    repair_store(path).append(asdict(proposal))


def new_proposal_id() -> str:
    return "rp-" + uuid.uuid4().hex[:10]


def load_proposal(record: Dict) -> RepairProposal:
    return RepairProposal(**record)
