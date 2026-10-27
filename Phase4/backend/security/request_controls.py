"""Bounded single-process request throttling and metadata-only audit events."""
from collections import deque
import os
import threading
import time
import uuid
import logging
from fastapi import HTTPException


class RequestLimiter:
    def __init__(self, clock=time.monotonic, max_keys=5000):
        self.clock, self.max_keys = clock, max_keys
        self.events = {}
        self.lock = threading.Lock()

    def check(self, identity, write):
        limit = int(os.environ.get("WRITE_REQUESTS_PER_MINUTE", "30") if write else os.environ.get("READ_REQUESTS_PER_MINUTE", "180"))
        limit = max(1, limit)
        now, key = self.clock(), (identity, write)
        with self.lock:
            if key not in self.events and len(self.events) >= self.max_keys:
                self.events.pop(next(iter(self.events)))
            events = self.events.setdefault(key, deque())
            while events and events[0] <= now - 60:
                events.popleft()
            if len(events) >= limit:
                raise HTTPException(429, "Too many requests. Try again shortly.", headers={"Retry-After": str(max(1, int(61 - (now-events[0]))))})
            events.append(now)


limiter = RequestLimiter()


def controls_enabled():
    return os.environ.get("REQUEST_CONTROLS_ENABLED", "true" if os.environ.get("VECTOR_BACKEND") in {"local", "neon"} else "false").lower() == "true"


def audit(request, status):
    is_report = request.url.path.endswith('/investigation/report')
    if not controls_enabled() or (request.method == "GET" and status < 400 and not is_report):
        return
    from backend.storage.vector_store import get_vector_store
    persistence = getattr(get_vector_store(), "persistence", None)
    if not persistence or not hasattr(persistence, "record_audit"):
        return
    principal = getattr(request.state, "principal", None)
    route = request.scope.get("route")
    event = {"id": uuid.uuid4().hex, "timestamp": time.time(),
             "workspace_id": request.path_params.get("ws") or request.query_params.get("workspace_id"),
             "actor": principal.uid if principal else "unauthenticated",
             "method": request.method, "route": getattr(route, "path", "unknown"), "status": status}
    try:
        persistence.record_audit(event)
    except Exception:
        # Do not expose document text, bearer tokens, DSNs or exception messages in logs.
        logging.getLogger(__name__).error("Audit persistence failed; request metadata could not be recorded.")
