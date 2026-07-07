"""Business context / entity map built only from verifiable sources.

Sources (each node carries its provenance):
- glossary: config/business_glossary.json (the same file the SQL agent uses)
- documents: the RAG ingestion manifest (what is actually in the vector store)
- tables: live SQL schema introspection, degrading to ``available: False``
  (never invented columns) when the database is unreachable

The relationship edges are deterministic: metric -> table edges come from
table names literally appearing in glossary definitions; document -> category
edges come from the manifest; the policy supersedence edge is read from the
corpus document's own front matter. No LLM, no fabrication.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from config.settings import settings
from context.business_context import load_glossary
from database.document_loaders import parse_front_matter
from database.ingestion_pipeline import CORPUS_BASE_DIR, load_rag_manifest

KNOWN_TABLES = ("sales_transactions", "returns", "customers")


def _glossary_nodes() -> List[Dict]:
    nodes = []
    for entry in load_glossary():
        nodes.append(
            {
                "id": entry.id,
                "term": entry.term,
                "definition": entry.definition,
                "aliases": list(entry.aliases),
                "provenance": "config/business_glossary.json",
            }
        )
    return nodes


def _table_nodes() -> Dict:
    """Introspect the live database schema; degrade honestly."""
    try:
        from sqlalchemy import create_engine, inspect

        engine = create_engine(settings.database_url)
        inspector = inspect(engine)
        tables = []
        for name in KNOWN_TABLES:
            if not inspector.has_table(name):
                continue
            columns = [
                {"name": col["name"], "type": str(col["type"])}
                for col in inspector.get_columns(name)
            ]
            tables.append({"name": name, "columns": columns, "provenance": "live schema introspection"})
        engine.dispose()
        return {"available": True, "tables": tables}
    except Exception as exc:
        return {"available": False, "tables": [], "error": str(exc)[:200]}


def _document_nodes(manifest: Optional[Dict] = None) -> List[Dict]:
    manifest = manifest if manifest is not None else load_rag_manifest()
    docs = []
    for key, entry in sorted(manifest.items()):
        docs.append(
            {
                "id": key,
                "filename": entry.get("filename"),
                "category": entry.get("category"),
                "format": entry.get("format", "pdf"),
                "provenance": "rag ingestion manifest",
            }
        )
    return docs


def _supersedence_edges() -> List[Dict]:
    """Read supersedes declarations from corpus front matter (truth on disk)."""
    edges = []
    base = Path(CORPUS_BASE_DIR)
    if not base.exists():
        return edges
    for path in base.rglob("*.md"):
        try:
            fields, _ = parse_front_matter(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if fields.get("supersedes"):
            edges.append(
                {
                    "from": path.name,
                    "to": fields["supersedes"].split(" ")[0],
                    "type": "supersedes",
                    "provenance": f"front matter of {path.name}",
                }
            )
    return edges


def _metric_table_edges(glossary_nodes: List[Dict]) -> List[Dict]:
    edges = []
    for node in glossary_nodes:
        definition = node["definition"].lower()
        for table in KNOWN_TABLES:
            if table in definition:
                edges.append(
                    {
                        "from": node["id"],
                        "to": table,
                        "type": "measured_from",
                        "provenance": "table name in glossary definition",
                    }
                )
    return edges


_SKU_PATTERN = re.compile(r"\b([A-Z]{3,5}-\d{4})\b")
_TICKET_PATTERN = re.compile(r"\b(T-\d{4}-\d{4})\b")
_CAPA_PATTERN = re.compile(r"\b(CAPA-\d{4}-\d{3})\b")
_TIERS = ("Bronze", "Silver", "Gold", "Platinum")


def _business_entities() -> Dict[str, List[Dict]]:
    """Extract concrete business entities from the readable corpus.

    Pattern-based and provenance-tagged: SKUs from the inventory export,
    ticket IDs from the ticket export, corrective actions and vendors from
    contracts, loyalty tiers from the glossary/policies. PDF-only entities
    (e.g. named competitors) are future work and not invented here.
    """
    base = Path(CORPUS_BASE_DIR)
    entities: Dict[str, List[Dict]] = {"skus": [], "tickets": [], "vendors": [],
                                       "corrective_actions": [], "loyalty_tiers": []}
    edges: List[Dict] = []
    if not base.exists():
        return {"entities": entities, "edges": edges}

    seen: Dict[str, set] = {k: set() for k in entities}
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for sku in _SKU_PATTERN.findall(text):
            if sku.startswith("CAPA-") or sku.startswith("IR-"):
                continue  # corrective-action / incident ids, not SKUs
            if sku not in seen["skus"]:
                seen["skus"].add(sku)
                entities["skus"].append({"id": sku, "provenance": f"pattern match in {path.name}"})
                edges.append({"from": sku, "to": path.name, "type": "recorded_in",
                              "provenance": "SKU pattern in document text"})
        for ticket in _TICKET_PATTERN.findall(text):
            if ticket not in seen["tickets"]:
                seen["tickets"].add(ticket)
                entities["tickets"].append({"id": ticket, "provenance": f"pattern match in {path.name}"})
                edges.append({"from": ticket, "to": path.name, "type": "recorded_in",
                              "provenance": "ticket id in document text"})
        for capa in _CAPA_PATTERN.findall(text):
            if capa not in seen["corrective_actions"]:
                seen["corrective_actions"].add(capa)
                entities["corrective_actions"].append(
                    {"id": capa, "provenance": f"pattern match in {path.name}"})
                edges.append({"from": capa, "to": path.name, "type": "recorded_in",
                              "provenance": "corrective action id in document text"})
        if "vendor_agreement" in path.name or "master vendor agreement" in text.lower():
            fields, _body = parse_front_matter(text)
            title = fields.get("title", path.stem)
            vendor = title.split("—")[-1].strip() if "—" in title else path.stem
            if vendor not in seen["vendors"]:
                seen["vendors"].add(vendor)
                entities["vendors"].append({"id": vendor, "provenance": f"contract title in {path.name}"})
                edges.append({"from": vendor, "to": path.name, "type": "governed_by",
                              "provenance": "vendor named in contract front matter"})
        for tier in _TIERS:
            if re.search(rf"\b{tier}\b", text) and tier not in seen["loyalty_tiers"]:
                seen["loyalty_tiers"].add(tier)
                entities["loyalty_tiers"].append({"id": tier, "provenance": f"first seen in {path.name}"})
    return {"entities": entities, "edges": edges}


_TRUST_CLASSES = [
    {"class": "cross_validated", "rank": 1,
     "meaning": "SQL and document figures agree within 1%; both cited"},
    {"class": "governed_database_value", "rank": 2,
     "meaning": "read-only SQL over the live database, business-context definitions applied"},
    {"class": "current_document", "rank": 3,
     "meaning": "cited document is the newest on its topic (no supersedence edge against it)"},
    {"class": "superseded_document", "rank": 4,
     "meaning": "document is superseded — usable for history, never for current policy answers"},
    {"class": "external_web", "rank": 5,
     "meaning": "live competitor scrape; labeled, never merged with internal facts"},
]


def _staleness(documents: List[Dict], supersedes_edges: List[Dict]) -> List[Dict]:
    """Mark documents that a newer document explicitly supersedes."""
    superseded_files = {edge["to"] for edge in supersedes_edges}
    flags = []
    for doc in documents:
        if doc["filename"] in superseded_files:
            newer = next(e["from"] for e in supersedes_edges if e["to"] == doc["filename"])
            flags.append({
                "filename": doc["filename"],
                "stale": True,
                "reason": f"superseded by {newer}",
                "provenance": "supersedes declaration in the newer document's front matter",
            })
    return flags


def build_context_map(manifest: Optional[Dict] = None,
                      include_schema: bool = True) -> Dict:
    glossary = _glossary_nodes()
    documents = _document_nodes(manifest)
    schema = _table_nodes() if include_schema else {"available": False, "tables": [], "error": "skipped"}

    categories: Dict[str, int] = {}
    formats: Dict[str, int] = {}
    for doc in documents:
        categories[doc["category"]] = categories.get(doc["category"], 0) + 1
        formats[doc["format"]] = formats.get(doc["format"], 0) + 1

    supersedes_edges = _supersedence_edges()
    business = _business_entities()
    relationships = _metric_table_edges(glossary) + supersedes_edges + business["edges"]
    for doc in documents:
        relationships.append(
            {"from": doc["filename"], "to": doc["category"], "type": "belongs_to", "provenance": "rag ingestion manifest"}
        )
    staleness = _staleness(documents, supersedes_edges)

    entity_count = sum(len(v) for v in business["entities"].values())
    return {
        "glossary": glossary,
        "schema": schema,
        "documents": documents,
        "entities": business["entities"],
        "staleness": staleness,
        "trust_model": _TRUST_CLASSES,
        "relationships": relationships,
        "stats": {
            "glossary_terms": len(glossary),
            "documents": len(documents),
            "document_categories": categories,
            "document_formats": formats,
            "tables": len(schema["tables"]),
            "business_entities": entity_count,
            "stale_documents": len(staleness),
            "relationships": len(relationships),
        },
        "honesty": {
            "sources": [
                "config/business_glossary.json",
                "rag ingestion manifest (vector-store truth)",
                "live schema introspection (or explicit unavailable)",
                "corpus front matter",
            ],
            "note": "Single demo tenant. Nodes and edges are derived from files and the live schema, never generated.",
        },
    }
