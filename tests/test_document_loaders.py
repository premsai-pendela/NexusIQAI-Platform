"""Unit tests for the multi-format document loaders."""

import json
import tempfile
import unittest
from pathlib import Path

from database.document_loaders import (
    SUPPORTED_EXTENSIONS,
    extract_document,
    infer_doc_type,
    is_supported,
    parse_front_matter,
)

CORPUS_DIR = Path(__file__).resolve().parents[1] / "data" / "corpus"


class FrontMatterTests(unittest.TestCase):
    def test_parses_key_values_and_strips_block(self):
        fields, body = parse_front_matter("---\ntitle: X\nas_of: 2025-01-01\n---\n\n# Body\n")
        self.assertEqual(fields["title"], "X")
        self.assertEqual(fields["as_of"], "2025-01-01")
        self.assertTrue(body.startswith("# Body"))

    def test_no_front_matter_returns_text_unchanged(self):
        fields, body = parse_front_matter("plain text")
        self.assertEqual(fields, {})
        self.assertEqual(body, "plain text")

    def test_unclosed_front_matter_treated_as_content(self):
        text = "---\ntitle: broken\nno closing"
        fields, body = parse_front_matter(text)
        self.assertEqual(fields, {})
        self.assertEqual(body, text)


class DocTypeInferenceTests(unittest.TestCase):
    def test_declared_type_wins(self):
        self.assertEqual(infer_doc_type(Path("x/whatever.md"), "Policy"), "policy")

    def test_filename_keywords(self):
        self.assertEqual(infer_doc_type(Path("a/business_glossary.md")), "glossary")
        self.assertEqual(infer_doc_type(Path("a/vendor_agreement_x.txt")), "contract")
        self.assertEqual(infer_doc_type(Path("support/tickets_q1.json")), "support_tickets")

    def test_unknown_falls_back_to_document(self):
        self.assertEqual(infer_doc_type(Path("a/other/misc.csv")), "document")


class LoaderContractTests(unittest.TestCase):
    """Every loader must return the (sections, metadata) pipeline contract."""

    def _assert_contract(self, sections, metadata, fmt):
        self.assertTrue(sections, f"no sections for {fmt}")
        for section in sections:
            self.assertIn("page_num", section)
            self.assertIn("text", section)
            self.assertTrue(section["text"].strip())
        for key in ("filename", "category", "pages", "extraction_method", "format", "doc_type"):
            self.assertIn(key, metadata)
        self.assertEqual(metadata["format"], fmt)
        self.assertEqual(metadata["pages"], len(sections))

    def test_markdown_sections_split_on_headings(self):
        path = CORPUS_DIR / "glossary" / "business_glossary.md"
        sections, metadata = extract_document(path)
        self._assert_contract(sections, metadata, "markdown")
        self.assertEqual(metadata["doc_type"], "glossary")
        self.assertEqual(metadata["as_of"], "2025-01-15")
        self.assertGreater(len(sections), 3)
        joined = " ".join(s["text"] for s in sections)
        self.assertIn("Net revenue", joined)

    def test_text_loader_reads_front_matter(self):
        path = CORPUS_DIR / "policies" / "data_retention_policy.txt"
        sections, metadata = extract_document(path)
        self._assert_contract(sections, metadata, "text")
        self.assertEqual(metadata["doc_type"], "policy")
        self.assertEqual(metadata["as_of"], "2024-12-01")
        self.assertNotIn("---", sections[0]["text"].split("\n")[0])

    def test_csv_loader_emits_header_summary_and_rows(self):
        path = CORPUS_DIR / "operations" / "warehouse_inventory_export.csv"
        sections, metadata = extract_document(path)
        self._assert_contract(sections, metadata, "csv")
        self.assertIn("Columns:", sections[0]["text"])
        self.assertIn("Total rows: 16", sections[0]["text"])
        joined = " ".join(s["text"] for s in sections)
        self.assertIn("Yoga Mat", joined)

    def test_json_loader_reads_tickets_and_as_of(self):
        path = CORPUS_DIR / "support_tickets" / "tickets_2025_q1.json"
        sections, metadata = extract_document(path)
        self._assert_contract(sections, metadata, "json")
        self.assertEqual(metadata["doc_type"], "support_tickets")
        self.assertEqual(metadata["as_of"], "2025-03-31")
        joined = " ".join(s["text"] for s in sections)
        self.assertIn("T-2025-0114", joined)
        self.assertIn("accelerometer calibration", joined)

    def test_html_loader_strips_markup(self):
        path = CORPUS_DIR / "communications" / "customer_newsletter_march2025.html"
        sections, metadata = extract_document(path)
        self._assert_contract(sections, metadata, "html")
        joined = " ".join(s["text"] for s in sections)
        self.assertIn("35-day return window", joined)
        self.assertNotIn("<h2>", joined)
        self.assertEqual(metadata["title"], "NexusIQ Newsletter — March 2025")


class EdgeCaseTests(unittest.TestCase):
    def test_unsupported_extension_raises(self):
        with self.assertRaises(ValueError):
            extract_document(Path("nope.xyz"))

    def test_is_supported_matches_extension_set(self):
        for ext in SUPPORTED_EXTENSIONS:
            self.assertTrue(is_supported(Path(f"a{ext}")))
        self.assertFalse(is_supported(Path("a.pdf")))

    def test_json_list_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.json"
            path.write_text(json.dumps([{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]))
            sections, metadata = extract_document(path)
            self.assertEqual(metadata["format"], "json")
            self.assertIn("alpha", sections[0]["text"])

    def test_empty_markdown_yields_no_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.md"
            path.write_text("   \n\n  ")
            sections, metadata = extract_document(path)
            self.assertEqual(sections, [])
            self.assertEqual(metadata["pages"], 0)


class CorpusIntegrityTests(unittest.TestCase):
    """The shipped demo corpus must stay loadable end to end."""

    def test_every_corpus_file_extracts_nonempty_sections(self):
        corpus_files = [
            p for p in CORPUS_DIR.rglob("*")
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        self.assertGreaterEqual(len(corpus_files), 8)
        for path in corpus_files:
            with self.subTest(file=str(path.relative_to(CORPUS_DIR))):
                sections, metadata = extract_document(path)
                self.assertTrue(sections)
                self.assertTrue(metadata["doc_type"])


if __name__ == "__main__":
    unittest.main()
