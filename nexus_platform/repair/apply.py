"""Deterministic application of LLM-proposed edits. No LLM calls here.

Edits arrive as SEARCH/REPLACE blocks (the most reliably *applied* edit
format below frontier tier — see ARCHITECTURE_LOG Entry 7). This layer is
deliberately strict about *where* an edit may land (the plan's file
allowlist, inside the scope fence) and deliberately forgiving about *how*
the search text matches (exact first, then whitespace-normalized), because
weak models get indentation subtly wrong far more often than they get the
target location wrong. Every rejection returns a concrete reason so the
proposer can feed it back to the model as an external correction signal.

Block format the proposer instructs models to emit:

    FILE: nexus_platform/example.py
    <<<<<<< SEARCH
    (verbatim lines that exist in the file today; empty for a new file)
    =======
    (replacement lines)
    >>>>>>> REPLACE
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from nexus_platform.repair import context_pack

_BLOCK_RE = re.compile(
    r"FILE:\s*(?P<path>[^\n]+)\n"
    r"(?:[^\n]*\n)*?"
    r"<{5,9} *SEARCH[^\n]*\n(?P<search>.*?)\n?={5,9}\n(?P<replace>.*?)\n?"
    r">{5,9} *REPLACE",
    re.DOTALL)


@dataclass
class Edit:
    path: str
    search: str
    replace: str


@dataclass
class ApplyResult:
    ok: bool
    reason: str
    files_changed: list


def parse_blocks(text: str) -> list[Edit]:
    edits = []
    for m in _BLOCK_RE.finditer(text):
        edits.append(Edit(path=m.group("path").strip().strip("`"),
                          search=m.group("search"),
                          replace=m.group("replace")))
    return edits


def _normalize(s: str) -> str:
    return "\n".join(line.rstrip() for line in s.strip("\n").splitlines())


def _find_normalized(haystack: str, needle: str) -> tuple[int, int] | None:
    """Locate `needle` in `haystack` ignoring trailing whitespace and
    leading/trailing blank lines. Returns (start, end) char offsets of the
    matching original region, or None."""
    hay_lines = haystack.splitlines(keepends=True)
    needle_norm = _normalize(needle).splitlines()
    if not needle_norm:
        return None
    n = len(needle_norm)
    stripped = [line.rstrip("\n").rstrip() for line in hay_lines]
    for i in range(len(stripped) - n + 1):
        if stripped[i:i + n] == needle_norm:
            start = sum(len(l) for l in hay_lines[:i])
            end = start + sum(len(l) for l in hay_lines[i:i + n])
            return start, end
    return None


def apply_edit(repo_root: Path, edit: Edit,
               allowed_files: list[str]) -> ApplyResult:
    """Apply one edit. Guardrails first, then lenient matching, then a
    syntax check — an edit that breaks the file's parse is rolled back."""
    rel = edit.path.strip().lstrip("./")
    if not context_pack.in_scope(rel):
        return ApplyResult(False, f"file {rel!r} is outside the scope fence "
                           f"({context_pack.IN_SCOPE_PREFIXES})", [])
    if rel not in allowed_files:
        return ApplyResult(False, f"file {rel!r} is not in the plan's "
                           f"FILES_TOUCHED list {allowed_files} — re-plan "
                           "instead of editing extra files", [])
    path = repo_root / rel

    if not edit.search.strip():
        if path.exists() and path.read_text().strip():
            return ApplyResult(False, f"empty SEARCH means create-new-file, "
                               f"but {rel} already exists and is not empty — "
                               "provide the exact lines to replace", [])
        path.parent.mkdir(parents=True, exist_ok=True)
        new_content = edit.replace if edit.replace.endswith("\n") \
            else edit.replace + "\n"
    else:
        if not path.exists():
            return ApplyResult(False, f"{rel} does not exist, but SEARCH is "
                               "non-empty — for a new file use an empty "
                               "SEARCH section", [])
        content = path.read_text()
        if edit.search in content:
            if content.count(edit.search) > 1:
                return ApplyResult(False, f"SEARCH text appears "
                                   f"{content.count(edit.search)} times in "
                                   f"{rel} — add surrounding lines to make "
                                   "it unique", [])
            new_content = content.replace(edit.search, edit.replace, 1)
        else:
            span = _find_normalized(content, edit.search)
            if span is None:
                return ApplyResult(False, f"SEARCH text not found in {rel} "
                                   "(even ignoring trailing whitespace). "
                                   "Copy the exact current lines from the "
                                   "file shown to you", [])
            new_content = content[:span[0]] + edit.replace + "\n" \
                + content[span[1]:]

    if rel.endswith(".py"):
        try:
            ast.parse(new_content)
        except SyntaxError as exc:
            return ApplyResult(False, f"edit would leave {rel} with a syntax "
                               f"error: {exc}", [])
    before = path.read_text() if path.exists() else None
    path.write_text(new_content)
    _ = before  # kept for symmetry; git in the worktree is the real undo
    return ApplyResult(True, "applied", [rel])


def apply_all(repo_root: Path, response_text: str,
              allowed_files: list[str]) -> ApplyResult:
    """Parse and apply every block in an LLM response, stopping at the
    first failure (partial application is fine — the worktree is git-managed
    and the proposer retries the failed block with feedback)."""
    edits = parse_blocks(response_text)
    if not edits:
        return ApplyResult(False, "no valid SEARCH/REPLACE blocks found in "
                           "the response — emit blocks exactly in the "
                           "format specified", [])
    changed: list[str] = []
    for edit in edits:
        result = apply_edit(repo_root, edit, allowed_files)
        if not result.ok:
            result.files_changed = changed
            return result
        changed.extend(result.files_changed)
    return ApplyResult(True, f"applied {len(edits)} edit(s)", changed)
