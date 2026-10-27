"""Exercise real SQLite transactions and lifecycle restoration without cloud services."""
import sqlite3
import pytest

from backend.storage.local_store import LocalStore, LocalVectorStore
from backend.storage.graph_store import GraphStore
from backend.services.attack_path_service import trace_attack_paths
from test_cyber_and_hosted_storage import publish


def batch_for(workspace="cyber", doc="topology", text="Gateway accesses Database."):
    batch = publish(GraphStore(), text, workspace, doc)
    batch.vectors = {batch.chunks[0].id: [1.0] + [0.0] * 767}
    return batch


def restore(path):
    graph, vectors = GraphStore(), LocalVectorStore(path)
    for batch in vectors.persistence.load_batches():
        graph.publish_batch(batch)
        vectors.cache_vectors(batch.workspace_id, batch.vectors)
    return graph, vectors


def test_restart_restores_graph_citations_and_scoped_search(tmp_path):
    path = tmp_path / "aegis.sqlite3"
    store = LocalStore(path)
    store.publish(batch_for())
    store.publish(batch_for("other"))
    graph, vectors = restore(path)
    route = trace_attack_paths("cyber", "Gateway", 3, graph)["paths"][0]
    assert route["nodes"] == ["Gateway", "Database"]
    assert route["citations"][0]["exact_quote"] == "Gateway accesses Database."
    assert vectors.query("cyber", [1.0] + [0.0] * 767) == [("topology-chunk", 1.0)]
    assert vectors.query("cyber", [1.0] + [0.0] * 767, allowed_chunk_ids=[]) == []
    assert vectors.query("missing", [1.0] + [0.0] * 767) == []
    vectors.clear()
    assert len(list(LocalStore(path).load_batches())) == 2


def test_edit_and_delete_survive_restart_without_cross_workspace_loss(tmp_path):
    path = tmp_path / "aegis.sqlite3"
    store = LocalStore(path)
    store.publish(batch_for())
    store.publish(batch_for("other"))
    store.publish(batch_for(text="Gateway accesses Vault."))
    graph, _ = restore(path)
    routes = trace_attack_paths("cyber", "Gateway", 3, graph)["paths"]
    assert routes[0]["nodes"] == ["Gateway", "Vault"]
    store.delete_document("cyber", "topology")
    graph, _ = restore(path)
    assert not trace_attack_paths("cyber", "Gateway", 3, graph)["paths"]
    assert trace_attack_paths("other", "Gateway", 3, graph)["paths"]


def test_failed_write_retains_previous_revision(tmp_path):
    store = LocalStore(tmp_path / "aegis.sqlite3")
    store.publish(batch_for())
    with store.connection() as conn:
        conn.execute("""CREATE TRIGGER reject_update BEFORE UPDATE ON documents
            BEGIN SELECT RAISE(ABORT, 'simulated disk write failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        store.publish(batch_for(text="Gateway accesses Vault."))
    assert list(store.load_batches())[0].chunks[0].text == "Gateway accesses Database."


def test_lifecycle_startup_restores_actual_persistence(tmp_path, monkeypatch):
    import backend.services.lifecycle_service as lifecycle
    vectors = LocalVectorStore(tmp_path / "aegis.sqlite3")
    vectors.persistence.publish(batch_for())
    graph = GraphStore()
    monkeypatch.setattr(lifecycle, "get_graph_store", lambda: graph)
    monkeypatch.setattr(lifecycle, "get_vector_store", lambda: vectors)
    service = lifecycle.LifecycleService()
    assert service.graph_store.get_document("cyber", "topology")
    assert service.vector_store.query("cyber", [1.0] + [0.0] * 767)


def test_health_reports_real_implementations(client):
    components = client.get("/health").json()["components"]
    assert components["kg_builder"]["adapter"] == "deterministic-rule-extractor"
    assert components["embedder"]["learned_semantic_embeddings"] is False
