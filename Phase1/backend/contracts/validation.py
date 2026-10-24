"""Cross-record validation that cannot be expressed by an ID-only model."""

from .models import Chunk, EntityMention, Evidence, Relation


def validate_evidence_for_chunk(evidence: Evidence, chunk: Chunk) -> None:
    if evidence.chunk_id != chunk.id:
        raise ValueError("evidence chunk_id does not match chunk")
    if evidence.end > len(chunk.text):
        raise ValueError("evidence end exceeds chunk text length")
    if evidence.quote != chunk.text[evidence.start : evidence.end]:
        raise ValueError("evidence quote must exactly match the chunk span")


def validate_entity_mention_for_chunk(mention: EntityMention, chunk: Chunk) -> None:
    if mention.workspace_id != chunk.workspace_id:
        raise ValueError("entity mention and chunk must share workspace")
    if mention.document_id != chunk.document_id or mention.revision_id != chunk.revision_id:
        raise ValueError("entity mention and chunk must share document and revision")
    if mention.chunk_id != chunk.id:
        raise ValueError("entity mention chunk_id does not match chunk")
    if mention.end > len(chunk.text) or mention.quote != chunk.text[mention.start : mention.end]:
        raise ValueError("entity mention quote must exactly match the chunk span")


def validate_relation_context(relation: Relation, evidence_chunk: Chunk) -> None:
    if relation.workspace_id != evidence_chunk.workspace_id:
        raise ValueError("relation and evidence must share workspace")
    if relation.revision_id != evidence_chunk.revision_id:
        raise ValueError("relation and evidence must share revision")
    validate_evidence_for_chunk(relation.evidence, evidence_chunk)
