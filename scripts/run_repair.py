"""Trigger the Health Check Agent's repair pipeline on a stored finding.

The pipeline itself (nexus_platform/repair/) does the diagnosing, planning,
test-writing, and code-editing — on the product's own free-tier LLM chain.
This script only points it at a finding and prints what it did.

Usage:
    .venv/bin/python scripts/run_repair.py --company acmecloud --finding hf_xxxx
    .venv/bin/python scripts/run_repair.py --company acmecloud --list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from nexus_platform import store  # noqa: E402
from nexus_platform.repair import runner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True)
    parser.add_argument("--finding", help="health_findings id (hf_…)")
    parser.add_argument("--list", action="store_true",
                        help="list open findings and exit")
    parser.add_argument("--worktree", default=None,
                        help="override the worktree directory")
    parser.add_argument("--resume-from", default=None,
                        help="previous session log to reuse the pipeline's "
                             "own localize/understand/hypothesize/plan "
                             "outputs from (saves quota on retries)")
    args = parser.parse_args()

    if args.list or not args.finding:
        for f in store.list_findings(args.company):
            print(f"{f['id']}  {f['status']:<18} {f['severity']:<7} "
                  f"{f['payload'].get('kind', '?'):<36} {f['summary'][:80]}")
        return 0

    outcome = runner.run_repair(args.company, args.finding, REPO_ROOT,
                                worktree_dir=args.worktree,
                                resume_session=args.resume_from)
    print(json.dumps({
        "finding": outcome.finding_id, "gate_passed": outcome.ok,
        "reason": outcome.reason, "branch": outcome.branch,
        "worktree": outcome.worktree, "commit": outcome.commit,
        "files_changed": sorted(set(outcome.files_changed)),
        "llm_calls": outcome.llm_calls, "models_used": outcome.models_used,
        "session_log": outcome.session_log,
    }, indent=2))
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
