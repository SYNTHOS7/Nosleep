from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.contracts.models import (
    Chunk, ChunkLocation, Document, EntityMention, Evidence, Relation, RelationModality,
)
from backend.contracts.validation import (
    validate_entity_mention_for_chunk, validate_evidence_for_chunk, validate_relation_context,
)


UTC = datetime(2026, 10, 24, tzinfo=timezone.utc)


def chunk() -> Chunk:
    return Chunk(
        id="chunk-1", workspace_id="ws-1", document_id="doc-1", revision_id="rev-1", index=0,
        text="Acme supports IPv6.", text_hash="hash", location=ChunkLocation(start_offset=0, end_offset=19),
    )


def evidence() -> Evidence:
    return Evidence(chunk_id="chunk-1", start=0, end=19, quote="Acme supports IPv6.")


def relation(**overrides: object) -> Relation:
    data: dict[str, object] = {
        "id": "rel-1", "workspace_id": "ws-1", "revision_id": "rev-1", "subject_id": "entity-1",
        "object_entity_id": "entity-2", "predicate": "SUPPORTS", "predicate_original": "supports",
        "polarity": "positive", "modality": "asserted", "evidence": evidence(),
        "extraction_method": "llm", "extraction_model": "model", "extraction_version": "v1",
    }
    data.update(overrides)
    return Relation.model_validate(data)


def test_forbidden_extra_field() -> None:
    with pytest.raises(ValidationError):
        Document.model_validate({
            "id": "d", "workspace_id": "w", "filename": "x.txt", "source_type": "txt",
            "created_at": UTC, "unexpected": True,
        })


def test_timestamps_must_be_utc() -> None:
    with pytest.raises(ValidationError, match="UTC"):
        Document(id="d", workspace_id="w", filename="x.txt", source_type="txt", created_at=datetime(2026, 1, 1))


def test_evidence_must_match_exact_chunk_span() -> None:
    validate_evidence_for_chunk(evidence(), chunk())
    with pytest.raises(ValueError, match="exactly match"):
        validate_evidence_for_chunk(Evidence(chunk_id="chunk-1", start=0, end=4, quote="Acme!"), chunk())


def test_relation_requires_exactly_one_object_endpoint() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        relation(object_entity_id=None, object_value_id=None)
    with pytest.raises(ValidationError, match="exactly one"):
        relation(object_value_id="value-1")


def test_conditional_relation_requires_condition() -> None:
    with pytest.raises(ValidationError, match="requires condition"):
        relation(modality=RelationModality.CONDITIONAL)
    assert relation(modality=RelationModality.CONDITIONAL, condition="when enabled").condition == "when enabled"


def test_relation_context_requires_same_workspace_and_revision() -> None:
    validate_relation_context(relation(), chunk())
    with pytest.raises(ValueError, match="workspace"):
        validate_relation_context(relation(workspace_id="ws-2"), chunk())


def test_entity_mention_is_source_bound_and_exact() -> None:
    mention = EntityMention(
        id="mention-1", workspace_id="ws-1", document_id="doc-1", revision_id="rev-1",
        entity_id="entity-1", chunk_id="chunk-1", start=0, end=4, quote="Acme", created_at=UTC,
    )
    validate_entity_mention_for_chunk(mention, chunk())
    with pytest.raises(ValueError, match="exactly match"):
        validate_entity_mention_for_chunk(mention.model_copy(update={"quote": "ACME"}), chunk())
