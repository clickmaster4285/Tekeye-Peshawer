"""
Short-lived pass for watching a city's cameras straight from the city server.

HQ signs the pass; the browser hands it to the city with each video request, so the video
goes browser <-> city and never through HQ. The signing secret is the SHA-256 of the city's
sync API key: HQ stores exactly that hash, and the city computes it from its raw key, so
no extra secret has to be shared.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

PASS_TTL_SEC = 300


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, body: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def issue_pass(loc: str, *, user: str = "", ttl: int = PASS_TTL_SEC) -> tuple[str, int] | None:
    """HQ: (pass, expires_at) for one city, or None when the city has no active sync key."""
    from city_sync.models import SyncCredential

    cred = SyncCredential.objects.filter(
        location_code=loc.upper(), is_active=True, revoked_at__isnull=True
    ).first()
    if cred is None:
        return None
    exp = int(time.time()) + ttl
    body = _b64(json.dumps({"loc": loc.upper(), "exp": exp, "sub": user[:150]}, separators=(",", ":")).encode())
    return f"{body}.{_sign(cred.key_hash, body)}", exp


def check_pass(token: str) -> dict | None:
    """City: the pass's claims when HQ signed it for this city and it has not expired."""
    from city_sync.identity import is_city, location_code
    from city_sync.models import SyncCredential
    from city_sync.worker import _load_api_key

    if not is_city() or not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    try:
        raw_key = _load_api_key()
    except RuntimeError:
        return None
    if not raw_key or not hmac.compare_digest(sig, _sign(SyncCredential.hash_key(raw_key), body)):
        return None
    try:
        claims = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(claims, dict) or claims.get("loc") != location_code():
        return None
    if int(claims.get("exp") or 0) < time.time():
        return None
    return claims
