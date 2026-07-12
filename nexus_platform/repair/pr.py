"""Branch + pull-request helpers. PR-only exit — no merge path exists here.

Deliberately absent, forever: any call to the merge API, any `gh pr` verb
other than `create`/`view`, any write that targets a protected branch. The
identity/approval design on the target repo means a merge attempt could not
satisfy branch protection anyway (the token shares the reviewer's identity
and GitHub forbids self-approval) — but this code must never even try. See
docs/platform improvements/CONTEXT.md §"GitHub access".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

FORBIDDEN_BRANCHES = ("master", "main")


def _git(args: list[str], cwd: str | Path) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr[:400]}")
    return proc.stdout.strip()


def create_fix_worktree(repo_root: str | Path, branch: str,
                        worktree_dir: str | Path, base: str = "master") -> Path:
    """New branch off `base` in a separate worktree; main checkout untouched."""
    if branch in FORBIDDEN_BRANCHES:
        raise ValueError("refusing to operate on a protected branch name")
    _git(["worktree", "add", "-b", branch, str(worktree_dir), base], repo_root)
    return Path(worktree_dir)


def commit_paths(worktree: str | Path, paths: list[str], message: str) -> str:
    _git(["add", *paths], worktree)
    _git(["commit", "-m", message], worktree)
    return _git(["rev-parse", "HEAD"], worktree)


def push_branch(worktree: str | Path, branch: str, remote: str = "origin") -> None:
    if branch in FORBIDDEN_BRANCHES:
        raise ValueError("refusing to push a protected branch")
    _git(["push", "-u", remote, f"{branch}:{branch}"], worktree)


def open_pr(worktree: str | Path, title: str, body_file: str | Path,
            base: str = "master") -> str:
    """Open the PR and return its URL. A human reviews and merges — always."""
    proc = subprocess.run(
        ["gh", "pr", "create", "--base", base, "--title", title,
         "--body-file", str(body_file)],
        cwd=str(worktree), capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"gh pr create failed: {proc.stderr[:400]}")
    return proc.stdout.strip().splitlines()[-1]
