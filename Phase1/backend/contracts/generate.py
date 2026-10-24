"""Generate the committed JSON Schema from the Pydantic source models."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from .models import (
    Chunk, Conflict, Document, Entity, EntityMention, Evidence, Operation, QueryRequest,
    QueryResponse, Relation, Revision, Topic, TopicMembership, Value,
)
from .integration import (
    CorpusSnapshot, DerivedDelta, EvidencePackage, EvidencePath, EvidencePathStep,
    ExtractionBatch, PublishReceipt,
)


class ContractSchema(BaseModel):
    """Schema-only envelope exporting every public canonical model."""

    document: Document | None = None
    revision: Revision | None = None
    chunk: Chunk | None = None
    entity: Entity | None = None
    entity_mention: EntityMention | None = None
    value: Value | None = None
    evidence: Evidence | None = None
    relation: Relation | None = None
    topic: Topic | None = None
    topic_membership: TopicMembership | None = None
    conflict: Conflict | None = None
    operation: Operation | None = None
    query_request: QueryRequest | None = None
    query_response: QueryResponse | None = None
    extraction_batch: ExtractionBatch | None = None
    corpus_snapshot: CorpusSnapshot | None = None
    derived_delta: DerivedDelta | None = None
    publish_receipt: PublishReceipt | None = None
    evidence_path_step: EvidencePathStep | None = None
    evidence_path: EvidencePath | None = None
    evidence_package: EvidencePackage | None = None


def generate_schema(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    schema = ContractSchema.model_json_schema()
    output.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    repository_root = Path(__file__).resolve().parents[2]
    generate_schema(repository_root / "generated" / "contracts.schema.json")
