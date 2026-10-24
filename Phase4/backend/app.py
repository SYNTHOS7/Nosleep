"""FastAPI application for Person 4: API, Integration, and Split-Screen UI backend."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import zipfile

from backend.contracts.api_models import (
    BatchMutationReceipt,
    BatchStatusResponse,
    DocumentItemView,
    DocumentListResponse,
    ErrorResponse,
    GraphSlice,
    HealthResponse,
    MutationReceipt,
    OperationView,
    QueryRequest,
    QueryResponse,
    SourceView,
    TopicList,
)
from backend.contracts.models import Operation, OperationStatus, OperationType
from backend.ingestion.operations import get_operation_manager
from backend.services.lifecycle_service import get_lifecycle_service
from backend.services.query_service import get_query_service
from backend.services.topic_service import get_topic_service
from backend.storage.graph_store import get_graph_store

app = FastAPI(
    title="Interactive Knowledge Base API",
    version="1.0.0",
    description="Person 4 FastAPI backend providing document lifecycle, grounded query answering, topics, and graph slices.",
)

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "kb_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_code=f"HTTP_{exc.status_code}",
            message=str(exc.detail),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Mask raw exception secrets/paths
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="INTERNAL_SERVER_ERROR",
            message="An internal error occurred while processing the request.",
        ).model_dump(),
    )


@app.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Component readiness and pinned versions with no secrets exposed."""
    return HealthResponse(
        status="healthy",
        components={
            "api": {"status": "ready", "version": "1.0.0"},
            "graph_store": {"status": "ready", "type": "in_memory_transactional"},
            "vector_store": {"status": "ready", "dimension": 768},
            "unstructured_parser": {"status": "ready", "fallback": "pypdf_local"},
            "kg_builder": {"status": "ready", "adapter": "neo4j-graphrag-adapter"},
            "embedder": {"status": "ready", "model": "paraphrase-multilingual-mpnet-base-v2"},
        },
        pinned_versions={
            "python": "3.11.16",
            "fastapi": "0.115.0+",
            "pydantic": "2.10.0+",
            "embedding_dim": "768",
            "tokenizer": "cl100k_base",
            "react_graph_renderer": "canvas-force-directed",
        },
    )


@app.post(
    "/v1/workspaces/{ws}/documents",
    response_model=MutationReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    ws: str,
    file: Optional[UploadFile] = File(None),
    raw_text: Optional[str] = Form(None),
    filename: Optional[str] = Form(None),
) -> MutationReceipt:
    """Accepts document upload and returns MutationReceipt (HTTP 202)."""
    if not ws or not ws.isalnum() and "-" not in ws and "_" not in ws:
        raise HTTPException(status_code=400, detail="Invalid workspace ID.")

    doc_id = f"doc-{uuid.uuid4().hex[:12]}"
    source_type = "txt"

    if file:
        fname = file.filename or "upload.txt"
        ext = os.path.splitext(fname)[1].lower()
        source_type = "pdf" if ext == ".pdf" else "txt"
        file_path = os.path.join(UPLOAD_DIR, f"{doc_id}_{fname}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    elif raw_text:
        fname = filename or "pasted_source.txt"
        file_path = os.path.join(UPLOAD_DIR, f"{doc_id}_{fname}")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(raw_text)
    else:
        raise HTTPException(status_code=400, detail="Either file or raw_text must be provided.")

    op_manager = get_operation_manager()
    op = op_manager.create_operation(
        workspace_id=ws,
        document_id=doc_id,
        operation_type=OperationType.ADD,
        source_ref=file_path,
        source_type=source_type,
        current_revision=1,
        new_revision=1,
    )

    # Process immediately in background executor
    lifecycle_service = get_lifecycle_service()
    op_manager.executor.submit(lifecycle_service.process_operation, op)

    return MutationReceipt(
        status="accepted",
        operation_id=op.id,
        document_id=doc_id,
        workspace_id=ws,
        accepted_at=op.accepted_at,
        retry_after=1,
    )


@app.get(
    "/v1/workspaces/{ws}/documents",
    response_model=DocumentListResponse,
)
def list_workspace_documents(ws: str) -> DocumentListResponse:
    """Returns all documents ingested in the workspace."""
    graph_store = get_graph_store()
    raw_docs = graph_store.list_documents(ws)
    docs = [
        DocumentItemView(
            id=d["id"],
            workspace_id=d["workspace_id"],
            source_name=d["source_name"],
            source_type=d["source_type"],
            revision=d["revision"],
            chunk_count=d["chunk_count"],
            created_at=d.get("created_at"),
        )
        for d in raw_docs
    ]
    return DocumentListResponse(workspace_id=ws, documents=docs, total=len(docs))


@app.post(
    "/v1/workspaces/{ws}/documents/batch",
    response_model=BatchMutationReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_documents_batch(
    ws: str,
    files: List[UploadFile] = File(...),
) -> BatchMutationReceipt:
    """
    Accepts bulk document uploads (supports 500+ files or .zip bundles)
    and queues them concurrently for background ingestion.
    """
    if not ws or (not ws.isalnum() and "-" not in ws and "_" not in ws):
        raise HTTPException(status_code=400, detail="Invalid workspace ID.")

    if not files:
        raise HTTPException(status_code=400, detail="No files provided for batch ingestion.")

    op_manager = get_operation_manager()
    lifecycle_service = get_lifecycle_service()

    queued_doc_ids: List[str] = []
    queued_op_ids: List[str] = []

    for upload in files:
        fname = upload.filename or "file.txt"
        ext = os.path.splitext(fname)[1].lower()

        # Handle zip bundles containing multiple files
        if ext == ".zip":
            zip_path = os.path.join(UPLOAD_DIR, f"bundle_{uuid.uuid4().hex[:8]}_{fname}")
            with open(zip_path, "wb") as buffer:
                shutil.copyfileobj(upload.file, buffer)

            extract_dir = os.path.join(UPLOAD_DIR, f"extracted_{uuid.uuid4().hex[:8]}")
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            for root, _, z_files in os.walk(extract_dir):
                for z_file in z_files:
                    z_ext = os.path.splitext(z_file)[1].lower()
                    if z_ext in [".txt", ".pdf", ".md", ".json", ".csv"]:
                        z_doc_id = f"doc-{uuid.uuid4().hex[:12]}"
                        z_src_path = os.path.join(root, z_file)
                        z_source_type = "pdf" if z_ext == ".pdf" else "txt"
                        op = op_manager.create_operation(
                            workspace_id=ws,
                            document_id=z_doc_id,
                            operation_type=OperationType.ADD,
                            source_ref=z_src_path,
                            source_type=z_source_type,
                            current_revision=1,
                            new_revision=1,
                        )
                        op_manager.executor.submit(lifecycle_service.process_operation, op)
                        queued_doc_ids.append(z_doc_id)
                        queued_op_ids.append(op.id)
            continue

        # Handle individual file
        doc_id = f"doc-{uuid.uuid4().hex[:12]}"
        source_type = "pdf" if ext == ".pdf" else "txt"
        file_path = os.path.join(UPLOAD_DIR, f"{doc_id}_{fname}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(upload.file, buffer)

        op = op_manager.create_operation(
            workspace_id=ws,
            document_id=doc_id,
            operation_type=OperationType.ADD,
            source_ref=file_path,
            source_type=source_type,
            current_revision=1,
            new_revision=1,
        )
        op_manager.executor.submit(lifecycle_service.process_operation, op)
        queued_doc_ids.append(doc_id)
        queued_op_ids.append(op.id)

    return BatchMutationReceipt(
        status="accepted",
        workspace_id=ws,
        total_documents=len(queued_doc_ids),
        operation_ids=queued_op_ids,
        document_ids=queued_doc_ids,
        accepted_at=time.time(),
        message=f"Successfully accepted {len(queued_doc_ids)} documents for background ingestion.",
    )


@app.get(
    "/v1/workspaces/{ws}/operations/batch-status",
    response_model=BatchStatusResponse,
)
def get_batch_status(ws: str, operation_ids: Optional[str] = Query(None)) -> BatchStatusResponse:
    """Returns aggregated status and percentage completion for a batch of operations."""
    op_manager = get_operation_manager()
    if operation_ids:
        op_id_list = [oid.strip() for oid in operation_ids.split(",") if oid.strip()]
    else:
        op_id_list = [
            op.id for op in list(op_manager.active_operations.values()) if op.workspace_id == ws
        ]

    total = len(op_id_list)
    completed = 0
    failed = 0
    in_prog = 0
    for oid in op_id_list:
        op = op_manager.active_operations.get(oid) or op_manager.load_checkpoint(oid)
        if op:
            if op.status == OperationStatus.COMPLETED:
                completed += 1
            elif op.status == OperationStatus.FAILED:
                failed += 1
            else:
                in_prog += 1

    pct = round(((completed + failed) / max(1, total)) * 100, 1)
    return BatchStatusResponse(
        workspace_id=ws,
        total=total,
        completed=completed,
        failed=failed,
        in_progress=in_prog,
        percent_complete=pct,
        is_finished=(completed + failed >= total) if total > 0 else True,
        operation_ids=op_id_list,
    )


@app.put(
    "/v1/workspaces/{ws}/documents/{doc_id}",
    response_model=MutationReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def edit_document(
    ws: str,
    doc_id: str,
    expected_revision_id: int = Form(...),
    file: Optional[UploadFile] = File(None),
    raw_text: Optional[str] = Form(None),
    filename: Optional[str] = Form(None),
) -> MutationReceipt:
    """Edits a document with expected_revision_id validation (HTTP 202)."""
    graph_store = get_graph_store()
    current_doc = graph_store.get_document(ws, doc_id)

    if not current_doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    if current_doc.revision != expected_revision_id:
        raise HTTPException(
            status_code=409,
            detail=f"Stale revision: expected revision {expected_revision_id}, but current document is revision {current_doc.revision}.",
        )

    source_type = current_doc.source_type
    if file:
        fname = file.filename or current_doc.source_name
        ext = os.path.splitext(fname)[1].lower()
        source_type = "pdf" if ext == ".pdf" else "txt"
        file_path = os.path.join(UPLOAD_DIR, f"{doc_id}_rev{expected_revision_id+1}_{fname}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    elif raw_text:
        fname = filename or current_doc.source_name
        file_path = os.path.join(UPLOAD_DIR, f"{doc_id}_rev{expected_revision_id+1}_{fname}")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(raw_text)
    else:
        raise HTTPException(status_code=400, detail="Either file or raw_text must be provided for edit.")

    new_rev = expected_revision_id + 1
    op_manager = get_operation_manager()
    op = op_manager.create_operation(
        workspace_id=ws,
        document_id=doc_id,
        operation_type=OperationType.EDIT,
        source_ref=file_path,
        source_type=source_type,
        current_revision=expected_revision_id,
        new_revision=new_rev,
    )

    lifecycle_service = get_lifecycle_service()
    op_manager.executor.submit(lifecycle_service.process_operation, op)

    return MutationReceipt(
        status="accepted",
        operation_id=op.id,
        document_id=doc_id,
        workspace_id=ws,
        accepted_at=op.accepted_at,
        retry_after=1,
    )


@app.delete(
    "/v1/workspaces/{ws}/documents/{doc_id}",
    response_model=MutationReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
def delete_document(ws: str, doc_id: str) -> MutationReceipt:
    """Deletes a document from the workspace (HTTP 202)."""
    graph_store = get_graph_store()
    current_doc = graph_store.get_document(ws, doc_id)
    if not current_doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    op_manager = get_operation_manager()
    op = op_manager.create_operation(
        workspace_id=ws,
        document_id=doc_id,
        operation_type=OperationType.DELETE,
        current_revision=current_doc.revision,
        new_revision=current_doc.revision,
    )

    lifecycle_service = get_lifecycle_service()
    op_manager.executor.submit(lifecycle_service.process_operation, op)

    return MutationReceipt(
        status="accepted",
        operation_id=op.id,
        document_id=doc_id,
        workspace_id=ws,
        accepted_at=op.accepted_at,
        retry_after=1,
    )


@app.get("/v1/operations/{op_id}", response_model=OperationView)
def get_operation(op_id: str) -> OperationView:
    """Returns operation view with execution stage timings and metrics."""
    op_manager = get_operation_manager()
    op = op_manager.active_operations.get(op_id) or op_manager.load_checkpoint(op_id)
    if not op:
        raise HTTPException(status_code=404, detail="Operation not found.")

    return OperationView(
        id=op.id,
        workspace_id=op.workspace_id,
        document_id=op.document_id,
        status=op.status,
        operation_type=op.operation_type,
        stage_timings=op.stage_timings,
        metrics=op.metrics,
        error_message=op.error_message,
        accepted_at=op.accepted_at,
        ready_at=op.ready_at,
    )


@app.post("/v1/query", response_model=QueryResponse)
def run_query(request: QueryRequest) -> QueryResponse:
    """Answers a question grounded with citations, graph slice, and conflict detection."""
    if not request.workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required.")
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty.")

    query_service = get_query_service()
    return query_service.query(request)


@app.get("/v1/topics", response_model=TopicList)
def list_topics(workspace_id: str = Query(...)) -> TopicList:
    """Returns all discovered topics for the workspace."""
    topic_service = get_topic_service()
    return topic_service.list_topics(workspace_id)


@app.post("/v1/topics/discover", response_model=TopicList)
def discover_topics(workspace_id: str = Query(...), k: int = 3) -> TopicList:
    """Triggers topic discovery and clustering for workspace."""
    topic_service = get_topic_service()
    topic_service.discover_and_freeze_topics(workspace_id, k_clusters=k)
    return topic_service.list_topics(workspace_id)


@app.get("/v1/chunks/{chunk_id}/source", response_model=SourceView)
def get_chunk_source(chunk_id: str) -> SourceView:
    """Returns source provenance and exact quote for a chunk."""
    graph_store = get_graph_store()
    source_view = graph_store.get_chunk_source(chunk_id)
    if not source_view:
        raise HTTPException(status_code=404, detail="Chunk not found.")
    return source_view


@app.get("/v1/workspaces/{ws}/graph", response_model=GraphSlice)
def get_workspace_graph(ws: str) -> GraphSlice:
    """Returns full knowledge graph slice for workspace visualization."""
    graph_store = get_graph_store()
    return graph_store.get_full_workspace_graph(ws)


# Mount built React split-screen UI on root path
from fastapi.staticfiles import StaticFiles

FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")

