"""Local-only transactional document persistence with a rebuilt cosine index."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.contracts.models import ExtractionBatch


class LocalStore:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("LOCAL_DATABASE_PATH", "data/aegis-local.sqlite3")).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS documents (
                workspace_id TEXT NOT NULL, document_id TEXT NOT NULL, batch TEXT NOT NULL,
                PRIMARY KEY (workspace_id, document_id))""")

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
