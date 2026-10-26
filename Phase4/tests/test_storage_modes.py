from backend.storage.db_manager import DatabaseManager


def test_in_memory_mode_never_starts_chroma_disk_mirroring(monkeypatch):
    monkeypatch.setenv('VECTOR_BACKEND', 'in_memory')
    monkeypatch.delenv('CHROMA_MIRROR_ENABLED', raising=False)
    calls = []
    monkeypatch.setattr(DatabaseManager, '_init_chroma', lambda self: calls.append('chroma'))
    monkeypatch.setattr(DatabaseManager, '_init_neo4j', lambda self: None)
    manager = DatabaseManager()
    assert calls == []
    assert manager.get_status()['chromadb']['status'] == 'disabled'
    manager._chroma_executor.shutdown()


def test_firebase_never_enables_the_legacy_mirror(monkeypatch):
    monkeypatch.setenv('VECTOR_BACKEND', 'firebase')
    monkeypatch.setenv('CHROMA_MIRROR_ENABLED', 'true')
    calls = []
    monkeypatch.setattr(DatabaseManager, '_init_chroma', lambda self: calls.append('chroma'))
    monkeypatch.setattr(DatabaseManager, '_init_neo4j', lambda self: None)
    manager = DatabaseManager()
    assert calls == []
    manager._chroma_executor.shutdown()
