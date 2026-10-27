import pytest
from fastapi import HTTPException
from backend.security.request_controls import RequestLimiter
from backend.storage.local_store import LocalStore


def test_request_limits_expire_and_separate_actors_and_read_write(monkeypatch):
    monkeypatch.setenv("WRITE_REQUESTS_PER_MINUTE", "2")
    monkeypatch.setenv("READ_REQUESTS_PER_MINUTE", "3")
    now = [10.0]
    limiter = RequestLimiter(clock=lambda: now[0])
    limiter.check("alice", True)
    limiter.check("alice", True)
    with pytest.raises(HTTPException) as error:
        limiter.check("alice", True)
    assert error.value.status_code == 429 and error.value.headers["Retry-After"]
    limiter.check("alice", False)
    limiter.check("bob", True)
    now[0] += 61
    limiter.check("alice", True)


def test_limiter_identity_memory_is_bounded():
    limiter = RequestLimiter(max_keys=2)
    for i in range(10):
        limiter.check(str(i), False)
    assert len(limiter.events) == 2


def test_audit_survives_restart_and_is_scoped(tmp_path):
    path = tmp_path / "audit.sqlite3"
    store = LocalStore(path)
    store.record_audit({"id": "one", "workspace_id": "a", "timestamp": 1, "status": 202})
    store.record_audit({"id": "two", "workspace_id": "b", "timestamp": 2, "status": 403})
    assert [event["id"] for event in LocalStore(path).list_audit("a")] == ["one"]


def test_audit_endpoint_requires_admin(client, monkeypatch):
    import backend.security.access as access
    monkeypatch.setenv("AUTH_MODE", "neon")
    monkeypatch.setattr(access, "verify_identity", lambda token: {"uid": "viewer"})
    monkeypatch.setattr(access, "load_memberships", lambda uid: {"workspaces": {"a": "viewer"}})
    assert client.get("/v1/workspaces/a/audit", headers={"Authorization": "Bearer valid"}).status_code == 403


def test_request_audit_excludes_headers_and_body(client, monkeypatch, tmp_path):
    import backend.storage.vector_store as vectors
    from backend.security.request_controls import limiter
    limiter.events.clear()
    monkeypatch.setenv("REQUEST_CONTROLS_ENABLED", "true")
    store = vectors.get_vector_store()
    persistence = LocalStore(tmp_path / "audit.sqlite3")
    monkeypatch.setattr(store, "persistence", persistence, raising=False)
    response = client.post("/v1/topics/discover?workspace_id=private&k=0",
                           headers={"Authorization": "Bearer secret-token"}, json={"text": "private source content"})
    assert response.status_code == 422
    events = persistence.list_audit("private")
    assert events and events[0]["status"] == 422
    assert "secret-token" not in str(events) and "private source content" not in str(events)
