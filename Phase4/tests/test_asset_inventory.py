from concurrent.futures import ThreadPoolExecutor
import pytest
from backend.services.asset_service import AssetInput, AssetConflictError, MemoryAssets, save_asset, assess_routes
from backend.storage.local_store import LocalStore
from backend.storage.graph_store import GraphStore
from test_cyber_and_hosted_storage import publish


@pytest.fixture
def memory(monkeypatch):
    import backend.services.asset_service as service
    store = MemoryAssets()
    monkeypatch.setattr(service, 'repository', lambda: store)
    return store


def test_real_sqlite_restart_version_conflicts_and_recreate_tokens(tmp_path):
    path = tmp_path / 'assets.sqlite3'
    store = LocalStore(path)
    first = save_asset('a', AssetInput(name='Database', criticality='critical'), 'analyst', store)
    assert LocalStore(path).list_assets('a')[0]['criticality'] == 'critical'
    assert LocalStore(path).list_assets('b') == []
    update = AssetInput(name='Database', criticality='high', expected_version=1, expected_token=first['revision_token'])
    second = save_asset('a', update, 'editor', store)
    assert second['version'] == 2 and second['updated_by'] == 'editor'
    with pytest.raises(AssetConflictError): save_asset('a', update, 'stale-editor', store)
    assert not store.delete_asset('a', first['id'], 1, first['revision_token'])
    assert store.delete_asset('a', second['id'], 2, second['revision_token'])
    recreated = save_asset('a', AssetInput(name='Database'), 'new-editor', store)
    assert recreated['revision_token'] != first['revision_token']
    with pytest.raises(AssetConflictError): save_asset('a', update, 'old-editor', store)
    assert not store.delete_asset('a', first['id'], 1, first['revision_token'])


def test_concurrent_creates_do_not_overwrite_each_other(tmp_path):
    store = LocalStore(tmp_path / 'race.sqlite3')
    def create(actor):
        try: return save_asset('race', AssetInput(name='Gateway'), actor, store)
        except AssetConflictError: return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ['one','two']))
    assert sum(result is not None for result in results) == 1
    assert len(store.list_assets('race')) == 1


def test_route_priorities_keep_evidence_and_do_not_infer_exploitability():
    graph, store = GraphStore(), MemoryAssets()
    text = 'Gateway communicates with Auth_Service. Auth_Service accesses Customer_Database. Customer_Database does not access Backup_Vault. Gateway may access Test_Server.'
    publish(graph, text, workspace='triage')
    save_asset('triage', AssetInput(name='Gateway', exposure='internet'), 'analyst', store)
    save_asset('triage', AssetInput(name='Customer_Database', criticality='critical'), 'analyst', store)
    result = assess_routes('triage', 'Gateway', store, graph)
    first = result['routes'][0]
    assert first['nodes'][-1] == 'Customer_Database' and first['review_priority'] == 'review_first'
    assert first['exploitability'] == 'not_determined'
    assert all(route['nodes'][-1] not in {'Backup_Vault','Test_Server'} for route in result['routes'])
    for route in result['routes']:
        assert route['context_source'] == 'analyst_supplied_unverified'
        assert route['citations']
        for citation in route['citations']:
            assert text[citation['start_char']:citation['end_char']] == citation['exact_quote']
    assert assess_routes('other', 'Gateway', store, graph)['routes'] == []


def test_api_graph_matching_stale_edits_and_role_isolation(client, memory, monkeypatch):
    client.post('/v1/workspaces/inventory/demo/cyber')
    created = client.put('/v1/workspaces/inventory/assets', json={'name':'Core_Banking_Database','criticality':'critical'})
    assert created.status_code == 200
    record = created.json()
    assert record['source_kind'] == 'analyst_supplied'
    assert client.get('/v1/workspaces/inventory/assets').json()['assets'][0]['graph_match']
    assert client.put('/v1/workspaces/inventory/assets', json={'name':'Core_Banking_Database'}).status_code == 409
    assert client.put('/v1/workspaces/inventory/assets', json={'name':'invalid','criticality':'supercritical'}).status_code == 422
    assert client.get('/v1/workspaces/inventory/route-assessment?entry_point=%20').status_code == 400
    import backend.security.access as access
    monkeypatch.setenv('AUTH_MODE', 'neon')
    monkeypatch.setattr(access, 'verify_identity', lambda token: {'uid':'reader'})
    monkeypatch.setattr(access, 'load_memberships', lambda uid: {'workspaces':{'inventory':'viewer'}})
    headers = {'Authorization':'Bearer token'}
    assert client.get('/v1/workspaces/inventory/assets',headers=headers).status_code == 200
    assert client.get('/v1/workspaces/inventory/route-assessment?entry_point=Legacy_PHP_Gateway',headers=headers).status_code == 200
    assert client.get('/v1/workspaces/other/assets',headers=headers).status_code == 403
    assert client.put('/v1/workspaces/inventory/assets',headers=headers,json={'name':'New'}).status_code == 403
    assert client.delete(f"/v1/workspaces/inventory/assets/{record['id']}?expected_version=1&expected_token={record['revision_token']}",headers=headers).status_code == 403
