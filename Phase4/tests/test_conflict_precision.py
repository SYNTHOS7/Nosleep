from backend.storage.graph_store import GraphStore
from test_cyber_and_hosted_storage import publish


def test_multi_target_edges_are_not_conflicts():
    store = GraphStore()
    publish(store, 'Gateway accesses Database_A. Gateway accesses Database_B. Gateway does not access Database_C.')
    assert store.conflicts['cyber'] == []


def test_synthetic_heading_negation_is_not_a_claim():
    store = GraphStore()
    batch = publish(store, 'SYNTHETIC DEMO: This actor is not real. Gateway accesses Database.')
    assert not any(e.name in {'SYNTHETIC','DEMO'} for e in batch.aggregated_entities)
    assert len(batch.aggregated_relations) == 1


def test_same_target_opposite_claims_still_conflict():
    store = GraphStore()
    publish(store, 'Patch mitigates CVE-2024-4577.', doc='vendor-a')
    publish(store, 'Patch does not mitigate CVE-2024-4577.', doc='vendor-b')
    assert len(store.conflicts['cyber']) == 1
    conflict = store.conflicts['cyber'][0]
    assert conflict.source_a['quote'] == 'Patch mitigates CVE-2024-4577.'
    assert conflict.source_b['quote'] == 'Patch does not mitigate CVE-2024-4577.'


def test_demo_has_one_relevant_dispute(client):
    client.post('/v1/workspaces/precision/demo/cyber')
    result = client.post('/v1/query', json={'workspace_id':'precision','query':'Conflicting mitigation claims for CVE-2024-4577'}).json()
    assert len(result['conflicts']) == 1
    assert 'Gateway_Patch' in result['conflicts'][0]['statement_a']
    unrelated = client.post('/v1/query', json={'workspace_id':'precision','query':'Conflicting claims for CVE-2099-99999'}).json()
    assert unrelated['conflicts'] == []
