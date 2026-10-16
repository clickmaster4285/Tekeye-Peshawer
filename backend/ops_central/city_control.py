"""Federated City Control Grid — aggregate each city's Django/ML stack."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from datetime import datetime
from typing import Any

from django.utils import timezone

from .client import (
    fetch_ml_cameras,
    fetch_remote_cameras,
    fetch_remote_city_ops_stats,
    mark_server_health,
)
from .models import ConnectionMode, RemoteServer
from .utils import token_for_user

KNOWN_LOCATION_CODES = (
    "PESHAWAR",
    "KOHAT",
    "NOWSHERA",
    "MARDAN",
    "DI_KHAN",
    "SWH_RATTA_KULACHI",
    "ABBOTTABAD",
    "DDK",
    "THAKOT",
    "HAYATABAD",
    "LOCAL",
)

DISPLAY_NAMES = {
    "PESHAWAR": "Peshawar",
    "KOHAT": "Kohat",
    "NOWSHERA": "Nowshera",
    "MARDAN": "Mardan",
    "DI_KHAN": "DI Khan",
    "SWH_RATTA_KULACHI": "SWH Ratta Kulachi",
    "ABBOTTABAD": "Abbottabad",
    "DDK": "DDK",
    "THAKOT": "Thakot",
    "HAYATABAD": "Hayatabad",
    "LOCAL": "Local ML",
}


def _normalize_key(raw: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (raw or "").strip().upper()).strip("_")


def location_key_for_server(server: RemoteServer) -> str:
    code = _normalize_key(server.location_code or "")
    if code:
        return code
    if server.site_id and getattr(server, "site", None):
        site_code = _normalize_key(getattr(server.site, "code", "") or "")
        if site_code:
            return site_code
    name = (server.name or "").strip()
    upper = name.upper()
    compact = re.sub(r"[\s_\-]+", "", upper)
    for known in KNOWN_LOCATION_CODES:
        needle = known.replace("_", "")
        if needle and needle in compact:
            return known
        label = DISPLAY_NAMES.get(known, "").upper().replace(" ", "")
        if label and label in compact:
            return known
    return _normalize_key(name) or "UNKNOWN"


def display_city_name(key: str, fallback: str = "") -> str:
    if key in DISPLAY_NAMES:
        return DISPLAY_NAMES[key]
    if fallback:
        return fallback
    return key.replace("_", " ").title() if key else "Unknown"


def _camera_online(cam: dict) -> bool:
    status = str(cam.get("status") or "").strip().lower()
    if status in ("offline", "inactive", "down", "disconnected", "error"):
        return False
    if status in ("online", "active", "live", "running", "ok"):
        return True
    if isinstance(cam.get("connected"), bool) and cam["connected"]:
        return True
    if isinstance(cam.get("is_active"), bool):
        return cam["is_active"]
    return bool(
        (cam.get("view_stream_url") or "").strip()
        or (cam.get("webrtc_stream_url") or "").strip()
        or (cam.get("ml_live_stream_url") or "").strip()
        or (cam.get("ml_stream_key") or "").strip()
    )


def _server_token(server: RemoteServer, request_user) -> str:
    token = (server.auth_token or "").strip()
    if not token or token in ("pending", "ml-only"):
        token = token_for_user(request_user) or ""
    return token


def _fetch_server_cameras(server: RemoteServer, request_user) -> dict[str, Any]:
    if server.is_ml_mode():
        return fetch_ml_cameras(server.resolved_ml_base_url(), server_name=server.name)
    token = _server_token(server, request_user)
    if not token:
        return {"ok": False, "error": "No auth token for remote Django.", "cameras": []}
    return fetch_remote_cameras(server.normalized_base_url(), token)


def _derive_status(
    healthy: bool, cameras_online: int, cameras_total: int
) -> tuple[str, str]:
    if not healthy and cameras_total == 0:
        return "Offline", "No Signal"
    if cameras_total == 0:
        return ("Degraded", "Limited") if healthy else ("Offline", "No Signal")
    ratio = cameras_online / cameras_total
    if not healthy or cameras_online == 0:
        return "Offline", "No Signal"
    if ratio < 0.95:
        return "Degraded", "Limited"
    return "Online", "Good"


def _format_sync(iso: str | None) -> tuple[str, str]:
    if not iso:
        return "—", "No sync"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "—", "No sync"
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    absolute = timezone.localtime(dt).strftime("%b %d, %H:%M")
    sec = max(0, int((timezone.now() - dt).total_seconds()))
    if sec < 60:
        relative = f"{max(1, sec)} sec ago"
    elif sec < 3600:
        relative = f"{sec // 60} min ago"
    elif sec < 48 * 3600:
        relative = f"{sec // 3600} hr ago"
    else:
        relative = f"{sec // 86400} d ago"
    return absolute, relative


def build_city_control_board(*, request_user, overall_timeout: float = 12.0) -> dict[str, Any]:
    """Aggregate cameras + Django DB stats per city location."""
    from .synced_board import synced_alerts, synced_city_rows

    # HQ + cities on Locations & Sync come from the data synced here; remote servers
    # only fill in locations that do not sync.
    synced = synced_city_rows()
    synced_keys = {row["location_code"] for row in synced}
    if synced:
        synced_keys.add("LOCAL")  # this HQ's own ML server: already in the HQ row

    servers = list(
        RemoteServer.objects.filter(is_active=True).select_related("site").order_by("name")
    )

    groups: dict[str, list[RemoteServer]] = {}
    for server in servers:
        key = location_key_for_server(server)
        if key in synced_keys:
            continue
        groups.setdefault(key, []).append(server)
    servers = [s for members in groups.values() for s in members]

    # Parallel per-server camera fetch + django ops fetch (one django per location preferred).
    camera_jobs: dict[int, Any] = {}
    ops_jobs: dict[str, Any] = {}  # location_key -> future

    with ThreadPoolExecutor(max_workers=min(12, max(2, len(servers) * 2 or 2))) as pool:
        for server in servers:
            camera_jobs[server.pk] = pool.submit(_fetch_server_cameras, server, request_user)

        for key, members in groups.items():
            django_servers = [s for s in members if not s.is_ml_mode()]
            # Prefer first django member for DB federation; skip ML-only locations.
            target = django_servers[0] if django_servers else None
            if target is None:
                continue
            token = _server_token(target, request_user)
            if not token:
                continue
            ops_jobs[key] = pool.submit(
                fetch_remote_city_ops_stats,
                target.normalized_base_url(),
                token,
                timeout=7.0,
            )

        futures = list(camera_jobs.values()) + list(ops_jobs.values())
        if futures:
            wait(futures, timeout=overall_timeout, return_when=ALL_COMPLETED)

    camera_results: dict[int, dict] = {}
    for sid, fut in camera_jobs.items():
        try:
            camera_results[sid] = fut.result(timeout=0)
        except Exception as exc:  # noqa: BLE001
            camera_results[sid] = {"ok": False, "error": str(exc), "cameras": []}

    ops_results: dict[str, dict] = {}
    for key, fut in ops_jobs.items():
        try:
            ops_results[key] = fut.result(timeout=0)
        except Exception as exc:  # noqa: BLE001
            ops_results[key] = {
                "ok": False,
                "error": str(exc),
                "seizures_30d": 0,
                "detentions_30d": 0,
                "ai_detections_24h": 0,
                "staff_total": 0,
                "staff_online": 0,
                "recent_alerts": [],
            }

    cities: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []

    for key, members in groups.items():
        cameras_online = 0
        cameras_total = 0
        healthy = False
        last_seen = None
        server_ids: list[int] = []
        display_name = display_city_name(key, members[0].name if members else key)
        is_hq = key == "PESHAWAR"
        modes = set()
        errors: list[str] = []

        for server in members:
            server_ids.append(server.pk)
            modes.add(server.connection_mode or ConnectionMode.ML)
            result = camera_results.get(server.pk) or {}
            cams = list(result.get("cameras") or [])
            ok = bool(result.get("ok"))
            mark_server_health(server, ok=ok, error=result.get("error") or "")
            server.refresh_from_db()
            if ok:
                healthy = True
                # Refresh cache when live fetch succeeded
                if cams:
                    server.cached_cameras = cams
                    server.cameras_fetched_at = timezone.now()
                    server.save(
                        update_fields=["cached_cameras", "cameras_fetched_at", "updated_at"]
                    )
            elif server.cached_cameras:
                cams = list(server.cached_cameras or [])
                healthy = True  # show last-known cameras
            else:
                if result.get("error"):
                    errors.append(str(result.get("error")))

            cameras_total += len(cams)
            cameras_online += sum(1 for c in cams if isinstance(c, dict) and _camera_online(c))

            if server.last_seen_at:
                iso = server.last_seen_at.isoformat()
                if not last_seen or iso > last_seen:
                    last_seen = iso

            # Prefer site/server display name when not a known code
            if key not in DISPLAY_NAMES and server.name:
                display_name = server.name

        ops = ops_results.get(key) or {}
        if ops.get("ok"):
            healthy = True
        elif ops.get("error") and ConnectionMode.DJANGO in modes:
            errors.append(str(ops.get("error")))

        status, connectivity = _derive_status(healthy, cameras_online, cameras_total)
        last_sync, last_sync_relative = _format_sync(last_seen)

        seizures_30d = int(ops.get("seizures_30d") or 0)
        detentions_30d = int(ops.get("detentions_30d") or 0)
        ai_24h = int(ops.get("ai_detections_24h") or 0)
        staff_total = int(ops.get("staff_total") or 0)
        staff_online = int(ops.get("staff_online") or 0)

        city = {
            "id": key.lower().replace("_", "-"),
            "location_code": key,
            "city": display_name,
            "is_hq": is_hq,
            "status": status,
            "connectivity": connectivity,
            "cameras_online": cameras_online,
            "cameras_total": cameras_total,
            "ai_detections_24h": ai_24h,
            "seizures_30d": seizures_30d,
            "detentions_30d": detentions_30d,
            "staff_online": staff_online,
            "staff_total": staff_total,
            "last_sync": last_sync,
            "last_sync_relative": last_sync_relative,
            "server_ids": server_ids,
            "connection_modes": sorted(modes),
            "ops_source": ops.get("source") or ("django" if ConnectionMode.DJANGO in modes else "ml"),
            "error": "; ".join(errors[:2]) if status == "Offline" and errors else "",
        }
        cities.append(city)

        if status == "Offline":
            alerts.append(
                {
                    "id": f"offline-{city['id']}",
                    "time": timezone.localtime().strftime("%H:%M"),
                    "city": display_name,
                    "title": "City connection offline",
                    "severity": "Critical",
                }
            )
        elif status == "Degraded":
            alerts.append(
                {
                    "id": f"degraded-{city['id']}",
                    "time": timezone.localtime().strftime("%H:%M"),
                    "city": display_name,
                    "title": "Low connectivity / cameras degraded",
                    "severity": "Medium",
                }
            )

        for alert in ops.get("recent_alerts") or []:
            if not isinstance(alert, dict):
                continue
            alerts.append(
                {
                    "id": f"ai-{city['id']}-{len(alerts)}",
                    "time": str(alert.get("time") or "")[11:16] or timezone.localtime().strftime("%H:%M"),
                    "city": display_name,
                    "title": alert.get("title") or "AI alert",
                    "severity": alert.get("severity") or "Info",
                }
            )

    cities.extend(synced)
    alerts = synced_alerts(synced) + alerts

    cities.sort(key=lambda c: (0 if c.get("is_hq") else 1, c.get("city") or ""))
    for i, city in enumerate(cities, start=1):
        city["rank"] = i
        cam_pct = (
            round(100 * city["cameras_online"] / city["cameras_total"])
            if city["cameras_total"]
            else 0
        )
        city["bars"] = {
            "cameras": cam_pct,
            "ai": 0,
            "seizures": 0,
            "detentions": 0,
        }

    max_ai = max((c["ai_detections_24h"] for c in cities), default=1) or 1
    max_sz = max((c["seizures_30d"] for c in cities), default=1) or 1
    max_dt = max((c["detentions_30d"] for c in cities), default=1) or 1
    for city in cities:
        city["bars"]["ai"] = min(100, round(100 * city["ai_detections_24h"] / max_ai))
        city["bars"]["seizures"] = min(100, round(100 * city["seizures_30d"] / max_sz))
        city["bars"]["detentions"] = min(100, round(100 * city["detentions_30d"] / max_dt))

    online = sum(1 for c in cities if c["status"] == "Online")
    offline = sum(1 for c in cities if c["status"] == "Offline")
    degraded = sum(1 for c in cities if c["status"] == "Degraded")
    total_cams = sum(c["cameras_total"] for c in cities)
    total_ai = sum(c["ai_detections_24h"] for c in cities)
    total_sz = sum(c["seizures_30d"] for c in cities)
    total_dt = sum(c["detentions_30d"] for c in cities)

    kpis = [
        {
            "id": "cameras",
            "label": "Total Cameras",
            "value": f"{total_cams:,}",
            "support": "Across all cities",
            "tone": "blue",
        },
        {
            "id": "ai",
            "label": "AI Detections (24h)",
            "value": f"{total_ai:,}",
            "support": "People · Vehicles · Weapons · Plates",
            "tone": "purple",
        },
        {
            "id": "seizures",
            "label": "Seizures (30d)",
            "value": f"{total_sz:,}",
            "support": "All cities combined",
            "tone": "red",
        },
        {
            "id": "detentions",
            "label": "Detentions (30d)",
            "value": f"{total_dt:,}",
            "support": "All cities combined",
            "tone": "orange",
        },
        {
            "id": "online",
            "label": "Online Cities",
            "value": f"{online} / {len(cities)}",
            "support": f"{offline} offline | {degraded} degraded",
            "tone": "green",
        },
    ]

    alerts.sort(key=lambda a: a.get("at") or a.get("time") or "", reverse=True)

    return {
        "ok": True,
        "cities": cities,
        "kpis": kpis,
        "alerts": alerts[:30],
        "server_count": len(servers),
        "city_count": len(cities),
        "generated_at": timezone.now().isoformat(),
    }
