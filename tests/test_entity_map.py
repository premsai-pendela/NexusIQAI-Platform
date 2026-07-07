"""Tests for the provenance-tagged business context / entity map."""

import unittest

from context.entity_map import build_context_map, _supersedence_edges


FAKE_MANIFEST = {
    "08_analytics/01_Returns_Refunds_Policy.pdf": {
        "filename": "01_Returns_Refunds_Policy.pdf",
        "category": "08_analytics",
    },
    "corpus/policies/returns_refunds_policy_v3.md": {
        "filename": "returns_refunds_policy_v3.md",
        "category": "policies",
        "format": "md",
    },
}


class ContextMapTests(unittest.TestCase):
    def test_map_builds_from_manifest_without_database(self):
        result = build_context_map(manifest=FAKE_MANIFEST, include_schema=False)

        self.assertEqual(result["stats"]["documents"], 2)
        self.assertEqual(result["stats"]["document_formats"], {"pdf": 1, "md": 1})
        self.assertFalse(result["schema"]["available"])
        self.assertGreater(result["stats"]["glossary_terms"], 0)

    def test_metric_table_edges_come_from_definitions(self):
        result = build_context_map(manifest={}, include_schema=False)
        edges = [r for r in result["relationships"] if r["type"] == "measured_from"]
        self.assertTrue(edges, "expected at least one metric->table edge")
        for edge in edges:
            self.assertIn(edge["to"], ("sales_transactions", "returns", "customers"))
            self.assertEqual(edge["provenance"], "table name in glossary definition")

    def test_supersedence_edge_read_from_corpus_front_matter(self):
        edges = _supersedence_edges()
        v3 = [e for e in edges if e["from"] == "returns_refunds_policy_v3.md"]
        self.assertEqual(len(v3), 1)
        self.assertEqual(v3[0]["to"], "01_Returns_Refunds_Policy.pdf")
        self.assertEqual(v3[0]["type"], "supersedes")

    def test_every_node_and_edge_carries_provenance(self):
        result = build_context_map(manifest=FAKE_MANIFEST, include_schema=False)
        for node in result["glossary"] + result["documents"]:
            self.assertIn("provenance", node)
        for edge in result["relationships"]:
            self.assertIn("provenance", edge)

    def test_honesty_block_present(self):
        result = build_context_map(manifest={}, include_schema=False)
        self.assertIn("never generated", result["honesty"]["note"])


if __name__ == "__main__":
    unittest.main()


class DeepContextTests(unittest.TestCase):
    def setUp(self):
        self.map = build_context_map(manifest={}, include_schema=False)

    def test_business_entities_extracted_with_provenance(self):
        entities = self.map["entities"]
        self.assertIn("FOOD-5001", [e["id"] for e in entities["skus"]])
        self.assertNotIn("CAPA-2024", [e["id"] for e in entities["skus"]])
        self.assertIn("T-2025-0114", [e["id"] for e in entities["tickets"]])
        self.assertIn("CAPA-2024-091", [e["id"] for e in entities["corrective_actions"]])
        self.assertTrue(any("Apex" in v["id"] for v in entities["vendors"]))
        for group in entities.values():
            for entity in group:
                self.assertIn("provenance", entity)

    def test_entity_edges_link_to_source_documents(self):
        recorded = [r for r in self.map["relationships"] if r["type"] == "recorded_in"]
        self.assertTrue(any(r["from"] == "FOOD-5001" and
                            r["to"] == "warehouse_inventory_export.csv" for r in recorded))

    def test_trust_model_ranks_evidence_classes(self):
        ranks = [t["rank"] for t in self.map["trust_model"]]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(self.map["trust_model"][0]["class"], "cross_validated")

    def test_staleness_flags_superseded_pdf(self):
        result = build_context_map(include_schema=False)
        stale = {s["filename"]: s for s in result["staleness"]}
        self.assertIn("01_Returns_Refunds_Policy.pdf", stale)
        self.assertIn("returns_refunds_policy_v3.md", stale["01_Returns_Refunds_Policy.pdf"]["reason"])
