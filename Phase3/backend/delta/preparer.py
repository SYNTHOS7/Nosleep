"""
Delta preparation module.
Prepares DerivedDelta containing incremental topic memberships, topic updates,
and detected conflicts for Person 1's publication lock.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple

from backend.contracts.models import (
    Chunk,
    Conflict,
    DerivedDelta,
    Relation,
    Topic,
    TopicMembership,
)
from backend.storage.interface import CorpusSnapshot
from backend.topics.manager import TopicManager
from backend.conflicts.detector import find_conflicts


def prepare_delta(
    operation_id: str,
    staged_revision_id: str,
    snapshot: CorpusSnapshot,
    topic_manager: Optional[TopicManager] = None,
) -> DerivedDelta:
    """
    Computes incremental topic assignments and conflict detections for a staged revision.
    Produces DerivedDelta without altering lifecycle state or active repository records.
    """
    topic_manager = topic_manager or TopicManager()

    # 1. Identify staged chunks and relations
    staged_chunks = [c for c in snapshot.chunks.values() if c.revision_id == staged_revision_id]
    staged_relations = [r for r in snapshot.relations.values() if r.revision_id == staged_revision_id]

    # Staged embeddings
    staged_embeddings = {
        c.id: snapshot.chunk_embeddings[c.id]
        for c in staged_chunks
        if c.id in snapshot.chunk_embeddings
    }

    # 2. Incremental topic assignments
    active_topics = [t for t in snapshot.topics.values() if t.active]
    new_memberships: List[TopicMembership] = []
    updated_topics: List[Topic] = []

    if active_topics and staged_chunks:
        new_memberships, updated_topics = topic_manager.assign_staged_chunks_to_topics(
            staged_chunks=staged_chunks,
            staged_embeddings=staged_embeddings,
            existing_topics=active_topics,
        )

    # 3. Conflict detection
    # Active relations in snapshot + staged relations
    all_relations_for_detection = snapshot.get_active_relations() + staged_relations
    staged_rel_ids = [r.id for r in staged_relations]

    detected_conflicts = find_conflicts(
        active_relations=all_relations_for_detection,
        changed_relation_ids=staged_rel_ids,
        values_by_id=snapshot.values,
    )

    # Filter out conflicts that were already present in snapshot
    existing_conf_keys = {
        (min(c.left_relation_id, c.right_relation_id), max(c.left_relation_id, c.right_relation_id), c.kind)
        for c in snapshot.conflicts
    }

    new_conflicts = [
        c for c in detected_conflicts
        if (min(c.left_relation_id, c.right_relation_id), max(c.left_relation_id, c.right_relation_id), c.kind)
        not in existing_conf_keys
    ]

    return DerivedDelta(
        operation_id=operation_id,
        staged_revision_id=staged_revision_id,
        new_topics=[],
        updated_topics=updated_topics,
        new_memberships=new_memberships,
        deleted_membership_ids=[],
        new_conflicts=new_conflicts,
        retired_conflict_ids=[],
    )
