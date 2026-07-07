"""
Multi-format document loaders for the NexusIQ ingestion pipeline.

Each loader returns the same contract as
``RAGPipelineSetup.extract_text_from_pdf``:

    (sections, metadata)

where ``sections`` is a list of ``{"page_num": int, "text": str}`` dicts
(``page_num`` is a 1-based section index for non-paginated formats) and
``metadata`` carries ``filename``, ``category``, ``pages``,
``extraction_method``, plus format-aware fields: ``format``, ``doc_type``,
and ``as_of`` when the source declares one.

Supported formats: Markdown (.md), plain text (.txt), CSV (.csv),
JSON (.json), and HTML (.html/.htm). PDFs stay on the existing extractor.
"""

from __future__ import annotations

import csv
import io
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SUPPORTED_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".html", ".htm"}

# Rows of a CSV textualized per section; keeps sections chunker-friendly.
_CSV_ROWS_PER_SECTION = 12
# JSON records textualized per section.
_JSON_RECORDS_PER_SECTION = 6

_DOC_TYPE_HINTS = (
    ("glossary", "glossary"),
    ("dictionary", "data_dictionary"),
    ("policy", "policy"),
    ("policies", "policy"),
    ("ticket", "support_tickets"),
    ("meeting", "meeting_notes"),
    ("notes", "meeting_notes"),
    ("contract", "contract"),
    ("agreement", "contract"),
    ("inventory", "data_export"),
    ("export", "data_export"),
    ("newsletter", "communication"),
)


def is_supported(path: Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def infer_doc_type(path: Path, declared: Optional[str] = None) -> str:
    """Doc type from front matter when declared, else filename/dir keywords."""
    if declared:
        return str(declared).strip().lower().replace(" ", "_")
    haystack = f"{path.parent.name} {path.stem}".lower()
    for needle, doc_type in _DOC_TYPE_HINTS:
        if needle in haystack:
            return doc_type
    return "document"


def parse_front_matter(text: str) -> Tuple[Dict[str, str], str]:
    """Parse a minimal ``key: value`` front-matter block delimited by ---."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    fields: Dict[str, str] = {}
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body = "\n".join(lines[idx + 1:]).lstrip("\n")
            return fields, body
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip().lower()] = value.strip()
    # No closing delimiter: treat as plain content.
    return {}, text


class _TextExtractor(HTMLParser):
    """Extract readable text from HTML, skipping script/style."""

    _SKIP = {"script", "style", "noscript"}
    _BLOCK = {"p", "div", "section", "article", "li", "tr", "table",
              "h1", "h2", "h3", "h4", "h5", "h6", "br", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _base_metadata(path: Path, fmt: str, method: str) -> Dict[str, object]:
    return {
        "filename": path.name,
        "category": path.parent.name,
        "pages": 0,
        "extraction_method": method,
        "format": fmt,
        "doc_type": infer_doc_type(path),
    }


def _finalize(sections: List[Dict], metadata: Dict) -> Tuple[List[Dict], Dict]:
    sections = [s for s in sections if s["text"].strip()]
    metadata["pages"] = len(sections)
    return sections, metadata


def load_markdown(path: Path) -> Tuple[List[Dict], Dict]:
    text = path.read_text(encoding="utf-8")
    fields, body = parse_front_matter(text)
    metadata = _base_metadata(path, "markdown", "markdown_sections")
    metadata["doc_type"] = infer_doc_type(path, fields.get("doc_type"))
    if fields.get("as_of"):
        metadata["as_of"] = fields["as_of"]
    if fields.get("title"):
        metadata["title"] = fields["title"]

    # Split on top-level and second-level headings so each section stays
    # topically coherent; the chunker handles further splitting.
    pieces = re.split(r"(?m)^(?=#{1,2} )", body)
    sections = [
        {"page_num": i, "text": piece.strip()}
        for i, piece in enumerate([p for p in pieces if p.strip()], start=1)
    ]
    return _finalize(sections, metadata)


def load_text(path: Path) -> Tuple[List[Dict], Dict]:
    text = path.read_text(encoding="utf-8")
    fields, body = parse_front_matter(text)
    metadata = _base_metadata(path, "text", "plain_text")
    metadata["doc_type"] = infer_doc_type(path, fields.get("doc_type"))
    if fields.get("as_of"):
        metadata["as_of"] = fields["as_of"]

    # Paragraph blocks; group into ~2000-char sections.
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]
    sections: List[Dict] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) > 2000 and current:
            sections.append({"page_num": len(sections) + 1, "text": current.strip()})
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current.strip():
        sections.append({"page_num": len(sections) + 1, "text": current.strip()})
    return _finalize(sections, metadata)


def load_csv(path: Path) -> Tuple[List[Dict], Dict]:
    metadata = _base_metadata(path, "csv", "csv_rows")
    raw = path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(raw))
    rows = [row for row in reader if any((v or "").strip() for v in row.values())]
    columns = reader.fieldnames or []

    sections: List[Dict] = [{
        "page_num": 1,
        "text": (
            f"{path.stem.replace('_', ' ')} data export. "
            f"Columns: {', '.join(columns)}. Total rows: {len(rows)}."
        ),
    }]
    for start in range(0, len(rows), _CSV_ROWS_PER_SECTION):
        batch = rows[start:start + _CSV_ROWS_PER_SECTION]
        lines = []
        for row in batch:
            # Snake_case cell values (e.g. reorder_review) read poorly and
            # miss keyword search; render them as words in the indexed text.
            pairs = ", ".join(
                f"{k}: {str(v).replace('_', ' ')}"
                for k, v in row.items() if (v or "").strip()
            )
            lines.append(f"Record — {pairs}.")
        sections.append({"page_num": len(sections) + 1, "text": "\n".join(lines)})
    return _finalize(sections, metadata)


def _record_to_text(record: Dict) -> str:
    pairs = []
    for key, value in record.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        text = str(value).strip()
        if text:
            pairs.append(f"{key}: {text}")
    return "Record — " + "; ".join(pairs) + "."


def load_json(path: Path) -> Tuple[List[Dict], Dict]:
    metadata = _base_metadata(path, "json", "json_records")
    payload = json.loads(path.read_text(encoding="utf-8"))

    records: List[Dict] = []
    preamble = ""
    if isinstance(payload, list):
        records = [r for r in payload if isinstance(r, dict)]
    elif isinstance(payload, dict):
        if isinstance(payload.get("as_of"), str):
            metadata["as_of"] = payload["as_of"]
        if isinstance(payload.get("doc_type"), str):
            metadata["doc_type"] = infer_doc_type(path, payload["doc_type"])
        if isinstance(payload.get("description"), str):
            preamble = payload["description"]
        for key in ("records", "tickets", "entries", "items", "data"):
            if isinstance(payload.get(key), list):
                records = [r for r in payload[key] if isinstance(r, dict)]
                break
        else:
            # Flat object: treat the whole payload as one record.
            records = [payload]

    sections: List[Dict] = []
    if preamble:
        sections.append({"page_num": 1, "text": preamble})
    for start in range(0, len(records), _JSON_RECORDS_PER_SECTION):
        batch = records[start:start + _JSON_RECORDS_PER_SECTION]
        text = "\n".join(_record_to_text(r) for r in batch)
        sections.append({"page_num": len(sections) + 1, "text": text})
    return _finalize(sections, metadata)


def load_html(path: Path) -> Tuple[List[Dict], Dict]:
    metadata = _base_metadata(path, "html", "html_text")
    parser = _TextExtractor()
    parser.feed(path.read_text(encoding="utf-8"))
    text = parser.text()

    title_match = re.search(r"<title>(.*?)</title>", path.read_text(encoding="utf-8"),
                            re.IGNORECASE | re.DOTALL)
    if title_match:
        metadata["title"] = title_match.group(1).strip()

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    sections: List[Dict] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) > 2000 and current:
            sections.append({"page_num": len(sections) + 1, "text": current.strip()})
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current.strip():
        sections.append({"page_num": len(sections) + 1, "text": current.strip()})
    return _finalize(sections, metadata)


_LOADERS = {
    ".md": load_markdown,
    ".txt": load_text,
    ".csv": load_csv,
    ".json": load_json,
    ".html": load_html,
    ".htm": load_html,
}


def extract_document(path: Path) -> Tuple[List[Dict], Dict]:
    """Extract (sections, metadata) from any supported non-PDF document."""
    path = Path(path)
    loader = _LOADERS.get(path.suffix.lower())
    if loader is None:
        raise ValueError(f"Unsupported document format: {path.suffix} ({path.name})")
    return loader(path)
