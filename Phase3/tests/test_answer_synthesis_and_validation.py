"""
Tests for answer synthesis, citation validation, repair mechanism, and conflict presentation.
"""

import unittest

from backend.contracts.models import (
    AnswerStatement,
    Chunk,
    Conflict,
    Entity,
    Evidence,
    EvidencePackage,
    EvidencePath,
    GraphEdgeView,
    Location,
    ProvenanceLink,
    QueryRequest,
    Relation,
)
from backend.answers.synthesizer import synthesize, validate_citations
from backend.adapters.llm import GroundedLLMAdapter


class MockHallucinatingLLMAdapter(GroundedLLMAdapter):
    """Mock adapter that intentionally injects a hallucinated citation."""
    def synthesize_statements(self, question, package, language="en"):
        # Returns a statement citing a non-existent chunk ID
        return [
            AnswerStatement(
                statement_text="PaymentGateway connects to AuthService.",
                citation_chunk_ids=["hallucinated_chunk_999"],
                citation_path_ids=[],
                is_inference=False,
                confidence=1.0,
            )
        ]


class TestAnswerSynthesisAndValidation(unittest.TestCase):
    def setUp(self):
        self.ws_id = "ws_synthesis_test"
        self.chunk1 = Chunk(
            id="c1",
            workspace_id=self.ws_id,
            document_id="d1",
            revision_id="r1",
            index=0,
            text="PaymentGateway depends on AuthService for authentication tokens.",
            text_hash="h1",
            location=Location(start_offset=0, end_offset=65),
        )
        self.ent_pg = Entity(id="ent_pg", workspace_id=self.ws_id, name="PaymentGateway", normalized_name="paymentgateway", type="Service")
        self.ent_as = Entity(id="ent_as", workspace_id=self.ws_id, name="AuthService", normalized_name="authservice", type="Service")

        self.rel1 = Relation(
            id="rel1",
            workspace_id=self.ws_id,
            revision_id="r1",
            subject_id=self.ent_pg.id,
            object_entity_id=self.ent_as.id,
            predicate="DEPENDS_ON",
            predicate_original="depends on",
            polarity="positive",
            evidence=Evidence(chunk_id=self.chunk1.id, start=0, end=len(self.chunk1.text), quote=self.chunk1.text),
            extraction_model="model_v1",
            extraction_version="v1",
        )

        self.path1 = EvidencePath(
            path_id="path_pg_as",
            node_ids=[self.ent_pg.id, self.ent_as.id],
            edges=[
                GraphEdgeView(
                    id="edge_rel1",
                    source_id=self.ent_pg.id,
                    target_id=self.ent_as.id,
                    predicate="DEPENDS_ON",
                    relation_id=self.rel1.id,
                    source_chunk_id=self.chunk1.id,
                )
            ],
            provenance_links=[
                ProvenanceLink(chunk_id=self.chunk1.id, revision_id="r1", document_id="d1")
            ],
        )

        self.package = EvidencePackage(
            workspace_id=self.ws_id,
            corpus_epoch=1,
            chunks=[self.chunk1],
            relations=[self.rel1],
            entities=[self.ent_pg, self.ent_as],
            values=[],
            paths=[self.path1],
            topics=[],
            conflicts=[],
            searched_count=1,
            available_count=10,
        )

    def test_valid_grounded_synthesis(self):
        req = QueryRequest(workspace_id=self.ws_id, question="What does PaymentGateway depend on?")
        stmts = synthesize(req, self.package)

        self.assertTrue(len(stmts) >= 1)
        stmt = stmts[0]
        self.assertIn("PaymentGateway DEPENDS_ON AuthService", stmt.statement_text)
        self.assertIn(self.chunk1.id, stmt.citation_chunk_ids)
        self.assertIn(self.path1.path_id, stmt.citation_path_ids)
        # Verify validation passes
        self.assertTrue(validate_citations(stmts, {self.chunk1.id}, {self.path1.path_id}))

    def test_citation_validation_and_repair_fallback(self):
        req = QueryRequest(workspace_id=self.ws_id, question="What does PaymentGateway depend on?")
        hallucinating_adapter = MockHallucinatingLLMAdapter()

        stmts = synthesize(req, self.package, llm_adapter=hallucinating_adapter)
        self.assertEqual(len(stmts), 1)
        # Because repair failed to find any valid citations for the hallucinated statement,
        # it fell back to extractive insufficient evidence
        stmt = stmts[0]
        self.assertIn("Insufficient evidence", stmt.statement_text)
        self.assertEqual(len(stmt.citation_chunk_ids), 0)

    def test_conflict_presentation_shows_both_sources(self):
        chunk_b = Chunk(
            id="c2",
            workspace_id=self.ws_id,
            document_id="d2",
            revision_id="r2",
            index=0,
            text="PaymentGateway operates completely standalone without AuthService.",
            text_hash="h2",
            location=Location(start_offset=0, end_offset=68),
        )
        rel2 = Relation(
            id="rel2",
            workspace_id=self.ws_id,
            revision_id="r2",
            subject_id=self.ent_pg.id,
            object_entity_id=self.ent_as.id,
            predicate="DEPENDS_ON",
            predicate_original="operates standalone without",
            polarity="negative",
            evidence=Evidence(chunk_id=chunk_b.id, start=0, end=len(chunk_b.text), quote=chunk_b.text),
            extraction_model="model_v1",
            extraction_version="v1",
        )
        conflict = Conflict(
            id="conf_neg_01",
            workspace_id=self.ws_id,
            left_relation_id=self.rel1.id,
            right_relation_id=rel2.id,
            kind="negation",
            state="supported",
            explanation="Polarity conflict on PaymentGateway DEPENDS_ON AuthService",
            evidence_chunk_ids=[self.chunk1.id, chunk_b.id],
            detector_version="v1",
        )

        conflict_package = EvidencePackage(
            workspace_id=self.ws_id,
            corpus_epoch=1,
            chunks=[self.chunk1, chunk_b],
            relations=[self.rel1, rel2],
            entities=[self.ent_pg, self.ent_as],
            values=[],
            paths=[],
            topics=[],
            conflicts=[conflict],
            searched_count=2,
            available_count=10,
        )

        req = QueryRequest(workspace_id=self.ws_id, question="Does PaymentGateway depend on AuthService?")
        stmts = synthesize(req, conflict_package)

        self.assertTrue(len(stmts) >= 1)
        stmt = stmts[0]
        # Must show both sources and cite both chunks
        self.assertIn("Conflicting claims detected", stmt.statement_text)
        self.assertIn(self.chunk1.id, stmt.citation_chunk_ids)
        self.assertIn(chunk_b.id, stmt.citation_chunk_ids)
        self.assertIn(conflict.id, stmt.contradiction_ref_ids)

    def test_no_evidence_returns_insufficient_evidence(self):
        empty_package = EvidencePackage(
            workspace_id=self.ws_id,
            corpus_epoch=1,
            chunks=[],
            relations=[],
            entities=[],
            values=[],
            paths=[],
            topics=[],
            conflicts=[],
            searched_count=0,
            available_count=10,
        )
        req = QueryRequest(workspace_id=self.ws_id, question="Does service X exist?")
        stmts = synthesize(req, empty_package)
        self.assertEqual(len(stmts), 1)
        self.assertIn("No supporting evidence found", stmts[0].statement_text)
        self.assertEqual(len(stmts[0].citation_chunk_ids), 0)


if __name__ == "__main__":
    unittest.main()
