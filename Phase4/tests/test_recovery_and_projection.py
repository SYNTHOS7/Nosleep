import json
import os
import pytest

from backend.contracts.models import OperationType, OperationStatus, Topic, TopicAssignment
from backend.ingestion.operations import OperationManager, atomic_json_write
from backend.storage.local_store import LocalStore
from backend.storage.graph_store import GraphStore
from backend.storage.neo4j_projection import Neo4jProjection, snapshot_workspace
from test_local_durability import batch_for


def test_topics_round_trip_filters_stale_assignments(tmp_path):
    store = LocalStore(tmp_path / "local.sqlite3")
    batch = batch_for()
    store.publish(batch)
    topic = Topic(id="theme", workspace_id="cyber", label="Gateway", slug="gateway", description="Grounded terms")
    store.save_topics("cyber", [topic], [TopicAssignment(topic_id="theme", chunk_id="topology-chunk"),
                                        TopicAssignment(topic_id="theme", chunk_id="deleted")])
    graph = GraphStore()
    graph.publish_batch(batch)
    ws, topics, assignments = next(LocalStore(store.path).load_topics())
    graph.replace_topics(ws, topics, assignments)
    assert graph.get_topic_chunks("cyber", "theme") == ["topology-chunk"]
    with pytest.raises(ValueError):
        store.save_topics("other", [topic], [])


def test_atomic_checkpoint_failure_preserves_old_record(tmp_path, monkeypatch):
    path = tmp_path / "checkpoint.json"
    atomic_json_write(str(path), '{"status":"ACCEPTED"}')
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        atomic_json_write(str(path), '{"status":"COMPLETED"}')
    assert json.loads(path.read_text())["status"] == "ACCEPTED"
    assert list(tmp_path.iterdir()) == [path]


def test_recovery_submits_only_nonterminal_operations(tmp_path):
    manager = OperationManager(str(tmp_path), max_workers=1)
    ops = [manager.create_operation("cyber", f"document-{i}", OperationType.ADD) for i in range(3)]
    ops[1].status = OperationStatus.COMPLETED
    ops[2].status = OperationStatus.STAGED
    for op in ops:
        manager.save_checkpoint(op)
    manager.executor.shutdown()
    restart = OperationManager(str(tmp_path), max_workers=1)
    resumed = []
    restart.recover_on_restart(resumed.append)
    restart.executor.shutdown()
    assert set(resumed) == {ops[0].id, ops[2].id}


class Result:
    def consume(self):
        return None


class RecordingDriver:
    def __init__(self):
        self.calls, self.commits = [], 0
    def session(self, **options):
        self.database = options["database"]
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute_write(self, callback):
        callback(self)
        self.commits += 1
    def run(self, query, **params):
        self.calls.append((query, params))
        return Result()


def test_projection_keeps_untrusted_content_as_parameters_and_retains_evidence():
    graph = GraphStore()
    batch = batch_for()
    graph.publish_batch(batch)
    nodes, edges = snapshot_workspace(graph, "cyber")
    relation = next(e for e in edges if e["predicate"] == "ACCESSES")
    assert json.loads(relation["payload"])["provenance"]["exact_quote"] == "Gateway accesses Database."
    hostile_workspace = "x'}) DETACH DELETE n //"
    driver = RecordingDriver()
    Neo4jProjection(driver).replace_workspace(hostile_workspace, nodes, edges)
    assert driver.commits == 1 and len(driver.calls) == 3
    for query, params in driver.calls:
        assert hostile_workspace not in query
        assert params["workspace"] == hostile_workspace
    assert "AegisManaged" in driver.calls[0][0]
    assert "Gateway accesses Database." not in driver.calls[-1][0]


def test_projection_failure_does_not_lose_authoritative_documents(monkeypatch):
    from backend.storage.db_manager import DatabaseManager
    monkeypatch.setenv("VECTOR_BACKEND", "local")
    monkeypatch.setenv("NEO4J_PROJECTION_ENABLED", "true")
    monkeypatch.setattr(DatabaseManager, "_init_neo4j", lambda self: None)
    manager = DatabaseManager()
    graph = GraphStore()
    graph.publish_batch(batch_for())
    class BrokenDriver(RecordingDriver):
        def execute_write(self, callback):
            raise RuntimeError("private credentials in failure")
    manager.neo4j_driver = BrokenDriver()
    manager.sync_graph(graph, "cyber")
    assert manager.projection_status == "pending_retry"
    assert graph.get_document("cyber", "topology")
    assert "private credentials" not in str(manager.get_status())
    manager._chroma_executor.shutdown()
