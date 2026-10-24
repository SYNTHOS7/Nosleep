"""
Conflict and contradiction detection module.
Implements the 3 testable conflict conditions defined in 03-topics-retrieval-answers-and-conflicts.md:
1. Opposite polarity on identical subject/predicate/object
2. Distinct values on exclusive predicates
3. Explicit incompatible statements in planted fixture catalog
"""

from __future__ import annotations
import hashlib
from typing import Dict, List, Optional, Set, Tuple

from backend.contracts.models import Conflict, Relation, Value


# Pre-configured list of exclusive predicates (where an entity can only have one active value)
EXCLUSIVE_PREDICATES = {
    "has_status",
    "status",
    "version",
    "has_version",
    "location",
    "located_in",
    "founded_in",
    "cost",
    "pricing_tier",
    "max_connections",
    "encryption_mode",
    "license_type",
}

# Planted fixture catalog of known incompatible statement pairs
# Format: ((subject_norm, pred_norm, obj_norm), (subject_norm, pred_norm, obj_norm))
PLANTED_INCOMPATIBLE_PAIRS = [
    (
        ("auth_service", "uses_architecture", "microservice"),
        ("auth_service", "uses_architecture", "monolith"),
    ),
    (
        ("payment_api", "license", "open_source"),
        ("payment_api", "license", "proprietary"),
    ),
    (
        ("storage_cluster", "persistence", "in_memory_only"),
        ("storage_cluster", "persistence", "disk_persisted"),
    ),
    (
        ("api_gateway", "exposure", "public_facing"),
        ("api_gateway", "exposure", "internal_only"),
    ),
]


def _normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    return text.strip().lower().replace(" ", "_").replace("-", "_")


def _conflict_id(left_id: str, right_id: str, kind: str) -> str:
    pair = sorted([left_id, right_id])
    raw = f"{pair[0]}::{pair[1]}::{kind}"
    return f"conflict_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"


def find_conflicts(
    active_relations: List[Relation],
    changed_relation_ids: Optional[List[str]] = None,
    values_by_id: Optional[Dict[str, Value]] = None,
) -> List[Conflict]:
    """
    Detects defined testable conflicts among relations.
    If changed_relation_ids is provided, focuses detection on pairs involving at least one changed relation.
    """
    values_by_id = values_by_id or {}
    conflicts: List[Conflict] = []
    seen_pairs: Set[Tuple[str, str, str]] = set()

    changed_set = set(changed_relation_ids) if changed_relation_ids is not None else None

    # Compare all pairs (N is bounded in our system; for large corpora, index by subject)
    # Index relations by normalized subject
    by_subject: Dict[str, List[Relation]] = {}
    for r in active_relations:
        subj = _normalize(r.subject_id)
        by_subject.setdefault(subj, []).append(r)

    for subj, rel_list in by_subject.items():
        n = len(rel_list)
        for i in range(n):
            rel_a = rel_list[i]
            for j in range(i + 1, n):
                rel_b = rel_list[j]

                # Optimization: if changed_set is provided, at least one relation must be in changed_set
                if changed_set is not None:
                    if rel_a.id not in changed_set and rel_b.id not in changed_set:
                        continue

                # Don't compare identical relation
                if rel_a.id == rel_b.id:
                    continue

                pred_a = _normalize(rel_a.predicate)
                pred_b = _normalize(rel_b.predicate)

                # Check Condition 1: Opposite Polarity on identical subject/predicate/object
                # Case 1A: Object is Entity
                if (
                    rel_a.object_entity_id
                    and rel_b.object_entity_id
                    and _normalize(rel_a.object_entity_id) == _normalize(rel_b.object_entity_id)
                    and pred_a == pred_b
                ):
                    if rel_a.polarity != rel_b.polarity:
                        cid = _conflict_id(rel_a.id, rel_b.id, "negation")
                        pair_key = (min(rel_a.id, rel_b.id), max(rel_a.id, rel_b.id), "negation")
                        if pair_key not in seen_pairs:
                            seen_pairs.add(pair_key)
                            conflicts.append(
                                Conflict(
                                    id=cid,
                                    workspace_id=rel_a.workspace_id,
                                    left_relation_id=rel_a.id,
                                    right_relation_id=rel_b.id,
                                    kind="negation",
                                    state="supported",
                                    explanation=(
                                        f"Direct polarity negation: Relation {rel_a.id} asserts {rel_a.polarity} "
                                        f"while {rel_b.id} asserts {rel_b.polarity} for ({subj}, {pred_a}, {rel_a.object_entity_id})."
                                    ),
                                    evidence_chunk_ids=list(
                                        set([rel_a.evidence.chunk_id, rel_b.evidence.chunk_id])
                                    ),
                                    detector_version="conflict-detector-v1",
                                )
                            )

                # Case 1B: Object is Value with same normalized value and opposite polarity
                if rel_a.object_value_id and rel_b.object_value_id and pred_a == pred_b:
                    val_a = values_by_id.get(rel_a.object_value_id)
                    val_b = values_by_id.get(rel_b.object_value_id)
                    norm_val_a = _normalize(val_a.normalized_value) if val_a else _normalize(rel_a.object_value_id)
                    norm_val_b = _normalize(val_b.normalized_value) if val_b else _normalize(rel_b.object_value_id)

                    if norm_val_a == norm_val_b and rel_a.polarity != rel_b.polarity:
                        cid = _conflict_id(rel_a.id, rel_b.id, "negation")
                        pair_key = (min(rel_a.id, rel_b.id), max(rel_a.id, rel_b.id), "negation")
                        if pair_key not in seen_pairs:
                            seen_pairs.add(pair_key)
                            conflicts.append(
                                Conflict(
                                    id=cid,
                                    workspace_id=rel_a.workspace_id,
                                    left_relation_id=rel_a.id,
                                    right_relation_id=rel_b.id,
                                    kind="negation",
                                    state="supported",
                                    explanation=(
                                        f"Value negation: Relation {rel_a.id} ({rel_a.polarity}) vs "
                                        f"{rel_b.id} ({rel_b.polarity}) for value '{norm_val_a}'."
                                    ),
                                    evidence_chunk_ids=list(
                                        set([rel_a.evidence.chunk_id, rel_b.evidence.chunk_id])
                                    ),
                                    detector_version="conflict-detector-v1",
                                )
                            )

                # Check Condition 2: Same subject/predicate but distinct normalized Value objects for exclusive predicate
                if pred_a == pred_b and pred_a in EXCLUSIVE_PREDICATES:
                    if rel_a.object_value_id and rel_b.object_value_id:
                        val_a = values_by_id.get(rel_a.object_value_id)
                        val_b = values_by_id.get(rel_b.object_value_id)
                        norm_val_a = _normalize(val_a.normalized_value) if val_a else _normalize(rel_a.object_value_id)
                        norm_val_b = _normalize(val_b.normalized_value) if val_b else _normalize(rel_b.object_value_id)

                        if norm_val_a != norm_val_b:
                            cid = _conflict_id(rel_a.id, rel_b.id, "exclusive_value")
                            pair_key = (min(rel_a.id, rel_b.id), max(rel_a.id, rel_b.id), "exclusive_value")
                            if pair_key not in seen_pairs:
                                seen_pairs.add(pair_key)
                                conflicts.append(
                                    Conflict(
                                        id=cid,
                                        workspace_id=rel_a.workspace_id,
                                        left_relation_id=rel_a.id,
                                        right_relation_id=rel_b.id,
                                        kind="exclusive_value",
                                        state="supported",
                                        explanation=(
                                            f"Exclusive value conflict on predicate '{pred_a}': "
                                            f"Source A asserts '{norm_val_a}' vs Source B asserts '{norm_val_b}'."
                                        ),
                                        evidence_chunk_ids=list(
                                            set([rel_a.evidence.chunk_id, rel_b.evidence.chunk_id])
                                        ),
                                        detector_version="conflict-detector-v1",
                                    )
                                )

                # Check Condition 3: Explicit incompatible statement pairs from planted catalog
                if rel_a.object_entity_id:
                    obj_a = _normalize(rel_a.object_entity_id)
                elif rel_a.object_value_id:
                    v_node = values_by_id.get(rel_a.object_value_id)
                    obj_a = _normalize(v_node.normalized_value if v_node else rel_a.object_value_id)
                else:
                    obj_a = ""

                if rel_b.object_entity_id:
                    obj_b = _normalize(rel_b.object_entity_id)
                elif rel_b.object_value_id:
                    v_node = values_by_id.get(rel_b.object_value_id)
                    obj_b = _normalize(v_node.normalized_value if v_node else rel_b.object_value_id)
                else:
                    obj_b = ""

                triple_a = (subj, pred_a, obj_a)
                triple_b = (subj, pred_b, obj_b)

                for pair_left, pair_right in PLANTED_INCOMPATIBLE_PAIRS:
                    if (triple_a == pair_left and triple_b == pair_right) or (
                        triple_a == pair_right and triple_b == pair_left
                    ):
                        cid = _conflict_id(rel_a.id, rel_b.id, "incompatible_statement")
                        pair_key = (min(rel_a.id, rel_b.id), max(rel_a.id, rel_b.id), "incompatible_statement")
                        if pair_key not in seen_pairs:
                            seen_pairs.add(pair_key)
                            conflicts.append(
                                Conflict(
                                    id=cid,
                                    workspace_id=rel_a.workspace_id,
                                    left_relation_id=rel_a.id,
                                    right_relation_id=rel_b.id,
                                    kind="incompatible_statement",
                                    state="supported",
                                    explanation=(
                                        f"Incompatible statement pair from fixture catalog: "
                                        f"({triple_a}) is incompatible with ({triple_b})."
                                    ),
                                    evidence_chunk_ids=list(
                                        set([rel_a.evidence.chunk_id, rel_b.evidence.chunk_id])
                                    ),
                                    detector_version="conflict-detector-v1",
                                )
                            )

    return conflicts
