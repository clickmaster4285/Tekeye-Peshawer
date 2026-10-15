"""Sync API authentication — one credential bound to one LOCATION_CODE."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from city_sync.models import SyncCredential


@dataclass
class SyncPrincipal:
    location_code: str
    is_authenticated: bool = True

    @property
    def pk(self):
        return self.location_code


class SyncApiKeyAuthentication(BaseAuthentication):
    """
    Authorization: Bearer <raw-key>
    or X-CIIS-Sync-Key: <raw-key>
    """

    header_names = ("HTTP_AUTHORIZATION", "HTTP_X_CIIS_SYNC_KEY")

    def authenticate(self, request):
        raw = self._extract_key(request)
        if not raw:
            return None

        # Dev fallback: SYNC_API_KEYS="DI_KHAN=secret,ABBOTTABAD=secret"
        env_map = self._env_key_map()
        key_hash = SyncCredential.hash_key(raw)

        cred = (
            SyncCredential.objects.filter(key_hash=key_hash, is_active=True, revoked_at__isnull=True)
            .first()
        )
        if cred:
            return (SyncPrincipal(location_code=cred.location_code), raw)

        for loc, secret in env_map.items():
            if secret and secret == raw:
                return (SyncPrincipal(location_code=loc), raw)

        raise AuthenticationFailed("Invalid sync API key")

    def _extract_key(self, request) -> str:
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return (request.META.get("HTTP_X_CIIS_SYNC_KEY") or "").strip()

    def _env_key_map(self) -> dict[str, str]:
        raw = getattr(settings, "SYNC_API_KEYS", "") or ""
        out: dict[str, str] = {}
        for part in str(raw).split(","):
            part = part.strip()
            if not part or "=" not in part:
                continue
            loc, secret = part.split("=", 1)
            out[loc.strip().upper()] = secret.strip()
        return out
