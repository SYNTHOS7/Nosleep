"""Firestore durability with atomic revision publication and a local cosine index.

Only the Render backend uses the Admin SDK. No Firebase credentials reach React.
"""
import gzip
import hashlib
import json
import os
import uuid

from backend.contracts.models import ExtractionBatch

PAGE_BYTES = 700_000  # Below Firestore's 1 MiB document limit, including metadata.
MAX_BATCH_BYTES = 64 * 1024 * 1024


def _key(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def get_firebase_app():
    import firebase_admin
    from firebase_admin import credentials
    try:
        return firebase_admin.get_app("aegisgraph")
    except ValueError:
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        credential = credentials.Certificate(json.loads(raw)) if raw else credentials.ApplicationDefault()
        options = {}
        if os.environ.get("FIREBASE_PROJECT_ID"):
            options["projectId"] = os.environ["FIREBASE_PROJECT_ID"]
        return firebase_admin.initialize_app(credential, options, name="aegisgraph")


class FirebaseStore:
    def __init__(self, client=None):
        if client is None:
            from firebase_admin import firestore
            client = firestore.client(app=get_firebase_app())
        self.client = client
        self.workspaces = client.collection("aegis_workspaces")

    def _document(self, workspace_id, document_id):
        return self.workspaces.document(_key(workspace_id)).collection("documents").document(_key(document_id))

    def publish(self, batch):
        raw = batch.model_dump_json().encode("utf-8")
        if len(raw) > MAX_BATCH_BYTES:
            raise ValueError("Extracted document exceeds the 64 MiB persistence limit")
        payload = gzip.compress(raw)
        revision = uuid.uuid4().hex
        doc = self._document(batch.workspace_id, batch.document.id)
        pages = doc.collection("pages")
        page_ids = []
        # Pages are immutable. The last write atomically publishes their manifest.
        # A failed page write leaves the previous revision readable.
        for offset in range(0, len(payload), PAGE_BYTES):
            page_id = f"{revision}-{offset // PAGE_BYTES:06d}"
            pages.document(page_id).set({"payload": payload[offset:offset + PAGE_BYTES]})
            page_ids.append(page_id)
        self.workspaces.document(_key(batch.workspace_id)).set({"workspace_id": batch.workspace_id}, merge=True)
        doc.set({"workspace_id": batch.workspace_id, "document_id": batch.document.id,
                 "revision": revision, "pages": page_ids, "sha256": hashlib.sha256(payload).hexdigest(),
                 "deleted": False})

    def load_batches(self):
        for workspace in self.workspaces.stream():
            for snapshot in workspace.reference.collection("documents").stream():
                manifest = snapshot.to_dict()
                if manifest.get("deleted"):
                    continue
                payload = b"".join(snapshot.reference.collection("pages").document(page).get().to_dict()["payload"]
                                   for page in manifest["pages"])
                if hashlib.sha256(payload).hexdigest() != manifest["sha256"]:
                    raise RuntimeError("Firebase document integrity verification failed")
                # Bound decompression even when stored data has been corrupted.
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
                    raw = compressed.read(MAX_BATCH_BYTES + 1)
                if len(raw) > MAX_BATCH_BYTES:
                    raise ValueError("Stored document exceeds the persistence limit")
                batch = ExtractionBatch.model_validate_json(raw)
                if (batch.workspace_id != manifest["workspace_id"] or batch.document.id != manifest["document_id"]):
                    raise RuntimeError("Firebase document identity verification failed")
                yield batch

    def delete_document(self, workspace_id, document_id):
        doc = self._document(workspace_id, document_id)
        # Publish a tombstone first so interrupted cleanup cannot resurrect a document.
        doc.set({"workspace_id": workspace_id, "document_id": document_id, "deleted": True})
        for page in doc.collection("pages").stream():
            page.reference.delete()


class FirebaseVectorStore:
    """Persist extracted batches in Firebase; rebuild cosine search on startup.

This is a single-backend-instance index suitable for the demo corpus. It does
not claim to implement Firestore native vector search or distributed indexing.
"""
    def __init__(self, client=None):
        from backend.storage.vector_store import VectorStore
        self.index = VectorStore()
        self._vectors = self.index._vectors
        self.persistence = FirebaseStore(client)

    def cache_vectors(self, workspace_id, vectors):
        self.index.upsert_vectors(workspace_id, vectors)

    def upsert_vectors(self, workspace_id, vectors):
        self.cache_vectors(workspace_id, vectors)

    def remove_chunks(self, workspace_id, chunk_ids):
        self.index.remove_chunks(workspace_id, chunk_ids)

    def query(self, workspace_id, query_vector, top_k=5, allowed_chunk_ids=None):
        return self.index.query(workspace_id, query_vector, top_k, allowed_chunk_ids)

    def get_vectors(self, workspace_id):
        return self.index.get_vectors(workspace_id)

    def clear(self):
        self.index.clear()
