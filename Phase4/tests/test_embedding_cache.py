import hashlib
import re
import numpy as np
from backend.ingestion.embedder import _generate_multilingual_vectors, _word_vector, PINNED_DIMENSION


def test_cached_word_vectors_preserve_existing_embeddings():
    text = 'Gateway gateway हिंदी Database'
    reference = np.zeros(PINNED_DIMENSION)
    for word in re.findall(r'\w+', text.lower()):
        digest = hashlib.sha256(word.encode()).digest()
        reference += np.random.default_rng(int.from_bytes(digest[:4], 'big')).standard_normal(PINNED_DIMENSION)
    reference /= np.linalg.norm(reference)
    actual = _generate_multilingual_vectors([text])[0]
    assert np.array_equal(actual, reference)
    before = _word_vector('gateway', PINNED_DIMENSION).copy()
    _generate_multilingual_vectors(['gateway gateway gateway'])
    assert np.array_equal(before, _word_vector('gateway', PINNED_DIMENSION))
    assert not _word_vector('gateway', PINNED_DIMENSION).flags.writeable
