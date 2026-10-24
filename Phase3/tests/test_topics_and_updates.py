"""
Tests for topic discovery, representative evidence selection, and Phase 2 incremental centroid updates.
"""

import unittest
from datetime import datetime, timezone
import numpy as np

from backend.contracts.models import Chunk, Document, Location, Revision, Topic
from backend.topics.manager import TopicManager
from backend.adapters.llm import GroundedLLMAdapter
from backend.storage.interface import InMemoryStorageRepository


class TestTopicsAndUpdates(unittest.TestCase):
    def setUp(self):
        self.workspace_id = "ws_test_topics"
        self.repo = InMemoryStorageRepository(self.workspace_id)
        self.manager = TopicManager(llm_adapter=GroundedLLMAdapter())

        # Create sample document and revision
        self.doc = Document(
            id="doc_01",
            workspace_id=self.workspace_id,
            filename="arch.txt",
            source_type="txt",
            active_revision_id="rev_01",
        )
        self.repo.add_document(self.doc)

        self.rev = Revision(
            id="rev_01",
            document_id=self.doc.id,
            content_hash="hash_rev_01",
            parser_version="p1",
            chunker_version="c1",
            extractor_version="e1",
            embedding_version="multilingual-embed-v1",
            state="published",
            source_ref="s3://bucket/arch.txt",
        )
        self.repo.add_revision(self.rev)

        # Create active chunks in 2 distinct clusters
        self.chunks = []
        self.embeddings = {}

        # Cluster A: Authentication chunks
        for i in range(3):
            c = Chunk(
                id=f"chunk_auth_{i}",
                workspace_id=self.workspace_id,
                document_id=self.doc.id,
                revision_id=self.rev.id,
                index=i,
                text=f"Authentication service token validation and OAuth policy details part {i}.",
                text_hash=f"hash_auth_{i}",
                location=Location(start_offset=0, end_offset=50),
            )
            vec = [1.0 if j < 32 else 0.0 for j in range(64)]
            # Add slight variance
            vec[i] += 0.1
            norm = float(np.linalg.norm(vec))
            self.chunks.append(c)
            self.embeddings[c.id] = [x / norm for x in vec]
            self.repo.add_chunk(c, self.embeddings[c.id])

        # Cluster B: Database chunks
        for i in range(3):
            c = Chunk(
                id=f"chunk_db_{i}",
                workspace_id=self.workspace_id,
                document_id=self.doc.id,
                revision_id=self.rev.id,
                index=i + 3,
                text=f"Postgres database cluster replication and persistence configuration part {i}.",
                text_hash=f"hash_db_{i}",
                location=Location(start_offset=0, end_offset=50),
            )
            vec = [0.0 if j < 32 else 1.0 for j in range(64)]
            vec[32 + i] += 0.1
            norm = float(np.linalg.norm(vec))
            self.chunks.append(c)
            self.embeddings[c.id] = [x / norm for x in vec]
            self.repo.add_chunk(c, self.embeddings[c.id])

    def test_topic_discovery_and_labeling(self):
        topics, memberships = self.manager.discover_topics_from_corpus(
            workspace_id=self.workspace_id,
            chunks=self.chunks,
            embeddings=self.embeddings,
            method="kmeans",
            k_clusters=2,
        )

        self.assertEqual(len(topics), 2)
        self.assertEqual(len(memberships), 6)

        for topic in topics:
            self.assertEqual(topic.workspace_id, self.workspace_id)
            self.assertTrue(topic.label)
            self.assertTrue(topic.description)
            self.assertTrue(topic.representative_chunk_ids)
            # Verify representative chunks actually exist in the input chunks
            chunk_ids = {c.id for c in self.chunks}
            for rep_id in topic.representative_chunk_ids:
                self.assertIn(rep_id, chunk_ids)

    def test_unclustered_chunks_remain_searchable(self):
        # Add an outlier chunk
        outlier = Chunk(
            id="chunk_outlier",
            workspace_id=self.workspace_id,
            document_id=self.doc.id,
            revision_id=self.rev.id,
            index=10,
            text="Unrelated miscellaneous notes on office cafeteria hours.",
            text_hash="hash_outlier",
            location=Location(start_offset=0, end_offset=40),
        )
        self.repo.add_chunk(outlier, [0.0] * 64)

        snapshot = self.repo.get_snapshot(self.workspace_id)
        active_chunks = snapshot.get_active_chunks()
        active_ids = {c.id for c in active_chunks}
        self.assertIn("chunk_outlier", active_ids)

    def test_phase2_incremental_centroid_update(self):
        # First discover initial topics
        topics, _ = self.manager.discover_topics_from_corpus(
            workspace_id=self.workspace_id,
            chunks=self.chunks,
            embeddings=self.embeddings,
            method="kmeans",
            k_clusters=2,
        )

        # Stage a new revision chunk belonging to Authentication
        new_auth_chunk = Chunk(
            id="chunk_new_auth",
            workspace_id=self.workspace_id,
            document_id=self.doc.id,
            revision_id="rev_02",
            index=0,
            text="Authentication service updated with MFA tokens.",
            text_hash="hash_new_auth",
            location=Location(start_offset=0, end_offset=40),
        )
        # Vector very close to Cluster A
        vec = [1.0 if j < 32 else 0.0 for j in range(64)]
        norm = float(np.linalg.norm(vec))
        new_emb = {new_auth_chunk.id: [x / norm for x in vec]}

        # Perform incremental centroid assignment
        memberships, updated_topics = self.manager.assign_staged_chunks_to_topics(
            staged_chunks=[new_auth_chunk],
            staged_embeddings=new_emb,
            existing_topics=topics,
        )

        self.assertTrue(len(memberships) >= 1)
        mem = memberships[0]
        self.assertEqual(mem.chunk_id, new_auth_chunk.id)
        self.assertEqual(mem.method, "centroid")
        self.assertTrue(mem.score > 0.7)

        # Check targeted refresh if central evidence was added
        if updated_topics:
            self.assertEqual(updated_topics[0].summary_status, "fresh")
            self.assertIn(new_auth_chunk.id, updated_topics[0].representative_chunk_ids)


if __name__ == "__main__":
    unittest.main()
