"""Firestore contract checks without credentials or a remote project."""
import pytest
from backend.storage.firebase_store import FirebaseStore, FirebaseVectorStore
from test_cyber_and_hosted_storage import publish
from backend.storage.graph_store import GraphStore


class Snapshot:
    def __init__(self, reference, data):
        self.reference, self.data = reference, data
    def to_dict(self):
        return self.data


class Reference:
    def __init__(self, db, path):
        self.db, self.path = db, path
    def collection(self, name):
        return Collection(self.db, self.path + '/' + name)
    def set(self, data, merge=False):
        if self.db.fail_pages and '/pages/' in self.path:
            raise RuntimeError('Simulated write failure')
        self.db.rows[self.path] = {**self.db.rows.get(self.path, {}), **data} if merge else dict(data)
    def get(self):
        return Snapshot(self, self.db.rows.get(self.path))
    def delete(self):
        self.db.rows.pop(self.path, None)


class Collection:
    def __init__(self, db, path):
        self.db, self.path = db, path
    def document(self, key):
        return Reference(self.db, self.path + '/' + key)
    def stream(self):
        return [Snapshot(Reference(self.db, path), data) for path, data in list(self.db.rows.items())
                if path.startswith(self.path + '/') and path.count('/') == self.path.count('/') + 1]


class FakeFirestore:
    def __init__(self):
        self.rows, self.fail_pages = {}, False
    def collection(self, name):
        return Collection(self, name)


def test_firebase_roundtrip_edit_delete_and_workspace_isolation(monkeypatch):
    # Tiny page size forces the same split/reassembly path used for large documents.
    monkeypatch.setattr('backend.storage.firebase_store.PAGE_BYTES', 50)
    client = FakeFirestore()
    persistence = FirebaseStore(client)
    batch = publish(GraphStore(), 'Gateway accesses Database.')
    persistence.publish(batch)
    other = batch.model_copy(deep=True)
    other.workspace_id = 'another'
    other.document.workspace_id = 'another'
    persistence.publish(other)
    assert len(list(persistence.load_batches())) == 2
    updated = batch.model_copy(deep=True)
    updated.document.revision = 2
    persistence.publish(updated)
    restored = [b for b in persistence.load_batches() if b.workspace_id == 'cyber'][0]
    assert restored.document.revision == 2
    assert restored.chunks[0].text == batch.chunks[0].text
    persistence.delete_document('cyber', 'topology')
    assert [b.workspace_id for b in persistence.load_batches()] == ['another']
    assert not list(persistence._document('cyber', 'topology').collection('pages').stream())


def test_failed_firebase_publication_retains_previous_revision():
    client = FakeFirestore()
    persistence = FirebaseStore(client)
    batch = publish(GraphStore(), 'Gateway accesses Database.')
    persistence.publish(batch)
    client.fail_pages = True
    with pytest.raises(RuntimeError):
        persistence.publish(batch)
    assert list(persistence.load_batches())[0].document.id == batch.document.id


def test_firebase_integrity_failure_is_not_silently_accepted():
    client = FakeFirestore()
    persistence = FirebaseStore(client)
    persistence.publish(publish(GraphStore(), 'Gateway accesses Database.'))
    page = next(path for path in client.rows if '/pages/' in path)
    client.rows[page]['payload'] = b'corrupted'
    with pytest.raises(RuntimeError, match='integrity'):
        list(persistence.load_batches())


def test_firebase_vector_cache_scopes_topics_and_normalizes():
    store = FirebaseVectorStore(FakeFirestore())
    store.cache_vectors('one', {'a': [3, 0], 'b': [0, 2]})
    store.cache_vectors('two', {'other': [1, 0]})
    assert store.query('one', [1, 0], allowed_chunk_ids=['b']) == [('b', 0.0)]
    assert store.query('one', [1, 0], allowed_chunk_ids=[]) == []
    assert store.query('one', [1, 0])[0] == ('a', 1.0)
    store.remove_chunks('one', ['a'])
    assert list(store.get_vectors('one')) == ['b']
