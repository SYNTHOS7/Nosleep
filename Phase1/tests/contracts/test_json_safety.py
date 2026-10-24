import math
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.contracts.models import Document, Operation, QueryResponse, Topic


UTC = datetime(2026, 10, 24, tzinfo=timezone.utc)


def operation(**overrides: object) -> Operation:
    data: dict[str, object] = {
        "id": "op-1", "workspace_id": "ws", "document_id": "doc", "kind": "add", "stage": "queued",
        "accepted_at": UTC, "deadline_at": UTC,
    }
    data.update(overrides)
    return Operation.model_validate(data)


def test_non_json_checkpoint_is_rejected() -> None:
    with pytest.raises(ValidationError, match="JSON-safe"):
        operation(checkpoint={"invalid": {1, 2}})


def test_document_metadata_must_be_json_safe() -> None:
    with pytest.raises(ValidationError, match="JSON-safe"):
        Document(
            id="doc", workspace_id="ws", filename="source.txt", source_type="txt", created_at=UTC,
            metadata={"invalid": object()},
        )


def test_non_finite_numbers_are_rejected() -> None:
    with pytest.raises(ValidationError, match="finite"):
        operation(timings_ms={"parse": math.nan})
    with pytest.raises(ValidationError, match="finite"):
        Topic(
            id="t", workspace_id="w", label="l", description="d", cluster_version="c", embedding_version="e",
            centroid=[math.inf], summary_status="ready",
        )
    with pytest.raises(ValidationError, match="finite"):
        QueryResponse(
            request_id="r", corpus_epoch=0, status="answered", language="en", plan={}, statements=[],
            evidence={}, graph={}, latency_ms=math.nan,
        )
