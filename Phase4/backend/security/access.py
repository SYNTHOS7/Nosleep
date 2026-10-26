"""Neon Auth identity plus live, server-managed workspace memberships."""
from dataclasses import dataclass
import os
import re

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

ROLES = {"viewer": 0, "editor": 1, "admin": 2}


def auth_mode():
    hosted = os.environ.get("RENDER") == "true" or os.environ.get("APP_ENV") == "production"
    mode = os.environ.get("AUTH_MODE", "neon" if hosted or os.environ.get("VECTOR_BACKEND") == "neon" else "demo")
    if mode not in {"demo", "neon"}:
        raise ValueError("AUTH_MODE must be demo or neon")
    if mode == "demo" and (hosted or os.environ.get("VECTOR_BACKEND") == "neon"):
        raise ValueError("Hosted/Neon deployments require AUTH_MODE=neon")
    return mode


@dataclass
class Principal:
    uid: str
    email: str
    workspaces: dict
    platform_admin: bool = False


def verify_identity(token):
    from backend.security.neon_identity import verify_identity as verify
    return verify(token)


def load_memberships(uid):
    from backend.storage.neon_store import NeonStore
    return NeonStore().get_memberships(uid)


def authenticate(authorization):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in to access this workspace.")
    try:
        identity = verify_identity(authorization[7:])
    except Exception:
        raise HTTPException(401, "Your session is invalid or expired. Sign in again.") from None
    try:
        record = load_memberships(identity["uid"])
    except Exception:
        raise HTTPException(503, "Workspace access could not be verified.") from None
    if record.get("disabled") is True:
        raise HTTPException(403, "Account access is disabled.")
    memberships = {name: role for name, role in record.get("workspaces", {}).items() if role in ROLES}
    return Principal(identity["uid"], identity.get("email", ""), memberships, record.get("platform_admin") is True)


def require_workspace(principal, workspace, write=False):
    role = principal.workspaces.get(workspace)
    if principal.platform_admin:
        return
    if role not in ROLES or (write and ROLES[role] < ROLES["editor"]):
        raise HTTPException(403, "You do not have permission for this workspace action.")


class ProtectedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            path = request.url.path
            for key in ("ws", "doc_id", "op_id"):
                value = request.path_params.get(key)
                if value and not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
                    raise HTTPException(400, "Invalid resource identifier.")
            if path in {"/health", "/v1/auth/config"} or request.method == "OPTIONS":
                return await original(request)
            if auth_mode() == "demo":
                # Local demonstration mode must never accept database credentials.
                if path == "/v1/database/configure":
                    raise HTTPException(403, "Database administration requires authenticated mode.")
                request.state.principal = Principal("local-demo", "", {})
                return await original(request)
            principal = await run_in_threadpool(authenticate, request.headers.get("authorization"))
            request.state.principal = principal
            if path.startswith("/v1/database/"):
                if not principal.platform_admin:
                    raise HTTPException(403, "Platform administrator access is required.")
            elif path != "/v1/auth/me":
                workspace = request.path_params.get("ws") or request.query_params.get("workspace_id")
                write = request.method != "GET" and path != "/v1/query"
                if path == "/v1/query":
                    try:
                        body = await request.json()
                    except ValueError:
                        raise HTTPException(400, "Invalid query payload.") from None
                    if not isinstance(body, dict):
                        raise HTTPException(400, "Invalid query payload.")
                    workspace = body.get("workspace_id")
                if "op_id" in request.path_params:
                    from backend.ingestion.operations import get_operation_manager
                    op_id = request.path_params["op_id"]
                    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", op_id):
                        raise HTTPException(404, "Operation not found.")
                    operation = get_operation_manager().load_checkpoint(op_id)
                    if operation is None:
                        raise HTTPException(404, "Operation not found.")
                    workspace = operation.workspace_id
                if "chunk_id" in request.path_params:
                    from backend.storage.graph_store import get_graph_store
                    store = get_graph_store()
                    chunk_id = request.path_params["chunk_id"]
                    workspace = next((ws for ws, chunks in store.chunks.items() if chunk_id in chunks), None)
                    if workspace is None:
                        raise HTTPException(404, "Source not found.")
                if not workspace:
                    raise HTTPException(400, "A workspace is required.")
                require_workspace(principal, workspace, write)
                if path.endswith("/operations/batch-status"):
                    from backend.ingestion.operations import get_operation_manager
                    for operation_id in request.query_params.get("operation_ids", "").split(","):
                        if operation_id:
                            if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", operation_id):
                                raise HTTPException(400, "Invalid operation identifier.")
                            operation = get_operation_manager().load_checkpoint(operation_id)
                            if operation and operation.workspace_id != workspace:
                                raise HTTPException(403, "Operation belongs to a different workspace.")
            return await original(request)

        return handler
