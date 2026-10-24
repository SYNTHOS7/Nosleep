import json
from pathlib import Path

from backend.contracts.ids import (
    canonical_json, chunk_id, conflict_id, entity_id, entity_mention_id, evidence_path_id,
    relation_id, revision_id, value_id,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "deterministic_ids.json"


def test_canonical_json_is_stable() -> None:
    assert canonical_json({"z": "é", "a": [2, 1]}) == '{"a":[2,1],"z":"é"}'


def test_golden_identifiers() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = fixture["input"]
    expected = fixture["expected"]
    relation_evidence = dict(source["relation"]["evidence"])
    relation_evidence["chunk_id"] = expected["chunk_id"]
    actual = {
        "revision_id": revision_id(source["document_id"], source["content_hash"], source["pipeline"]),
        "chunk_id": chunk_id(expected["revision_id"], source["chunk_index"], source["text_hash"], source["location"]),
        "entity_id": entity_id(source["workspace_id"], source["entity_type"], source["normalized_name"]),
        "entity_mention_id": entity_mention_id(
            expected["revision_id"], expected["entity_id"], expected["chunk_id"],
            source["mention"]["start"], source["mention"]["end"], source["mention"]["quote"],
        ),
        "relation_id": relation_id(
            expected["revision_id"], expected["entity_id"], source["relation"]["object_entity_id"], None,
            source["relation"]["predicate"], source["relation"]["polarity"], source["relation"]["modality"],
            source["relation"]["condition"], None, None, relation_evidence,
        ),
    }
    assert actual == expected


def test_golden_integration_identifiers() -> None:
    fixture_path = Path(__file__).parents[1] / "fixtures" / "integration_ids.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    source = fixture["input"]
    expected = fixture["expected"]
    assert {
        "value_id": value_id(source["workspace_id"], **source["value"]),
        "conflict_id": conflict_id(source["workspace_id"], source["conflict"]["kind"], *source["conflict"]["relation_ids"]),
        "evidence_path_id": evidence_path_id(source["workspace_id"], source["path"]["snapshot_epoch"], source["path"]["ordered_steps"]),
    } == expected
