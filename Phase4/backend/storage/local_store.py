"""Local-only transactional document persistence with a rebuilt cosine index."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.contracts.models import ExtractionBatch, Topic, TopicAssignment
import json


class LocalStore:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("LOCAL_DATABASE_PATH", "data/aegis-local.sqlite3")).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS documents (
                workspace_id TEXT NOT NULL, document_id TEXT NOT NULL, batch TEXT NOT NULL,
                PRIMARY KEY (workspace_id, document_id))""")
            conn.execute("CREATE TABLE IF NOT EXISTS topic_state (workspace_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS audit_events (id TEXT PRIMARY KEY, workspace_id TEXT, timestamp REAL NOT NULL, payload TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS audit_workspace_time ON audit_events(workspace_id,timestamp)")
            conn.execute("CREATE TABLE IF NOT EXISTS assets (workspace_id TEXT NOT NULL, asset_id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(workspace_id,asset_id))")

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def publish(self, batch):
        # Serialize and validate before replacing the previous committed revision.
        payload = ExtractionBatch.model_validate_json(batch.model_dump_json()).model_dump_json()
        with self.connection() as conn:
            conn.execute("""INSERT INTO documents(workspace_id,document_id,batch) VALUES (?,?,?)
                ON CONFLICT(workspace_id,document_id) DO UPDATE SET batch=excluded.batch""",
                (batch.workspace_id, batch.document.id, payload))

    def load_batches(self):
        with self.connection() as conn:
            for workspace, document, payload in conn.execute(
                    "SELECT workspace_id,document_id,batch FROM documents ORDER BY workspace_id,document_id"):
                batch = ExtractionBatch.model_validate_json(payload)
                if batch.workspace_id != workspace or batch.document.id != document:
                    raise ValueError("Local document identity does not match its workspace")
                yield batch

    def delete_document(self, workspace_id, document_id):
        with self.connection() as conn:
            conn.execute("DELETE FROM documents WHERE workspace_id=? AND document_id=?", (workspace_id, document_id))

    def save_topics(self, workspace, topics, assignments):
        if any(t.workspace_id != workspace for t in topics):
            raise ValueError("Topic workspace mismatch")
        payload = json.dumps({"topics": [t.model_dump() for t in topics],
                              "assignments": [a.model_dump() for a in assignments]})
        with self.connection() as conn:
            conn.execute("INSERT INTO topic_state VALUES (?,?) ON CONFLICT(workspace_id) DO UPDATE SET payload=excluded.payload",
                         (workspace, payload))

    def load_topics(self):
        with self.connection() as conn:
            for workspace, payload in conn.execute("SELECT workspace_id,payload FROM topic_state"):
                data = json.loads(payload)
                topics = [Topic.model_validate(t) for t in data["topics"]]
                if any(t.workspace_id != workspace for t in topics):
                    raise ValueError("Topic workspace mismatch")
                yield workspace, topics, [TopicAssignment.model_validate(a) for a in data["assignments"]]

    def record_audit(self, event):
        with self.connection() as conn:
            conn.execute("INSERT INTO audit_events VALUES (?,?,?,?)", (event["id"], event["workspace_id"], event["timestamp"], json.dumps(event)))

    def list_audit(self, workspace, limit=100):
        with self.connection() as conn:
            return [json.loads(row[0]) for row in conn.execute("SELECT payload FROM audit_events WHERE workspace_id=? ORDER BY timestamp DESC LIMIT ?", (workspace, min(max(limit, 1), 500)))]

    def list_assets(self, workspace):
        with self.connection() as conn:
            return [json.loads(row[0]) for row in conn.execute("SELECT payload FROM assets WHERE workspace_id=? ORDER BY asset_id", (workspace,))]

    def write_asset(self, workspace, record, expected):
        with self.connection() as conn:
            if expected == 0:
                result = conn.execute("INSERT OR IGNORE INTO assets VALUES (?,?,?,?)", (workspace, record["id"], record["version"], json.dumps(record)))
            else:
                result = conn.execute("UPDATE assets SET version=?,payload=? WHERE workspace_id=? AND asset_id=? AND version=? AND json_extract(payload,'$.revision_token')=?",
                    (record["version"], json.dumps(record), workspace, record["id"], expected, record["revision_token"]))
            return result.rowcount == 1

    def delete_asset(self, workspace, identifier, expected, token):
        with self.connection() as conn:
            return conn.execute("DELETE FROM assets WHERE workspace_id=? AND asset_id=? AND version=? AND json_extract(payload,'$.revision_token')=?", (workspace, identifier, expected, token)).rowcount == 1


class LocalVectorStore:
    def __init__(self, path=None):
        from backend.storage.vector_store import VectorStore
        self.index = VectorStore()
        self._vectors = self.index._vectors
        self.persistence = LocalStore(path)

    def cache_vectors(self, workspace_id, vectors):
        self.index.upsert_vectors(workspace_id, vectors)

    def upsert_vectors(self, workspace_id, vectors):
        raise RuntimeError("Local vectors must be published with their document batch")

    def remove_chunks(self, workspace_id, chunk_ids):
        self.index.remove_chunks(workspace_id, chunk_ids)

    def query(self, workspace_id, query_vector, top_k=5, allowed_chunk_ids=None):
        return self.index.query(workspace_id, query_vector, top_k, allowed_chunk_ids)

    def get_vectors(self, workspace_id):
        return self.index.get_vectors(workspace_id)

    def clear(self):
        self.index.clear()  # Cache reset never deletes saved documents.
