"""Failure memory recall: match a new question against past failures.

Deterministic keyword-overlap matching (no LLM). Recall returns past
failure records whose question shares enough content words with the new
question, joined with any repair proposals that reference them — so the
system (and the UI) can say "this question class failed before, and here
is the verified repair" instead of silently repeating history.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from learning.records import failure_store, repair_store

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "to", "in", "for", "on", "at", "is", "are",
         "was", "were", "what", "which", "who", "how", "our", "we", "and",
         "or", "do", "does", "did", "under", "with", "by", "from", "it"}

MIN_SHARED_WORDS = 2


def _tokens(text: str) -> set:
    return {w for w in _WORD.findall(str(text).lower()) if w not in _STOP}


def recall(question: str,
           failure_path: Optional[Path] = None,
           repair_path: Optional[Path] = None,
           limit: int = 5) -> Dict:
    """Return past failures similar to the question, with linked repairs."""
    q_words = _tokens(question)
    failures = list(failure_store(failure_path).load().values())
    proposals = list(repair_store(repair_path).load().values())

    by_failure: Dict[str, List[Dict]] = {}
    for proposal in proposals:
        for failure_id in proposal.get("failure_ids", []):
            by_failure.setdefault(failure_id, []).append({
                "proposal_id": proposal["proposal_id"],
                "title": proposal["title"],
                "status": proposal["status"],
                "human_approved": proposal.get("human_approved", False),
            })

    matches = []
    for failure in failures:
        shared = q_words & _tokens(failure.get("question", ""))
        if len(shared) >= MIN_SHARED_WORDS:
            matches.append({
                "failure_id": failure["failure_id"],
                "failure_kind": failure["failure_kind"],
                "question": failure["question"],
                "shared_terms": sorted(shared),
                "overlap": len(shared),
                "repairs": by_failure.get(failure["failure_id"], []),
            })
    matches.sort(key=lambda m: m["overlap"], reverse=True)
    return {
        "question": question,
        "matches": matches[:limit],
        "note": "deterministic keyword recall over the failure store; "
                "no similarity model, no LLM",
    }
