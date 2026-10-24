"""
Storage interfaces and in-memory repository implementation.
Conforms to Person 1's storage specification in 01-storage-contracts-lifecycle.md.
Provides active-revision filtering, bounded Cypher-like traversal, vector search, and lexical search.
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple
from dataclasses import dataclass, field

from backend.contracts.models import (
    Chunk,
    Conflict,
    Document,
    Entity,
    EvidencePackage,
    EvidencePath,
    GraphEdgeView,
    GraphNodeView,
    GraphSlice,
    ProvenanceLink,
    Relation,
    Revision,
    Topic,
    TopicMembership,
    Value,
    DerivedDelta,
)


@dataclass
class CorpusSnapshot:
    workspace_id: str
    epoch: int
    active_revisions: Dict[str, str] = field(default_factory=dict)  # doc_id -> rev_id
    documents: Dict[str, Document] = field(default_factory=dict)     # doc_id -> Document
    revisions: Dict[str, Revision] = field(default_factory=dict)     # rev_id -> Revision
    chunks: Dict[str, Chunk] = field(default_factory=dict)           # chunk_id -> Chunk
    entities: Dict[str, Entity] = field(default_factory=dict)       # entity_id -> Entity
    values: Dict[str, Value] = field(default_factory=dict)           # value_id -> Value
    relations: Dict[str, Relation] = field(default_factory=dict)     # relation_id -> Relation
    topics: Dict[str, Topic] = field(default_factory=dict)           # topic_id -> Topic
    topic_memberships: List[TopicMembership] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)
    chunk_embeddings: Dict[str, List[float]] = field(default_factory=dict)  # chunk_id -> vector

    def is_chunk_active(self, chunk: Chunk) -> bool:
        if chunk.workspace_id != self.workspace_id:
            return False
        return self.active_revisions.get(chunk.document_id) == chunk.revision_id

    def is_relation_active(self, relation: Relation) -> bool:
        if relation.workspace_id != self.workspace_id:
            return False
        chunk = self.chunks.get(relation.evidence.chunk_id)
        if not chunk:
            return False
        return self.is_chunk_active(chunk)

    def get_active_chunks(self) -> List[Chunk]:
        return [c for c in self.chunks.values() if self.is_chunk_active(c)]

    def get_active_relations(self) -> List[Relation]:
        return [r for r in self.relations.values() if self.is_relation_active(r)]


class StorageRepositoryProtocol(Protocol):
    def get_snapshot(self, workspace_id: str) -> CorpusSnapshot: ...
    def vector_candidates(self, vector: List[float], snapshot: CorpusSnapshot, limit: int, topic_ids: Optional[List[str]] = None) -> List[str]: ...
    def lexical_candidates(self, text: str, snapshot: CorpusSnapshot, limit: int, topic_ids: Optional[List[str]] = None) -> List[str]: ...
    def fetch_evidence(self, chunk_ids: List[str], snapshot: CorpusSnapshot) -> EvidencePackage: ...
    def expand_paths(self, entity_ids: List[str], snapshot: CorpusSnapshot, max_hops: int, topic_ids: Optional[List[str]] = None) -> List[EvidencePath]: ...
    def publish(self, operation_id: str, delta: DerivedDelta, expected_epoch: int) -> int: ...


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


class InMemoryStorageRepository:
    """
    In-memory reference implementation of Person 1's repository.
    Enforces workspace boundaries, active-revision isolation, and bounds.
    """

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        self.epoch = 1
        self.documents: Dict[str, Document] = {}
        self.revisions: Dict[str, Revision] = {}
        self.chunks: Dict[str, Chunk] = {}
        self.entities: Dict[str, Entity] = {}
        self.values: Dict[str, Value] = {}
        self.relations: Dict[str, Relation] = {}
        self.topics: Dict[str, Topic] = {}
        self.topic_memberships: List[TopicMembership] = []
        self.conflicts: List[Conflict] = []
        self.chunk_embeddings: Dict[str, List[float]] = {}
        self.active_revisions: Dict[str, str] = {}  # doc_id -> rev_id

    def add_document(self, doc: Document) -> None:
        self.documents[doc.id] = doc
        if doc.active_revision_id:
            self.active_revisions[doc.id] = doc.active_revision_id

    def add_revision(self, rev: Revision) -> None:
        self.revisions[rev.id] = rev

    def add_chunk(self, chunk: Chunk, embedding: Optional[List[float]] = None) -> None:
        self.chunks[chunk.id] = chunk
        if embedding:
            self.chunk_embeddings[chunk.id] = embedding

    def add_entity(self, entity: Entity) -> None:
        self.entities[entity.id] = entity

    def add_value(self, val: Value) -> None:
        self.values[val.id] = val

    def add_relation(self, rel: Relation) -> None:
        self.relations[rel.id] = rel

    def add_topic(self, topic: Topic) -> None:
        self.topics[topic.id] = topic

    def add_topic_membership(self, mem: TopicMembership) -> None:
        self.topic_memberships.append(mem)

    def add_conflict(self, conf: Conflict) -> None:
        self.conflicts.append(conf)

    def get_snapshot(self, workspace_id: str) -> CorpusSnapshot:
        if workspace_id != self.workspace_id:
            return CorpusSnapshot(workspace_id=workspace_id, epoch=0)
        return CorpusSnapshot(
            workspace_id=self.workspace_id,
            epoch=self.epoch,
            active_revisions=dict(self.active_revisions),
            documents=dict(self.documents),
            revisions=dict(self.revisions),
            chunks=dict(self.chunks),
            entities=dict(self.entities),
            values=dict(self.values),
            relations=dict(self.relations),
            topics=dict(self.topics),
            topic_memberships=list(self.topic_memberships),
            conflicts=list(self.conflicts),
            chunk_embeddings=dict(self.chunk_embeddings),
        )

    def _get_allowed_chunks_for_topics(self, snapshot: CorpusSnapshot, topic_ids: Optional[List[str]]) -> Optional[Set[str]]:
        if not topic_ids:
            return None
        allowed: Set[str] = set()
        for mem in snapshot.topic_memberships:
            if mem.topic_id in topic_ids:
                allowed.add(mem.chunk_id)
        return allowed

    def vector_candidates(
        self,
        vector: List[float],
        snapshot: CorpusSnapshot,
        limit: int = 10,
        topic_ids: Optional[List[str]] = None,
    ) -> List[str]:
        allowed_chunk_ids = self._get_allowed_chunks_for_topics(snapshot, topic_ids)
        scored: List[Tuple[float, str]] = []
        for chunk_id, emb in snapshot.chunk_embeddings.items():
            chunk = snapshot.chunks.get(chunk_id)
            if not chunk or not snapshot.is_chunk_active(chunk):
                continue
            if allowed_chunk_ids is not None and chunk_id not in allowed_chunk_ids:
                continue
            sim = _cosine_similarity(vector, emb)
            scored.append((sim, chunk_id))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [cid for _, cid in scored[:limit]]

    def lexical_candidates(
        self,
        text: str,
        snapshot: CorpusSnapshot,
        limit: int = 10,
        topic_ids: Optional[List[str]] = None,
    ) -> List[str]:
        allowed_chunk_ids = self._get_allowed_chunks_for_topics(snapshot, topic_ids)
        query_terms = set(text.lower().split())
        scored: List[Tuple[float, str]] = []

        for chunk in snapshot.get_active_chunks():
            if allowed_chunk_ids is not None and chunk.id not in allowed_chunk_ids:
                continue
            chunk_text = chunk.text.lower()
            # Simple term frequency + exact match bonus
            score = 0.0
            if text.lower() in chunk_text:
                score += 5.0
            for term in query_terms:
                if len(term) > 2 and term in chunk_text:
                    score += 1.0
            if score > 0.0:
                scored.append((score, chunk.id))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [cid for _, cid in scored[:limit]]

    def fetch_evidence(self, chunk_ids: List[str], snapshot: CorpusSnapshot) -> EvidencePackage:
        active_chunks = [snapshot.chunks[cid] for cid in chunk_ids if cid in snapshot.chunks and snapshot.is_chunk_active(snapshot.chunks[cid])]
        active_chunk_ids = {c.id for c in active_chunks}

        # Active relations directly supported by these chunks
        relations = [
            rel for rel in snapshot.get_active_relations()
            if rel.evidence.chunk_id in active_chunk_ids
        ]

        # Entities and values involved
        entity_ids: Set[str] = set()
        value_ids: Set[str] = set()
        for rel in relations:
            entity_ids.add(rel.subject_id)
            if rel.object_entity_id:
                entity_ids.add(rel.object_entity_id)
            if rel.object_value_id:
                value_ids.add(rel.object_value_id)

        entities = [snapshot.entities[eid] for eid in entity_ids if eid in snapshot.entities]
        values = [snapshot.values[vid] for vid in value_ids if vid in snapshot.values]

        # Active conflicts relating to these relations or chunks
        rel_ids = {r.id for r in relations}
        conflicts = [
            c for c in snapshot.conflicts
            if c.left_relation_id in rel_ids or c.right_relation_id in rel_ids
            or any(cid in active_chunk_ids for cid in c.evidence_chunk_ids)
        ]

        # Topics associated with these chunks
        chunk_topics: Set[str] = set()
        for mem in snapshot.topic_memberships:
            if mem.chunk_id in active_chunk_ids:
                chunk_topics.add(mem.topic_id)
        topics = [snapshot.topics[tid] for tid in chunk_topics if tid in snapshot.topics and snapshot.topics[tid].active]

        return EvidencePackage(
            workspace_id=snapshot.workspace_id,
            corpus_epoch=snapshot.epoch,
            chunks=active_chunks,
            relations=relations,
            entities=entities,
            values=values,
            paths=[],
            topics=topics,
            conflicts=conflicts,
            searched_count=len(active_chunks),
            available_count=len(snapshot.get_active_chunks()),
        )

    def expand_paths(
        self,
        entity_ids: List[str],
        snapshot: CorpusSnapshot,
        max_hops: int = 2,
        topic_ids: Optional[List[str]] = None,
    ) -> List[EvidencePath]:
        """
        Bounded graph expansion: max 4 hops, max 200 nodes, max 300 edges, max 5 paths.
        Preserves direct domain edges + explicit provenance Chunk -> Revision -> Document.
        Enforces topic scope filtering on every edge.
        """
        max_hops = min(max_hops, 4)
        allowed_chunk_ids = self._get_allowed_chunks_for_topics(snapshot, topic_ids)
        active_relations = snapshot.get_active_relations()

        # Build adjacency
        # Adjacency: entity_id -> list of (Relation, target_entity_id)
        adj: Dict[str, List[Tuple[Relation, str]]] = {}
        for rel in active_relations:
            if allowed_chunk_ids is not None and rel.evidence.chunk_id not in allowed_chunk_ids:
                continue
            if not rel.object_entity_id:
                continue
            adj.setdefault(rel.subject_id, []).append((rel, rel.object_entity_id))
            # Also allow reverse traversal for discovery
            adj.setdefault(rel.object_entity_id, []).append((rel, rel.subject_id))

        paths: List[EvidencePath] = []
        path_count = 0

        for start_id in entity_ids:
            if start_id not in snapshot.entities:
                continue
            # BFS queue: (current_node, [relations_traversed], [node_sequence])
            queue: List[Tuple[str, List[Relation], List[str]]] = [(start_id, [], [start_id])]
            visited_at_depth: Set[Tuple[str, int]] = {(start_id, 0)}

            while queue and path_count < 5:
                curr, rel_path, node_seq = queue.pop(0)
                if rel_path:
                    # Construct an EvidencePath
                    path_id = f"path_{len(paths) + 1}_{start_id}_{curr}"
                    edge_views: List[GraphEdgeView] = []
                    provenance_links: List[ProvenanceLink] = []

                    for r in rel_path:
                        edge_views.append(
                            GraphEdgeView(
                                id=f"edge_{r.id}",
                                source_id=r.subject_id,
                                target_id=r.object_entity_id or "",
                                predicate=r.predicate,
                                relation_id=r.id,
                                source_chunk_id=r.evidence.chunk_id,
                                is_topic_membership=False,
                                properties={
                                    "polarity": r.polarity,
                                    "modality": r.modality,
                                    "predicate_original": r.predicate_original,
                                },
                            )
                        )
                        chunk = snapshot.chunks.get(r.evidence.chunk_id)
                        if chunk:
                            provenance_links.append(
                                ProvenanceLink(
                                    chunk_id=chunk.id,
                                    revision_id=chunk.revision_id,
                                    document_id=chunk.document_id,
                                )
                            )

                    paths.append(
                        EvidencePath(
                            path_id=path_id,
                            node_ids=list(node_seq),
                            edges=edge_views,
                            provenance_links=provenance_links,
                        )
                    )
                    path_count += 1
                    if path_count >= 5:
                        break

                if len(rel_path) < max_hops:
                    for rel, nxt in adj.get(curr, []):
                        if nxt not in node_seq and (nxt, len(rel_path) + 1) not in visited_at_depth:
                            visited_at_depth.add((nxt, len(rel_path) + 1))
                            queue.append((nxt, rel_path + [rel], node_seq + [nxt]))

        return paths

    def publish(self, operation_id: str, delta: DerivedDelta, expected_epoch: int) -> int:
        if self.epoch != expected_epoch:
            raise ValueError(f"Epoch mismatch: expected {expected_epoch}, current {self.epoch}")
        # Apply delta
        for t in delta.new_topics:
            self.topics[t.id] = t
        for t in delta.updated_topics:
            self.topics[t.id] = t
        for m in delta.new_memberships:
            self.topic_memberships.append(m)
        if delta.deleted_membership_ids:
            del_set = set(delta.deleted_membership_ids)
            self.topic_memberships = [
                m for m in self.topic_memberships if (m.topic_id, m.chunk_id) not in del_set
            ]
        for c in delta.new_conflicts:
            self.conflicts.append(c)
        if delta.retired_conflict_ids:
            ret_set = set(delta.retired_conflict_ids)
            self.conflicts = [c for c in self.conflicts if c.id not in ret_set]

        self.epoch += 1
        return self.epoch
