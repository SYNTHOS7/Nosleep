"""Lifecycle service managing add, edit, delete, idempotency, and 60-second updates."""

from __future__ import annotations

import os
import time
import hashlib
from typing import Dict, Optional

from backend.contracts.models import (
    Document,
    ExtractionBatch,
    Operation,
    OperationStatus,
    OperationType,
)
from backend.ingestion.operations import get_operation_manager
from backend.ingestion.pipeline import build_batch
from backend.storage.graph_store import get_graph_store
from backend.storage.vector_store import get_vector_store


class StaleRevisionError(Exception):
    """Raised when an edit specifies an expected_revision_id that does not match current state."""
    pass


class LifecycleService:
    """Orchestrates end-to-end document lifecycle with idempotent ingestion and durable checkpointing."""

    def __init__(self):
        self.op_manager = get_operation_manager()
        self.graph_store = get_graph_store()
        self.vector_store = get_vector_store()
        self.persistence = getattr(self.vector_store, "persistence", None)
        if self.persistence:
            for batch in self.persistence.load_batches():
                self.graph_store.publish_batch(batch)
                self.vector_store.cache_vectors(batch.workspace_id, batch.vectors)
            if hasattr(self.persistence, "load_topics"):
                for workspace, topics, assignments in self.persistence.load_topics():
                    self.graph_store.replace_topics(workspace, topics, assignments)

    def process_operation(self, op: Operation) -> Operation:
        """
        Executes the operation through parsing, chunking, extraction, embedding,
        graph publication, vector indexing, and checkpointing.
        """
        start_time = time.time()
        ws = op.workspace_id
        doc_id = op.document_id

        try:
            if op.operation_type == OperationType.DELETE:
                chunk_ids = [cid for cid, ch in self.graph_store.chunks.get(ws, {}).items() if ch.document_id == doc_id]
                if self.persistence:
                    self.persistence.delete_document(ws, doc_id)
                # 1. Clean up from GraphStore
                self.graph_store.delete_document(ws, doc_id)
                # 2. Clean up from VectorStore
                if self.persistence:
                    for cid in chunk_ids:
                        self.vector_store._vectors.get(ws, {}).pop(cid, None)
                else:
                    self.vector_store.remove_chunks(ws, chunk_ids)

                self.save_topics(ws)
                self.sync_graph(ws)

                op.status = OperationStatus.COMPLETED
                op.ready_at = time.time()
                op.stage_timings["total"] = op.ready_at - start_time
                self.op_manager.save_checkpoint(op)
                self.op_manager.release_lock(doc_id)
                return op

            # Handle ADD or EDIT
            source_file = op.source_ref
            if not source_file or not os.path.exists(source_file):
                raise FileNotFoundError(f"Source file {source_file} not found.")

            # Compute content hash for idempotency check
            with open(source_file, "rb") as f:
                content_bytes = f.read()
            content_hash = hashlib.sha256(content_bytes).hexdigest()

            # Idempotency check on ADD:
            if op.operation_type == OperationType.ADD:
                existing_doc = self.graph_store.get_document_by_hash(ws, content_hash)
                if existing_doc:
                    # Document already ingested with same content hash - idempotent skip duplicate creation
                    op.status = OperationStatus.COMPLETED
                    op.ready_at = time.time()
                    op.metrics["idempotent_duplicate"] = True
                    op.metrics["existing_document_id"] = existing_doc.id
                    op.stage_timings["total"] = op.ready_at - start_time
                    self.op_manager.save_checkpoint(op)
                    self.op_manager.release_lock(doc_id)
                    return op

            # If EDIT: verify document exists and clean previous revision records
            old_chunk_ids = []
            if op.operation_type == OperationType.EDIT:
                old_doc = self.graph_store.get_document(ws, doc_id)
                if old_doc:
                    # Remove old revision state while preserving shared entities
                    old_chunk_ids = [cid for cid, ch in self.graph_store.chunks.get(ws, {}).items() if ch.document_id == doc_id]

            # Build extraction batch via Person 2 pipeline
            batch: ExtractionBatch = build_batch(op)

            if self.persistence:
                self.persistence.publish(batch)
            if op.operation_type == OperationType.EDIT:
                self.graph_store.delete_document(ws, doc_id)
                if not self.persistence:
                    self.vector_store.remove_chunks(ws, old_chunk_ids)
                else:
                    for cid in old_chunk_ids:
                        self.vector_store._vectors.get(ws, {}).pop(cid, None)

            # Publish into GraphStore
            self.graph_store.publish_batch(batch)

            # Publish into VectorStore
            if self.persistence:
                self.vector_store.cache_vectors(ws, batch.vectors)
            else:
                self.vector_store.upsert_vectors(ws, batch.vectors)

            # Persist into Chroma persistent database
            try:
                from backend.storage.db_manager import get_db_manager
                get_db_manager().sync_vectors_to_chroma(ws, batch.vectors)
            except Exception:
                pass

            # Phase 3 Incremental centroid topic assignment (if topics exist in workspace)
            ws_topics = self.graph_store.topics.get(ws, {})
            if ws_topics:
                try:
                    import numpy as np
                    from backend.contracts.models import TopicAssignment

                    # Precompute normalized centroids once per topic
                    topic_centroids = {}
                    for t_id in ws_topics:
                        top_cids = self.graph_store.get_topic_chunks(ws, t_id)
                        top_vecs = [
                            self.vector_store._vectors.get(ws, {}).get(cid)
                            for cid in top_cids
                            if cid in self.vector_store._vectors.get(ws, {})
                        ]
                        if top_vecs:
                            cent = np.mean(top_vecs, axis=0)
                            cent_norm = np.linalg.norm(cent)
                            if cent_norm > 0:
                                topic_centroids[t_id] = cent / cent_norm

                    for ch in batch.chunks:
                        ch_vec = batch.vectors.get(ch.id)
                        if ch_vec and topic_centroids:
                            ch_arr = np.array(ch_vec)
                            ch_norm = np.linalg.norm(ch_arr)
                            if ch_norm > 0:
                                ch_unit = ch_arr / ch_norm
                                best_topic_id = None
                                best_sim = -1.0
                                for t_id, cent_unit in topic_centroids.items():
                                    sim = float(np.dot(ch_unit, cent_unit))
                                    if sim > best_sim:
                                        best_sim = sim
                                        best_topic_id = t_id
                                if best_topic_id and best_sim > 0.4:
                                    self.graph_store.assign_topic(
                                        ws,
                                        TopicAssignment(topic_id=best_topic_id, chunk_id=ch.id, confidence=round(best_sim, 3)),
                                    )
                except Exception:
                    pass

            self.save_topics(ws)
            self.sync_graph(ws)
            # Mark completed
            op.status = OperationStatus.COMPLETED
            op.ready_at = time.time()
            op.stage_timings["total"] = op.ready_at - start_time
            op.metrics.update({
                "chunk_count": len(batch.chunks),
                "entity_count": len(batch.aggregated_entities),
                "relation_count": len(batch.aggregated_relations),
                "value_count": len(batch.aggregated_values),
                "vector_count": len(batch.vectors),
            })
            self.op_manager.save_checkpoint(op, batch=batch)
            self.op_manager.release_lock(doc_id)
            return op

        except Exception as e:
            op.status = OperationStatus.FAILED
            op.error_message = str(e)
            op.ready_at = time.time()
            op.stage_timings["total"] = op.ready_at - start_time
            try:
                self.op_manager.save_checkpoint(op)
            finally:
                self.op_manager.release_lock(doc_id)
            raise

    def save_topics(self, workspace):
        if self.persistence and hasattr(self.persistence, "save_topics"):
            self.persistence.save_topics(workspace, self.graph_store.get_topics(workspace),
                                         self.graph_store.topic_assignments.get(workspace, []))

    def sync_graph(self, workspace):
        from backend.storage.db_manager import get_db_manager
        get_db_manager().sync_graph(self.graph_store, workspace)

    def resume_operation(self, operation_id):
        op = self.op_manager.load_checkpoint(operation_id)
        if not op:
            return
        current = self.graph_store.get_document(op.workspace_id, op.document_id)
        if op.operation_type == OperationType.EDIT and current and current.revision >= op.new_revision:
            # The document commit may have succeeded before its completion checkpoint.
            op.status = OperationStatus.COMPLETED
            op.metrics["recovered_committed_revision"] = True
            self.op_manager.save_checkpoint(op)
            self.op_manager.release_lock(op.document_id)
            return
        self.process_operation(op)


_default_lifecycle_service = LifecycleService()


def get_lifecycle_service() -> LifecycleService:
    return _default_lifecycle_service
