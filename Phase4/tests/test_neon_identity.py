import time
from types import SimpleNamespace
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from backend.security import neon_identity


@pytest.fixture
def issuer(monkeypatch):
    monkeypatch.setenv('NEON_AUTH_URL', 'https://auth.example.test/neondb/auth')
    private = Ed25519PrivateKey.generate()
    calls = []
    class Keys:
        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=private.public_key())
    monkeypatch.setattr(neon_identity, 'jwks_client', lambda url: calls.append(url) or Keys())
    def token(**overrides):
        now = int(time.time())
        payload = {'sub':'user-1','email':'user@example.com','iat':now,'exp':now+900,
                   'iss':'https://auth.example.test','aud':'https://auth.example.test'}
        payload.update(overrides)
        return jwt.encode(payload, private, algorithm='EdDSA', headers={'kid':'test-key'})
    return token, calls


def test_neon_checks_signature_origin_and_subject(issuer):
    token, calls = issuer
    assert neon_identity.verify_identity(token()) == {'uid':'user-1','email':'user@example.com'}
    assert calls == ['https://auth.example.test/neondb/auth/.well-known/jwks.json']


@pytest.mark.parametrize('overrides', [{'iss':'https://wrong.test'}, {'aud':'https://wrong.test'},
    {'exp':1}, {'banned':True}, {'sub':''}])
def test_invalid_claims_fail_closed(issuer, overrides):
    token, _ = issuer
    with pytest.raises((ValueError, jwt.InvalidTokenError)):
        neon_identity.verify_identity(token(**overrides))


def test_untrusted_signing_key_is_rejected(issuer):
    token, _ = issuer
    payload = jwt.decode(token(), options={'verify_signature':False})
    attacker = Ed25519PrivateKey.generate()
    forged = jwt.encode(payload, attacker, algorithm='EdDSA')
    with pytest.raises(jwt.InvalidSignatureError):
        neon_identity.verify_identity(forged)


def test_configured_endpoint_cannot_be_plaintext(monkeypatch):
    monkeypatch.setenv('NEON_AUTH_URL', 'http://auth.example.test')
    with pytest.raises(ValueError):
        neon_identity.auth_settings()
