"""Neo4j AuraDB graph repository conforming to Task 1 GraphRepository protocol."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Sequence

from neo4j import Driver, GraphDatabase

from backend.contracts.ids import evidence_path_id
from backend.contracts.integration import (
    CorpusSnapshot,
    DerivedDelta,
    EvidencePackage,
    EvidencePath,
    EvidencePathStep,
    ExtractionBatch,
    PublishReceipt,
    revalidate_extraction_batch,
    validate_evidence_path_provenance,
)
from backend.contracts.models import (
    Chunk,
    ChunkLocation,
    Conflict,
    Document,
    Entity,
    EntityMention,
    Evidence,
    Operation,
    OperationKind,
    OperationState,
    Relation,
    Revision,
    RevisionState,
    Topic,
    TopicMembership,
    Value,
)
from .interfaces import (
    EpochConflict,
    OperationConflict,
    StorageError,
    WorkspaceViolation,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


ALLOWED_RELATION_TYPES = {
    "SUPPORTS", "CONTRADICTS", "RELATED_TO", "MENTIONS", "LOCATED_IN", "PART_OF",
    "IS_A", "HAS_A", "WORKS_AT", "FOUNDED_BY", "AFFILIATED_WITH", "PRODUCES",
    "OWNS", "DEPENDS_ON", "USES", "IMPLEMENTS", "REGULATES", "CAUSES", "INTERACTS_WITH",
}


def _safe_relation_type(predicate: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9_]", "_", predicate.strip().upper())
    if cleaned in ALLOWED_RELATION_TYPES:
        return cleaned
    return "RELATED_TO"


class Neo4jGraphRepository:
    """Production Neo4j AuraDB implementation of GraphRepository."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        driver: Driver | None = None,
    ) -> None:
        if driver is not None:
            self._driver = driver
        else:
            final_uri = uri or os.environ.get("NEO4J_URI", "neo4j+s://aura.example.databases.neo4j.io")
            final_user = user or os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER", "neo4j")
            final_password = password or os.environ.get("NEO4J_PASSWORD", "")
            self._driver = GraphDatabase.driver(final_uri, auth=(final_user, final_password))
        self._database = database or os.environ.get("NEO4J_DATABASE", "neo4j")

    def close(self) -> None:
        self._driver.close()

    def ensure_schema(self) -> None:
        """Create uniqueness constraints and full-text indexes for Task 1 entities."""
        queries = [
            "CREATE CONSTRAINT c_doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT c_rev_id IF NOT EXISTS FOR (r:Revision) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT c_chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT c_entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT c_value_id IF NOT EXISTS FOR (v:Value) REQUIRE v.id IS UNIQUE",
            "CREATE CONSTRAINT c_topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE",
            "CREATE CONSTRAINT c_conflict_id IF NOT EXISTS FOR (cf:Conflict) REQUIRE cf.id IS UNIQUE",
            "CREATE CONSTRAINT c_op_id IF NOT EXISTS FOR (o:Operation) REQUIRE o.id IS UNIQUE",
            "CREATE CONSTRAINT c_ws_id IF NOT EXISTS FOR (w:Workspace) REQUIRE w.id IS UNIQUE",
        ]
        with self._driver.session(database=self._database) as session:
            for q in queries:
                try:
                    session.run(q).consume()
                except Exception:
                    pass

    def register_document(self, document: Document) -> None:
        with self._driver.session(database=self._database) as session:
            def _tx(tx: Any) -> None:
                existing = tx.run(
                    "MATCH (d:Document {id: $id}) RETURN d.workspace_id AS ws",
                    id=document.id,
                ).single()
                if existing and existing["ws"] != document.workspace_id:
                    raise WorkspaceViolation("document ID already belongs to another workspace")

                tx.run(
                    """
                    MERGE (w:Workspace {id: $ws_id})
                    ON CREATE SET w.epoch = 0
                    MERGE (d:Document {id: $id})
                    ON CREATE SET
                        d.workspace_id = $ws_id,
                        d.filename = $filename,
                        d.source_type = $source_type,
                        d.active_revision_id = $active_revision_id,
                        d.deleted = $deleted,
                        d.created_at = $created_at
                    ON MATCH SET
                        d.filename = $filename,
                        d.source_type = $source_type,
                        d.deleted = $deleted
                    """,
                    id=document.id,
                    ws_id=document.workspace_id,
                    filename=document.filename,
                    source_type=document.source_type.value,
                    active_revision_id=document.active_revision_id,
                    deleted=document.deleted,
                    created_at=document.created_at.isoformat(),
                ).consume()

            session.execute_write(_tx)

    def create_operation(self, operation: Operation) -> None:
        with self._driver.session(database=self._database) as session:
            def _tx(tx: Any) -> None:
                existing = tx.run(
                    "MATCH (o:Operation {id: $id}) RETURN o.json AS json",
                    id=operation.id,
                ).single()
                if existing:
                    existing_op = Operation.model_validate_json(existing["json"])
                    if existing_op != operation:
                        raise OperationConflict("operation ID is not idempotent")
                    return

                doc = tx.run(
                    "MATCH (d:Document {id: $doc_id}) RETURN d.workspace_id AS ws",
                    doc_id=operation.document_id,
                ).single()
                if doc is None or doc["ws"] != operation.workspace_id:
                    raise WorkspaceViolation("operation document must exist in its workspace")

                tx.run(
                    """
                    MERGE (w:Workspace {id: $ws_id})
                    ON CREATE SET w.epoch = 0
                    CREATE (o:Operation {
                        id: $id,
                        workspace_id: $ws_id,
                        document_id: $doc_id,
                        state: $state,
                        stage: $stage,
                        json: $json
                    })
                    """,
                    id=operation.id,
                    ws_id=operation.workspace_id,
                    doc_id=operation.document_id,
                    state=operation.state.value,
                    stage=operation.stage,
                    json=operation.model_dump_json(),
                ).consume()

            session.execute_write(_tx)

    def get_operation(self, operation_id: str, workspace_id: str) -> Operation:
        with self._driver.session(database=self._database) as session:
            rec = session.run(
                "MATCH (o:Operation {id: $id}) RETURN o.workspace_id AS ws, o.json AS json",
                id=operation_id,
            ).single()
            if rec is None:
                raise StorageError("operation not found")
            if rec["ws"] != workspace_id:
                raise WorkspaceViolation("operation does not belong to workspace")
            return Operation.model_validate_json(rec["json"])

    def claim_operation(self, operation_id: str, workspace_id: str) -> Operation:
        with self._driver.session(database=self._database) as session:
            def _tx(tx: Any) -> Operation:
                rec = tx.run(
                    "MATCH (o:Operation {id: $id}) RETURN o.workspace_id AS ws, o.json AS json",
                    id=operation_id,
                ).single()
                if rec is None:
                    raise StorageError("operation not found")
                if rec["ws"] != workspace_id:
                    raise WorkspaceViolation("operation does not belong to workspace")
                op = Operation.model_validate_json(rec["json"])
                if op.state is OperationState.QUEUED:
                    updated = op.model_copy(update={"state": OperationState.RUNNING, "stage": "running"})
                    tx.run(
                        "MATCH (o:Operation {id: $id}) SET o.state = $state, o.stage = $stage, o.json = $json",
                        id=operation_id,
                        state=updated.state.value,
                        stage=updated.stage,
                        json=updated.model_dump_json(),
                    ).consume()
                    return updated
                if op.state is OperationState.RUNNING:
                    return op
                raise OperationConflict("only queued or running operations can be claimed")

            return session.execute_write(_tx)

    def stage_revision(self, operation_id: str, revision: Revision) -> None:
        with self._driver.session(database=self._database) as session:
            def _tx(tx: Any) -> None:
                rec = tx.run(
                    "MATCH (o:Operation {id: $id}) RETURN o.json AS json",
                    id=operation_id,
                ).single()
                if rec is None:
                    raise StorageError("operation not found")
                operation = Operation.model_validate_json(rec["json"])
                if operation.kind is OperationKind.DELETE:
                    raise OperationConflict("delete operations cannot stage revisions")
                if operation.document_id != revision.document_id or operation.new_revision_id != revision.id:
                    raise OperationConflict("revision must match operation document and new_revision_id")
                if revision.state is not RevisionState.STAGED:
                    raise OperationConflict("only staged revisions may be registered")

                rev_rec = tx.run(
                    "MATCH (r:Revision {id: $id}) RETURN r.json AS json",
                    id=revision.id,
                ).single()
                if rev_rec:
                    existing = Revision.model_validate_json(rev_rec["json"])
                    if existing != revision:
                        raise OperationConflict("revision ID is not idempotent")
                    return

                tx.run(
                    """
                    MERGE (r:Revision {id: $id})
                    ON CREATE SET
                        r.document_id = $doc_id,
                        r.state = $state,
                        r.json = $json
                    WITH r
                    MATCH (d:Document {id: $doc_id})
                    MERGE (d)-[:HAS_REVISION]->(r)
                    """,
                    id=revision.id,
                    doc_id=revision.document_id,
                    state=revision.state.value,
                    json=revision.model_dump_json(),
                ).consume()

            session.execute_write(_tx)

    def stage_batch(self, operation_id: str, batch: ExtractionBatch) -> None:
        checked = revalidate_extraction_batch(batch)
        with self._driver.session(database=self._database) as session:
            def _tx(tx: Any) -> None:
                op_rec = tx.run(
                    "MATCH (o:Operation {id: $id}) RETURN o.json AS json",
                    id=operation_id,
                ).single()
                if op_rec is None:
                    raise StorageError("operation not found")
                operation = Operation.model_validate_json(op_rec["json"])
                if operation.kind is OperationKind.DELETE:
                    raise OperationConflict("delete operations cannot stage extraction batches")
                if (operation.workspace_id, operation.document_id, operation.new_revision_id) != (
                    checked.workspace_id, checked.document_id, checked.revision_id
                ):
                    raise WorkspaceViolation("batch must match operation workspace, document, and revision")

                rev_rec = tx.run(
                    "MATCH (r:Revision {id: $id}) RETURN r.state AS state",
                    id=checked.revision_id,
                ).single()
                if rev_rec is None or rev_rec["state"] != RevisionState.STAGED.value:
                    raise OperationConflict("batch requires an existing staged revision")

                batch_rec = tx.run(
                    "MATCH (b:StagedBatch {operation_id: $op_id}) RETURN b.json AS json",
                    op_id=operation_id,
                ).single()
                if batch_rec:
                    existing = ExtractionBatch.model_validate_json(batch_rec["json"])
                    if existing != checked:
                        raise OperationConflict("operation batch is not idempotent")
                    return

                # Save StagedBatch
                tx.run(
                    """
                    MERGE (b:StagedBatch {operation_id: $op_id})
                    SET b.workspace_id = $ws_id, b.revision_id = $rev_id, b.json = $json
                    """,
                    op_id=operation_id,
                    ws_id=checked.workspace_id,
                    rev_id=checked.revision_id,
                    json=checked.model_dump_json(),
                ).consume()

                # Ingest chunks
                for chunk in checked.chunks:
                    tx.run(
                        """
                        MERGE (c:Chunk {id: $id})
                        SET c.workspace_id = $ws_id,
                            c.document_id = $doc_id,
                            c.revision_id = $rev_id,
                            c.index = $index,
                            c.text = $text,
                            c.text_hash = $text_hash,
                            c.start_offset = $start,
                            c.end_offset = $end,
                            c.json = $json
                        WITH c
                        MATCH (r:Revision {id: $rev_id})
                        MERGE (r)-[:CONTAINS_CHUNK]->(c)
                        """,
                        id=chunk.id,
                        ws_id=chunk.workspace_id,
                        doc_id=chunk.document_id,
                        rev_id=chunk.revision_id,
                        index=chunk.index,
                        text=chunk.text,
                        text_hash=chunk.text_hash,
                        start=chunk.location.start_offset,
                        end=chunk.location.end_offset,
                        json=chunk.model_dump_json(),
                    ).consume()

                # Ingest entities
                for entity in checked.entities:
                    tx.run(
                        """
                        MERGE (e:Entity {id: $id})
                        SET e.workspace_id = $ws_id,
                            e.name = $name,
                            e.normalized_name = $norm_name,
                            e.type = $type,
                            e.json = $json
                        """,
                        id=entity.id,
                        ws_id=entity.workspace_id,
                        name=entity.name,
                        norm_name=entity.normalized_name,
                        type=entity.type,
                        json=entity.model_dump_json(),
                    ).consume()

                # Ingest values
                for val in checked.values:
                    tx.run(
                        """
                        MERGE (v:Value {id: $id})
                        SET v.workspace_id = $ws_id,
                            v.kind = $kind,
                            v.lexical_value = $lex,
                            v.normalized_value = $norm,
                            v.unit = $unit,
                            v.json = $json
                        """,
                        id=val.id,
                        ws_id=val.workspace_id,
                        kind=val.kind.value,
                        lex=val.lexical_value,
                        norm=val.normalized_value,
                        unit=val.unit,
                        json=val.model_dump_json(),
                    ).consume()

                # Ingest entity mentions
                for mention in checked.entity_mentions:
                    tx.run(
                        """
                        MERGE (m:EntityMention {id: $id})
                        SET m.workspace_id = $ws_id,
                            m.document_id = $doc_id,
                            m.revision_id = $rev_id,
                            m.chunk_id = $chunk_id,
                            m.entity_id = $entity_id,
                            m.start = $start,
                            m.end = $end,
                            m.quote = $quote,
                            m.json = $json
                        WITH m
                        MATCH (c:Chunk {id: $chunk_id}), (e:Entity {id: $entity_id})
                        MERGE (c)-[:MENTIONS_ENTITY]->(m)
                        MERGE (m)-[:REFERS_TO]->(e)
                        """,
                        id=mention.id,
                        ws_id=mention.workspace_id,
                        doc_id=mention.document_id,
                        rev_id=mention.revision_id,
                        chunk_id=mention.chunk_id,
                        entity_id=mention.entity_id,
                        start=mention.start,
                        end=mention.end,
                        quote=mention.quote,
                        json=mention.model_dump_json(),
                    ).consume()

                # Ingest relations
                for rel in checked.relations:
                    rel_type = _safe_relation_type(rel.predicate)
                    dest_node = "Entity" if rel.object_entity_id else "Value"
                    dest_id = rel.object_entity_id or rel.object_value_id
                    query = f"""
                    MATCH (s:Entity {{id: $s_id}}), (o:{dest_node} {{id: $o_id}})
                    MERGE (s)-[r:{rel_type} {{id: $id}}]->(o)
                    SET r.workspace_id = $ws_id,
                        r.revision_id = $rev_id,
                        r.predicate = $predicate,
                        r.predicate_original = $predicate_original,
                        r.polarity = $polarity,
                        r.modality = $modality,
                        r.evidence_chunk_id = $evidence_chunk_id,
                        r.evidence_start = $evidence_start,
                        r.evidence_end = $evidence_end,
                        r.evidence_quote = $evidence_quote,
                        r.json = $json
                    """
                    tx.run(
                        query,
                        s_id=rel.subject_id,
                        o_id=dest_id,
                        id=rel.id,
                        ws_id=rel.workspace_id,
                        rev_id=rel.revision_id,
                        predicate=rel.predicate,
                        predicate_original=rel.predicate_original,
                        polarity=rel.polarity.value,
                        modality=rel.modality.value,
                        evidence_chunk_id=rel.evidence.chunk_id,
                        evidence_start=rel.evidence.start,
                        evidence_end=rel.evidence.end,
                        evidence_quote=rel.evidence.quote,
                        json=rel.model_dump_json(),
                    ).consume()

                updated_op = operation.model_copy(update={"stage": "graph_staged"})
                tx.run(
                    "MATCH (o:Operation {id: $id}) SET o.stage = 'graph_staged', o.json = $json",
                    id=operation_id,
                    json=updated_op.model_dump_json(),
                ).consume()

            session.execute_write(_tx)

    def get_staged_batch(self, operation_id: str, workspace_id: str) -> ExtractionBatch:
        self.get_operation(operation_id, workspace_id)
        with self._driver.session(database=self._database) as session:
            rec = session.run(
                "MATCH (b:StagedBatch {operation_id: $op_id}) RETURN b.json AS json",
                op_id=operation_id,
            ).single()
            if rec is None:
                raise StorageError("staged batch not found")
            return revalidate_extraction_batch(ExtractionBatch.model_validate_json(rec["json"]))

    def get_snapshot(self, workspace_id: str) -> CorpusSnapshot:
        with self._driver.session(database=self._database) as session:
            rec = session.run(
                """
                MERGE (w:Workspace {id: $ws_id})
                ON CREATE SET w.epoch = 0
                WITH w
                OPTIONAL MATCH (d:Document {workspace_id: $ws_id, deleted: false})
                WHERE d.active_revision_id IS NOT NULL
                RETURN w.epoch AS epoch, collect(DISTINCT d.active_revision_id) AS active_revs
                """,
                ws_id=workspace_id,
            ).single()
            epoch = rec["epoch"] if rec else 0
            active_revs = [r for r in rec["active_revs"] if r] if rec else []
            return CorpusSnapshot(
                workspace_id=workspace_id,
                epoch=epoch,
                active_revision_ids=sorted(active_revs),
                captured_at=_now(),
            )

    def publish(self, operation_id: str, delta: DerivedDelta, expected_epoch: int) -> PublishReceipt:
        with self._driver.session(database=self._database) as session:
            def _tx(tx: Any) -> PublishReceipt:
                op_rec = tx.run(
                    "MATCH (o:Operation {id: $id}) RETURN o.json AS json, o.published_receipt AS receipt",
                    id=operation_id,
                ).single()
                if op_rec is None:
                    raise StorageError("operation not found")
                if op_rec["receipt"]:
                    return PublishReceipt.model_validate_json(op_rec["receipt"])

                operation = Operation.model_validate_json(op_rec["json"])
                if delta.operation_id != operation_id:
                    raise OperationConflict("delta operation ID must match publication operation")

                ws_rec = tx.run(
                    """
                    MERGE (w:Workspace {id: $ws_id})
                    ON CREATE SET w.epoch = 0
                    WITH w
                    OPTIONAL MATCH (d:Document {workspace_id: $ws_id, deleted: false})
                    WHERE d.active_revision_id IS NOT NULL
                    RETURN w.epoch AS epoch, collect(DISTINCT d.active_revision_id) AS active_revs
                    """,
                    ws_id=operation.workspace_id,
                ).single()
                current_epoch = ws_rec["epoch"]
                current_active_revs = set(ws_rec["active_revs"])

                if expected_epoch != current_epoch or delta.snapshot.epoch != expected_epoch:
                    raise EpochConflict("expected epoch no longer matches authoritative graph state")

                doc_rec = tx.run(
                    "MATCH (d:Document {id: $doc_id}) RETURN d.active_revision_id AS active_rev, d.json AS json",
                    doc_id=operation.document_id,
                ).single()
                old_revision_id = doc_rec["active_rev"] if doc_rec else None

                if operation.expected_revision_id != old_revision_id:
                    raise OperationConflict("operation expected_revision_id does not match active document revision")

                if operation.kind is OperationKind.DELETE:
                    kind = "noop" if old_revision_id is None else "deletion"
                    new_revision_id = None
                    post_revision_ids = {r for r in current_active_revs if r != old_revision_id}
                else:
                    batch_rec = tx.run(
                        "MATCH (b:StagedBatch {operation_id: $op_id}) RETURN b.json AS json",
                        op_id=operation_id,
                    ).single()
                    rev_rec = tx.run(
                        "MATCH (r:Revision {id: $id}) RETURN r.state AS state, r.json AS json",
                        id=operation.new_revision_id or "",
                    ).single()
                    if batch_rec is None or rev_rec is None or rev_rec["state"] != RevisionState.STAGED.value:
                        raise OperationConflict("publication requires a staged graph batch and revision")
                    if delta.staged_revision_id not in {None, operation.new_revision_id}:
                        raise OperationConflict("delta staged revision does not match operation")
                    new_revision_id = operation.new_revision_id
                    kind = "initial" if old_revision_id is None else "replacement"
                    post_revision_ids = set(current_active_revs)
                    if old_revision_id:
                        post_revision_ids.discard(old_revision_id)
                    post_revision_ids.add(new_revision_id)

                # Validate conflicts
                if delta.snapshot.workspace_id != operation.workspace_id:
                    raise WorkspaceViolation("delta snapshot does not belong to operation workspace")

                active_rel_ids_res = tx.run(
                    """
                    MATCH ()-[r]->()
                    WHERE r.workspace_id = $ws_id AND r.revision_id IN $rev_ids
                    RETURN collect(DISTINCT r.id) AS ids
                    """,
                    ws_id=operation.workspace_id,
                    rev_ids=list(post_revision_ids),
                ).single()
                active_rel_ids = set(active_rel_ids_res["ids"] if active_rel_ids_res else [])

                active_chunks_res = tx.run(
                    """
                    MATCH (c:Chunk {workspace_id: $ws_id})
                    WHERE c.revision_id IN $rev_ids
                    RETURN collect(DISTINCT c.id) AS ids
                    """,
                    ws_id=operation.workspace_id,
                    rev_ids=list(post_revision_ids),
                ).single()
                active_chunk_ids = set(active_chunks_res["ids"] if active_chunks_res else [])

                for conflict in delta.conflicts_to_upsert:
                    if {conflict.left_relation_id, conflict.right_relation_id}.difference(active_rel_ids):
                        raise StorageError("conflict must reference relations active after publication")
                    if not set(conflict.evidence_chunk_ids).issubset(active_chunk_ids):
                        raise StorageError("conflict must retain active source evidence")

                for cid in delta.conflict_ids_to_retire:
                    cf_rec = tx.run("MATCH (cf:Conflict {id: $id}) RETURN cf.json AS json", id=cid).single()
                    if cf_rec:
                        cf = Conflict.model_validate_json(cf_rec["json"])
                        if {cf.left_relation_id, cf.right_relation_id}.issubset(active_rel_ids):
                            raise StorageError("cannot retire a conflict still supported by active relations")

                # Apply document active revision update
                if operation.kind is OperationKind.DELETE:
                    tx.run(
                        "MATCH (d:Document {id: $doc_id}) SET d.active_revision_id = null, d.deleted = true",
                        doc_id=operation.document_id,
                    ).consume()
                else:
                    tx.run(
                        """
                        MATCH (d:Document {id: $doc_id})
                        SET d.active_revision_id = $new_rev, d.deleted = false
                        WITH d
                        MATCH (r:Revision {id: $new_rev})
                        SET r.state = 'published'
                        """,
                        doc_id=operation.document_id,
                        new_rev=new_revision_id,
                    ).consume()

                if old_revision_id:
                    tx.run(
                        "MATCH (r:Revision {id: $old_rev}) SET r.state = 'retired'",
                        old_rev=old_revision_id,
                    ).consume()

                # Upsert Topics
                for topic in delta.topics_to_upsert:
                    tx.run(
                        """
                        MERGE (t:Topic {id: $id})
                        SET t.workspace_id = $ws_id,
                            t.label = $label,
                            t.description = $desc,
                            t.active = $active,
                            t.json = $json
                        """,
                        id=topic.id,
                        ws_id=topic.workspace_id,
                        label=topic.label,
                        desc=topic.description,
                        active=topic.active,
                        json=topic.model_dump_json(),
                    ).consume()

                # Update Topic Memberships
                if old_revision_id:
                    tx.run(
                        "MATCH ()-[m:HAS_MEMBER]->() WHERE m.revision_id = $old_rev DELETE m",
                        old_rev=old_revision_id,
                    ).consume()

                for mem in delta.topic_memberships_to_upsert:
                    tx.run(
                        """
                        MATCH (t:Topic {id: $tid}), (c:Chunk {id: $cid})
                        MERGE (t)-[m:HAS_MEMBER {revision_id: $rev_id}]->(c)
                        SET m.score = $score, m.method = $method, m.json = $json
                        """,
                        tid=mem.topic_id,
                        cid=mem.chunk_id,
                        rev_id=mem.revision_id,
                        score=mem.score,
                        method=mem.method.value,
                        json=mem.model_dump_json(),
                    ).consume()

                # Upsert Conflicts
                for conf in delta.conflicts_to_upsert:
                    tx.run(
                        """
                        MERGE (cf:Conflict {id: $id})
                        SET cf.workspace_id = $ws_id,
                            cf.left_relation_id = $left,
                            cf.right_relation_id = $right,
                            cf.kind = $kind,
                            cf.state = $state,
                            cf.json = $json
                        """,
                        id=conf.id,
                        ws_id=conf.workspace_id,
                        left=conf.left_relation_id,
                        right=conf.right_relation_id,
                        kind=conf.kind.value,
                        state=conf.state.value,
                        json=conf.model_dump_json(),
                    ).consume()

                for cid in delta.conflict_ids_to_retire:
                    tx.run("MATCH (cf:Conflict {id: $id}) DETACH DELETE cf", id=cid).consume()

                resulting_epoch = current_epoch if kind == "noop" else current_epoch + 1
                if resulting_epoch != current_epoch:
                    tx.run(
                        "MATCH (w:Workspace {id: $ws_id}) SET w.epoch = $epoch",
                        ws_id=operation.workspace_id,
                        epoch=resulting_epoch,
                    ).consume()

                now_ts = _now()
                receipt = PublishReceipt(
                    operation_id=operation.id,
                    workspace_id=operation.workspace_id,
                    document_id=operation.document_id,
                    publication_kind=kind,
                    previous_epoch=current_epoch,
                    resulting_epoch=resulting_epoch,
                    previous_active_revision_id=old_revision_id,
                    active_revision_id=new_revision_id,
                    neo4j_publication_applied=kind != "noop",
                    vectors_verified_before_publication=True if kind in {"initial", "replacement"} else None,
                    post_publication_cleanup_required=kind in {"replacement", "deletion"},
                    read_probe_required=kind != "noop",
                    published_at=now_ts,
                )

                updated_op = operation.model_copy(
                    update={
                        "state": OperationState.RUNNING,
                        "stage": "published_cleanup_pending",
                        "visible_at": now_ts,
                        "checkpoint": {"published": True, "receipt": receipt.model_dump(mode="json")},
                    }
                )
                tx.run(
                    """
                    MATCH (o:Operation {id: $id})
                    SET o.state = 'running',
                        o.stage = 'published_cleanup_pending',
                        o.published_receipt = $receipt,
                        o.json = $json
                    """,
                    id=operation_id,
                    receipt=receipt.model_dump_json(),
                    json=updated_op.model_dump_json(),
                ).consume()

                return receipt

            return session.execute_write(_tx)

    def cleanup(self, operation_id: str, workspace_id: str) -> None:
        with self._driver.session(database=self._database) as session:
            def _tx(tx: Any) -> None:
                op_rec = tx.run(
                    "MATCH (o:Operation {id: $id}) RETURN o.workspace_id AS ws, o.published_receipt AS receipt, o.json AS json",
                    id=operation_id,
                ).single()
                if op_rec is None:
                    raise StorageError("operation not found")
                if op_rec["ws"] != workspace_id:
                    raise WorkspaceViolation("operation does not belong to workspace")
                if not op_rec["receipt"]:
                    raise OperationConflict("cleanup requires published operation")

                operation = Operation.model_validate_json(op_rec["json"])

                # Find retired revisions for this document
                retired_res = tx.run(
                    """
                    MATCH (d:Document {id: $doc_id})-[:HAS_REVISION]->(r:Revision)
                    WHERE r.state = 'retired'
                    RETURN collect(r.id) AS rev_ids
                    """,
                    doc_id=operation.document_id,
                ).single()
                retired_revs = set(retired_res["rev_ids"] if retired_res else [])

                if retired_revs:
                    # Delete chunks, mentions, source relations belonging to retired revisions
                    tx.run(
                        """
                        MATCH (c:Chunk) WHERE c.revision_id IN $rev_ids
                        DETACH DELETE c
                        """,
                        rev_ids=list(retired_revs),
                    ).consume()
                    tx.run(
                        """
                        MATCH (m:EntityMention) WHERE m.revision_id IN $rev_ids
                        DETACH DELETE m
                        """,
                        rev_ids=list(retired_revs),
                    ).consume()
                    tx.run(
                        """
                        MATCH ()-[r]->() WHERE r.revision_id IN $rev_ids
                        DELETE r
                        """,
                        rev_ids=list(retired_revs),
                    ).consume()
                    tx.run(
                        """
                        MATCH ()-[m:HAS_MEMBER]->() WHERE m.revision_id IN $rev_ids
                        DELETE m
                        """,
                        rev_ids=list(retired_revs),
                    ).consume()

                # Cleanup conflicts whose relations are no longer both active
                tx.run(
                    """
                    MATCH (cf:Conflict {workspace_id: $ws_id})
                    WHERE NOT EXISTS {
                        MATCH ()-[r1 {id: cf.left_relation_id}]->(), ()-[r2 {id: cf.right_relation_id}]->()
                    }
                    DETACH DELETE cf
                    """,
                    ws_id=workspace_id,
                ).consume()

                updated_op = operation.model_copy(update={"stage": "graph_cleanup_complete"})
                tx.run(
                    "MATCH (o:Operation {id: $id}) SET o.stage = 'graph_cleanup_complete', o.json = $json",
                    id=operation_id,
                    json=updated_op.model_dump_json(),
                ).consume()

            session.execute_write(_tx)

    def mark_cleanup_pending(self, operation_id: str, workspace_id: str, error: str) -> None:
        with self._driver.session(database=self._database) as session:
            def _tx(tx: Any) -> None:
                op_rec = tx.run(
                    "MATCH (o:Operation {id: $id}) RETURN o.workspace_id AS ws, o.json AS json",
                    id=operation_id,
                ).single()
                if op_rec is None:
                    raise StorageError("operation not found")
                if op_rec["ws"] != workspace_id:
                    raise WorkspaceViolation("operation does not belong to workspace")
                op = Operation.model_validate_json(op_rec["json"])
                updated = op.model_copy(
                    update={
                        "state": OperationState.RUNNING,
                        "stage": "cleanup_pending",
                        "errors": [*op.errors, error],
                        "checkpoint": {**op.checkpoint, "cleanup_pending": True},
                    }
                )
                tx.run(
                    "MATCH (o:Operation {id: $id}) SET o.state = 'running', o.stage = 'cleanup_pending', o.json = $json",
                    id=operation_id,
                    json=updated.model_dump_json(),
                ).consume()

            session.execute_write(_tx)

    def mark_ready_after_probe(self, operation_id: str, workspace_id: str) -> None:
        with self._driver.session(database=self._database) as session:
            def _tx(tx: Any) -> None:
                op_rec = tx.run(
                    "MATCH (o:Operation {id: $id}) RETURN o.workspace_id AS ws, o.published_receipt AS receipt, o.json AS json",
                    id=operation_id,
                ).single()
                if op_rec is None:
                    raise StorageError("operation not found")
                if op_rec["ws"] != workspace_id:
                    raise WorkspaceViolation("operation does not belong to workspace")
                if not op_rec["receipt"]:
                    raise OperationConflict("only published operations can be marked ready")
                op = Operation.model_validate_json(op_rec["json"])
                updated = op.model_copy(
                    update={
                        "state": OperationState.READY,
                        "stage": "ready",
                        "finished_at": _now(),
                        "checkpoint": {**op.checkpoint, "cleanup_pending": False},
                    }
                )
                tx.run(
                    "MATCH (o:Operation {id: $id}) SET o.state = 'ready', o.stage = 'ready', o.json = $json",
                    id=operation_id,
                    json=updated.model_dump_json(),
                ).consume()

            session.execute_write(_tx)

    def _require_current_snapshot(self, snapshot: CorpusSnapshot) -> None:
        current = self.get_snapshot(snapshot.workspace_id)
        if current.epoch != snapshot.epoch or current.active_revision_ids != snapshot.active_revision_ids:
            raise EpochConflict("snapshot changed; caller must retry")

    def active_chunk_ids(self, snapshot: CorpusSnapshot) -> list[str]:
        self._require_current_snapshot(snapshot)
        if not snapshot.active_revision_ids:
            return []
        with self._driver.session(database=self._database) as session:
            res = session.run(
                """
                MATCH (c:Chunk {workspace_id: $ws_id})
                WHERE c.revision_id IN $rev_ids
                RETURN c.id AS id
                ORDER BY c.index ASC
                """,
                ws_id=snapshot.workspace_id,
                rev_ids=list(snapshot.active_revision_ids),
            )
            return [r["id"] for r in res]

    def lexical_candidates(self, text: str, snapshot: CorpusSnapshot, limit: int) -> list[str]:
        self._require_current_snapshot(snapshot)
        if limit <= 0 or not snapshot.active_revision_ids:
            return []
        with self._driver.session(database=self._database) as session:
            res = session.run(
                """
                MATCH (c:Chunk {workspace_id: $ws_id})
                WHERE c.revision_id IN $rev_ids AND toLower(c.text) CONTAINS toLower($text)
                RETURN c.id AS id
                LIMIT $limit
                """,
                ws_id=snapshot.workspace_id,
                rev_ids=list(snapshot.active_revision_ids),
                text=text,
                limit=limit,
            )
            return [r["id"] for r in res]

    def fetch_evidence(self, chunk_ids: Sequence[str], snapshot: CorpusSnapshot) -> EvidencePackage:
        self._require_current_snapshot(snapshot)
        if not chunk_ids or not snapshot.active_revision_ids:
            return EvidencePackage(
                snapshot=snapshot,
                documents=[],
                revisions=[],
                chunks=[],
                entities=[],
                values=[],
                relations=[],
            )

        with self._driver.session(database=self._database) as session:
            # Chunks
            chunks_res = session.run(
                """
                MATCH (c:Chunk {workspace_id: $ws_id})
                WHERE c.id IN $cids AND c.revision_id IN $rev_ids
                RETURN c.json AS json
                """,
                ws_id=snapshot.workspace_id,
                cids=list(chunk_ids),
                rev_ids=list(snapshot.active_revision_ids),
            )
            raw_chunks = [Chunk.model_validate_json(r["json"]) for r in chunks_res]
            truncated = False
            if len(raw_chunks) > 200:
                chunks = raw_chunks[:200]
                truncated = True
            else:
                chunks = raw_chunks
            rev_ids = {c.revision_id for c in chunks}
            chunk_id_set = {c.id for c in chunks}

            # Documents
            docs_res = session.run(
                """
                MATCH (d:Document {workspace_id: $ws_id, deleted: false})
                WHERE d.active_revision_id IN $rev_ids
                RETURN d.json AS json, d.id AS id, d.filename AS fn, d.source_type AS st, d.active_revision_id AS ar, d.created_at AS ca
                """,
                ws_id=snapshot.workspace_id,
                rev_ids=list(rev_ids),
            )
            documents: list[Document] = []
            for r in docs_res:
                if r["json"]:
                    documents.append(Document.model_validate_json(r["json"]))
                else:
                    documents.append(
                        Document(
                            id=r["id"],
                            workspace_id=snapshot.workspace_id,
                            filename=r["fn"],
                            source_type=r["st"],
                            active_revision_id=r["ar"],
                            created_at=datetime.fromisoformat(r["ca"]),
                        )
                    )

            # Revisions
            revs_res = session.run(
                """
                MATCH (r:Revision)
                WHERE r.id IN $rev_ids
                RETURN r.json AS json
                """,
                rev_ids=list(rev_ids),
            )
            revisions = [Revision.model_validate_json(r["json"]) for r in revs_res if r["json"]]

            # Relations
            rels_res = session.run(
                """
                MATCH ()-[r]->()
                WHERE r.workspace_id = $ws_id AND r.revision_id IN $rev_ids AND r.evidence_chunk_id IN $cids
                RETURN r.json AS json
                """,
                ws_id=snapshot.workspace_id,
                rev_ids=list(rev_ids),
                cids=list(chunk_id_set),
            )
            raw_relations = [Relation.model_validate_json(r["json"]) for r in rels_res if r["json"]]
            if len(raw_relations) > 300:
                relations = raw_relations[:300]
                truncated = True
            else:
                relations = raw_relations

            # Entities and Values needed by relations
            subject_ids = {rel.subject_id for rel in relations}
            obj_ent_ids = {rel.object_entity_id for rel in relations if rel.object_entity_id}
            obj_val_ids = {rel.object_value_id for rel in relations if rel.object_value_id}
            all_ent_ids = list(subject_ids | obj_ent_ids)

            entities: list[Entity] = []
            if all_ent_ids:
                ents_res = session.run(
                    """
                    MATCH (e:Entity {workspace_id: $ws_id})
                    WHERE e.id IN $eids
                    RETURN e.json AS json
                    """,
                    ws_id=snapshot.workspace_id,
                    eids=all_ent_ids,
                )
                entities = [Entity.model_validate_json(r["json"]) for r in ents_res if r["json"]]

            values: list[Value] = []
            if obj_val_ids:
                vals_res = session.run(
                    """
                    MATCH (v:Value {workspace_id: $ws_id})
                    WHERE v.id IN $vids
                    RETURN v.json AS json
                    """,
                    ws_id=snapshot.workspace_id,
                    vids=list(obj_val_ids),
                )
                values = [Value.model_validate_json(r["json"]) for r in vals_res if r["json"]]

            available_count = len(raw_chunks) if truncated else None
            searched_count = len(chunks) if truncated else None
            return EvidencePackage(
                snapshot=snapshot,
                documents=documents,
                revisions=revisions,
                chunks=chunks,
                entities=entities,
                values=values,
                relations=relations,
                truncated=truncated,
                available_chunk_count=available_count,
                searched_chunk_count=searched_count,
            )

    def expand_paths(self, entity_ids: Sequence[str], snapshot: CorpusSnapshot, max_hops: int) -> list[EvidencePath]:
        self._require_current_snapshot(snapshot)
        if max_hops < 1 or not entity_ids or not snapshot.active_revision_ids:
            return []

        with self._driver.session(database=self._database) as session:
            rels_res = session.run(
                """
                MATCH (s:Entity)-[r]->(o)
                WHERE r.workspace_id = $ws_id
                  AND r.revision_id IN $rev_ids
                  AND (s.id IN $eids OR o.id IN $eids)
                RETURN r.json AS rel_json, r.evidence_chunk_id AS chunk_id
                LIMIT 20
                """,
                ws_id=snapshot.workspace_id,
                rev_ids=list(snapshot.active_revision_ids),
                eids=list(entity_ids),
            )
            rel_items = [(r["rel_json"], r["chunk_id"]) for r in rels_res if r["rel_json"]]
            if not rel_items:
                return []

            chunk_ids = list({item[1] for item in rel_items})
            chunks_res = session.run(
                "MATCH (c:Chunk) WHERE c.id IN $cids RETURN c.id AS id, c.json AS json, c.document_id AS doc_id",
                cids=chunk_ids,
            )
            chunks_by_id = {r["id"]: (Chunk.model_validate_json(r["json"]), r["doc_id"]) for r in chunks_res if r["json"]}

            rev_ids = list(snapshot.active_revision_ids)
            revs_res = session.run("MATCH (r:Revision) WHERE r.id IN $rids RETURN r.id AS id, r.json AS json", rids=rev_ids)
            revs_by_id = {r["id"]: Revision.model_validate_json(r["json"]) for r in revs_res if r["json"]}

            doc_ids = list({v[1] for v in chunks_by_id.values()})
            docs_res = session.run(
                """
                MATCH (d:Document) WHERE d.id IN $dids
                RETURN d.id AS id, d.json AS json, d.filename AS fn, d.source_type AS st, d.active_revision_id AS ar, d.created_at AS ca
                """,
                dids=doc_ids,
            )
            docs_by_id: dict[str, Document] = {}
            for r in docs_res:
                if r["json"]:
                    docs_by_id[r["id"]] = Document.model_validate_json(r["json"])
                else:
                    docs_by_id[r["id"]] = Document(
                        id=r["id"],
                        workspace_id=snapshot.workspace_id,
                        filename=r["fn"],
                        source_type=r["st"],
                        active_revision_id=r["ar"],
                        created_at=datetime.fromisoformat(r["ca"]),
                    )

            paths: list[EvidencePath] = []
            for rel_json, cid in rel_items:
                relation = Relation.model_validate_json(rel_json)
                chunk_info = chunks_by_id.get(cid)
                if not chunk_info:
                    continue
                chunk, doc_id = chunk_info
                revision = revs_by_id.get(relation.revision_id)
                document = docs_by_id.get(doc_id)
                if not revision or not document:
                    continue

                step = EvidencePathStep(
                    relation_id=relation.id,
                    subject_id=relation.subject_id,
                    object_entity_id=relation.object_entity_id,
                    object_value_id=relation.object_value_id,
                    traversal_direction="forward",
                    evidence_chunk_id=chunk.id,
                    revision_id=relation.revision_id,
                    document_id=doc_id,
                )
                path = EvidencePath(
                    id=evidence_path_id(snapshot.workspace_id, snapshot.epoch, [step.model_dump(mode="json")]),
                    workspace_id=snapshot.workspace_id,
                    snapshot_epoch=snapshot.epoch,
                    steps=[step],
                )
                paths.append(
                    validate_evidence_path_provenance(
                        path,
                        relations=[relation],
                        chunks=[chunk],
                        revisions=[revision],
                        documents=[document],
                    )
                )
                if len(paths) >= 5:
                    break

            return paths
