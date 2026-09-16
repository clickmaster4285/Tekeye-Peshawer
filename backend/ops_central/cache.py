"""Central Ops camera cache helpers."""

from __future__ import annotations

import logging

from .models import RemoteServer

logger = logging.getLogger(__name__)


def parse_camera_id(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def resolve_stream_key(stream_key: str, camera_id, code: str) -> str:
    key = (stream_key or "").strip()
    if key:
        return key
    cid = parse_camera_id(camera_id)
    if cid:
        return f"cam-{cid}"
    code = (code or "").strip()
    if code:
        return code if code.startswith("cam-") else f"cam-{code}"
    return ""


def camera_matches_entry(
    cam: dict,
    *,
    stream_key: str,
    camera_id: int | None,
    code: str,
) -> bool:
    if stream_key and (cam.get("ml_stream_key") or cam.get("code") or "") == stream_key:
        return True
    if camera_id is not None and cam.get("id") == camera_id:
        return True
    if code and (cam.get("code") or "") == code:
        return True
    if stream_key.startswith("cam-"):
        sid = stream_key[4:]
        if sid.isdigit() and cam.get("id") == int(sid):
            return True
    return False


def prune_server_camera_cache(
    server: RemoteServer,
    *,
    stream_key: str,
    camera_id: int | None,
    code: str,
) -> list[dict]:
    cached = list(server.cached_cameras or [])
    if not cached:
        return cached
    pruned = [
        cam
        for cam in cached
        if isinstance(cam, dict)
        and not camera_matches_entry(
            cam,
            stream_key=stream_key,
            camera_id=camera_id,
            code=code,
        )
    ]
    if len(pruned) != len(cached):
        server.cached_cameras = pruned
        server.save(update_fields=["cached_cameras", "updated_at"])
    return pruned


def prune_camera_from_all_server_caches(
    *,
    camera_id: int | None,
    stream_key: str = "",
    code: str = "",
) -> int:
    """Remove a camera from every RemoteServer cache. Returns number of servers updated."""
    key = resolve_stream_key(stream_key, camera_id, code)
    updated = 0
    for server in RemoteServer.objects.all():
        before = len(server.cached_cameras or [])
        after = len(
            prune_server_camera_cache(
                server,
                stream_key=key,
                camera_id=camera_id,
                code=code,
            )
        )
        if after != before:
            updated += 1
    if updated:
        logger.info(
            "[ops-cache] Pruned camera id=%s stream_key=%s from %s server cache(s)",
            camera_id,
            key,
            updated,
        )
    return updated


def server_is_local_hub(server: RemoteServer) -> bool:
    ml = (server.resolved_ml_base_url() or "").lower()
    base = (server.normalized_base_url() or "").lower()
    return any(host in ml or host in base for host in ("127.0.0.1", "localhost", "::1"))


def stream_key_camera_id(key: str) -> int | None:
    raw = (key or "").strip()
    if raw.lower().startswith("cam-") and raw[4:].isdigit():
        return int(raw[4:])
    return parse_camera_id(raw)


def django_owns_ml_inventory(server: RemoteServer) -> bool:
    """True when this hub's Camera table is the source of truth for the ML node."""
    if server_is_local_hub(server):
        return True
    from cameras.models import Camera

    return Camera.objects.filter(ml_server_id=server.pk).exists()


def _live_feed_flags(live: dict | None) -> tuple[bool, bool]:
    live = live or {}
    has_frame = bool(live.get("has_frame"))
    connected = bool(live.get("connected") or has_frame)
    return connected, has_frame


def _row_from_django_camera(camera, *, live: dict | None, server_name: str) -> dict:
    connected, has_frame = _live_feed_flags(live)
    site = getattr(getattr(camera, "nvr", None), "site", None)
    return {
        "id": camera.pk,
        "code": camera.code or camera.stream_key,
        "name": camera.name,
        "label": camera.name,
        "display_label": camera.display_label,
        "location": camera.location or "",
        "site_code": getattr(site, "code", "") or camera.location or "",
        "site_name": getattr(site, "name", "") or "",
        "nvr_name": getattr(getattr(camera, "nvr", None), "name", "") or "",
        "channel": camera.channel,
        "purpose": camera.purpose,
        "purpose_label": camera.purpose_label,
        "ml_enabled": camera.is_active,
        "is_rtsp": True,
        "ml_stream_key": camera.stream_key,
        "ml_live_stream_url": "",
        "raw_stream_url": "",
        "status": "Online" if connected else "Offline",
        "is_active": camera.is_active,
        "connected": connected,
        "has_frame": has_frame,
        "detections": (live or {}).get("detections", 0),
        "registered": bool(live),
    }


def bind_ml_cameras_to_django_registry(
    server: RemoteServer,
    ml_cameras: list,
    *,
    unregister_orphans: bool = True,
) -> list[dict]:
    """
    For hub-owned ML nodes, Django cameras assigned to this server are the live list.
    ML leftovers from deleted cameras are unregistered and omitted.
    """
    if not django_owns_ml_inventory(server):
        return [cam for cam in ml_cameras if isinstance(cam, dict)]

    from cameras.models import Camera

    from .client import unregister_ml_camera_remote

    live_by_key: dict[str, dict] = {}
    for cam in ml_cameras:
        if not isinstance(cam, dict):
            continue
        key = (cam.get("ml_stream_key") or cam.get("code") or cam.get("key") or "").strip()
        if key:
            live_by_key[key] = cam

    assigned = list(
        Camera.objects.filter(is_active=True, ml_server_id=server.pk)
        .select_related("nvr", "nvr__site")
        .order_by("id")
    )
    keep_keys = {cam.stream_key for cam in assigned}
    out = [
        _row_from_django_camera(
            cam,
            live=live_by_key.get(cam.stream_key),
            server_name=server.name,
        )
        for cam in assigned
    ]

    if unregister_orphans:
        ml_base = (server.resolved_ml_base_url() or "").rstrip("/")
        for key, live in live_by_key.items():
            if key in keep_keys:
                continue
            pk = stream_key_camera_id(key)
            still_exists = (
                Camera.objects.filter(pk=pk, is_active=True).exists() if pk else False
            )
            if still_exists and not Camera.objects.filter(pk=pk, ml_server_id=server.pk).exists():
                # Camera moved/unassigned — drop from this node only.
                pass
            if ml_base:
                result = unregister_ml_camera_remote(ml_base, key)
                if result.get("ok"):
                    logger.info(
                        "[ops-cache] Unregistered orphan %s from %s",
                        key,
                        server.name,
                    )
            prune_server_camera_cache(
                server,
                stream_key=key,
                camera_id=pk,
                code=(live.get("code") or ""),
            )

    return out
