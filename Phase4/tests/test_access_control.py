"""Authorization tests exercise actual route handling with verified-identity stubs."""
import pytest
from backend.security import access
from backend.ingestion.operations import get_operation_manager
from backend.contracts.models import Operation, OperationType
from backend.storage.graph_store import get_graph_store
from test_cyber_and_hosted_storage import publish


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'neon')
    monkeypatch.setattr(access, 'verify_identity', lambda token: {'uid': token, 'email': token + '@example.com'})
    memberships = {
        'reader': {'workspaces': {'alpha': 'viewer'}},
        'writer': {'workspaces': {'alpha': 'editor'}},
        'other': {'workspaces': {'beta': 'editor'}},
        'operator': {'platform_admin': True},
    }
    monkeypatch.setattr(access, 'load_memberships', lambda uid: memberships.get(uid, {}))
    return lambda uid: {'Authorization': 'Bearer ' + uid}


def test_private_api_rejects_unsigned_requests(client, secured):
    assert client.get('/v1/workspaces/alpha/documents').status_code == 401
    assert client.post('/v1/query', json={'workspace_id':'alpha', 'query':'hello'}).status_code == 401
    assert client.get('/v1/auth/config').json()['mode'] == 'neon'


def test_roles_and_cross_workspace_access(client, secured):
    assert client.get('/v1/workspaces/alpha/documents', headers=secured('reader')).status_code == 200
    assert client.post('/v1/query', json={'workspace_id':'alpha', 'query':'test'}, headers=secured('reader')).status_code == 200
    assert client.get('/v1/workspaces/beta/documents', headers=secured('reader')).status_code == 403
    assert client.post('/v1/workspaces/alpha/demo/cyber', headers=secured('reader')).status_code == 403
    assert client.post('/v1/query', json={'workspace_id':'beta', 'query':'test'}, headers=secured('writer')).status_code == 403
    assert client.get('/v1/auth/me', headers=secured('reader')).json()['workspaces'] == {'alpha':'viewer'}
    assert client.post('/v1/workspaces/alpha/demo/cyber', headers=secured('writer')).status_code == 200


def test_admin_routes_and_membership_removal_apply_immediately(client, secured, monkeypatch):
    assert client.get('/v1/database/status', headers=secured('writer')).status_code == 403
    assert client.post('/v1/database/configure', json={}, headers=secured('reader')).status_code == 403
    assert client.get('/v1/database/status', headers=secured('operator')).status_code == 200
    assert client.get('/v1/workspaces/alpha/documents', headers=secured('writer')).status_code == 200
    monkeypatch.setattr(access, 'load_memberships', lambda uid: {})
    assert client.get('/v1/workspaces/alpha/documents', headers=secured('writer')).status_code == 403


def test_operations_and_citations_are_not_workspace_bypasses(client, secured):
    batch = publish(get_graph_store(), 'Gateway accesses Database.', workspace='beta')
    chunk_id = batch.chunks[0].id
    assert client.get(f'/v1/chunks/{chunk_id}/source', headers=secured('reader')).status_code == 403
    assert client.get(f'/v1/chunks/{chunk_id}/source', headers=secured('other')).status_code == 200
    manager = get_operation_manager()
    op = Operation(id='op-private-beta', workspace_id='beta', document_id='private', operation_type=OperationType.ADD)
    manager.active_operations[op.id] = op
    try:
        assert client.get(f'/v1/operations/{op.id}', headers=secured('reader')).status_code == 403
        assert client.get('/v1/workspaces/alpha/operations/batch-status', params={'operation_ids':op.id}, headers=secured('reader')).status_code == 403
        assert client.get(f'/v1/operations/{op.id}', headers=secured('other')).status_code == 200
    finally:
        manager.active_operations.pop(op.id, None)


def test_invalid_tokens_and_membership_outage_fail_closed(client, secured, monkeypatch):
    def invalid(token):
        raise ValueError('Expired or revoked')
    monkeypatch.setattr(access, 'verify_identity', invalid)
    assert client.get('/v1/auth/me', headers=secured('reader')).status_code == 401
    monkeypatch.setattr(access, 'verify_identity', lambda token: {'uid': token})
    def outage(uid):
        raise RuntimeError('Neon unavailable')
    monkeypatch.setattr(access, 'load_memberships', outage)
    assert client.get('/v1/workspaces/alpha/documents', headers=secured('reader')).status_code == 503


def test_local_demo_cannot_configure_databases_and_hosted_cannot_disable_auth(client, monkeypatch):
    monkeypatch.setenv('AUTH_MODE', 'demo')
    assert client.post('/v1/database/configure', json={}).status_code == 403
    monkeypatch.setenv('VECTOR_BACKEND', 'neon')
    with pytest.raises(ValueError):
        access.auth_mode()


def test_upload_identifiers_filenames_and_archives_are_bounded(client):
    import io
    import zipfile
    result = client.post('/v1/workspaces/local/documents', json={'raw_text':'Gateway accesses Database.', 'document_id':'../../escape'})
    assert result.status_code == 400
    result = client.post('/v1/workspaces/local/documents', json={'raw_text':'Gateway accesses Database.', 'filename':'file.txt:stream'})
    assert result.status_code == 400
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('../escape.txt', 'attacker data')
    result = client.post('/v1/workspaces/local/documents/batch', files=[('files',('unsafe.zip',archive.getvalue(),'application/zip'))])
    assert result.status_code == 400
    result = client.post('/v1/workspaces/local/documents', content=b'x', headers={'Content-Length':str(51 * 1024 * 1024)})
    assert result.status_code == 413
