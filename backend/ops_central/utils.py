"""Shared helpers for Central Ops."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from django.conf import settings
from rest_framework.authtoken.models import Token


def parse_location_url_map(raw: str) -> dict[str, str]:
    """Parse 'ABBOTTABAD=http://host:8000,DI_KHAN=http://…' into a dict."""
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip().upper()
        val = val.strip().rstrip("/")
        if key and val:
            out[key] = val
    return out


def ensure_http_url(value: str | None, *, default_port: int | None = 8000) -> str:
    """
    Accept host, host:port, or full URL.
    - Adds http:// if scheme is missing
    - If default_port is set and the URL has no port, appends that port
      (Django API default 8000). Pass default_port=None to leave bare host as :80.
    """
    value = (value or "").strip().rstrip("/")
    if not value:
        return ""

    if "://" not in value:
        value = f"http://{value}"

    parsed = urlparse(value)
    if not parsed.hostname:
        return value.rstrip("/")

    # Already has an explicit port
    if parsed.port is not None:
        return value.rstrip("/")

    # https without port → leave as 443; http without port → apply default_port
    if parsed.scheme == "https":
        return value.rstrip("/")

    if default_port is None:
        return value.rstrip("/")

    netloc = parsed.hostname
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        netloc = f"{userinfo}@{netloc}"
    netloc = f"{netloc}:{default_port}"
    return urlunparse((parsed.scheme, netloc, parsed.path or "", "", "", "")).rstrip("/")


def ensure_ml_url(value: str | None) -> str:
    """Normalize ML service URL; default port 8100 when omitted.

    If the user pasted a Django URL (:8000), remap to ML (:8100).
    """
    normalized = ensure_http_url(value, default_port=8100)
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.port == 8000 and parsed.hostname:
        netloc = parsed.hostname
        if parsed.username:
            userinfo = parsed.username
            if parsed.password:
                userinfo += f":{parsed.password}"
            netloc = f"{userinfo}@{netloc}"
        netloc = f"{netloc}:8100"
        return urlunparse((parsed.scheme or "http", netloc, "", "", "", "")).rstrip("/")
    return normalized



def token_for_user(user) -> str:
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    token, _ = Token.objects.get_or_create(user=user)
    return token.key


def resolve_remote_token(request, explicit: str | None = None) -> str:
    """Prefer explicit token; otherwise use the logged-in user's API token."""
    explicit = (explicit or "").strip()
    if explicit:
        return explicit
    return token_for_user(getattr(request, "user", None))


def ensure_default_remote_server(user) -> None:
    """Create one default local ML server if the registry is empty."""
    from .models import ConnectionMode, RemoteServer

    if RemoteServer.objects.exists():
        return
    RemoteServer.objects.create(
        name="Local ML",
        location_code="LOCAL",
        connection_mode=ConnectionMode.ML,
        base_url="http://127.0.0.1:8100",
        ml_base_url="http://127.0.0.1:8100",
        auth_token="ml-only",
        is_active=True,
        notes="Default ML node (auto-created)",
        cached_cameras=[],
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def ensure_sync_city_remote_servers(user=None) -> int:
    """
    Register Ops RemoteServers for each SYNC_CITY_BASE_URLS entry so City Grid
    can fetch live cameras / Django ops for sync-connected cities (e.g. Abbottabad).
    """
    from .models import ConnectionMode, RemoteServer

    base_map = parse_location_url_map(getattr(settings, "SYNC_CITY_BASE_URLS", "") or "")
    ml_map = parse_location_url_map(getattr(settings, "SYNC_CITY_ML_URLS", "") or "")
    token_map = parse_location_url_map(getattr(settings, "SYNC_CITY_API_TOKENS", "") or "")
    if not base_map:
        return 0

    display = {
        "PESHAWAR": "Peshawar",
        "ABBOTTABAD": "Abbottabad",
        "DI_KHAN": "DI Khan",
        "MARDAN": "Mardan",
        "NOWSHERA": "Nowshera",
        "KOHAT": "Kohat",
    }

    created_or_updated = 0
    for loc, base_url in base_map.items():
        base_url = ensure_http_url(base_url, default_port=8000)
        ml_url = ensure_http_url(ml_map.get(loc, ""), default_port=8100) if ml_map.get(loc) else ""
        token = (token_map.get(loc) or "").strip()
        if not token:
            token = token_for_user(user) or "pending"

        qs = RemoteServer.objects.filter(location_code__iexact=loc)
        server = qs.first()
        if server is None:
            # Also match by name containing the location
            server = (
                RemoteServer.objects.filter(name__icontains=loc.replace("_", " "))
                .exclude(location_code__iexact="LOCAL")
                .first()
            )

        fields = {
            "name": display.get(loc, loc.replace("_", " ").title()),
            "location_code": loc,
            "connection_mode": ConnectionMode.DJANGO,
            "base_url": base_url,
            "is_active": True,
            "notes": "Auto-linked from SYNC_CITY_BASE_URLS (city_sync)",
        }
        if ml_url:
            fields["ml_base_url"] = ml_url
        # Don't wipe a hand-set token with "pending"
        if token and token != "pending":
            fields["auth_token"] = token
        elif server is None:
            fields["auth_token"] = token or "pending"

        if server is None:
            RemoteServer.objects.create(
                **fields,
                cached_cameras=[],
                created_by=user if getattr(user, "is_authenticated", False) else None,
            )
            created_or_updated += 1
        else:
            update_fields = []
            for key, val in fields.items():
                if getattr(server, key, None) != val:
                    setattr(server, key, val)
                    update_fields.append(key)
            if update_fields:
                server.save(update_fields=update_fields + ["updated_at"])
                created_or_updated += 1

    return created_or_updated
