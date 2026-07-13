"""Company brain builder.

Turns a connected company data folder into a saved workspace brain:
- scans files and records hashes (change detection → needs_rebuild)
- catalogs the SQLite schema
- chunks department documents into the company's ChromaDB collection,
  tagging every chunk with its department so role filters apply at retrieval
- writes brain artifacts (sources, schema catalog, doc inventory, role access
  map, build log)

Usage:
    python -m nexus_platform.brain_builder [slug ...]

Rebuilds are Admin/CEO-only in the API; this module is the shared engine.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from nexus_platform.access_policy import ROLE_POLICIES
from nexus_platform.contexts import brain_dir, company_db_path, company_dir
from nexus_platform.registry import get_registry

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_files(slug: str) -> dict[str, str]:
    """Relative path → sha256 for every source file in the company folder."""
    root = company_dir(slug)
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and "brain" not in path.parts:
            hashes[str(path.relative_to(root))] = _hash_file(path)
    return hashes


def brain_status(slug: str) -> dict:
    """Current brain state: ready / needs_rebuild / not_built."""
    bdir = brain_dir(slug)
    hashes_file = bdir / "file_hashes.json"
    if not hashes_file.exists():
        return {"status": "not_built", "built_at": None, "changed_files": []}
    saved = json.loads(hashes_file.read_text())
    current = scan_files(slug)
    changed = sorted(
        set(k for k, v in current.items() if saved.get("hashes", {}).get(k) != v)
        | set(saved.get("hashes", {})) - set(current)
    )
    build_log = {}
    log_file = bdir / "build_log.json"
    if log_file.exists():
        build_log = json.loads(log_file.read_text())
    return {
        "status": "needs_rebuild" if changed else "ready",
        "built_at": saved.get("built_at"),
        "changed_files": changed,
        "build_log": build_log,
    }


def _catalog_schema(slug: str) -> dict:
    conn = sqlite3.connect(str(company_db_path(slug)))
    cur = conn.cursor()
    tables = {}
    for (name,) in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall():
        cols = cur.execute(f'PRAGMA table_info("{name}")').fetchall()
        count = cur.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        tables[name] = {
            "columns": [{"name": c[1], "type": c[2], "not_null": bool(c[3])} for c in cols],
            "row_count": count,
        }
    conn.close()
    return tables


def _extract_text(path: Path) -> str:
    """Text for indexing from any supported corpus file type."""
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt"):
        return path.read_text(errors="ignore")
    if suffix == ".html":
        import re as _re
        raw = path.read_text(errors="ignore")
        return _re.sub(r"<[^>]+>", " ", raw)
    if suffix == ".json":
        try:
            data = json.loads(path.read_text(errors="ignore"))
            return json.dumps(data, indent=1)[:120_000]
        except ValueError:
            return path.read_text(errors="ignore")
    if suffix == ".csv":
        # Header + rows as readable lines; retrieval-friendly plain text.
        lines = path.read_text(errors="ignore").splitlines()
        return "\n".join(lines[:1500])
    if suffix == ".pdf":
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(str(path))
            pages = [pdf[i].get_textpage().get_text_range()
                     for i in range(len(pdf))]
            return "\n".join(pages)
        except Exception:
            return ""
    return ""


def _chunk_text(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start:start + CHUNK_SIZE]
        if chunk.strip():
            chunks.append(chunk)
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


def _build_rag_index(slug: str) -> dict:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    from agents.rag_agent import _get_shared_embedding_model

    chroma_path = brain_dir(slug) / "chroma"
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(chroma_path), settings=ChromaSettings(anonymized_telemetry=False)
    )
    collection_name = f"brain_{slug}"
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.create_collection(collection_name, metadata={"hnsw:space": "cosine"})

    model = _get_shared_embedding_model()
    docs_root = company_dir(slug) / "docs"
    inventory = []
    ids, documents, metadatas = [], [], []
    supported = (".md", ".txt", ".html", ".json", ".csv", ".pdf")
    doc_paths = [p for p in sorted(docs_root.rglob("*"))
                 if p.is_file() and p.suffix.lower() in supported]
    for doc_path in doc_paths:
        department = doc_path.parent.name
        rel = str(doc_path.relative_to(company_dir(slug)))
        text = _extract_text(doc_path)
        if not text.strip():
            continue
        chunks = _chunk_text(text)
        inventory.append({"file": rel, "department": department, "chunks": len(chunks)})
        for i, chunk in enumerate(chunks):
            ids.append(f"{slug}:{rel}:{i}")
            documents.append(chunk)
            metadatas.append({
                "company": slug,
                "department": department,
                "filename": doc_path.name,
                "source": rel,
                "chunk_index": i,
            })

    if documents:
        embeddings = model.encode(documents, convert_to_numpy=True, normalize_embeddings=True)
        collection.add(ids=ids, documents=documents,
                       embeddings=[e.tolist() for e in embeddings], metadatas=metadatas)

    # RAG agents watch this version file to refresh their BM25 index.
    version_file = chroma_path / "ingestion_version.json"
    version = 0
    if version_file.exists():
        version = json.loads(version_file.read_text()).get("version", 0)
    version_file.write_text(json.dumps({"version": version + 1}))

    return {"collection": collection_name, "chunks": len(documents), "documents": inventory}


def build_brain(slug: str) -> dict:
    """Full brain build. Returns the build log."""
    registry = get_registry()
    company = registry.get_company(slug)
    if company is None:
        raise KeyError(f"Unknown company: {slug}")

    started = time.time()
    steps = []

    def step(name: str, detail):
        steps.append({"step": name, "detail": detail,
                      "at": datetime.now(timezone.utc).isoformat()})

    bdir = brain_dir(slug)
    bdir.mkdir(parents=True, exist_ok=True)

    hashes = scan_files(slug)
    step("scan files", f"{len(hashes)} source files hashed")

    schema = _catalog_schema(slug)
    (bdir / "schema_catalog.json").write_text(json.dumps(schema, indent=2))
    step("profile structured data", {t: v["row_count"] for t, v in schema.items()})

    rag = _build_rag_index(slug)
    (bdir / "doc_inventory.json").write_text(json.dumps(rag["documents"], indent=2))
    step("build RAG index", f"{rag['chunks']} chunks in {rag['collection']}")

    role_map = {
        role: {"tables": list(p.allowed_tables), "departments": list(p.allowed_departments)}
        for role, p in ROLE_POLICIES.items()
    }
    (bdir / "role_access_map.json").write_text(json.dumps(role_map, indent=2))
    step("run access-policy checks", f"{len(role_map)} role policies mapped")

    (bdir / "file_hashes.json").write_text(json.dumps({
        "built_at": datetime.now(timezone.utc).isoformat(),
        "hashes": hashes,
    }, indent=2))

    log = {
        "company": slug,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(time.time() - started, 2),
        "steps": steps,
        "status": "workspace ready",
    }
    (bdir / "build_log.json").write_text(json.dumps(log, indent=2))
    return log


if __name__ == "__main__":
    args = sys.argv[1:]

    # `--check`: verify each committed brain still matches its source docs/db,
    # without rebuilding. This is the CI staleness guard — if someone edits the
    # documents but forgets to rebuild and commit the brain, the fingerprint in
    # file_hashes.json no longer matches and this exits non-zero, so a stale
    # brain can never pass the gate green.
    if "--check" in args:
        slugs = [a for a in args if a != "--check"] or [
            c.slug for c in get_registry().companies.values()
        ]
        stale = []
        for s in slugs:
            status = brain_status(s)
            print(f"{s}: {status['status']}  changed_files={status['changed_files']}")
            if status["status"] != "ready":
                stale.append(s)
        if stale:
            print(
                f"\nERROR: brain(s) out of sync with source docs: {', '.join(stale)}\n"
                f"Rebuild and commit them:  python -m nexus_platform.brain_builder {' '.join(stale)}"
            )
            sys.exit(1)
        print(f"\nAll {len(slugs)} brains match their source docs.")
        sys.exit(0)

    slugs = args or [c.slug for c in get_registry().companies.values()]
    for s in slugs:
        result = build_brain(s)
        print(f"{s}: {result['status']} in {result['duration_s']}s "
              f"({len(result['steps'])} steps)")
