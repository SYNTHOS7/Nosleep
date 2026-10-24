"""
Tests for Hindi query routing, English evidence retrieval, and route evaluation.
"""

import unittest

from backend.contracts.models import (
    Chunk,
    Document,
    Entity,
    Evidence,
    Location,
    QueryRequest,
    Relation,
    Revision,
)
from backend.storage.interface import InMemoryStorageRepository
from backend.adapters.embedding import DeterministicMultilingualEmbeddingAdapter
from backend.answers.service import execute_query
from backend.hindi.evaluator import evaluate_hindi_retrieval_routes, FROZEN_HINDI_EVAL_SET


class TestHindiQuery(unittest.TestCase):
    def setUp(self):
        self.ws_id = "ws_hindi_test"
        self.repo = InMemoryStorageRepository(self.ws_id)
        self.embedder = DeterministicMultilingualEmbeddingAdapter(dimension=64)

        # Setup English document
        doc = Document(id="doc_en_01", workspace_id=self.ws_id, filename="arch.txt", source_type="txt", active_revision_id="rev_01")
        rev = Revision(id="rev_01", document_id="doc_en_01", content_hash="h1", parser_version="v1", chunker_version="v1", extractor_version="v1", embedding_version="v1", state="published", source_ref="ref1")
        self.repo.add_document(doc)
        self.repo.add_revision(rev)

        # English chunks
        self.chunk1 = Chunk(
            id="chunk_en_pg",
            workspace_id=self.ws_id,
            document_id="doc_en_01",
            revision_id="rev_01",
            index=0,
            text="PaymentGateway depends on AuthService for transaction authentication.",
            text_hash="h_pg",
            location=Location(start_offset=0, end_offset=70),
        )
        self.chunk2 = Chunk(
            id="chunk_en_db",
            workspace_id=self.ws_id,
            document_id="doc_en_01",
            revision_id="rev_01",
            index=1,
            text="DatabaseCluster encryption and security status is active and verified.",
            text_hash="h_db",
            location=Location(start_offset=0, end_offset=72),
        )

        self.repo.add_chunk(self.chunk1, self.embedder.embed_texts([self.chunk1.text], purpose="document")[0])
        self.repo.add_chunk(self.chunk2, self.embedder.embed_texts([self.chunk2.text], purpose="document")[0])

        # Entities and Relation
        self.ent_pg = Entity(id="ent_pg", workspace_id=self.ws_id, name="PaymentGateway", normalized_name="paymentgateway", type="Service")
        self.ent_as = Entity(id="ent_as", workspace_id=self.ws_id, name="AuthService", normalized_name="authservice", type="Service")
        self.repo.add_entity(self.ent_pg)
        self.repo.add_entity(self.ent_as)

        self.rel1 = Relation(
            id="rel_pg_as",
            workspace_id=self.ws_id,
            revision_id="rev_01",
            subject_id=self.ent_pg.id,
            object_entity_id=self.ent_as.id,
            predicate="DEPENDS_ON",
            predicate_original="depends on",
            polarity="positive",
            evidence=Evidence(chunk_id=self.chunk1.id, start=0, end=len(self.chunk1.text), quote=self.chunk1.text),
            extraction_model="model_v1",
            extraction_version="v1",
        )
        self.repo.add_relation(self.rel1)

    def test_hindi_query_retrieves_english_evidence_and_responds_in_hindi(self):
        hindi_q = "भुगतान गेटवे किस सेवा पर निर्भर करता है?"
        req = QueryRequest(
            workspace_id=self.ws_id,
            question=hindi_q,
            answer_language="hi",
        )
        res = execute_query(req, self.repo, self.embedder)

        self.assertEqual(res.status, "answered")
        self.assertEqual(res.language, "hi")
        self.assertEqual(res.plan.query_language, "hi")

        # Source evidence chunks must remain in English!
        self.assertTrue(len(res.evidence.chunks) >= 1)
        first_chunk = res.evidence.chunks[0]
        self.assertEqual(first_chunk.id, self.chunk1.id)
        self.assertIn("PaymentGateway depends on AuthService", first_chunk.text)

        # Answer statement text is in Hindi
        self.assertTrue(len(res.statements) >= 1)
        stmt = res.statements[0]
        self.assertIn("साक्ष्य", stmt.statement_text)
        # But citations point to English chunk and path!
        self.assertIn(self.chunk1.id, stmt.citation_chunk_ids)

    def test_evaluate_hindi_retrieval_routes(self):
        eval_result = evaluate_hindi_retrieval_routes(
            storage_repo=self.repo,
            workspace_id=self.ws_id,
            embedding_adapter=self.embedder,
        )

        self.assertIn("route_a_mean_score", eval_result)
        self.assertIn("route_b_mean_score", eval_result)
        self.assertIn("chosen_route", eval_result)
        self.assertTrue(eval_result["source_evidence_preserved_in_english"])
        self.assertTrue(len(eval_result["per_question_details"]) == len(FROZEN_HINDI_EVAL_SET))


if __name__ == "__main__":
    unittest.main()
