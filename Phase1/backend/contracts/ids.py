"""Stable SHA-256 identifiers over documented canonical JSON payloads."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, uuid4

from pydantic import BaseModel


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="json", exclude_none=False))
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical timestamps must be timezone-aware UTC")
        if value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("canonical timestamps must be UTC")
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON cannot contain non-finite numbers")
        return value
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            normalized[key] = _normalize(item)
        return normalized
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """RFC-style deterministic JSON: UTF-8, sorted keys, compact separators, no NaN."""
    return json.dumps(
        _normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def sha256_id(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def document_id() -> str:
    return str(uuid4())


def revision_id(document_id_value: str, content_hash: str, pipeline_configuration: Mapping[str, Any]) -> str:
    return sha256_id({"content_hash": content_hash, "document_id": document_id_value, "pipeline": pipeline_configuration})


def chunk_id(revision_id_value: str, index: int, text_hash: str, location: Mapping[str, Any]) -> str:
    return sha256_id({"index": index, "location": location, "revision_id": revision_id_value, "text_hash": text_hash})


def entity_id(workspace_id: str, entity_type: str, normalized_name: str) -> str:
    return sha256_id({"normalized_name": normalized_name, "type": entity_type, "workspace_id": workspace_id})


def value_id(workspace_id: str, kind: str, normalized_value: str, unit: str | None) -> str:
    """Return canonical Value identity; callers normalize value and unit upstream."""
    return sha256_id({
        "kind": kind,
        "normalized_value": normalized_value,
        "unit": unit,
        "workspace_id": workspace_id,
    })


def entity_mention_id(
    revision_id_value: str, entity_id_value: str, chunk_id_value: str, start: int, end: int, quote: str
) -> str:
    return sha256_id({
        "chunk_id": chunk_id_value, "end": end, "entity_id": entity_id_value,
        "quote": quote, "revision_id": revision_id_value, "start": start,
    })


def relation_id(
    revision_id_value: str,
    subject_id: str,
    object_entity_id: str | None,
    object_value_id: str | None,
    predicate: str,
    polarity: str,
    modality: str,
    condition: str | None,
    valid_from: datetime | None,
    valid_to: datetime | None,
    evidence: Mapping[str, Any],
) -> str:
    return sha256_id({
        "condition": condition,
        "evidence": evidence,
        "modality": modality,
        "object_entity_id": object_entity_id,
        "object_value_id": object_value_id,
        "polarity": polarity,
        "predicate": predicate,
        "revision_id": revision_id_value,
        "subject_id": subject_id,
        "valid_from": valid_from,
        "valid_to": valid_to,
    })


def conflict_id(workspace_id: str, kind: str, first_relation_id: str, second_relation_id: str) -> str:
    """Return the identity of one unordered source-specific relation pair."""
    if first_relation_id == second_relation_id:
        raise ValueError("conflict relation IDs must be distinct")
    relation_ids = sorted((first_relation_id, second_relation_id))
    return sha256_id({"kind": kind, "relation_ids": relation_ids, "workspace_id": workspace_id})


def evidence_path_id(workspace_id: str, snapshot_epoch: int, ordered_steps: list[Mapping[str, Any]]) -> str:
    """Return a snapshot-scoped identity for an ordered, directed evidence path."""
    return sha256_id({
        "ordered_steps": ordered_steps,
        "snapshot_epoch": snapshot_epoch,
        "workspace_id": workspace_id,
    })


def topic_id() -> str:
    return str(uuid4())
