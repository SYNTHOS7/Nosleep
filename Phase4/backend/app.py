"""FastAPI application for Person 4: API, Integration, and Split-Screen UI backend."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid
import re
from contextlib import asynccontextmanager
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
from backend.services.asset_service import AssetInput

@asynccontextmanager
async def lifespan(application):
    if os.environ.get("VECTOR_BACKEND") in {"local", "neon"}:
        service = get_lifecycle_service()
        get_operation_manager().recover_on_restart(service.resume_operation)
        from backend.storage.db_manager import get_db_manager
        get_db_manager().sync_graph(service.graph_store)
    yield


app = FastAPI(
    title="AegisGraph AI API",
    version="1.0.0",
    lifespan=lifespan,
    description="Person 4 FastAPI backend providing document lifecycle, grounded query answering, topics, and graph slices.",
)

from backend.security.access import ProtectedRoute, auth_mode
auth_mode()  # Reject unsafe storage/auth combinations at startup.
app.router.route_class = ProtectedRoute


from backend.security.upload_limits import UploadLimitMiddleware
app.add_middleware(UploadLimitMiddleware)


@app.get("/v1/auth/config")
def get_auth_config():
    return {"mode": auth_mode(), "demo": auth_mode() == "demo"}


@app.get("/architecture")
def architecture_view():
    from fastapi.responses import FileResponse
    from pathlib import Path
    return FileResponse(Path(__file__).resolve().parents[2] / "flowcharts.html", media_type="text/html")


@app.get("/v1/auth/me")
def get_current_user(request: Request):
    principal = request.state.principal
    return {"uid": principal.uid, "email": principal.email,
            "workspaces": principal.workspaces, "platform_admin": principal.platform_admin}

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:8080").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data", "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)


def upload_path(workspace, filename):
    """Unique source paths prevent cross-workspace/document uploads overwriting each other."""
    directory = os.path.join(UPLOAD_DIR, workspace, uuid.uuid4().hex)
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, safe_filename(filename))


def safe_filename(name):
    # Treat both slash styles as separators on every deployment OS.
    cleaned = os.path.basename(str(name).replace("\\", "/"))
    if not cleaned or cleaned in {".", ".."} or any(ord(c) < 32 or c in '<>:"|?*' for c in cleaned) or len(cleaned) > 160:
        raise HTTPException(400, "Invalid source filename.")
    return cleaned


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
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


from backend.ingestion.local_ai import LocalAIError


@app.exception_handler(LocalAIError)
async def local_ai_exception_handler(request: Request, error: LocalAIError):
    return JSONResponse(status_code=503, content={"error_code": "LOCAL_AI_UNAVAILABLE", "message": str(error)})


@app.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Component readiness and pinned versions with no secrets exposed."""
    from backend.storage.db_manager import get_db_manager
    db_status = get_db_manager().get_status()

    return HealthResponse(
        status="healthy",
        components={
            "api": {"status": "ready", "version": "1.0.0"},
            "graph_store": {"status": "ready", "type": db_status["active_mode"]},
            "vector_store": {"status": "ready", "dimension": 768, "backend": db_status["vector_backend"], "chroma": db_status["chromadb"]["status"]},
            "unstructured_parser": {"status": "ready", "fallback": "pypdf_local"},
            "kg_builder": {"status": "configured" if os.environ.get("EXTRACTOR_PROVIDER") == "ollama" else "ready",
                           "adapter": "ollama-grounded-extraction" if os.environ.get("EXTRACTOR_PROVIDER") == "ollama" else "deterministic-rule-extractor"},
            "embedder": {"status": "configured" if os.environ.get("EMBEDDING_PROVIDER") == "ollama" else "ready",
                         "model": os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest") if os.environ.get("EMBEDDING_PROVIDER") == "ollama" else "deterministic-word-hash",
                         "learned_semantic_embeddings": os.environ.get("EMBEDDING_PROVIDER") == "ollama"},
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


@app.get("/v1/database/status")
def get_database_status_endpoint():
    """Returns real-time connectivity status of Neo4j, ChromaDB, and atomic disk storage."""
    from backend.storage.db_manager import get_db_manager
    return get_db_manager().get_status()


@app.get("/v1/workspaces/{ws}/audit")
def get_workspace_audit(ws: str, limit: int = Query(100, ge=1, le=500)):
    from backend.storage.vector_store import get_vector_store
    persistence = getattr(get_vector_store(), "persistence", None)
    return {"workspace_id": ws, "events": persistence.list_audit(ws, limit) if persistence else []}


@app.get("/v1/workspaces/{ws}/assets")
def list_asset_inventory(ws: str):
    from backend.services.asset_service import repository
    assets = sorted(repository().list_assets(ws), key=lambda item: item["name"].casefold())
    names = {name.casefold() for name in get_graph_store().entities.get(ws, {})}
    return {"workspace_id": ws, "assets": [{**asset, "graph_match": asset["name"].casefold() in names} for asset in assets]}


@app.put("/v1/workspaces/{ws}/assets")
def save_asset_inventory(ws: str, value: AssetInput, request: Request):
    from backend.services.asset_service import save_asset, AssetConflictError
    try:
        return save_asset(ws, value, request.state.principal.uid)
    except AssetConflictError as error:
        raise HTTPException(409, str(error)) from None


@app.delete("/v1/workspaces/{ws}/assets/{asset_id}")
def delete_asset_inventory(ws: str, asset_id: str, expected_version: int = Query(..., ge=1, le=2147483646),
                           expected_token: str = Query(..., pattern=r"^[0-9a-f]{32}$")):
    from backend.services.asset_service import repository
    if not re.fullmatch(r"asset-[0-9a-f]{24}", asset_id):
        raise HTTPException(400, "Invalid asset identifier")
    if not repository().delete_asset(ws, asset_id, expected_version, expected_token):
        raise HTTPException(409, "Asset changed or was removed. Refresh before deleting.")
    return {"deleted": True}


@app.get("/v1/workspaces/{ws}/route-assessment")
def review_route_priority(ws: str, entry_point: str = Query(..., min_length=1, max_length=160)):
    from backend.services.asset_service import assess_routes
    if not entry_point.strip():
        raise HTTPException(400, "Enter an entry asset or CVE name")
    return assess_routes(ws, entry_point.strip())


@app.post("/v1/database/configure")
async def configure_database_endpoint(request: Request):
    """Allows runtime configuration and connectivity testing of Neo4j credentials."""
    body = await request.json()
    uri = body.get("uri", "")
    username = body.get("username", "neo4j")
    password = body.get("password", "")
    database = body.get("database", "neo4j")
    from backend.storage.db_manager import get_db_manager
    return get_db_manager().configure_neo4j(uri, username, password, database)


@app.post(
    "/v1/workspaces/{ws}/documents",
    response_model=MutationReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    ws: str,
    request: Request,
    file: Optional[UploadFile] = File(None),
    raw_text: Optional[str] = Form(None),
    filename: Optional[str] = Form(None),
) -> MutationReceipt:
    """Accepts document upload and returns MutationReceipt (HTTP 202)."""
    if not ws or not ws.isalnum() and "-" not in ws and "_" not in ws:
        raise HTTPException(status_code=400, detail="Invalid workspace ID.")

    doc_id = f"doc-{uuid.uuid4().hex[:12]}"
    source_type = "txt"

    # Support JSON payload fallback if form fields are not provided
    if not file and not raw_text:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
                raw_text = body.get("raw_text") or body.get("text")
                filename = body.get("filename")
                if body.get("document_id"):
                    doc_id = body.get("document_id")
            except Exception:
                pass

    if not isinstance(doc_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", doc_id):
        raise HTTPException(status_code=400, detail="Invalid document ID.")

    if file:
        fname = safe_filename(file.filename or "upload.txt")
        ext = os.path.splitext(fname)[1].lower()
        source_type = "pdf" if ext == ".pdf" else "txt"
        file_path = upload_path(ws, fname)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    elif raw_text:
        fname = safe_filename(filename or "pasted_source.txt")
        file_path = upload_path(ws, fname)
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

    # Fast synchronous processing for single document (completes in ~15ms with instantaneous readiness)
    lifecycle_service = get_lifecycle_service()
    try:
        lifecycle_service.process_operation(op)
    except Exception:
        # Checkpoint is already updated to FAILED and lock released in lifecycle_service
        pass

    return MutationReceipt(
        status="accepted",
        operation_id=op.id,
        document_id=doc_id,
        workspace_id=ws,
        accepted_at=op.accepted_at,
        retry_after=1,
    )


@app.post("/v1/workspaces/{ws}/imports/cisa-kev", response_model=MutationReceipt, status_code=202)
async def import_cisa_kev(ws: str, file: UploadFile = File(...)):
    """Validate an uploaded catalog and ingest a cited, normalized snapshot without network access."""
    from backend.ingestion.cisa_kev import normalize_catalog
    content = await file.read(5 * 1024 * 1024 + 1)
    try:
        catalog = normalize_catalog(content)
    except (ValueError, RecursionError):
        raise HTTPException(400, "Invalid CISA KEV catalog. Check its required fields, dates, count, unique CVE IDs and 5 MiB limit.") from None
    path = upload_path(ws, "cisa-kev-snapshot.txt")
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(catalog["text"])
    with open(os.path.join(os.path.dirname(path), "original-catalog.json"), "wb") as stream:
        stream.write(content)
    manager = get_operation_manager()
    op = manager.create_operation(ws, catalog["document_id"], OperationType.ADD, path, "txt")
    op.metrics.update({"import_format": "cisa-kev", "record_count": catalog["count"], "catalog_sha256": catalog["sha256"]})
    manager.save_checkpoint(op)
    manager.executor.submit(get_lifecycle_service().process_operation, op)
    return MutationReceipt(status="accepted", operation_id=op.id, document_id=op.document_id,
                           workspace_id=ws, accepted_at=op.accepted_at, retry_after=1)


@app.post("/v1/workspaces/{ws}/imports/scanner", response_model=MutationReceipt, status_code=202)
async def import_scanner_report(ws: str, format: str = Query(..., pattern="^(trivy|osv|sarif)$"), file: UploadFile = File(...)):
    from backend.ingestion.scanner_reports import normalize_report
    content = await file.read(5 * 1024 * 1024 + 1)
    try:
        report = normalize_report(content, format)
    except (ValueError, UnicodeError, TypeError, AttributeError, KeyError, RecursionError):
        raise HTTPException(400, "Invalid or unsupported report. Use Trivy vulnerability JSON, OSV JSON or SARIF 2.1.0 with located findings; maximum 5 MiB and 2000 findings. Secret-scanner reports are not accepted.") from None
    path = upload_path(ws, f"scanner-{format}.txt")
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(report["text"])
    manager = get_operation_manager()
    try:
        op = manager.create_operation(ws, report["document_id"], OperationType.ADD, path, "txt")
    except RuntimeError:
        raise HTTPException(409, "This report is already being imported. Wait for its operation to finish.") from None
    op.metrics.update({"import_format": "scanner-report", "scanner_format": format, "finding_count": report["count"]})
    manager.save_checkpoint(op)
    manager.executor.submit(get_lifecycle_service().process_operation, op)
    return MutationReceipt(status="accepted", operation_id=op.id, document_id=op.document_id,
                           workspace_id=ws, accepted_at=op.accepted_at, retry_after=1)


@app.get("/v1/workspaces/{ws}/investigation")
def run_investigation(ws: str, entry_point: str = Query(..., min_length=1, max_length=200)):
    if not entry_point.strip():
        raise HTTPException(400, "Enter a CVE identifier or entity name.")
    from backend.services.investigation_service import investigate
    return investigate(ws, entry_point)


@app.get("/v1/workspaces/{ws}/investigation/report")
def download_investigation_report(ws: str, entry_point: str = Query(..., min_length=1, max_length=200),
                                  format: str = Query("txt", pattern="^(txt|json)$")):
    from backend.services.investigation_reports import build_report, render_text, ReportChangedError
    from fastapi.responses import Response
    import json
    if not entry_point.strip():
        raise HTTPException(400, "Enter a CVE identifier or entity name.")
    try:
        report = build_report(ws, entry_point.strip())
    except ReportChangedError as error:
        raise HTTPException(409, str(error)) from None
    content = json.dumps(report, ensure_ascii=False, indent=2) if format == "json" else render_text(report)
    return Response(content=content, media_type="application/json" if format == "json" else "text/plain",
                    headers={"Content-Disposition": f'attachment; filename="aegisgraph-investigation.{format}"',
                             "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.post("/v1/workspaces/{ws}/imports/intel", response_model=MutationReceipt, status_code=202)
async def import_threat_catalog(ws: str, format: str = Query(..., pattern="^(nvd|stix)$"), file: UploadFile = File(...)):
    from backend.ingestion.threat_catalogs import normalize_catalog
    try:
        catalog = normalize_catalog(await file.read(5 * 1024 * 1024 + 1), format)
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
        raise HTTPException(400, "Invalid NVD 2.0 response or STIX 2.x bundle. Maximum 5 MiB and 5000 records.") from None
    path = upload_path(ws, f"{format}-catalog.txt")
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(catalog["text"])
    manager = get_operation_manager()
    try:
        op = manager.create_operation(ws, catalog["document_id"], OperationType.ADD, path, "txt")
    except RuntimeError:
        raise HTTPException(409, "This catalog is already being imported.") from None
    op.metrics.update({"import_format": "threat-catalog", "catalog_format": format, "record_count": catalog["count"]})
    manager.save_checkpoint(op)
    manager.executor.submit(get_lifecycle_service().process_operation, op)
    return MutationReceipt(status="accepted", operation_id=op.id, document_id=op.document_id,
                           workspace_id=ws, accepted_at=op.accepted_at, retry_after=1)


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
    if len(files) > 1000:
        raise HTTPException(status_code=413, detail="At most 1000 files are allowed per batch.")

    op_manager = get_operation_manager()
    lifecycle_service = get_lifecycle_service()

    queued_doc_ids: List[str] = []
    queued_op_ids: List[str] = []

    for upload in files:
        fname = safe_filename(upload.filename or "file.txt")
        ext = os.path.splitext(fname)[1].lower()

        # Handle zip bundles containing multiple files
        if ext == ".zip":
            zip_path = os.path.join(UPLOAD_DIR, f"bundle_{uuid.uuid4().hex[:8]}_{fname}")
            with open(zip_path, "wb") as buffer:
                shutil.copyfileobj(upload.file, buffer)

            extract_dir = os.path.join(UPLOAD_DIR, f"extracted_{uuid.uuid4().hex[:8]}")
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                members = zf.infolist()
                if len(members) > 1000 or sum(member.file_size for member in members) > 50 * 1024 * 1024:
                    raise HTTPException(413, "Archive exceeds the 1000-entry or 50 MiB expanded limit.")
                for member in members:
                    relative = member.filename.replace("\\", "/")
                    if relative.startswith("/") or ".." in relative.split("/") or ":" in relative or (member.external_attr >> 16) & 0o170000 == 0o120000:
                        raise HTTPException(400, "Archive contains an unsafe path or symbolic link.")
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
        file_path = upload_path(ws, fname)
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
        fname = safe_filename(file.filename or current_doc.source_name)
        ext = os.path.splitext(fname)[1].lower()
        source_type = "pdf" if ext == ".pdf" else "txt"
        file_path = upload_path(ws, fname)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    elif raw_text:
        fname = safe_filename(filename or current_doc.source_name)
        file_path = upload_path(ws, fname)
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

    # Immediate processing for edit operation
    lifecycle_service = get_lifecycle_service()
    try:
        lifecycle_service.process_operation(op)
    except Exception:
        pass

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

    # Immediate processing for delete operation
    lifecycle_service = get_lifecycle_service()
    try:
        lifecycle_service.process_operation(op)
    except Exception:
        pass

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
def discover_topics(workspace_id: str = Query(...), k: int = Query(3, ge=1, le=50)) -> TopicList:
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


@app.get("/v1/workspaces/{ws}/attack-paths")
def get_attack_paths(ws: str, entry_point: str = Query(..., min_length=1), max_depth: int = Query(3, ge=1, le=8)):
    from backend.services.attack_path_service import trace_attack_paths
    return trace_attack_paths(ws, entry_point, max_depth)


@app.post("/v1/workspaces/{ws}/demo/cyber")
def load_cyber_demo(ws: str):
    """Load labeled synthetic fixtures through the normal ingestion lifecycle."""
    from pathlib import Path
    corpus = Path(__file__).resolve().parents[2] / "data" / "cyber_corpus"
    results = []
    for source in sorted(corpus.glob("*.txt")):
        op = get_operation_manager().create_operation(workspace_id=ws,
            document_id=f"demo-{source.stem}", operation_type=OperationType.ADD,
            source_ref=str(source), source_type="txt")
        get_lifecycle_service().process_operation(op)
        results.append({"document_id": op.document_id, "status": op.status.value})
    if not results:
        raise HTTPException(status_code=503, detail="Cyber demo corpus is not included in this build.")
    return {"workspace_id": ws, "synthetic": True, "documents": results}


# Mount built React split-screen UI on root path
from fastapi.staticfiles import StaticFiles

FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.environ.get("SERVE_FRONTEND", "true").lower() == "true" and os.path.exists(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")

