"""Graph store implementing lexical, domain, and topic layers with provenance and conflict tracking."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Set, Tuple
from backend.contracts.models import (
    Chunk,
    Document,
    Entity,
    ExtractionBatch,
    Relation,
    Topic,
    TopicAssignment,
    ValueNode,
)
from backend.contracts.api_models import (
    ConflictPair,
    GraphEdge,
    GraphNode,
    GraphSlice,
    SourceView,
)


class GraphStore:
    """Thread-safe multi-workspace Graph Store managing lexical, domain, and topic layers."""

    def __init__(self):
        self._lock = threading.RLock()
        # workspace_id -> document_id -> Document
        self.documents: Dict[str, Dict[str, Document]] = {}
        # workspace_id -> chunk_id -> Chunk
        self.chunks: Dict[str, Dict[str, Chunk]] = {}
        # workspace_id -> entity_name -> Entity (aggregated canonical)
        self.entities: Dict[str, Dict[str, Entity]] = {}
        # workspace_id -> entity_name -> Set[source_doc_id] (for shared entity provenance)
        self.entity_doc_refs: Dict[str, Dict[str, Set[str]]] = {}
        # workspace_id -> value_id -> ValueNode
        self.values: Dict[str, Dict[str, ValueNode]] = {}
        # workspace_id -> relation_id -> Relation
        self.relations: Dict[str, Dict[str, Relation]] = {}
        # workspace_id -> relation_id -> Set[source_doc_id]
        self.relation_doc_refs: Dict[str, Dict[str, Set[str]]] = {}
        # workspace_id -> topic_id -> Topic
        self.topics: Dict[str, Dict[str, Topic]] = {}
        # workspace_id -> List[TopicAssignment]
        self.topic_assignments: Dict[str, List[TopicAssignment]] = {}
        # workspace_id -> List[ConflictPair]
        self.conflicts: Dict[str, List[ConflictPair]] = {}

    def _ensure_workspace(self, ws: str) -> None:
        if ws not in self.documents:
            self.documents[ws] = {}
            self.chunks[ws] = {}
            self.entities[ws] = {}
            self.entity_doc_refs[ws] = {}
            self.values[ws] = {}
            self.relations[ws] = {}
            self.relation_doc_refs[ws] = {}
            self.topics[ws] = {}
            self.topic_assignments[ws] = []
            self.conflicts[ws] = []

    def get_document(self, workspace_id: str, document_id: str) -> Optional[Document]:
        with self._lock:
            return self.documents.get(workspace_id, {}).get(document_id)

    def get_document_by_hash(self, workspace_id: str, content_hash: str) -> Optional[Document]:
        with self._lock:
            for doc in self.documents.get(workspace_id, {}).values():
                if doc.content_hash == content_hash:
                    return doc
            return None

    def get_chunk(self, workspace_id: str, chunk_id: str) -> Optional[Chunk]:
        with self._lock:
            return self.chunks.get(workspace_id, {}).get(chunk_id)

    def get_chunk_source(self, chunk_id: str) -> Optional[SourceView]:
        with self._lock:
            for ws, chunks in self.chunks.items():
                if chunk_id in chunks:
                    chunk = chunks[chunk_id]
                    doc = self.documents[ws].get(chunk.document_id)
                    source_name = doc.source_name if doc else "unknown"
                    return SourceView(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        source_name=source_name,
                        page_number=chunk.page_number,
                        start_char=chunk.start_char,
                        end_char=chunk.end_char,
                        exact_quote=chunk.text[:200],
                        revision=chunk.revision,
                    )
            return None

    def publish_batch(self, batch: ExtractionBatch) -> None:
        """Publishes an extraction batch into the graph atomically."""
        with self._lock:
            ws = batch.workspace_id
            self._ensure_workspace(ws)
            doc_id = batch.document.id

            # 1. Store or update document
            self.documents[ws][doc_id] = batch.document

            # 2. Store chunks
            for ch in batch.chunks:
                self.chunks[ws][ch.id] = ch

            # 3. Store values
            for val in batch.aggregated_values:
                self.values[ws][val.id] = val

            # 4. Store entities with multi-document reference tracking
            for ent in batch.aggregated_entities:
                self.entities[ws][ent.name] = ent
                if ent.name not in self.entity_doc_refs[ws]:
                    self.entity_doc_refs[ws][ent.name] = set()
                self.entity_doc_refs[ws][ent.name].add(doc_id)

            # 5. Store relations with multi-document reference tracking
            for rel in batch.aggregated_relations:
                self.relations[ws][rel.id] = rel
                if rel.id not in self.relation_doc_refs[ws]:
                    self.relation_doc_refs[ws][rel.id] = set()
                self.relation_doc_refs[ws][rel.id].add(doc_id)

            # 6. Detect contradictions across relations
            self._detect_conflicts(ws)

    def delete_document(self, workspace_id: str, document_id: str) -> None:
        """Deletes a document and cleans up orphaned chunks/relations while preserving shared entities."""
        with self._lock:
            if workspace_id not in self.documents or document_id not in self.documents[workspace_id]:
                return

            # Remove document
            del self.documents[workspace_id][document_id]

            # Remove document chunks
            chunks_to_remove = [
                cid for cid, ch in self.chunks[workspace_id].items() if ch.document_id == document_id
            ]
            for cid in chunks_to_remove:
                del self.chunks[workspace_id][cid]

            # Clean up relations
            rels_to_remove = []
            for rel_id, doc_set in self.relation_doc_refs[workspace_id].items():
                doc_set.discard(document_id)
                if not doc_set:
                    rels_to_remove.append(rel_id)

            for rel_id in rels_to_remove:
                self.relations[workspace_id].pop(rel_id, None)
                self.relation_doc_refs[workspace_id].pop(rel_id, None)

            # Clean up entities (only remove if no other document references it)
            ents_to_remove = []
            for ent_name, doc_set in self.entity_doc_refs[workspace_id].items():
                doc_set.discard(document_id)
                if not doc_set:
                    ents_to_remove.append(ent_name)

            for ent_name in ents_to_remove:
                self.entities[workspace_id].pop(ent_name, None)
                self.entity_doc_refs[workspace_id].pop(ent_name, None)

            # Clean up topic assignments pointing to removed chunks
            removed_chunks_set = set(chunks_to_remove)
            self.topic_assignments[workspace_id] = [
                ta for ta in self.topic_assignments[workspace_id] if ta.chunk_id not in removed_chunks_set
            ]

            # Refresh conflicts
            self._detect_conflicts(workspace_id)

    def _detect_conflicts(self, ws: str) -> None:
        """Detects contradictions between relations or assertions across documents."""
        self.conflicts[ws] = []
        rels = list(self.relations.get(ws, {}).values())

        for i in range(len(rels)):
            for j in range(i + 1, len(rels)):
                r1 = rels[i]
                r2 = rels[j]

                # Conflict condition 1: Same source & predicate, opposite polarity
                is_polarity_conflict = (
                    r1.source_entity_name.lower() == r2.source_entity_name.lower()
                    and r1.predicate.lower() == r2.predicate.lower()
                    and r1.polarity != r2.polarity
                )

                # Conflict condition 2: Same source & predicate, distinct target entities/values
                is_target_conflict = False
                if (
                    r1.source_entity_name.lower() == r2.source_entity_name.lower()
                    and r1.predicate.lower() == r2.predicate.lower()
                ):
                    t1 = (r1.target_entity_name or r1.target_value_id or "").lower()
                    t2 = (r2.target_entity_name or r2.target_value_id or "").lower()
                    if t1 and t2 and t1 != t2:
                        is_target_conflict = True

                # Conflict condition 3: Planted catalog incompatible pairs
                is_planted_conflict = False
                try:
                    from backend.conflicts.detector import PLANTED_INCOMPATIBLE_PAIRS
                    s1 = r1.source_entity_name.lower().replace(" ", "_")
                    p1 = r1.predicate.lower().replace(" ", "_")
                    o1 = (r1.target_entity_name or r1.target_value_id or "").lower().replace(" ", "_")
                    s2 = r2.source_entity_name.lower().replace(" ", "_")
                    p2 = r2.predicate.lower().replace(" ", "_")
                    o2 = (r2.target_entity_name or r2.target_value_id or "").lower().replace(" ", "_")
                    t1 = (s1, p1, o1)
                    t2 = (s2, p2, o2)
                    for pair_a, pair_b in PLANTED_INCOMPATIBLE_PAIRS:
                        if (t1 == pair_a and t2 == pair_b) or (t1 == pair_b and t2 == pair_a):
                            is_planted_conflict = True
                            break
                except Exception:
                    pass

                if is_polarity_conflict or is_target_conflict or is_planted_conflict:
                    chunk1 = self.chunks[ws].get(r1.provenance.source_chunk_id)
                    chunk2 = self.chunks[ws].get(r2.provenance.source_chunk_id)

                    doc1_id = chunk1.document_id if chunk1 else "doc-unknown"
                    doc2_id = chunk2.document_id if chunk2 else "doc-unknown"

                    doc1 = self.documents[ws].get(doc1_id)
                    doc2 = self.documents[ws].get(doc2_id)

                    stmt1 = f"{r1.source_entity_name} {r1.predicate} {r1.target_entity_name or r1.target_value_id or ''} [{r1.polarity}]"
                    stmt2 = f"{r2.source_entity_name} {r2.predicate} {r2.target_entity_name or r2.target_value_id or ''} [{r2.polarity}]"

                    conflict = ConflictPair(
                        statement_a=stmt1,
                        source_a={
                            "document_id": doc1_id,
                            "source_name": doc1.source_name if doc1 else "Source 1",
                            "chunk_id": r1.provenance.source_chunk_id,
                            "quote": r1.provenance.exact_quote,
                        },
                        statement_b=stmt2,
                        source_b={
                            "document_id": doc2_id,
                            "source_name": doc2.source_name if doc2 else "Source 2",
                            "chunk_id": r2.provenance.source_chunk_id,
                            "quote": r2.provenance.exact_quote,
                        },
                        description=f"Contradiction detected between {stmt1} and {stmt2}.",
                    )
                    self.conflicts[ws].append(conflict)

        # Chunk-level assertion scan for opposing claims (e.g. open vs closed, public vs private, deployed vs deprecated)
        opposing_pairs = [
            ("open", "closed"),
            ("publicly accessible", "strictly private"),
            ("deployed", "retracted"),
            ("deprecated", "production"),
        ]
        ws_chunks = list(self.chunks.get(ws, {}).values())
        for term_a, term_b in opposing_pairs:
            chunks_a = [c for c in ws_chunks if term_a in c.text.lower()]
            chunks_b = [c for c in ws_chunks if term_b in c.text.lower()]
            for ca in chunks_a:
                for cb in chunks_b:
                    if ca.document_id != cb.document_id:
                        doc_a = self.documents[ws].get(ca.document_id)
                        doc_b = self.documents[ws].get(cb.document_id)
                        pair = ConflictPair(
                            statement_a=f"Asserted as {term_a.upper()}",
                            source_a={
                                "document_id": ca.document_id,
                                "source_name": doc_a.source_name if doc_a else "Source A",
                                "chunk_id": ca.id,
                                "quote": ca.text[:150],
                            },
                            statement_b=f"Asserted as {term_b.upper()}",
                            source_b={
                                "document_id": cb.document_id,
                                "source_name": doc_b.source_name if doc_b else "Source B",
                                "chunk_id": cb.id,
                                "quote": cb.text[:150],
                            },
                            description=f"Contradiction between assertion '{term_a}' and '{term_b}'.",
                        )
                        # Check if not already in conflicts
                        if not any(c.source_a.get("chunk_id") == ca.id and c.source_b.get("chunk_id") == cb.id for c in self.conflicts[ws]):
                            self.conflicts[ws].append(pair)


    def register_topic(self, topic: Topic) -> None:
        with self._lock:
            self._ensure_workspace(topic.workspace_id)
            self.topics[topic.workspace_id][topic.id] = topic

    def assign_topic(self, workspace_id: str, assignment: TopicAssignment) -> None:
        with self._lock:
            self._ensure_workspace(workspace_id)
            self.topic_assignments[workspace_id].append(assignment)

    def get_topics(self, workspace_id: str) -> List[Topic]:
        with self._lock:
            return list(self.topics.get(workspace_id, {}).values())

    def get_topic_chunks(self, workspace_id: str, topic_id: str) -> List[str]:
        with self._lock:
            return [
                ta.chunk_id
                for ta in self.topic_assignments.get(workspace_id, [])
                if ta.topic_id == topic_id
            ]

    def traverse_subgraph(
        self,
        workspace_id: str,
        seed_entity_names: List[str],
        seed_chunk_ids: List[str],
        max_hops: int = 2,
    ) -> GraphSlice:
        """
        Traverses a bounded neighborhood around seed entities and chunks.
        Returns a rich GraphSlice containing nodes, edges, and highlighted path IDs.
        """
        with self._lock:
            self._ensure_workspace(workspace_id)
            nodes_dict: Dict[str, GraphNode] = {}
            edges_dict: Dict[str, GraphEdge] = {}
            highlighted_ids: Set[str] = set()

            ws_ents = self.entities.get(workspace_id, {})
            ws_rels = self.relations.get(workspace_id, {})
            ws_chunks = self.chunks.get(workspace_id, {})
            ws_topics = self.topics.get(workspace_id, {})
            ws_conflicts = self.conflicts.get(workspace_id, [])

            # Determine conflict relation IDs
            conflict_quotes = set()
            for conf in ws_conflicts:
                conflict_quotes.add(conf.source_a.get("quote", ""))
                conflict_quotes.add(conf.source_b.get("quote", ""))

            # 1. Add seed entities
            visited_entities: Set[str] = set()
            frontier: Set[str] = set()

            for name in seed_entity_names:
                for ent_key, ent in ws_ents.items():
                    if name.lower() in ent_key.lower():
                        frontier.add(ent.name)
                        node_id = f"ent:{ent.name}"
                        nodes_dict[node_id] = GraphNode(
                            id=node_id,
                            label=ent.label,
                            name=ent.name,
                            type="entity",
                            properties=ent.properties,
                            conflict_status="conflicting" if any(q in str(ent.properties) for q in conflict_quotes) else None,
                        )
                        highlighted_ids.add(node_id)

            # 2. Add seed chunks
            for cid in seed_chunk_ids:
                if cid in ws_chunks:
                    ch = ws_chunks[cid]
                    c_node_id = f"chunk:{ch.id}"
                    nodes_dict[c_node_id] = GraphNode(
                        id=c_node_id,
                        label="Chunk",
                        name=f"Chunk {ch.chunk_index} (P.{ch.page_number})",
                        type="chunk",
                        document_id=ch.document_id,
                        properties={"text": ch.text[:150], "page": ch.page_number},
                    )
                    highlighted_ids.add(c_node_id)

            # 3. Breadth-first traversal up to max_hops
            for _ in range(max_hops):
                next_frontier: Set[str] = set()
                for rel_id, rel in ws_rels.items():
                    s_name = rel.source_entity_name
                    t_name = rel.target_entity_name or rel.target_value_id or ""

                    is_relevant = (s_name in frontier) or (t_name in frontier)
                    # Also link if chunk is in seed chunks
                    if rel.provenance.source_chunk_id in seed_chunk_ids:
                        is_relevant = True

                    if is_relevant:
                        # Source node
                        s_id = f"ent:{s_name}"
                        if s_id not in nodes_dict and s_name in ws_ents:
                            ent = ws_ents[s_name]
                            nodes_dict[s_id] = GraphNode(
                                id=s_id,
                                label=ent.label,
                                name=ent.name,
                                type="entity",
                                properties=ent.properties,
                            )
                        # Target node
                        t_id = f"ent:{t_name}"
                        if t_id not in nodes_dict and t_name in ws_ents:
                            ent = ws_ents[t_name]
                            nodes_dict[t_id] = GraphNode(
                                id=t_id,
                                label=ent.label,
                                name=ent.name,
                                type="entity",
                                properties=ent.properties,
                            )
                        elif t_id not in nodes_dict and rel.target_value_id in self.values.get(workspace_id, {}):
                            val = self.values[workspace_id][rel.target_value_id]
                            nodes_dict[t_id] = GraphNode(
                                id=t_id,
                                label="Value",
                                name=val.raw_value,
                                type="value",
                                properties={"val_type": val.val_type, "normalized": val.normalized_value},
                            )

                        # Edge
                        e_id = f"rel:{rel.id}"
                        is_conflict = rel.provenance.exact_quote in conflict_quotes
                        edges_dict[e_id] = GraphEdge(
                            id=e_id,
                            source=s_id,
                            target=t_id,
                            predicate=rel.predicate,
                            edge_type="factual",
                            polarity=rel.polarity,
                            modality=rel.modality,
                            exact_quote=rel.provenance.exact_quote,
                            provenance={
                                "chunk_id": rel.provenance.source_chunk_id,
                                "method": rel.provenance.extraction_method,
                            },
                            conflict_status="conflicting" if is_conflict else None,
                        )
                        highlighted_ids.add(e_id)
                        if s_name not in visited_entities:
                            next_frontier.add(s_name)
                        if t_name not in visited_entities:
                            next_frontier.add(t_name)

                visited_entities.update(frontier)
                frontier = next_frontier
                if not frontier:
                    break

            # 4. Attach topic membership edges for chunks in slice
            for ta in self.topic_assignments.get(workspace_id, []):
                chunk_node_id = f"chunk:{ta.chunk_id}"
                if chunk_node_id in nodes_dict and ta.topic_id in ws_topics:
                    top = ws_topics[ta.topic_id]
                    top_node_id = f"topic:{top.id}"
                    if top_node_id not in nodes_dict:
                        nodes_dict[top_node_id] = GraphNode(
                            id=top_node_id,
                            label="Topic",
                            name=top.label,
                            type="topic",
                            properties={"slug": top.slug, "description": top.description},
                        )
                    edge_id = f"top_edge:{top.id}-{ta.chunk_id}"
                    edges_dict[edge_id] = GraphEdge(
                        id=edge_id,
                        source=top_node_id,
                        target=chunk_node_id,
                        predicate="HAS_MEMBER",
                        edge_type="topic_membership",
                        modality="CERTAIN",
                    )

            # 5. Attach provenance edges from chunks to documents
            for n_id, node in list(nodes_dict.items()):
                if node.type == "chunk" and node.document_id:
                    doc = self.documents[workspace_id].get(node.document_id)
                    if doc:
                        doc_node_id = f"doc:{doc.id}"
                        if doc_node_id not in nodes_dict:
                            nodes_dict[doc_node_id] = GraphNode(
                                id=doc_node_id,
                                label="Document",
                                name=doc.source_name,
                                type="document",
                                properties={"source_type": doc.source_type, "revision": doc.revision},
                            )
                        edge_id = f"prov_edge:{node.id}-{doc_node_id}"
                        edges_dict[edge_id] = GraphEdge(
                            id=edge_id,
                            source=node.id,
                            target=doc_node_id,
                            predicate="FROM_DOCUMENT",
                            edge_type="provenance",
                            modality="CERTAIN",
                        )

            return GraphSlice(
                nodes=list(nodes_dict.values()),
                edges=list(edges_dict.values()),
                highlighted_path_ids=list(highlighted_ids),
            )

    def get_full_workspace_graph(self, workspace_id: str) -> GraphSlice:
        """Returns the entire graph for the workspace."""
        all_ents = list(self.entities.get(workspace_id, {}).keys())
        all_chunks = list(self.chunks.get(workspace_id, {}).keys())
        return self.traverse_subgraph(workspace_id, all_ents, all_chunks, max_hops=1)

    def clear(self) -> None:
        with self._lock:
            self.documents.clear()
            self.chunks.clear()
            self.entities.clear()
            self.entity_doc_refs.clear()
            self.values.clear()
            self.relations.clear()
            self.relation_doc_refs.clear()
            self.topics.clear()
            self.topic_assignments.clear()
            self.conflicts.clear()


_default_graph_store = GraphStore()


def get_graph_store() -> GraphStore:
    return _default_graph_store
