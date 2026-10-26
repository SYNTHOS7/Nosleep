"""Verify Neon Auth's Ed25519 JWTs against its configured JWKS and origin."""
from functools import lru_cache
import os
from urllib.parse import urlsplit


def auth_settings():
    base = os.environ.get("NEON_AUTH_URL", "").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("NEON_AUTH_URL must be the HTTPS URL from your Neon Auth dashboard")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return base, origin


@lru_cache(maxsize=4)
def jwks_client(url):
    from jwt import PyJWKClient
    return PyJWKClient(url, cache_keys=True, lifespan=300, timeout=10)


def verify_identity(token):
    if not token or len(token) > 16384:
        raise ValueError("Invalid authentication token")
    import jwt
    base, origin = auth_settings()
    signing_key = jwks_client(base + "/.well-known/jwks.json").get_signing_key_from_jwt(token)
    payload = jwt.decode(token, signing_key.key, algorithms=["EdDSA"], issuer=origin, audience=origin,
                         options={"require": ["exp", "iat", "sub", "iss", "aud"]}, leeway=5)
    if payload.get("banned") is True or not isinstance(payload["sub"], str) or not payload["sub"]:
        raise ValueError("Account is unavailable")
    return {"uid": payload["sub"], "email": payload.get("email", "")}
