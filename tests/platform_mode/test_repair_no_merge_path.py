"""Structural anti-auto-merge gate.

The repair package and the campaign tooling must contain no merge
primitive, no push to master, and no merge API call — the only path to
master is a human reviewing and merging a PR. This test is the concrete
version of that rule: it fails the build if a merge path appears.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCANNED = [
    ROOT / "nexus_platform" / "repair",
    ROOT / "nexus_platform" / "sim",
    ROOT / "scripts" / "run_sim_campaign.py",
    ROOT / "scripts" / "run_repair.py",
]

FORBIDDEN = [
    re.compile(r"\bpr\s+merge\b"),
    re.compile(r"\bmerge_pull\b"),
    re.compile(r"/merge\b"),
    re.compile(r"pulls/\d+/merge"),
    re.compile(r"push[^\n]*\bmaster\b"),
    re.compile(r"push[^\n]*\bmain\b"),
    re.compile(r"git\s+merge\b"),
]


def _py_files():
    for target in SCANNED:
        if target.is_file():
            yield target
        elif target.is_dir():
            yield from target.rglob("*.py")


def test_no_merge_primitives_anywhere_in_repair_or_sim():
    hits = []
    for f in _py_files():
        text = f.read_text()
        for pattern in FORBIDDEN:
            for m in pattern.finditer(text):
                line_no = text[:m.start()].count("\n") + 1
                line = text.splitlines()[line_no - 1].strip()
                # The guard rails themselves may *name* protected branches
                # in refusal checks and comments; a hit only counts if it
                # is not a refusal/guard line.
                if "refus" in line.lower() or line.lstrip().startswith("#"):
                    continue
                hits.append(f"{f.relative_to(ROOT)}:{line_no}: {line[:80]}")
    assert not hits, f"merge primitives found: {hits}"


def test_pr_helper_refuses_protected_branches():
    from nexus_platform.repair import pr

    for bad in ("master", "main"):
        try:
            pr.create_fix_worktree(ROOT, bad, "/tmp/never-created")
            raised = False
        except ValueError:
            raised = True
        assert raised, f"create_fix_worktree accepted branch {bad!r}"
        try:
            pr.push_branch(ROOT, bad)
            raised = False
        except ValueError:
            raised = True
        assert raised, f"push_branch accepted branch {bad!r}"
