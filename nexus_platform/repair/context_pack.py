"""Evidence + code context assembly for the repair pipeline. Zero LLM calls.

Given a health finding, this module builds everything the proposer's LLM
stages need to reason about it: the finding itself, the trace payload(s)
behind it, a manifest of the in-scope product code (files + their def/class
index), and source slices of candidate files. Fault-localization *scoping*
starts from a generic route→module map derived from the product's
architecture (the trace records which route answered the question; each
route is implemented by a known set of modules). The LLM narrows from there
— this map never encodes what any specific fix looks like.

All code is read from the repair worktree, not the main checkout, so the
pipeline always reasons about the exact tree it is about to edit.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from nexus_platform import store

# Files a repair plan may touch (mirrors the initiative's scope fence).
IN_SCOPE_PREFIXES = ("nexus_platform/", "agents/", "tests/platform_mode/")

# Product modules eligible for localization. sim/ and repair/ are the Health
# Check Agent's own code — a product fix never belongs there.
_MANIFEST_GLOBS = ("nexus_platform/*.py", "agents/*.py")

# Which modules implement each answer route (from the platform architecture:
# orchestrator decides the route, query_service is the single entry point,
# then the route-specific engine runs). Generic across findings.
ROUTE_MODULES = {
    "sql_agent": ["nexus_platform/orchestrator.py", "agents/sql_agent.py",
                  "nexus_platform/deterministic.py"],
    "rag_agent": ["nexus_platform/orchestrator.py", "agents/rag_agent.py"],
    "fusion": ["nexus_platform/orchestrator.py", "agents/fusion_agent.py"],
    "deterministic": ["nexus_platform/deterministic.py",
                      "nexus_platform/orchestrator.py"],
    "clarification": ["nexus_platform/orchestrator.py"],
    "denied": ["nexus_platform/access_policy.py",
               "nexus_platform/query_service.py"],
}
_ALWAYS_CANDIDATES = ["nexus_platform/query_service.py"]

_WHOLE_FILE_MAX_LINES = 700

# Trace payload keys worth showing the model, in presentation order. The
# payload also contains bulky access-policy dumps that add tokens without
# adding diagnostic value; those are summarized separately.
_TRACE_KEYS = (
    "question", "resolved_question", "role", "company", "access_decision",
    "denied_reason", "route", "engine_route", "route_reason", "llm_skipped",
    "model_used", "confidence", "sql", "answer", "answer_text", "response",
    "citations", "chart_type", "engine_trace",
)


@dataclass
class EvidencePack:
    finding: dict
    traces: list[dict]
    company: str
    repo_root: Path
    candidate_files: list[str] = field(default_factory=list)
    manifest: str = ""

    def evidence_text(self) -> str:
        """The finding + trace evidence, formatted for a prompt."""
        f = self.finding
        lines = [
            f"FINDING {f['id']} (company={f['company']}, "
            f"severity={f['severity']}, kind={f['payload'].get('kind')})",
            f"Summary: {f['summary']}",
            f"Classifier recommendation: {f['payload'].get('recommendation')}",
            "",
        ]
        for tr in self.traces:
            lines.append(f"--- TRACE {tr.get('id', '?')} ---")
            payload = tr.get("payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    payload = {"raw": payload[:1500]}
            for key in _TRACE_KEYS:
                if key in payload and payload[key] not in (None, "", []):
                    val = payload[key]
                    text = (json.dumps(val, default=str)
                            if isinstance(val, (dict, list)) else str(val))
                    if len(text) > 1500:
                        text = text[:1500] + " …[truncated]"
                    lines.append(f"{key}: {text}")
            allowed = (payload.get("access_policy") or {}).get(
                "allowed_tables") or []
            if allowed:
                lines.append(f"allowed_tables ({len(allowed)}): "
                             f"{', '.join(map(str, allowed))}")
            lines.append("")
        return "\n".join(lines)


def load_evidence(company: str, finding_id: str, repo_root: str | Path,
                  store_root: Optional[str | Path] = None) -> EvidencePack:
    """Load a finding and its evidence traces from the store."""
    findings = {f["id"]: f for f in store.list_findings(company)}
    if finding_id not in findings:
        raise KeyError(f"finding {finding_id} not found for {company}")
    finding = findings[finding_id]
    traces = []
    for tid in finding["payload"].get("evidence", []):
        tr = store.get_trace(company, tid)
        if tr:
            traces.append(tr)
    pack = EvidencePack(finding=finding, traces=traces, company=company,
                        repo_root=Path(repo_root))
    pack.candidate_files = _candidate_files(pack)
    pack.manifest = build_manifest(pack.repo_root)
    return pack


def _candidate_files(pack: EvidencePack) -> list[str]:
    """Order candidate modules by the routes seen in the evidence traces."""
    ordered: list[str] = []
    for tr in pack.traces:
        payload = tr.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {}
        route = str(payload.get("route") or "")
        for key, modules in ROUTE_MODULES.items():
            if key in route:
                for m in modules:
                    if m not in ordered:
                        ordered.append(m)
    for m in _ALWAYS_CANDIDATES:
        if m not in ordered:
            ordered.append(m)
    return [m for m in ordered if (pack.repo_root / m).exists()]


def build_manifest(repo_root: Path) -> str:
    """File + def/class index of the in-scope product code."""
    lines = []
    for pattern in _MANIFEST_GLOBS:
        for path in sorted(repo_root.glob(pattern)):
            if path.name == "__init__.py":
                continue
            rel = path.relative_to(repo_root)
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            doc = (ast.get_docstring(tree) or "").strip().splitlines()
            head = doc[0][:100] if doc else ""
            defs = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs.append(f"{node.name}()")
                elif isinstance(node, ast.ClassDef):
                    methods = [n.name for n in node.body
                               if isinstance(n, (ast.FunctionDef,
                                                 ast.AsyncFunctionDef))]
                    defs.append(f"class {node.name}"
                                f"({', '.join(methods[:12])})")
            lines.append(f"{rel} — {head}")
            if defs:
                lines.append(f"    {'; '.join(defs)}")
    return "\n".join(lines)


def file_slice(repo_root: Path, rel_path: str,
               function_names: Optional[list[str]] = None) -> str:
    """Whole file when small; module header + named defs when large."""
    path = repo_root / rel_path
    source = path.read_text()
    lines = source.splitlines()
    if len(lines) <= _WHOLE_FILE_MAX_LINES or not function_names:
        if len(lines) > _WHOLE_FILE_MAX_LINES:
            # Large file and nothing narrower requested: header + def index.
            tree = ast.parse(source)
            idx = [f"  line {n.lineno}: "
                   f"{'class ' if isinstance(n, ast.ClassDef) else 'def '}"
                   f"{n.name}" for n in tree.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef))]
            header = "\n".join(lines[:60])
            return (f"### {rel_path} (first 60 lines + def index; "
                    f"{len(lines)} lines total)\n{header}\n\nDEF INDEX:\n"
                    + "\n".join(idx))
        return f"### {rel_path} (complete, {len(lines)} lines)\n{source}"

    tree = ast.parse(source)
    wanted = set(function_names)
    chunks = []
    header_end = min((n.lineno - 1 for n in tree.body
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                        ast.ClassDef))), default=len(lines))
    chunks.append("\n".join(lines[:min(header_end, 80)]))

    def _collect(nodes, prefix=""):
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                _collect(node.body, prefix=f"{node.name}.")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in wanted or f"{prefix}{node.name}" in wanted:
                    end = getattr(node, "end_lineno", node.lineno)
                    chunks.append("\n".join(lines[node.lineno - 1:end]))

    _collect(tree.body)
    body = "\n\n# …\n\n".join(chunks)
    return (f"### {rel_path} (module header + requested functions "
            f"{sorted(wanted)}; {len(lines)} lines total)\n{body}")


def test_style_example(repo_root: Path) -> str:
    """One existing platform test file, as a style pattern for generated
    tests. Chosen mechanically: the shortest non-trivial test module."""
    candidates = sorted(
        (p for p in (repo_root / "tests/platform_mode").glob("test_*.py")
         if 40 <= len(p.read_text().splitlines()) <= 400),
        key=lambda p: len(p.read_text()))
    if not candidates:
        return ""
    path = candidates[0]
    return (f"### {path.relative_to(repo_root)} (existing test file, "
            f"follow its style)\n{path.read_text()}")


def in_scope(rel_path: str) -> bool:
    clean = rel_path.strip().lstrip("./")
    return clean.startswith(IN_SCOPE_PREFIXES) and ".." not in clean
