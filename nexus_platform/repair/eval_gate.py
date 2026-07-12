"""Before/after eval gate for repair branches.

A fix is acceptable only if: (a) the targeted repro that failed BEFORE the
change passes AFTER it, and (b) the full platform suite shows zero new
failures vs. the BEFORE baseline. Anything else → discard the branch and
record the attempt.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class EvalRun:
    label: str                 # "before" | "after"
    command: str
    exit_code: int
    passed: int
    failed: int
    failed_tests: list
    duration_s: float


_FAIL_RE = re.compile(r"FAILED ([^\s]+)")
_COUNT_RE = re.compile(r"(\d+) passed")
_FAILCOUNT_RE = re.compile(r"(\d+) failed")


def run_pytest(args: list[str], label: str, cwd: str | Path = ".") -> EvalRun:
    cmd = [sys.executable, "-m", "pytest", "-q", *args]
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          timeout=1800)
    out = proc.stdout + proc.stderr
    passed = int(m.group(1)) if (m := _COUNT_RE.search(out)) else 0
    failed = int(m.group(1)) if (m := _FAILCOUNT_RE.search(out)) else 0
    return EvalRun(label=label, command=" ".join(cmd),
                   exit_code=proc.returncode, passed=passed, failed=failed,
                   failed_tests=_FAIL_RE.findall(out),
                   duration_s=round(time.time() - started, 1))


def gate(before: EvalRun, after: EvalRun, repro_before: EvalRun,
         repro_after: EvalRun) -> tuple[bool, str]:
    """True only when the repro flipped fail→pass and nothing regressed."""
    if repro_before.exit_code == 0:
        return False, ("repro passed BEFORE the fix — there is nothing to fix "
                       "or the repro does not encode the bug")
    if repro_after.exit_code != 0:
        return False, f"repro still fails after fix: {repro_after.failed_tests}"
    new_failures = [t for t in after.failed_tests
                    if t not in before.failed_tests]
    if new_failures:
        return False, f"fix introduces new failures: {new_failures}"
    return True, (f"repro flipped fail→pass; suite {after.passed} passed, "
                  f"no new failures vs baseline ({before.passed} passed)")


def save_evidence(path: str | Path, runs: list[EvalRun], verdict: tuple[bool, str]) -> None:
    Path(path).write_text(json.dumps(
        {"runs": [asdict(r) for r in runs],
         "gate_passed": verdict[0], "gate_reason": verdict[1]}, indent=2))
