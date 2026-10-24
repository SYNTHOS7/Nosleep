"""
Tests for query planning, deterministic routing rules, rationale codes, and Hindi detection.
"""

import unittest

from backend.contracts.models import (
    Entity,
    QueryRequest,
    Topic,
)
from backend.storage.interface import CorpusSnapshot
from backend.retrieval.planner import plan_query, detect_hindi


class TestQueryPlanner(unittest.TestCase):
    def setUp(self):
        self.workspace_id = "ws_planner_test"
        self.snapshot = CorpusSnapshot(
            workspace_id=self.workspace_id,
            epoch=1,
            entities={
                "ent_pg": Entity(id="ent_pg", workspace_id=self.workspace_id, name="PaymentGateway", normalized_name="paymentgateway", type="Service"),
                "ent_as": Entity(id="ent_as", workspace_id=self.workspace_id, name="AuthService", normalized_name="authservice", type="Service"),
            },
            topics={
                "top_1": Topic(
                    id="top_1",
                    workspace_id=self.workspace_id,
                    label="Payments",
                    description="Payments",
                    cluster_version="v1",
                    embedding_version="v1",
                    centroid=[],
                    representative_chunk_ids=[],
                    summary_evidence_ids=[],
                    active=True,
                ),
                "top_2": Topic(
                    id="top_2",
                    workspace_id=self.workspace_id,
                    label="Security",
                    description="Security",
                    cluster_version="v1",
                    embedding_version="v1",
                    centroid=[],
                    representative_chunk_ids=[],
                    summary_evidence_ids=[],
                    active=True,
                ),
            },
        )

    def test_thematic_routing(self):
        req = QueryRequest(
            workspace_id=self.workspace_id,
            question="What are the main themes across documents?",
        )
        plan = plan_query(req, self.snapshot)
        self.assertEqual(plan.query_type, "thematic")
        self.assertEqual(plan.rationale_code, "THEMATIC_PATTERN_KEYWORD")
        self.assertEqual(plan.query_language, "en")
        self.assertTrue(plan.use_vector)
        self.assertTrue(plan.use_lexical)
        self.assertFalse(plan.use_graph)

    def test_local_named_entity_routing(self):
        req = QueryRequest(
            workspace_id=self.workspace_id,
            question="What is the configuration of PaymentGateway?",
        )
        plan = plan_query(req, self.snapshot)
        self.assertEqual(plan.query_type, "local")
        self.assertEqual(plan.rationale_code, "LOCAL_NAMED_ENTITY")
        self.assertEqual(plan.query_language, "en")
        self.assertTrue(plan.use_graph)

    def test_hybrid_multi_hop_routing(self):
        req = QueryRequest(
            workspace_id=self.workspace_id,
            question="How does PaymentGateway connect to AuthService?",
        )
        plan = plan_query(req, self.snapshot)
        self.assertEqual(plan.query_type, "hybrid")
        self.assertEqual(plan.rationale_code, "HYBRID_CONNECTION_MULTI_HOP")
        self.assertEqual(plan.query_language, "en")
        self.assertTrue(plan.use_graph)
        self.assertTrue(plan.max_hops >= 2)

    def test_hindi_detection_and_labeling(self):
        hindi_q = "भुगतान गेटवे किस सेवा पर निर्भर करता है?"
        self.assertTrue(detect_hindi(hindi_q))

        req = QueryRequest(
            workspace_id=self.workspace_id,
            question=hindi_q,
        )
        plan = plan_query(req, self.snapshot)
        self.assertEqual(plan.query_language, "hi")

    def test_strict_topic_scoping_never_widens(self):
        # Selected scope with one topic
        req = QueryRequest(
            workspace_id=self.workspace_id,
            question="What are the themes?",
            scope="selected",
            topic_ids=["top_1"],
        )
        plan = plan_query(req, self.snapshot)
        self.assertEqual(plan.target_topic_ids, ["top_1"])
        self.assertNotIn("top_2", plan.target_topic_ids)


if __name__ == "__main__":
    unittest.main()
