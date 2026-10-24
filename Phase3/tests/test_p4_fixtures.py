"""
Tests for Person 4 QueryResponse fixtures.
Verifies all 7 fixture cases conform strictly to the Pydantic v2 contracts and JSON serialization.
"""

import json
import unittest

from backend.contracts.models import QueryResponse
from fixtures.query_response_fixtures import (
    ALL_FIXTURES,
    get_local_query_fixture,
    get_thematic_query_fixture,
    get_hybrid_query_fixture,
    get_hindi_query_fixture,
    get_conflict_query_fixture,
    get_truncation_query_fixture,
    get_insufficient_evidence_query_fixture,
)


class TestP4Fixtures(unittest.TestCase):
    def test_all_fixtures_present(self):
        expected_keys = {"local", "thematic", "hybrid", "hindi", "conflict", "truncation", "insufficient_evidence"}
        self.assertEqual(set(ALL_FIXTURES.keys()), expected_keys)

    def test_json_serialization_round_trip(self):
        for name, fixture in ALL_FIXTURES.items():
            # Dump to JSON
            json_str = fixture.model_dump_json()
            self.assertTrue(json_str)

            # Re-parse into QueryResponse
            reconstructed = QueryResponse.model_validate_json(json_str)
            self.assertEqual(reconstructed.request_id, fixture.request_id)
            self.assertEqual(reconstructed.status, fixture.status)

    def test_local_fixture_properties(self):
        fix = get_local_query_fixture()
        self.assertEqual(fix.status, "answered")
        self.assertEqual(fix.plan.query_type, "local")
        self.assertTrue(len(fix.statements) >= 1)
        self.assertTrue(len(fix.evidence.paths) >= 1)

    def test_thematic_fixture_properties(self):
        fix = get_thematic_query_fixture()
        self.assertEqual(fix.status, "answered")
        self.assertEqual(fix.plan.query_type, "thematic")
        self.assertTrue(len(fix.evidence.topics) >= 1)
        # Check that topic membership edges are marked is_topic_membership=True
        self.assertTrue(any(e.is_topic_membership for e in fix.graph.edges))

    def test_hybrid_fixture_properties(self):
        fix = get_hybrid_query_fixture()
        self.assertEqual(fix.status, "answered")
        self.assertEqual(fix.plan.query_type, "hybrid")
        self.assertTrue(len(fix.evidence.paths) >= 1)
        path = fix.evidence.paths[0]
        self.assertTrue(len(path.provenance_links) >= 2)

    def test_hindi_fixture_properties(self):
        fix = get_hindi_query_fixture()
        self.assertEqual(fix.status, "answered")
        self.assertEqual(fix.language, "hi")
        self.assertTrue(len(fix.statements) >= 1)
        # Verify statement has Hindi text
        self.assertIn("साक्ष्य", fix.statements[0].statement_text)
        # Evidence chunk is in English
        self.assertTrue(len(fix.evidence.chunks) >= 1)
        self.assertIn("PaymentGateway depends on AuthService", fix.evidence.chunks[0].text)

    def test_conflict_fixture_properties(self):
        fix = get_conflict_query_fixture()
        self.assertEqual(fix.status, "answered")
        self.assertTrue(len(fix.evidence.conflicts) >= 1)
        conf = fix.evidence.conflicts[0]
        self.assertTrue(len(conf.evidence_chunk_ids) >= 2)
        # Statements show both sources
        stmt = fix.statements[0]
        self.assertIn("Conflicting claims detected", stmt.statement_text)
        self.assertTrue(len(stmt.citation_chunk_ids) >= 2)
        self.assertIn(conf.id, stmt.contradiction_ref_ids)

    def test_truncation_fixture_properties(self):
        fix = get_truncation_query_fixture()
        self.assertEqual(fix.status, "answered")
        self.assertTrue(fix.evidence.truncated)
        self.assertTrue(fix.evidence.searched_count < fix.evidence.available_count)
        self.assertTrue(len(fix.warnings) >= 1)

    def test_insufficient_evidence_fixture_properties(self):
        fix = get_insufficient_evidence_query_fixture()
        self.assertEqual(fix.status, "insufficient_evidence")
        self.assertEqual(len(fix.evidence.chunks), 0)
        self.assertEqual(len(fix.evidence.relations), 0)
        self.assertTrue(len(fix.statements) >= 1)
        self.assertIn("No supporting evidence found", fix.statements[0].statement_text)


if __name__ == "__main__":
    unittest.main()
