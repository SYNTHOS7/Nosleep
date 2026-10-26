"""Transactional PostgreSQL durability and pgvector search for Neon."""
from contextlib import contextmanager
import json
import math
import os

from backend.contracts.models import ExtractionBatch


def vector_literal(vector):
    if len(vector) != 768 or not all(math.isfinite(float(v)) for v in vector):
        raise ValueError("Expected 768 finite embedding dimensions")
    if not any(float(v) for v in vector):
        raise ValueError("Cosine search requires a nonzero embedding")
    return json.dumps([float(v) for v in vector])


class NeonStore:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory
        self.database_url = os.environ.get("DATABASE_URL", "")
        if connection_factory is None and not self.database_url:
            raise ValueError("Neon storage requires a backend-only DATABASE_URL")

    @contextmanager
    def connection(self):
        try:
            if self.connection_factory:
                connection = self.connection_factory()
            else:
                import psycopg
                connection = psycopg.connect(self.database_url, sslmode="require", connect_timeout=10,
                                              options="-c statement_timeout=30000")
            with connection:
                yield connection
        except Exception:
            # SQL, DSNs and document content must not leak through operation errors.
            raise RuntimeError("Neon storage operation failed. Check database connectivity and schema setup.") from None

    def publish(self, batch):
        # Validate all vectors before opening the transaction or replacing old state.
        rows = [(batch.workspace_id, batch.document.id, cid, vector_literal(vector))
                for cid, vector in batch.vectors.items()]
        with self.connection() as conn:
            conn.execute("""INSERT INTO aegis.documents(workspace_id,document_id,batch)
                VALUES (%s,%s,%s::jsonb) ON CONFLICT (workspace_id,document_id)
                DO UPDATE SET batch=EXCLUDED.batch, updated_at=now()""",
                         (batch.workspace_id, batch.document.id, batch.model_dump_json()))
            conn.execute("DELETE FROM aegis.vectors WHERE workspace_id=%s AND document_id=%s",
                         (batch.workspace_id, batch.document.id))
            if rows:
                with conn.cursor() as cursor:
                    cursor.executemany("""INSERT INTO aegis.vectors(workspace_id,document_id,chunk_id,embedding)
                        VALUES (%s,%s,%s,%s::public.vector)""", rows)

    def load_batches(self):
        with self.connection() as conn:
            # A server cursor avoids fetching the full serialized corpus in one result.
            with conn.cursor(name="aegis_restore") as cursor:
                cursor.execute("SELECT workspace_id,document_id,batch FROM aegis.documents ORDER BY workspace_id,document_id")
                for workspace, document, payload in cursor:
                    batch = ExtractionBatch.model_validate(payload)
                    if batch.workspace_id != workspace or batch.document.id != document:
                        raise ValueError("Stored document identity does not match its workspace")
                    yield batch

    def delete_document(self, workspace_id, document_id):
        with self.connection() as conn:
            # Foreign-key cascade removes only this document's vectors in the same transaction.
            conn.execute("DELETE FROM aegis.documents WHERE workspace_id=%s AND document_id=%s",
                         (workspace_id, document_id))

    def query_vectors(self, workspace_id, vector, top_k, allowed_chunk_ids=None):
        if allowed_chunk_ids == [] or top_k <= 0:
            return []
        query = vector_literal(vector)
        with self.connection() as conn:
            result = conn.execute("""SELECT chunk_id, 1-(embedding <=> %s::public.vector) AS similarity
                FROM aegis.vectors WHERE workspace_id=%s
                AND (%s::text[] IS NULL OR chunk_id=ANY(%s::text[]))
                ORDER BY embedding <=> %s::public.vector, chunk_id LIMIT %s""",
                (query, workspace_id, allowed_chunk_ids, allowed_chunk_ids, query, min(top_k, 1000)))
            return [(chunk, float(score)) for chunk, score in result.fetchall()]

    def get_memberships(self, user_id):
        with self.connection() as conn:
            user = conn.execute("SELECT platform_admin,disabled FROM aegis.users WHERE user_id=%s", (user_id,)).fetchone()
            if user is None:
                return {}
            rows = conn.execute("SELECT workspace_id,role FROM aegis.memberships WHERE user_id=%s", (user_id,)).fetchall()
            return {"platform_admin": user[0], "disabled": user[1], "workspaces": dict(rows)}

    def set_access(self, user_id, workspace, role, platform_admin=None):
        if role not in {"viewer", "editor", "admin", "remove"}:
            raise ValueError("Invalid workspace role")
        with self.connection() as conn:
            conn.execute("INSERT INTO aegis.users(user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
            conn.execute("SELECT user_id FROM aegis.users WHERE user_id=%s FOR UPDATE", (user_id,))
            if role == "remove":
                conn.execute("DELETE FROM aegis.memberships WHERE user_id=%s AND workspace_id=%s", (user_id, workspace))
            else:
                conn.execute("""INSERT INTO aegis.memberships(user_id,workspace_id,role) VALUES (%s,%s,%s)
                    ON CONFLICT(user_id,workspace_id) DO UPDATE SET role=EXCLUDED.role""", (user_id, workspace, role))
            if platform_admin is not None:
                conn.execute("UPDATE aegis.users SET platform_admin=%s WHERE user_id=%s", (platform_admin, user_id))


class NeonVectorStore:
    def __init__(self, connection_factory=None):
        from backend.storage.vector_store import VectorStore
        self.index = VectorStore()
        self._vectors = self.index._vectors
        self.persistence = NeonStore(connection_factory)

    def cache_vectors(self, workspace_id, vectors):
        self.index.upsert_vectors(workspace_id, vectors)

    def upsert_vectors(self, workspace_id, vectors):
        raise RuntimeError("Neon vectors must be published with their document batch")

    def remove_chunks(self, workspace_id, chunk_ids):
        self.index.remove_chunks(workspace_id, chunk_ids)

    def query(self, workspace_id, query_vector, top_k=5, allowed_chunk_ids=None):
        return self.persistence.query_vectors(workspace_id, query_vector, top_k, allowed_chunk_ids)

    def get_vectors(self, workspace_id):
        return self.index.get_vectors(workspace_id)

    def clear(self):
        self.index.clear()  # Never clear shared database records from a cache reset.
