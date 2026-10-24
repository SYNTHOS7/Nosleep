"""
Tests for retrieval, rank fusion, active-revision isolation, topic scoping, and bounded graph expansion.
"""

import unittest

from backend.contracts.models import (
    Chunk,
    Document,
    Entity,
    Evidence,
    Location,
    QueryPlan,
    QueryRequest,
    Relation,
    Revision,
    Topic,
    TopicMembership,
)
from backend.storage.interface import InMemoryStorageRepository
from backend.adapters.embedding import DeterministicMultilingualEmbeddingAdapter
from backend.retrieval.fusion import reciprocal_rank_fusion
from backend.retrieval.engine import retrieve


class TestRetrievalAndFusion(unittest.TestCase):
    def setUp(self):
        self.workspace_id = "ws_retrieval_test"
        self.repo = InMemoryStorageRepository(self.workspace_id)
        self.embedder = DeterministicMultilingualEmbeddingAdapter(dimension=64)

        # Setup documents & revisions
        self.doc1 = Document(id="doc_1", workspace_id=self.workspace_id, filename="d1.txt", source_type="txt", active_revision_id="rev_active")
        self.doc2 = Document(id="doc_2", workspace_id=self.workspace_id, filename="d2.txt", source_type="txt", active_revision_id="rev_active_2")
        self.repo.add_document(self.doc1)
        self.repo.add_document(self.doc2)

        self.rev_active = Revision(id="rev_active", document_id="doc_1", content_hash="h1", parser_version="v1", chunker_version="v1", extractor_version="v1", embedding_version="v1", state="published", source_ref="ref1")
        self.rev_retired = Revision(id="rev_retired", document_id="doc_1", content_hash="h0", parser_version="v1", chunker_version="v1", extractor_version="v1", embedding_version="v1", state="retired", source_ref="ref0")
        self.rev_active_2 = Revision(id="rev_active_2", document_id="doc_2", content_hash="h2", parser_version="v1", chunker_version="v1", extractor_version="v1", embedding_version="v1", state="published", source_ref="ref2")
        self.repo.add_revision(self.rev_active)
        self.repo.add_revision(self.rev_retired)
        self.repo.add_revision(self.rev_active_2)

        # Chunks: active vs retired
        self.chunk_active = Chunk(id="chunk_act", workspace_id=self.workspace_id, document_id="doc_1", revision_id="rev_active", index=0, text="PaymentGateway processes customer credit card payments.", text_hash="hact", location=Location(start_offset=0, end_offset=50))
        self.chunk_retired = Chunk(id="chunk_ret", workspace_id=self.workspace_id, document_id="doc_1", revision_id="rev_retired", index=0, text="PaymentGateway old legacy version handles magnetic stripe.", text_hash="hret", location=Location(start_offset=0, end_offset=50))
        self.chunk_active_2 = Chunk(id="chunk_act_2", workspace_id=self.workspace_id, document_id="doc_2", revision_id="rev_active_2", index=0, text="AuthService validates tokens for PaymentGateway.", text_hash="hact2", location=Location(start_offset=0, end_offset=45))

        self.repo.add_chunk(self.chunk_active, self.embedder.embed_texts([self.chunk_active.text], purpose="document")[0])
        self.repo.add_chunk(self.chunk_retired, self.embedder.embed_texts([self.chunk_retired.text], purpose="document")[0])
        self.repo.add_chunk(self.chunk_active_2, self.embedder.embed_texts([self.chunk_active_2.text], purpose="document")[0])

        # Entities & Relations
        self.ent_pg = Entity(id="ent_pg", workspace_id=self.workspace_id, name="PaymentGateway", normalized_name="paymentgateway", type="Service")
        self.ent_as = Entity(id="ent_as", workspace_id=self.workspace_id, name="AuthService", normalized_name="authservice", type="Service")
        self.repo.add_entity(self.ent_pg)
        self.repo.add_entity(self.ent_as)

        self.rel1 = Relation(
            id="rel_act_1",
            workspace_id=self.workspace_id,
            revision_id="rev_active",
            subject_id=self.ent_pg.id,
            object_entity_id=self.ent_as.id,
            predicate="CONNECTS_TO",
            predicate_original="connects to",
            polarity="positive",
            evidence=Evidence(chunk_id=self.chunk_active.id, start=0, end=len(self.chunk_active.text), quote=self.chunk_active.text),
            extraction_model="test-model",
            extraction_version="v1",
        )
        self.repo.add_relation(self.rel1)

        # Topics
        self.topic1 = Topic(
            id="topic_pay",
            workspace_id=self.workspace_id,
            label="Payments",
            description="Payment processing",
            cluster_version="v1",
            embedding_version="v1",
            centroid=[0.1] * 64,
            representative_chunk_ids=[self.chunk_active.id],
            summary_evidence_ids=[self.chunk_active.id],
            active=True,
        )
        self.repo.add_topic(self.topic1)
        self.repo.add_topic_membership(
            TopicMembership(topic_id="topic_pay", chunk_id=self.chunk_active.id, revision_id="rev_active", method="cluster", score=0.9, assignment_version="v1")
        )

    def test_reciprocal_rank_fusion(self):
        list1 = ["chunk_a", "chunk_b", "chunk_c"]
        list2 = ["chunk_b", "chunk_a", "chunk_d"]

        fused = reciprocal_rank_fusion([list1, list2], k=60, limit=10)
        top_candidates = [cid for cid, score in fused]
        # Both chunk_a and chunk_b are in both lists
        self.assertIn("chunk_a", top_candidates[:2])
        self.assertIn("chunk_b", top_candidates[:2])
        # Score calculation check
        score_a = (1.0 / (60 + 1)) + (1.0 / (60 + 2))
        score_b = (1.0 / (60 + 2)) + (1.0 / (60 + 1))
        self.assertAlmostEqual(fused[0][1], score_a)

    def test_active_revision_isolation(self):
        snapshot = self.repo.get_snapshot(self.workspace_id)
        plan = QueryPlan(
            query_type="local",
            rationale_code="LOCAL_NAMED_ENTITY",
            query_language="en",
            target_topic_ids=[],
            use_vector=True,
            use_lexical=True,
            use_graph=True,
            max_hops=2,
            top_k=5,
        )
        req = QueryRequest(workspace_id=self.workspace_id, question="PaymentGateway magnetic stripe")
        package = retrieve(plan, req, snapshot, self.repo, self.embedder)

        retrieved_ids = {c.id for c in package.chunks}
        # Retired chunk MUST NOT be returned!
        self.assertNotIn("chunk_ret", retrieved_ids)
        self.assertIn("chunk_act", retrieved_ids)

    def test_topic_scoping_enforcement(self):
        snapshot = self.repo.get_snapshot(self.workspace_id)
        # Search with selected scope that excludes topic_pay
        plan = QueryPlan(
            query_type="local",
            rationale_code="LOCAL_NAMED_ENTITY",
            query_language="en",
            target_topic_ids=["topic_non_existent"],
            use_vector=True,
            use_lexical=True,
            use_graph=True,
            max_hops=2,
            top_k=5,
        )
        req = QueryRequest(
            workspace_id=self.workspace_id,
            question="PaymentGateway",
            scope="selected",
            topic_ids=["topic_non_existent"],
        )
        package = retrieve(plan, req, snapshot, self.repo, self.embedder)
        # Underfilled active-filtered retrieval returns limitation warning
        self.assertEqual(len(package.chunks), 0)
        self.assertTrue(any("Underfilled active-filtered retrieval" in lim for lim in package.limitations))

    def test_bounded_graph_expansion_and_provenance(self):
        snapshot = self.repo.get_snapshot(self.workspace_id)
        plan = QueryPlan(
            query_type="hybrid",
            rationale_code="HYBRID_CONNECTION_MULTI_HOP",
            query_language="en",
            target_topic_ids=[],
            use_vector=True,
            use_lexical=True,
            use_graph=True,
            max_hops=2,
            top_k=5,
        )
        req = QueryRequest(workspace_id=self.workspace_id, question="How does PaymentGateway connect to AuthService?")
        package = retrieve(plan, req, snapshot, self.repo, self.embedder)

        self.assertTrue(len(package.paths) >= 1)
        path = package.paths[0]
        # Verify edge direction and relation ID
        edge = path.edges[0]
        self.assertEqual(edge.relation_id, self.rel1.id)
        self.assertEqual(edge.source_id, self.ent_pg.id)
        self.assertEqual(edge.target_id, self.ent_as.id)
        self.assertFalse(edge.is_topic_membership)

        # Verify provenance link Chunk -> Revision -> Document
        self.assertTrue(len(path.provenance_links) >= 1)
        prov = path.provenance_links[0]
        self.assertEqual(prov.chunk_id, self.chunk_active.id)
        self.assertEqual(prov.revision_id, "rev_active")
        self.assertEqual(prov.document_id, "doc_1")


if __name__ == "__main__":
    unittest.main()
