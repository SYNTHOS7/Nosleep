"""Persistent Chroma vector repository conforming to Task 1 VectorRepository protocol."""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from typing import Sequence

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from backend.contracts.integration import CorpusSnapshot, ExtractionBatch, revalidate_extraction_batch
from .interfaces import VectorStageError


def _sanitize_collection_name(workspace_id: str) -> str:
    """Ensure Chroma collection name is 3-63 characters, [a-zA-Z0-9_-]."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", workspace_id)
    candidate = f"ws_{cleaned}"
    if 3 <= len(candidate) <= 63:
        return candidate
    digest = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()[:48]
    return f"ws_{digest}"


def _vectors_close(v1: Sequence[float], v2: Sequence[float], tol: float = 1e-5) -> bool:
    if len(v1) != len(v2):
        return False
    return all(math.isclose(a, b, rel_tol=tol, abs_tol=tol) for a, b in zip(v1, v2))


class ChromaVectorRepository:
    """Production persistent Chroma implementation of VectorRepository."""

    def __init__(
        self,
        persist_directory: str | Path | None = None,
        client: ClientAPI | None = None,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            path = persist_directory or os.environ.get("CHROMA_PERSIST_DIR", "./data/chroma")
            Path(path).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(path))

    def _get_collection(self, workspace_id: str) -> Collection | None:
        name = _sanitize_collection_name(workspace_id)
        try:
            return self._client.get_collection(name=name)
        except Exception:
            return None

    def _get_or_create_collection(self, workspace_id: str, profile: tuple[str, int]) -> Collection:
        name = _sanitize_collection_name(workspace_id)
        version, dimension = profile
        collection = self._get_collection(workspace_id)
        if collection is None:
            try:
                return self._client.create_collection(
                    name=name,
                    metadata={
                        "workspace_id": workspace_id,
                        "embedding_version": version,
                        "embedding_dimension": dimension,
                        "hnsw:space": "cosine",
                    },
                )
            except Exception:
                # If race occurred, retrieve it
                collection = self._client.get_collection(name=name)

        meta = collection.metadata or {}
        existing_version = meta.get("embedding_version")
        existing_dim = meta.get("embedding_dimension")
        if existing_version is not None and existing_dim is not None:
            if (str(existing_version), int(existing_dim)) != profile:
                raise VectorStageError("workspace embedding profile change requires explicit reindexing")
        return collection

    def stage_batch(self, workspace_id: str, batch: ExtractionBatch) -> None:
        checked = revalidate_extraction_batch(batch)
        profile = (checked.embedding_version, checked.embedding_dimension)
        try:
            collection = self._get_or_create_collection(workspace_id, profile)
        except VectorStageError:
            raise
        except Exception as error:
            raise VectorStageError(f"failed to initialize Chroma collection: {error}") from error

        chunk_ids = list(checked.chunk_vectors.keys())
        if not chunk_ids:
            return

        try:
            existing = collection.get(ids=chunk_ids, include=["embeddings", "metadatas"])
            existing_ids = list(existing.get("ids") or [])
            if existing_ids:
                raw_emb = existing.get("embeddings")
                existing_embeddings = list(raw_emb) if raw_emb is not None else []
                raw_meta = existing.get("metadatas")
                existing_metadatas = list(raw_meta) if raw_meta is not None else []
                for idx, cid in enumerate(existing_ids):
                    expected_vector = checked.chunk_vectors[cid]
                    existing_vec = existing_embeddings[idx] if idx < len(existing_embeddings) else None
                    existing_meta = existing_metadatas[idx] if idx < len(existing_metadatas) else {}
                    if existing_vec is not None and not _vectors_close(existing_vec, expected_vector):
                        raise VectorStageError("chunk vector ID is not idempotent")
                    if existing_meta:
                        if (
                            existing_meta.get("workspace_id") != workspace_id
                            or existing_meta.get("revision_id") != checked.revision_id
                            or existing_meta.get("embedding_dimension") != checked.embedding_dimension
                        ):
                            raise VectorStageError("chunk vector ID is not idempotent")

            embeddings = [list(checked.chunk_vectors[cid]) for cid in chunk_ids]
            metadatas = [
                {
                    "workspace_id": workspace_id,
                    "document_id": checked.document_id,
                    "revision_id": checked.revision_id,
                    "embedding_version": checked.embedding_version,
                    "embedding_dimension": checked.embedding_dimension,
                }
                for _ in chunk_ids
            ]
            documents = [chunk.text for chunk in checked.chunks]
            collection.upsert(
                ids=chunk_ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents,
            )
        except VectorStageError:
            raise
        except Exception as error:
            raise VectorStageError(f"failed to stage vectors in Chroma: {error}") from error

    def verify_staged(self, workspace_id: str, batch: ExtractionBatch) -> None:
        checked = revalidate_extraction_batch(batch)
        collection = self._get_collection(workspace_id)
        if collection is None:
            raise VectorStageError("staged vector profile does not match workspace profile")

        meta = collection.metadata or {}
        existing_version = meta.get("embedding_version")
        existing_dim = meta.get("embedding_dimension")
        if (
            existing_version is not None
            and existing_dim is not None
            and (str(existing_version), int(existing_dim)) != (checked.embedding_version, checked.embedding_dimension)
        ):
            raise VectorStageError("staged vector profile does not match workspace profile")

        chunk_ids = list(checked.chunk_vectors.keys())
        if not chunk_ids:
            return

        try:
            found = collection.get(ids=chunk_ids, include=["embeddings", "metadatas"])
            found_ids = set(found.get("ids") or [])
            if not set(chunk_ids).issubset(found_ids):
                raise VectorStageError("missing or mismatched staged vector")

            found_id_list = list(found.get("ids") or [])
            raw_emb = found.get("embeddings")
            found_embeddings = list(raw_emb) if raw_emb is not None else []
            raw_meta = found.get("metadatas")
            found_metadatas = list(raw_meta) if raw_meta is not None else []
            for idx, cid in enumerate(found_id_list):
                expected_vec = checked.chunk_vectors[cid]
                found_vec = found_embeddings[idx] if idx < len(found_embeddings) else None
                found_meta = found_metadatas[idx] if idx < len(found_metadatas) else {}
                if found_vec is None or not _vectors_close(found_vec, expected_vec):
                    raise VectorStageError("missing or mismatched staged vector")
                if (
                    found_meta.get("workspace_id") != workspace_id
                    or found_meta.get("revision_id") != checked.revision_id
                    or found_meta.get("embedding_dimension") != checked.embedding_dimension
                ):
                    raise VectorStageError("missing or mismatched staged vector")
        except VectorStageError:
            raise
        except Exception as error:
            raise VectorStageError(f"failed to verify staged vectors in Chroma: {error}") from error

    def vector_candidates(self, vector: list[float], snapshot: CorpusSnapshot, limit: int) -> list[str]:
        if limit <= 0 or not snapshot.active_revision_ids:
            return []

        collection = self._get_collection(snapshot.workspace_id)
        if collection is None:
            return []

        meta = collection.metadata or {}
        dim = meta.get("embedding_dimension")
        if dim is not None and int(dim) != len(vector):
            return []

        try:
            count = collection.count()
            if count == 0:
                return []

            if len(snapshot.active_revision_ids) == 1:
                where_filter = {
                    "$and": [
                        {"workspace_id": {"$eq": snapshot.workspace_id}},
                        {"revision_id": {"$eq": snapshot.active_revision_ids[0]}},
                    ]
                }
            else:
                where_filter = {
                    "$and": [
                        {"workspace_id": {"$eq": snapshot.workspace_id}},
                        {"revision_id": {"$in": list(snapshot.active_revision_ids)}},
                    ]
                }

            query_limit = min(limit, count)
            results = collection.query(
                query_embeddings=[vector],
                n_results=query_limit,
                where=where_filter,
            )
            result_ids = results.get("ids")
            if not result_ids or not result_ids[0]:
                return []
            return list(result_ids[0][:limit])
        except Exception:
            return []

    def cleanup(self, workspace_id: str, active_chunk_ids: set[str]) -> None:
        collection = self._get_collection(workspace_id)
        if collection is None:
            return

        try:
            existing = collection.get(include=["metadatas"])
            if not existing or not existing.get("ids"):
                return
            ids = existing["ids"]
            metas = existing.get("metadatas") or []
            to_delete: list[str] = []
            for cid, meta in zip(ids, metas):
                # Only clean up chunks for this workspace that are not active
                if meta.get("workspace_id") == workspace_id and cid not in active_chunk_ids:
                    to_delete.append(cid)
            if to_delete:
                collection.delete(ids=to_delete)
        except Exception as error:
            raise VectorStageError(f"failed to clean up retired Chroma vectors: {error}") from error
