"""Directed, bounded, evidence-backed potential attack routes."""
from collections import deque
import hashlib

from backend.contracts.api_models import GraphEdge, GraphNode, GraphSlice, SourceView
from backend.storage.graph_store import get_graph_store

TRAVERSABLE = {"EXPLOITS", "TARGETS", "COMMUNICATES_WITH", "ACCESSES", "EXFILTRATES"}


def trace_attack_paths(workspace_id, entry_point, max_depth=3, store=None, allowed_chunk_ids=None):
    if not 1 <= max_depth <= 8:
        raise ValueError("max_depth must be between 1 and 8")
    store = store if store is not None else get_graph_store()
    with store._lock:
        entities = dict(store.entities.get(workspace_id, {}))
        relations = list(store.relations.get(workspace_id, {}).values())
        chunks = dict(store.chunks.get(workspace_id, {}))
        documents = dict(store.documents.get(workspace_id, {}))
    entry = next((name for name in entities if name.casefold() == entry_point.casefold()), None)
    limits = "Potential routes from documented relationships; connectivity alone does not establish exploitability. Negated, uncertain, conditional, and disputed links are excluded."
    result = {"entry_point": entry_point, "workspace_id": workspace_id, "paths": [],
              "reachable_assets": [], "graph_path": GraphSlice().model_dump(), "limitations": limits}
    if entry is None:
        result["limitations"] += " Entry point not found in this workspace."
        return result
    # Opposing evidence must never silently become an affirmative route.
    denied = {(r.source_entity_name, r.predicate, r.target_entity_name) for r in relations
              if r.polarity == "NEGATIVE"}
    adjacency = {}
    for relation in relations:
        key = (relation.source_entity_name, relation.predicate, relation.target_entity_name)
        chunk = chunks.get(relation.provenance.source_chunk_id)
        p = relation.provenance
        if (relation.predicate in TRAVERSABLE and relation.polarity == "AFFIRMATIVE"
                and relation.modality == "CERTAIN" and not relation.condition and key not in denied
                and (allowed_chunk_ids is None or relation.provenance.source_chunk_id in allowed_chunk_ids)
                and relation.target_entity_name in entities and chunk and chunk.document_id in documents
                and chunk.text[p.char_start:p.char_end] == p.exact_quote):
            adjacency.setdefault(relation.source_entity_name, []).append(relation)
    queue = deque([(entry, [entry], [])])
    nodes, edges, assets = {entry}, {}, set()
    while queue and len(result["paths"]) < 200:
        current, names, route = queue.popleft()
        if len(route) >= max_depth:
            continue
        for relation in sorted(adjacency.get(current, []), key=lambda r: r.id):
            target = relation.target_entity_name
            if target in names:
                continue
            next_route = route + [relation]
            next_names = names + [target]
            citations = []
            ids = []
            for r in next_route:
                p = r.provenance
                ch = chunks[p.source_chunk_id]
                doc = documents[ch.document_id]
                citation = SourceView(chunk_id=ch.id, document_id=doc.id, source_name=doc.source_name,
                                      page_number=ch.page_number, start_char=ch.start_char + p.char_start,
                                      end_char=ch.start_char + p.char_end, exact_quote=p.exact_quote,
                                      revision=ch.revision).model_dump()
                citations.append(citation)
                edge_id = f"rel:{r.id}"
                ids.append(edge_id)
                edges[edge_id] = GraphEdge(id=edge_id, source=f"ent:{r.source_entity_name}",
                    target=f"ent:{r.target_entity_name}", predicate=r.predicate,
                    exact_quote=p.exact_quote, provenance=citation)
            path_id = "path:" + hashlib.sha256("|".join(ids).encode()).hexdigest()[:16]
            result["paths"].append({"path_id": path_id, "nodes": next_names, "edge_ids": ids, "citations": citations})
            nodes.update(next_names)
            if entities[target].label == "Asset":
                assets.add(target)
            queue.append((target, next_names, next_route))
            if len(result["paths"]) >= 200:
                break
    if queue:
        result["limitations"] += " Search stopped at the configured depth or 200-path limit."
    result["reachable_assets"] = sorted(assets)
    result["graph_path"] = GraphSlice(nodes=[GraphNode(id=f"ent:{name}", name=name,
        label=entities[name].label, properties=entities[name].properties) for name in sorted(nodes)],
        edges=list(edges.values()), highlighted_path_ids=list(edges)).model_dump()
    return result
