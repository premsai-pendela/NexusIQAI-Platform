"""Submit a simulation employee's questions to the analyst.

    # questions as JSON on stdin (list of strings or {question,family,difficulty})
    echo '["What is our headcount?", "What is our NPS for 2024?"]' \\
        | python -m sim_employees.ask --company acmecloud --employee admin@acmecloud.test

    # or from a file
    python -m sim_employees.ask --company acmecloud \\
        --employee admin@acmecloud.test --questions batch.json

Runs each question inside the employee's access boundary, tags traces
`source="simulated"`, paces between them (longer after any LLM turn), and
updates the employee's private memory. Traces land in whatever platform
database is configured — RDS when NEXUSIQ_PLATFORM_PG_URL is set (so they show
on the live site), local SQLite otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim_employees import runner  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--company", required=True)
    ap.add_argument("--employee", required=True)
    ap.add_argument("--questions", default=None,
                    help="JSON file of questions; omit to read JSON from stdin")
    ap.add_argument("--delay", type=float, default=15.0,
                    help="seconds between questions (default 15)")
    ap.add_argument("--llm-extra-delay", type=float, default=20.0,
                    help="extra seconds after a question that spent an LLM call")
    ap.add_argument("--target", choices=["local", "live"], default="local",
                    help="local = in-process (dev/eval); live = HTTP to the "
                         "deployed API so traces land in RDS (default local)")
    ap.add_argument("--base-url", default=None,
                    help="API base for --target live "
                         "(default https://api.nexusiq-ai.com/api/v1)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    raw = Path(args.questions).read_text() if args.questions else sys.stdin.read()
    try:
        questions = json.loads(raw)
    except ValueError as e:
        print(f"error: questions must be JSON (list of strings or objects): {e}",
              file=sys.stderr)
        return 2
    if not isinstance(questions, list) or not questions:
        print("error: expected a non-empty JSON list of questions",
              file=sys.stderr)
        return 2

    results = runner.ask(args.company, args.employee, questions,
                         delay=args.delay, llm_extra_delay=args.llm_extra_delay,
                         quiet=args.quiet, target=args.target,
                         base_url=args.base_url)
    weak = sum(1 for r in results if r.get("weak"))
    print(f"\n{args.employee}: {len(results)} question(s) asked, "
          f"{weak} weak spot(s) flagged for re-probe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
