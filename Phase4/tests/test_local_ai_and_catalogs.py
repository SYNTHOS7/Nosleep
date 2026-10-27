import json
import time
import pytest
from backend.ingestion import local_ai
from backend.contracts.models import Chunk


def test_only_loopback_model_endpoints_are_allowed(monkeypatch):
    for value in ('https://example.com', 'http://example.com:11434', 'http://127.0.0.1:11434/redirect', 'http://name:password@127.0.0.1:11434'):
        monkeypatch.setenv('OLLAMA_URL', value)
        with pytest.raises(local_ai.LocalAIError): local_ai.request('/api/tags')


def test_schema_quote_and_modality_guards(monkeypatch):
    source = 'Gateway may access Database. Gateway does not access Vault.'
    records = [dict(source_entity_name='Gateway', source_entity_label='Asset', predicate='ACCESSES',
                    target_entity_name=target, target_entity_label='Asset', polarity='AFFIRMATIVE',
                    modality='CERTAIN', exact_quote=quote) for target, quote in (
                    ('Database', 'Gateway may access Database.'), ('Vault', 'Gateway does not access Vault.'),
                    ('Imaginary', 'Gateway accesses Imaginary.'))]
    records.append({**records[0], 'predicate':'EXFILTRATES'})
    def request(path, payload=None):
        if path == '/api/tags': return {'models': [{'name':'qwen2.5-coder:7b','digest':'test-model'}]}
        assert payload['stream'] is False and 'tools' not in payload
        return {'message': {'content': json.dumps({'entities': [], 'relations': records})}}
    monkeypatch.setattr(local_ai, 'request', request)
    result = local_ai.extract(source)
    assert len(result['relations']) == 2
    assert result['relations'][0]['modality'] == 'POSSIBLE'
    assert result['relations'][1]['polarity'] == 'NEGATIVE'
    assert {'Gateway','Database','Vault'} == {e['name'] for e in result['entities']}


def test_embedding_profiles_block_old_hash_vectors(monkeypatch):
    from test_local_durability import batch_for
    monkeypatch.setenv('EMBEDDING_PROVIDER', 'ollama')
    monkeypatch.setattr(local_ai, 'request', lambda *a, **kw: {'models':[{'name':'nomic-embed-text:latest','digest':'test-digest'}]})
    with pytest.raises(local_ai.LocalAIError): local_ai.assert_batch_profile(batch_for())


def test_embeddings_validate_dimensions_and_never_fall_back(monkeypatch):
    from backend.ingestion.embedder import embed_texts, EmbeddingValidationError
    monkeypatch.setenv('EMBEDDING_PROVIDER', 'ollama')
    def request(path, payload=None):
        if path == '/api/tags': return {'models':[{'name':'nomic-embed-text:latest','digest':'test-digest'}]}
        assert payload['truncate'] is False and payload['input'][0].startswith('search_query: ')
        return {'embeddings': [[1.0, 2.0]]}
    monkeypatch.setattr(local_ai, 'request', request)
    with pytest.raises(EmbeddingValidationError): embed_texts(['query'], 'query')
    monkeypatch.setattr(local_ai, 'embed', lambda *a, **kw: (_ for _ in ()).throw(local_ai.LocalAIError('offline')))
    with pytest.raises(local_ai.LocalAIError): embed_texts(['query'], 'query')


def test_extraction_cache_isolated_by_workspace_document_and_provider():
    from backend.ingestion.extractor import build_cache_key
    chunk = Chunk(id='one', workspace_id='first', document_id='doc', chunk_index=0, page_number=1,
                  text='Gateway accesses Database.', token_count=4, start_char=0,end_char=25)
    assert build_cache_key(chunk) != build_cache_key(chunk.model_copy(update={'workspace_id':'second'}))
    assert build_cache_key(chunk) != build_cache_key(chunk.model_copy(update={'id':'two'}))


def catalogs():
    return {'nvd': {'version':'2.0','vulnerabilities':[{'cve': {'id':'CVE-2024-4577','descriptions':[{'lang':'en','value':'Synthetic vulnerability fixture.'}]}}]},
            'stix': {'type':'bundle','objects':[{'type':'attack-pattern','id':'attack-pattern--00000000-0000-4000-8000-000000000001',
                     'name':'Synthetic technique','description':'Passive source data.',
                     'external_references':[{'source_name':'mitre-attack','external_id':'T1059'}]}]}}


@pytest.mark.parametrize('format_name', ['nvd','stix'])
def test_offline_catalog_imports_are_scoped_and_do_not_invent_paths(client, format_name):
    from backend.storage.graph_store import get_graph_store
    raw = json.dumps(catalogs()[format_name]).encode()
    for _ in range(2):
        receipt = client.post(f'/v1/workspaces/intel/imports/intel?format={format_name}', files={'file':('fixture.json', raw)})
        assert receipt.status_code == 202
        for _ in range(200):
            operation = client.get(f"/v1/operations/{receipt.json()['operation_id']}").json()
            if operation['status'] in {'COMPLETED','FAILED'}: break
            time.sleep(.01)
        assert operation['status'] == 'COMPLETED'
    store = get_graph_store()
    assert len(store.documents['intel']) == 1
    assert not store.relations['intel']
    assert ('CVE-2024-4577' if format_name == 'nvd' else 'T1059') in store.entities['intel']
    assert client.post(f'/v1/workspaces/intel/imports/intel?format={format_name}',files={'file':('bad.json', b'{}')}).status_code == 400
