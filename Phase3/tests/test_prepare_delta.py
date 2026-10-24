"""
Tests for prepare_delta interface and DerivedDelta handoff to Person 1.
"""

import time
import unittest

from backend.contracts.models import (
    Chunk,
    Document,
    Entity,
    Evidence,
    Location,
    Relation,
    Revision,
    Topic,
    Value,
)
from backend.storage.interface import InMemoryStorageRepository
from backend.topics.manager import TopicManager
from backend.delta.preparer import prepare_delta


class TestPrepareDelta(unittest.TestCase):
    def setUp(self):
        self.ws_id = "ws_delta_test"
        self.repo = InMemoryStorageRepository(self.ws_id)
        self.topic_manager = TopicManager()

        # Existing active document and revision
        self.doc = Document(id="doc_1", workspace_id=self.ws_id, filename="sys.txt", source_type="txt", active_revision_id="rev_1")
        self.rev1 = Revision(id="rev_1", document_id="doc_1", content_hash="h1", parser_version="v1", chunker_version="v1", extractor_version="v1", embedding_version="v1", state="published", source_ref="ref1")
        self.repo.add_document(self.doc)
        self.repo.add_revision(self.rev1)

        # Existing active chunk
        self.chunk1 = Chunk(id="c1", workspace_id=self.ws_id, document_id="doc_1", revision_id="rev_1", index=0, text="PaymentAPI status is open_source.", text_hash="h1", location=Location(start_offset=0, end_offset=33))
        self.repo.add_chunk(self.chunk1, [0.5] * 64)

        # Existing active topic
        self.topic1 = Topic(
            id="topic_pay",
            workspace_id=self.ws_id,
            label="Payment Services",
            description="Payment processing services",
            cluster_version="v1",
            embedding_version="v1",
            centroid=[0.5] * 64,
            representative_chunk_ids=[self.chunk1.id],
            summary_evidence_ids=[self.chunk1.id],
            active=True,
        )
        self.repo.add_topic(self.topic1)

        # Existing active relation with open_source status
        val_os = Value(id="val_os", workspace_id=self.ws_id, kind="text", lexical_value="open_source", normalized_value="open_source")
        self.repo.add_value(val_os)

        rel1 = Relation(
            id="rel_act_os",
            workspace_id=self.ws_id,
            revision_id="rev_1",
            subject_id="PaymentAPI",
            object_value_id=val_os.id,
            predicate="has_status",
            predicate_original="status is",
            polarity="positive",
            evidence=Evidence(chunk_id=self.chunk1.id, start=0, end=len(self.chunk1.text), quote=self.chunk1.text),
            extraction_model="model_v1",
            extraction_version="v1",
        )
        self.repo.add_relation(rel1)

    def test_prepare_delta_incremental_topics_and_conflicts(self):
        # Stage a new revision for doc_1 (an edit operation)
        staged_rev_id = "rev_2_staged"
        staged_chunk = Chunk(
            id="c2_staged",
            workspace_id=self.ws_id,
            document_id="doc_1",
            revision_id=staged_rev_id,
            index=0,
            text="PaymentAPI status is proprietary and private.",
            text_hash="h2",
            location=Location(start_offset=0, end_offset=46),
        )
        self.repo.add_chunk(staged_chunk, [0.52] * 64)

        val_prop = Value(id="val_prop", workspace_id=self.ws_id, kind="text", lexical_value="proprietary", normalized_value="proprietary")
        self.repo.add_value(val_prop)

        staged_rel = Relation(
            id="rel_staged_prop",
            workspace_id=self.ws_id,
            revision_id=staged_rev_id,
            subject_id="PaymentAPI",
            object_value_id=val_prop.id,
            predicate="has_status",
            predicate_original="status is",
            polarity="positive",
            evidence=Evidence(chunk_id=staged_chunk.id, start=0, end=len(staged_chunk.text), quote=staged_chunk.text),
            extraction_model="model_v1",
            extraction_version="v1",
        )
        self.repo.add_relation(staged_rel)

        # Snapshot before publication
        snapshot = self.repo.get_snapshot(self.ws_id)

        t0 = time.perf_counter()
        delta = prepare_delta(
            operation_id="op_edit_01",
            staged_revision_id=staged_rev_id,
            snapshot=snapshot,
            topic_manager=self.topic_manager,
        )
        duration_ms = (time.perf_counter() - t0) * 1000.0

        # Timing test: delta preparation must finish well within 60s lifecycle (target < 500ms)
        self.assertTrue(duration_ms < 500.0)

        # Topic assignment: staged chunk assigned to topic_pay
        self.assertTrue(len(delta.new_memberships) >= 1)
        mem = delta.new_memberships[0]
        self.assertEqual(mem.chunk_id, staged_chunk.id)
        self.assertEqual(mem.topic_id, self.topic1.id)
        self.assertEqual(mem.method, "centroid")

        # Conflict detection: exclusive value conflict between rel_act_os and rel_staged_prop
        self.assertEqual(len(delta.new_conflicts), 1)
        conf = delta.new_conflicts[0]
        self.assertEqual(conf.kind, "exclusive_value")
        self.assertIn(staged_rel.id, [conf.left_relation_id, conf.right_relation_id])
        self.assertIn("rel_act_os", [conf.left_relation_id, conf.right_relation_id])

        # Handoff test: Person 1's repository publishes the delta
        initial_epoch = snapshot.epoch
        new_epoch = self.repo.publish(
            operation_id="op_edit_01",
            delta=delta,
            expected_epoch=initial_epoch,
        )
        self.assertEqual(new_epoch, initial_epoch + 1)
        # Verify repository now contains the published conflict and memberships
        published_snapshot = self.repo.get_snapshot(self.ws_id)
        self.assertEqual(len(published_snapshot.conflicts), 1)
        self.assertTrue(any(m.chunk_id == staged_chunk.id for m in published_snapshot.topic_memberships))


if __name__ == "__main__":
    unittest.main()
