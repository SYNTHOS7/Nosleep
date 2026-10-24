import math
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.contracts.ids import conflict_id, evidence_path_id, value_id
from backend.contracts.integration import (
    CorpusSnapshot, DerivedDelta, EvidencePackage, EvidencePath, EvidencePathStep,
    ExtractionBatch, PublishReceipt, revalidate_evidence_package, revalidate_evidence_path,
    revalidate_extraction_batch,
    validate_evidence_path_provenance,
)
from backend.contracts.models import (
    Chunk, ChunkLocation, Conflict, Document, Entity, EntityMention, Evidence, Relation,
    Revision, TopicMembership, Value,
)


UTC = datetime(2026, 10, 24, tzinfo=timezone.utc)


def _chunk(chunk_id: str = "chunk-1") -> Chunk:
    return Chunk(
        id=chunk_id, workspace_id="ws-1", document_id="doc-1", revision_id="rev-1", index=0,
        text="Acme supports IPv6.", text_hash="hash", location=ChunkLocation(start_offset=0, end_offset=19),
    )


def _entity(entity_id: str = "entity-1") -> Entity:
    return Entity(id=entity_id, workspace_id="ws-1", name="Acme", normalized_name="acme", type="Organization")


def _relation(relation_id: str = "rel-1", chunk_id: str = "chunk-1", subject_id: str = "entity-1", object_id: str = "entity-2") -> Relation:
    return Relation(
        id=relation_id, workspace_id="ws-1", revision_id="rev-1", subject_id=subject_id,
        object_entity_id=object_id, predicate="SUPPORTS", predicate_original="supports", polarity="positive",
        modality="asserted", evidence=Evidence(chunk_id=chunk_id, start=0, end=19, quote="Acme supports IPv6."),
        extraction_method="llm", extraction_model="model", extraction_version="v1",
    )


def _conflict() -> Conflict:
    return Conflict(
        id=conflict_id("ws-1", "incompatible_statement", "rel-1", "rel-2"), workspace_id="ws-1",
        left_relation_id="rel-1", right_relation_id="rel-2", kind="incompatible_statement", state="supported",
        explanation="Fixture pair", evidence_chunk_ids=["chunk-1", "chunk-2"], detector_version="fixture-v1",
    )


def _snapshot() -> CorpusSnapshot:
    return CorpusSnapshot(workspace_id="ws-1", epoch=7, active_revision_ids=["rev-1"], captured_at=UTC)


def test_extraction_batch_enforces_provenance_and_exact_vector_coverage() -> None:
    chunk = _chunk()
    entities = [_entity(), _entity("entity-2")]
    mention = EntityMention(
        id="mention-1", workspace_id="ws-1", document_id="doc-1", revision_id="rev-1", entity_id="entity-1",
        chunk_id="chunk-1", start=0, end=4, quote="Acme", created_at=UTC,
    )
    batch = ExtractionBatch(
        workspace_id="ws-1", document_id="doc-1", revision_id="rev-1", embedding_version="embed-v1",
        embedding_dimension=3, chunks=[chunk], entities=entities, entity_mentions=[mention], relations=[_relation()],
        chunk_vectors={"chunk-1": [0.1, 0.2, 0.3]},
    )
    assert batch.chunk_vectors["chunk-1"] == [0.1, 0.2, 0.3]
    with pytest.raises(ValidationError, match="cover exactly"):
        ExtractionBatch.model_validate({**batch.model_dump(), "chunk_vectors": {}})
    with pytest.raises(ValidationError, match="zero vectors"):
        ExtractionBatch.model_validate({**batch.model_dump(), "chunk_vectors": {"chunk-1": [0.0, 0.0, 0.0]}})
    with pytest.raises(ValidationError, match="embedding_dimension"):
        ExtractionBatch.model_validate({**batch.model_dump(), "chunk_vectors": {"chunk-1": [0.1, 0.2]}})
    for invalid_component in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValidationError, match="finite"):
            ExtractionBatch.model_validate({**batch.model_dump(), "chunk_vectors": {"chunk-1": [invalid_component, 0.2, 0.3]}})
    with pytest.raises(ValidationError, match="numeric int or float"):
        ExtractionBatch.model_validate({**batch.model_dump(), "chunk_vectors": {"chunk-1": ["0.1", 0.2, 0.3]}})
    with pytest.raises(ValidationError, match="batch workspace"):
        ExtractionBatch.model_validate({**batch.model_dump(), "chunks": [chunk.model_copy(update={"workspace_id": "ws-2"})]})


def test_value_and_conflict_identities_are_canonical() -> None:
    identity = value_id("ws-1", "number", "42", "ms")
    value = Value(id=identity, workspace_id="ws-1", kind="number", lexical_value="42 milliseconds", normalized_value="42", unit="ms")
    assert value.id == identity
    assert Value(id=identity, workspace_id="ws-1", kind="number", lexical_value="42 ms", normalized_value="42", unit="ms").id == identity
    with pytest.raises(ValidationError, match="canonical normalized identity"):
        Value(id="wrong", workspace_id="ws-1", kind="number", lexical_value="42", normalized_value="42", unit="ms")
    assert conflict_id("ws-1", "incompatible_statement", "rel-2", "rel-1") == _conflict().id
    with pytest.raises(ValueError, match="distinct"):
        conflict_id("ws-1", "incompatible_statement", "rel-1", "rel-1")
    with pytest.raises(ValidationError, match="lexicographically ordered"):
        Conflict.model_validate({**_conflict().model_dump(), "left_relation_id": "rel-2", "right_relation_id": "rel-1"})


def test_snapshot_delta_and_receipt_local_rules() -> None:
    snapshot = _snapshot()
    assert CorpusSnapshot(workspace_id="ws-1", epoch=0, captured_at=UTC).active_revision_ids == []
    with pytest.raises(ValidationError, match="unique"):
        CorpusSnapshot(workspace_id="ws-1", epoch=0, active_revision_ids=["rev-1", "rev-1"], captured_at=UTC)
    delta = DerivedDelta(
        operation_id="op-1", snapshot=snapshot, staged_revision_id="rev-2",
        topic_memberships_to_upsert=[TopicMembership(topic_id="topic-1", chunk_id="chunk-new", revision_id="rev-2", method="cluster", score=0.8, assignment_version="v1")],
        conflicts_to_upsert=[_conflict()],
    )
    assert delta.staged_revision_id == "rev-2"
    with pytest.raises(ValidationError, match="upserted and retired"):
        DerivedDelta.model_validate({**delta.model_dump(), "conflict_ids_to_retire": [_conflict().id]})
    receipt = PublishReceipt(
        operation_id="op-1", workspace_id="ws-1", document_id="doc-1", publication_kind="replacement",
        previous_epoch=7, resulting_epoch=8, previous_active_revision_id="rev-1", active_revision_id="rev-2",
        neo4j_publication_applied=True, vectors_verified_before_publication=True,
        post_publication_cleanup_required=True, read_probe_required=True, published_at=UTC,
    )
    assert receipt.resulting_epoch == 8
    with pytest.raises(ValidationError, match="vector staging"):
        PublishReceipt.model_validate({**receipt.model_dump(), "publication_kind": "deletion", "active_revision_id": None})


@pytest.mark.parametrize(
    ("publication_kind", "previous", "active", "vectors_verified", "cleanup", "read_probe", "previous_epoch", "resulting_epoch"),
    [
        ("initial", None, "rev-1", True, False, True, 0, 1),
        ("replacement", "rev-1", "rev-2", True, True, True, 7, 8),
        ("deletion", "rev-1", None, None, True, True, 7, 8),
        ("noop", "rev-1", "rev-1", None, False, False, 7, 7),
    ],
)
def test_publish_receipt_valid_publication_kinds(
    publication_kind: str,
    previous: str | None,
    active: str | None,
    vectors_verified: bool | None,
    cleanup: bool,
    read_probe: bool,
    previous_epoch: int,
    resulting_epoch: int,
) -> None:
    receipt = PublishReceipt(
        operation_id="op-1", workspace_id="ws-1", document_id="doc-1", publication_kind=publication_kind,
        previous_epoch=previous_epoch, resulting_epoch=resulting_epoch, previous_active_revision_id=previous,
        active_revision_id=active, neo4j_publication_applied=publication_kind != "noop",
        vectors_verified_before_publication=vectors_verified, post_publication_cleanup_required=cleanup,
        read_probe_required=read_probe, published_at=UTC,
    )
    assert receipt.publication_kind == publication_kind


def _package() -> EvidencePackage:
    document = Document(id="doc-1", workspace_id="ws-1", filename="source.txt", source_type="txt", active_revision_id="rev-1", created_at=UTC)
    revision = Revision(id="rev-1", document_id="doc-1", content_hash="hash", parser_version="p", chunker_version="c", extractor_version="x", embedding_version="e", state="published", source_ref="source", created_at=UTC)
    chunk1, chunk2 = _chunk("chunk-1"), _chunk("chunk-2")
    chunk2 = chunk2.model_copy(update={"index": 1})
    relation1 = _relation("rel-1", "chunk-1", "entity-1", "entity-2")
    relation2 = _relation("rel-2", "chunk-2", "entity-2", "entity-1")
    step = EvidencePathStep(relation_id="rel-1", subject_id="entity-1", object_entity_id="entity-2", traversal_direction="forward", evidence_chunk_id="chunk-1", revision_id="rev-1", document_id="doc-1")
    path = EvidencePath(id=evidence_path_id("ws-1", 7, [step.model_dump(mode="json")]), workspace_id="ws-1", snapshot_epoch=7, steps=[step])
    return EvidencePackage(
        snapshot=_snapshot(), documents=[document], revisions=[revision], chunks=[chunk1, chunk2],
        entities=[_entity(), _entity("entity-2")], relations=[relation1, relation2], conflicts=[_conflict()], paths=[path],
    )


def test_evidence_package_is_reference_closed_and_paths_are_connected() -> None:
    package = _package()
    assert EvidencePackage.model_validate_json(package.model_dump_json()) == package
    with pytest.raises(ValidationError, match="conflicts must reference"):
        EvidencePackage.model_validate({**package.model_dump(), "relations": package.relations[:1]})
    first = package.paths[0].steps[0]
    disconnected = EvidencePathStep(relation_id="rel-2", subject_id="entity-2", object_entity_id="entity-1", traversal_direction="reverse", evidence_chunk_id="chunk-2", revision_id="rev-1", document_id="doc-1")
    with pytest.raises(ValidationError, match="connected"):
        EvidencePath(id="bad", workspace_id="ws-1", snapshot_epoch=7, steps=[first, disconnected])
    with pytest.raises(ValidationError, match="share snapshot workspace"):
        EvidencePackage.model_validate({
            **package.model_dump(),
            "entities": [package.entities[0].model_copy(update={"workspace_id": "ws-2"}), package.entities[1]],
        })
    with pytest.raises(ValidationError, match="reference included evidence chunks"):
        EvidencePackage.model_validate({**package.model_dump(), "chunks": package.chunks[:1]})


def test_evidence_path_provenance_and_mutation_boundaries() -> None:
    package = _package()
    path = package.paths[0]
    assert validate_evidence_path_provenance(
        path, relations=package.relations, chunks=package.chunks,
        revisions=package.revisions, documents=package.documents,
    ) == path
    bad_step = path.steps[0].model_copy(update={"subject_id": "wrong-entity"})
    bad_path = EvidencePath(
        id=evidence_path_id("ws-1", 7, [bad_step.model_dump(mode="json")]),
        workspace_id="ws-1", snapshot_epoch=7, steps=[bad_step],
    )
    with pytest.raises(ValueError, match="relation endpoints and source provenance"):
        validate_evidence_path_provenance(
            bad_path, relations=package.relations, chunks=package.chunks,
            revisions=package.revisions, documents=package.documents,
        )
    with pytest.raises(ValidationError, match="frozen"):
        path.steps[0].subject_id = "wrong-entity"
    path.steps.append(path.steps[0])
    with pytest.raises(ValidationError, match="connected"):
        revalidate_evidence_path(path)

    batch = ExtractionBatch(
        workspace_id="ws-1", document_id="doc-1", revision_id="rev-1", embedding_version="embed-v1",
        embedding_dimension=1, chunks=[_chunk()], entities=[_entity(), _entity("entity-2")], relations=[_relation()],
        chunk_vectors={"chunk-1": [1.0]},
    )
    batch.chunks.append(_chunk())
    with pytest.raises(ValidationError, match="chunk IDs must be unique"):
        revalidate_extraction_batch(batch)

    package_for_revalidation = _package()
    package_for_revalidation.documents.clear()
    with pytest.raises(ValidationError, match="reference included documents"):
        revalidate_evidence_package(package_for_revalidation)


def test_evidence_package_rejects_standalone_deleted_or_inactive_documents() -> None:
    deleted = Document(id="doc-deleted", workspace_id="ws-1", filename="gone.txt", source_type="txt", deleted=True, created_at=UTC)
    with pytest.raises(ValidationError, match="active and non-deleted"):
        EvidencePackage(snapshot=CorpusSnapshot(workspace_id="ws-1", epoch=0, captured_at=UTC), documents=[deleted])
    inactive = Document(id="doc-1", workspace_id="ws-1", filename="source.txt", source_type="txt", active_revision_id="rev-2", created_at=UTC)
    revision = Revision(id="rev-1", document_id="doc-1", content_hash="hash", parser_version="p", chunker_version="c", extractor_version="x", embedding_version="e", state="published", source_ref="source", created_at=UTC)
    with pytest.raises(ValidationError, match="snapshot-active revision"):
        EvidencePackage(snapshot=_snapshot(), documents=[inactive], revisions=[revision])
