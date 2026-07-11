"""Run a simulated-employee attack campaign against one company workspace.

Usage:
    python scripts/run_sim_campaign.py --company acmecloud
    python scripts/run_sim_campaign.py --company acmecloud --no-llm   # zero LLM calls
    python scripts/run_sim_campaign.py --company acmecloud --dry-run  # list candidates

Manual/CLI trigger only — never wired into any request hot path. Traces are
tagged source=simulated and never appear in default reports.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", default="acmecloud")
    ap.add_argument("--roles", nargs="*", default=None)
    ap.add_argument("--llm-roles", nargs="*", default=None,
                    help="roles allowed to spend LLM-path budget "
                         "(default: Analyst HR Admin)")
    ap.add_argument("--no-llm", action="store_true",
                    help="skip every LLM-path candidate (zero LLM calls)")
    ap.add_argument("--max-llm-calls", type=int, default=None)
    ap.add_argument("--delay", type=float, default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the candidate set and coverage, run nothing")
    ap.add_argument("--json-out", default=None,
                    help="write the full campaign report to this path")
    args = ap.parse_args()

    from nexus_platform.sim.question_gen import (coverage_matrix,
                                                 generate_candidates)

    if args.dry_run:
        cands = generate_candidates(args.company, roles=args.roles,
                                    llm_roles=args.llm_roles)
        for c in cands:
            print(f"[{c.difficulty:8s}] {c.role:8s} {c.family:24s} "
                  f"{c.path_expected:13s} {c.turns[0].question[:70]}"
                  f"{' (+%d turns)' % (len(c.turns) - 1) if len(c.turns) > 1 else ''}")
        print(json.dumps(coverage_matrix(cands), indent=2))
        return 0

    from nexus_platform.sim import runner

    kwargs = {}
    if args.max_llm_calls is not None:
        kwargs["max_llm_calls"] = args.max_llm_calls
    if args.delay is not None:
        kwargs["delay_seconds"] = args.delay
    report = runner.run_campaign(args.company, roles=args.roles,
                                 include_llm=not args.no_llm,
                                 llm_roles=args.llm_roles, **kwargs)

    print(f"\n=== Campaign {report['campaign_id']} — {report['company']} ===")
    print(f"turns: {report['turns_run']}  labels: {report['labels']}")
    print(f"budget: {report['budget']['llm_turns_used']} LLM turns, "
          f"~{report['budget']['est_tokens']} tokens, "
          f"{len(report['budget']['skipped'])} skipped")
    print(f"findings: {len(report['findings'])}")
    for f in report["findings"]:
        print(f"  [{f['severity']:6s}] {f['kind']:36s} ×{f.get('occurrences', 1)} "
              f"— {f['summary'][:90]}")
    if report["errors"]:
        print(f"errors: {len(report['errors'])}")
        for e in report["errors"]:
            print(f"  {e['family']}/{e['role']}: {e['error']}")
    if report.get("report_id"):
        print(f"saved report: {report['report_id']}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, default=str))
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
