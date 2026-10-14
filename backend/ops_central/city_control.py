"""Federated City Control Grid — aggregate each city's Django/ML stack + city_sync."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
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


def _sync_offline_after_sec() -> int:
    return int(getattr(settings, "SYNC_GRID_OFFLINE_AFTER_SEC", 90) or 90)


def _status_from_city_sync_heartbeat(last_heartbeat_at, *, dead_outbox: int = 0, failed_media: int = 0) -> tuple[str, str]:
    """Map city_sync heartbeat age → City Grid Online/Degraded/Offline."""
    if not last_heartbeat_at:
        return "Offline", "No Signal"
    age = max(0, int((timezone.now() - last_heartbeat_at).total_seconds()))
    offline_after = _sync_offline_after_sec()
    if age > 1800:
        return "Offline", "No Signal"
    if age > offline_after:
        return "Offline", "No Signal"
    if dead_outbox > 0 or failed_media > 0:
        return "Degraded", "Limited"
    return "Online", "Good"


def _replica_ops_stats(location_code: str) -> dict[str, Any]:
    """Aggregate HQ replica rows for City Grid KPIs (live synced city data)."""
    try:
        from city_sync.models import HqReplicaRow
    except Exception:  # noqa: BLE001
        return {
            "ok": False,
            "source": "city_sync",
            "seizures_30d": 0,
            "detentions_30d": 0,
            "ai_detections_24h": 0,
            "staff_total": 0,
            "staff_online": 0,
            "replica_total": 0,
            "attendance_30d": 0,
            "visitors_30d": 0,
            "recent_alerts": [],
        }

    loc = (location_code or "").upper()
    now = timezone.now()
    since_24h = now - timedelta(hours=24)
    since_30d = now - timedelta(days=30)
    base = HqReplicaRow.objects.filter(location_code=loc, is_deleted=False)

    def _count(entity_type: str, since=None) -> int:
        qs = base.filter(entity_type=entity_type)
        if since is not None:
            qs = qs.filter(received_at__gte=since)
        return qs.count()

    staff_total = _count("staff")
    ai_24h = _count("detection_event", since_24h)
    seizures_30d = _count("note_sheet", since_30d)
    detentions_30d = _count("detention_memo", since_30d)
    replica_total = base.count()
    recent_alerts: list[dict[str, Any]] = []
    if ai_24h:
        recent_alerts.append(
            {
                "time": now.isoformat(),
                "title": f"{ai_24h} AI detections synced (24h)",
                "severity": "Info",
            }
        )

    return {
        "ok": True,
        "source": "city_sync",
        "seizures_30d": seizures_30d,
        "detentions_30d": detentions_30d,
        "ai_detections_24h": ai_24h,
        "staff_total": staff_total,
        "staff_online": staff_total,
        "replica_total": replica_total,
        "attendance_30d": _count("attendance", since_30d),
        "visitors_30d": _count("visitor", since_30d),
        "recent_alerts": recent_alerts,
    }


def _detection_type_label(class_name: str, label: str) -> str:
    text = f"{class_name} {label}".lower()
    if any(k in text for k in ("plate", "anpr", "license")):
        return "License Plate"
    if any(k in text for k in ("weapon", "gun", "knife", "rifle")):
        return "Weapon"
    if any(k in text for k in ("vehicle", "car", "truck", "bus", "bike", "motorcycle")):
        return "Vehicle"
    if any(k in text for k in ("person", "people", "face", "staff", "human", "pedestrian")):
        return "Person"
    raw = (class_name or label or "Object").strip().replace("_", " ")
    return raw[:1].upper() + raw[1:] if raw else "Object"


def _format_detection_time(raw: Any) -> str:
    if not raw:
        return "—"
    try:
        if isinstance(raw, datetime):
            dt = raw
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return timezone.localtime(dt).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return str(raw)[:16]


def list_sync_detections(
    *,
    location_code: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Recent AI detections from HQ city_sync replicas (City Grid UI)."""
    try:
        from city_sync.models import HqReplicaRow
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "results": [], "count": 0}

    limit = max(1, min(int(limit or 50), 200))
    qs = HqReplicaRow.objects.filter(entity_type="detection_event", is_deleted=False)
    loc = (location_code or "").strip().upper()
    if loc:
        qs = qs.filter(location_code=loc)
    qs = qs.order_by("-received_at")[:limit]

    results: list[dict[str, Any]] = []
    for row in qs:
        payload = row.payload if isinstance(row.payload, dict) else {}
        class_name = str(payload.get("class_name") or "")
        label = str(payload.get("label") or class_name or "Detection")
        employee = str(payload.get("employee_name") or "").strip()
        object_label = employee or label or class_name or "Detection"
        cam_id = payload.get("camera_id") or payload.get("camera")
        camera = f"Cam {cam_id}" if cam_id not in (None, "") else "Camera"
        created = payload.get("created_at") or row.updated_at or row.received_at
        conf = payload.get("confidence")
        try:
            confidence = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            confidence = None
        results.append(
            {
                "id": str(row.entity_id),
                "location_code": row.location_code,
                "time": _format_detection_time(created),
                "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created or ""),
                "type": _detection_type_label(class_name, label),
                "object": object_label,
                "camera": camera,
                "class_name": class_name,
                "label": label,
                "confidence": confidence,
                "is_alert": bool(payload.get("is_alert")),
                "source": "city_sync",
            }
        )

    return {
        "ok": True,
        "location_code": loc or "ALL",
        "count": len(results),
        "results": results,
        "source": "city_sync",
    }


def _merge_city_sync_into_board(cities: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> None:
    """
    Ensure every city_sync-connected location appears on the City Grid.

    - Adds cards for locations that only heartbeat/sync (no Ops RemoteServer).
    - Fills empty ops stats from HqReplicaRow when django/ML remote returned zeros.
    """
    try:
        from city_sync.models import HqCityStatus
    except Exception:  # noqa: BLE001
        return

    by_key = {str(c.get("location_code") or "").upper(): c for c in cities if c.get("location_code")}

    for st in HqCityStatus.objects.all().order_by("location_code"):
        key = (st.location_code or "").upper()
        if not key:
            continue
        # Skip pure local-dev placeholder codes if somehow present
        if key in ("LOCAL", "UNKNOWN"):
            continue

        sync_ops = _replica_ops_stats(key)
        sync_status, sync_conn = _status_from_city_sync_heartbeat(
            st.last_heartbeat_at,
            dead_outbox=int(st.dead_outbox or 0),
            failed_media=int(st.failed_media or 0),
        )
        hb_iso = st.last_heartbeat_at.isoformat() if st.last_heartbeat_at else None
        last_sync, last_sync_relative = _format_sync(hb_iso)
        display = display_city_name(key, key)

        existing = by_key.get(key)
        if existing is None:
            city = {
                "id": key.lower().replace("_", "-"),
                "location_code": key,
                "city": display,
                "is_hq": key == "PESHAWAR",
                "status": sync_status,
                "connectivity": sync_conn,
                "cameras_online": 0,
                "cameras_total": 0,
                "ai_detections_24h": int(sync_ops.get("ai_detections_24h") or 0),
                "seizures_30d": int(sync_ops.get("seizures_30d") or 0),
                "detentions_30d": int(sync_ops.get("detentions_30d") or 0),
                "staff_online": int(sync_ops.get("staff_online") or 0),
                "staff_total": int(sync_ops.get("staff_total") or 0),
                "last_sync": last_sync,
                "last_sync_relative": last_sync_relative,
                "server_ids": [],
                "connection_modes": ["city_sync"],
                "ops_source": "city_sync",
                "replica_total": int(sync_ops.get("replica_total") or 0),
                "attendance_30d": int(sync_ops.get("attendance_30d") or 0),
                "visitors_30d": int(sync_ops.get("visitors_30d") or 0),
                "error": "",
            }
            cities.append(city)
            by_key[key] = city
            if sync_status == "Offline":
                alerts.append(
                    {
                        "id": f"sync-offline-{city['id']}",
                        "time": timezone.localtime().strftime("%H:%M"),
                        "city": display,
                        "title": "City sync heartbeat offline",
                        "severity": "Critical",
                    }
                )
            elif sync_status == "Online":
                alerts.append(
                    {
                        "id": f"sync-online-{city['id']}",
                        "time": timezone.localtime().strftime("%H:%M"),
                        "city": display,
                        "title": f"Synced replicas: {city['replica_total']}",
                        "severity": "Info",
                    }
                )
            continue

        # Enrich existing Ops card with sync heartbeat + replica stats when empty.
        modes = list(existing.get("connection_modes") or [])
        if "city_sync" not in modes:
            modes.append("city_sync")
            existing["connection_modes"] = modes

        if existing.get("status") == "Offline" and sync_status == "Online":
            existing["status"] = sync_status
            existing["connectivity"] = sync_conn
        elif existing.get("status") == "Degraded" and sync_status == "Online":
            # Keep degraded if cameras bad, but refresh sync time
            pass

        # Prefer fresher heartbeat for "last sync" display
        if hb_iso and (
            existing.get("last_sync_relative") in ("No sync", "—", "", None)
            or sync_status == "Online"
        ):
            existing["last_sync"] = last_sync
            existing["last_sync_relative"] = last_sync_relative

        if int(existing.get("ai_detections_24h") or 0) == 0:
            existing["ai_detections_24h"] = int(sync_ops.get("ai_detections_24h") or 0)
        if int(existing.get("seizures_30d") or 0) == 0:
            existing["seizures_30d"] = int(sync_ops.get("seizures_30d") or 0)
        if int(existing.get("detentions_30d") or 0) == 0:
            existing["detentions_30d"] = int(sync_ops.get("detentions_30d") or 0)
        if int(existing.get("staff_total") or 0) == 0:
            existing["staff_total"] = int(sync_ops.get("staff_total") or 0)
            existing["staff_online"] = int(sync_ops.get("staff_online") or 0)

        existing["replica_total"] = int(sync_ops.get("replica_total") or 0)
        existing["attendance_30d"] = int(sync_ops.get("attendance_30d") or 0)
        existing["visitors_30d"] = int(sync_ops.get("visitors_30d") or 0)
        if existing.get("ops_source") in ("ml", "", None) and existing["replica_total"]:
            existing["ops_source"] = "city_sync"


def build_city_control_board(*, request_user, overall_timeout: float = 12.0) -> dict[str, Any]:
    """Aggregate cameras + Django DB stats per city location (+ city_sync replicas)."""
    servers = list(
        RemoteServer.objects.filter(is_active=True).select_related("site").order_by("name")
    )

    groups: dict[str, list[RemoteServer]] = {}
    for server in servers:
        key = location_key_for_server(server)
        groups.setdefault(key, []).append(server)

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

    # Merge city_sync heartbeats + HQ replicas so connected cities show on the frontend grid.
    _merge_city_sync_into_board(cities, alerts)

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
    total_replicas = sum(int(c.get("replica_total") or 0) for c in cities)

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
            "support": "Remote Django + city sync replicas",
            "tone": "purple",
        },
        {
            "id": "seizures",
            "label": "Seizures (30d)",
            "value": f"{total_sz:,}",
            "support": "Remote Django + city sync replicas",
            "tone": "red",
        },
        {
            "id": "detentions",
            "label": "Detentions (30d)",
            "value": f"{total_dt:,}",
            "support": "Remote Django + city sync replicas",
            "tone": "orange",
        },
        {
            "id": "online",
            "label": "Online Cities",
            "value": f"{online} / {len(cities)}",
            "support": f"{offline} offline | {degraded} degraded | {total_replicas:,} synced rows",
            "tone": "green",
        },
    ]

    alerts.sort(key=lambda a: a.get("time") or "", reverse=True)

    return {
        "ok": True,
        "cities": cities,
        "kpis": kpis,
        "alerts": alerts[:12],
        "server_count": len(servers),
        "city_count": len(cities),
        "generated_at": timezone.now().isoformat(),
    }
