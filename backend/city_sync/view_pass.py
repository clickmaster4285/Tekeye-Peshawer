"""
Short-lived pass for watching a city's cameras straight from the city server.

HQ signs the pass; the browser hands it to the city with each video request, so the video
goes browser <-> city and never through HQ. HQ signs with an Ed25519 private key kept in a
file (never in the database), and every city verifies with HQ's public key, which arrives
on each heartbeat answer. Reading HQ's database alone is therefore not enough to forge a
pass, and a city holds nothing that lets it sign one.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from django.conf import settings

logger = logging.getLogger(__name__)

PASS_TTL_SEC = 300
_PRIVATE_KEY_FILE = "view_pass_ed25519.pem"
_HQ_PUBLIC_KEY_FILE = "hq_view_pass_public.key"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _key_dir() -> Path:
    path = Path(getattr(settings, "VIEW_PASS_KEY_DIR", "") or (Path(settings.BASE_DIR) / ".keys"))
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# HQ side
# ---------------------------------------------------------------------------


def _hq_private_key() -> Ed25519PrivateKey:
    """HQ's signing key; made on first use and kept in VIEW_PASS_KEY_DIR."""
    path = _key_dir() / _PRIVATE_KEY_FILE
    if not path.exists():
        pem = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        # O_EXCL: two workers starting together cannot write two different keys.
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as fh:
                fh.write(pem)
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def hq_public_key_b64() -> str:
    """HQ: public half of the signing key, sent to cities on every heartbeat answer."""
    raw = _hq_private_key().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return _b64(raw)


def issue_pass(loc: str, *, user: str = "", ttl: int = PASS_TTL_SEC) -> tuple[str, int] | None:
    """HQ: (pass, expires_at) for one city, or None when the city has no active sync key."""
    from city_sync.models import SyncCredential

    if not SyncCredential.objects.filter(
        location_code=loc.upper(), is_active=True, revoked_at__isnull=True
    ).exists():
        return None
    exp = int(time.time()) + ttl
    body = _b64(json.dumps({"loc": loc.upper(), "exp": exp, "sub": user[:150]}, separators=(",", ":")).encode())
    return f"{body}.{_b64(_hq_private_key().sign(body.encode()))}", exp


# ---------------------------------------------------------------------------
# City side
# ---------------------------------------------------------------------------


def save_hq_public_key(key_b64: str) -> None:
    """City: remember HQ's public key from a heartbeat answer (shared by web and worker processes)."""
    key_b64 = (key_b64 or "").strip()
    try:
        if len(_unb64(key_b64)) != 32:
            return
    except (ValueError, TypeError):
        return
    path = _key_dir() / _HQ_PUBLIC_KEY_FILE
    try:
        if path.exists() and path.read_text().strip() == key_b64:
            return
        tmp = path.with_suffix(".tmp")
        tmp.write_text(key_b64)
        os.replace(tmp, path)
        logger.info("Saved HQ view-pass public key")
    except OSError:
        logger.exception("Could not save HQ view-pass public key")


def _hq_public_key() -> Ed25519PublicKey | None:
    path = _key_dir() / _HQ_PUBLIC_KEY_FILE
    try:
        return Ed25519PublicKey.from_public_bytes(_unb64(path.read_text().strip()))
    except (OSError, ValueError, TypeError):
        return None


def check_pass(token: str) -> dict | None:
    """City: the pass's claims when HQ signed it for this city and it has not expired."""
    from city_sync.identity import is_city, location_code

    if not is_city() or not token or "." not in token:
        return None
    public_key = _hq_public_key()
    if public_key is None:
        return None
    body, sig = token.rsplit(".", 1)
    try:
        public_key.verify(_unb64(sig), body.encode())
        claims = json.loads(_unb64(body))
    except (InvalidSignature, ValueError, TypeError):
        return None
    if not isinstance(claims, dict) or claims.get("loc") != location_code():
        return None
    if int(claims.get("exp") or 0) < time.time():
        return None
    return claims
