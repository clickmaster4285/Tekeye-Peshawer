"""
City Control Grid rows built from the data cities sync to this HQ (Stage 6).

HQ plus every city on Locations & Sync. Status comes from the city's heartbeat, cameras
from the live counts it reports, and detections / seizures / detentions / staff from the
records it synced here. Nothing is fetched from the city servers at request time.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from city_sync.identity import is_hq, local_rows_q, location_code

PEOPLE = {"person", "crowd"}
VEHICLES = {"car", "truck", "motorcycle", "bus", "microbus", "bicycle", "vehicle", "van", "rickshaw"}
WEAPONS = {"weapon", "heavy-weapon", "knife", "gun", "pistol", "rifle"}
PLATES = {"license_plate", "license plate", "plate", "number_plate"}

GROUPS = (("Person", PEOPLE), ("Vehicle", VEHICLES), ("Weapon", WEAPONS), ("License Plate", PLATES))
TREND_KEYS = {"Person": "people", "Vehicle": "vehicles", "Weapon": "weapons", "License Plate": "plates"}
TRACKED = PEOPLE | VEHICLES | WEAPONS | PLATES

STATE = {
    "ONLINE": ("Online", "Good"),
    "DEGRADED": ("Degraded", "Limited"),
    "OFFLINE": ("Offline", "No Signal"),
    "LONG_OFFLINE": ("Offline", "No Signal"),
    "UNKNOWN": ("Offline", "No Signal"),
}


def detection_group(class_name: str | None) -> str | None:
    name = (class_name or "").strip().lower()
    for label, names in GROUPS:
        if name in names:
            return label
    return None


def _tracked_q() -> Q:
    q = Q()
    for name in TRACKED:
        q |= Q(class_name__iexact=name)
    return q


def _loc_q(code: str, hq: str, prefix: str = "") -> Q:
    """Rows of one location; HQ's own rows include untagged ones."""
    return local_rows_q(prefix) if code == hq else Q(**{f"{prefix}location_code": code})


def _when(dt) -> tuple[str, str, str]:
    """(\"Oct 16, 10:47\", \"2 min ago\", ISO) for a datetime."""
    if not dt:
        return "—", "No sync", ""
    sec = max(0, int((timezone.now() - dt).total_seconds()))
    if sec < 60:
        rel = f"{max(1, sec)} sec ago"
    elif sec < 3600:
        rel = f"{sec // 60} min ago"
    elif sec < 48 * 3600:
        rel = f"{sec // 3600} hr ago"
    else:
        rel = f"{sec // 86400} d ago"
    return timezone.localtime(dt).strftime("%b %d, %H:%M"), rel, dt.isoformat()


def _delta(now_count: int, before: int) -> str:
    if not before:
        return "—" if not now_count else "new"
    pct = round(100 * (now_count - before) / before)
    return f"{'+' if pct >= 0 else ''}{pct}%"


def _camera_names(events) -> dict[tuple[str, int], str]:
    """(location, source camera id) -> name, for city copies (their cameras are not HQ rows)."""
    from city_sync.models import CityCamera

    wanted = {(e.location_code, e.source_camera_id) for e in events if e.source_camera_id}
    if not wanted:
        return {}
    q = Q()
    for loc, pk in wanted:
        q |= Q(location_code=loc, origin_pk=pk)
    return {(c.location_code, c.origin_pk): c.name or c.code for c in CityCamera.objects.filter(q)}


def _event_row(event, names: dict, hq: str) -> dict[str, Any]:
    if event.camera_id:
        camera = getattr(event.camera, "name", "") or f"Camera {event.camera_id}"
    else:
        camera = names.get((event.location_code, event.source_camera_id)) or (
            f"Camera {event.source_camera_id}" if event.source_camera_id else "—"
        )
    group = detection_group(event.class_name)
    return {
        "id": event.pk,
        "time": timezone.localtime(event.created_at).strftime("%H:%M"),
        "at": event.created_at.isoformat(),
        "type": group or "Object",
        "object": event.label or event.class_name or "",
        "camera": camera,
        "image": event.clip.url if event.clip else "",
        "location_code": event.location_code or hq,
        "is_alert": bool(event.is_alert),
    }


def _city_numbers(code: str, hq: str, now) -> dict[str, Any]:
    from cameras.models import DetectionEvent
    from detentions.models import DetentionMemo
    from seizure_management.models import NoteSheet
    from users.models import Attendance, Staff

    loc = _loc_q(code, hq)
    day, month = now - timedelta(hours=24), now - timedelta(days=30)
    events = DetectionEvent.objects.filter(loc)
    sheets = NoteSheet.objects.filter(loc, is_deleted=False)
    memos = DetentionMemo.objects.filter(loc, is_deleted=False)
    ai_24h = events.filter(created_at__gte=day).count()
    seizures = sheets.filter(created_at__gte=month).count()
    detentions = memos.filter(created_at__gte=month).count()
    return {
        "ai_detections_24h": ai_24h,
        "seizures_30d": seizures,
        "detentions_30d": detentions,
        "staff_total": Staff.objects.filter(loc, is_deleted=False).count(),
        "staff_online": Attendance.objects.filter(loc, is_deleted=False, date=timezone.localdate())
        .exclude(status__in=["absent", "leave", "on_leave"])
        .values("staff_id")
        .distinct()
        .count(),
        "ai_delta": _delta(ai_24h, events.filter(created_at__gte=day - timedelta(hours=24), created_at__lt=day).count()),
        "seizure_delta": _delta(
            seizures, sheets.filter(created_at__gte=month - timedelta(days=30), created_at__lt=month).count()
        ),
        "detention_delta": _delta(
            detentions, memos.filter(created_at__gte=month - timedelta(days=30), created_at__lt=month).count()
        ),
    }


def _city_detail(code: str, hq: str, now) -> dict[str, Any]:
    """Recent detections and 7-day charts for the city detail page."""
    from cameras.models import DetectionEvent
    from detentions.models import DetentionMemo
    from seizure_management.models import NoteSheet

    loc = _loc_q(code, hq)
    start = timezone.localdate() - timedelta(days=6)
    days = [start + timedelta(days=i) for i in range(7)]
    label = {d: d.strftime("%a") for d in days}

    recent = list(
        DetectionEvent.objects.filter(loc, _tracked_q()).select_related("camera").order_by("-created_at")[:10]
    )
    names = _camera_names(recent)

    trend = {d: {"day": label[d], "people": 0, "vehicles": 0, "weapons": 0, "plates": 0} for d in days}
    rows = (
        DetectionEvent.objects.filter(loc, _tracked_q(), created_at__date__gte=start)
        .annotate(d=TruncDate("created_at"))
        .values("d", "class_name")
        .annotate(n=Count("pk"))
    )
    for row in rows:
        group = detection_group(row["class_name"])
        if group and row["d"] in trend:
            trend[row["d"]][TREND_KEYS[group]] += row["n"]

    ops = {d: {"day": label[d], "seizures": 0, "detentions": 0} for d in days}
    for model, key in ((NoteSheet, "seizures"), (DetentionMemo, "detentions")):
        for row in (
            model.objects.filter(loc, is_deleted=False, created_at__date__gte=start)
            .annotate(d=TruncDate("created_at"))
            .values("d")
            .annotate(n=Count("pk"))
        ):
            if row["d"] in ops:
                ops[row["d"]][key] = row["n"]

    return {
        "detections": [_event_row(e, names, hq) for e in recent],
        "trend": [trend[d] for d in days],
        "ops_bars": [ops[d] for d in days],
    }


def _hq_cameras(code: str, hq: str, raw: dict, state: str, now) -> tuple[int, int]:
    """(online, total). HQ counts its own; a city reports its counts in the heartbeat."""
    if code == hq:
        from cameras.live_status import camera_counts

        counts = camera_counts()
        return counts["cameras_online"], counts["cameras_total"]

    from cameras.models import DetectionEvent
    from city_sync.models import CityCamera

    total = raw.get("cameras_total")
    online = raw.get("cameras_online")
    if not isinstance(total, int):
        total = CityCamera.objects.filter(location_code=code).count()
    if state in ("OFFLINE", "LONG_OFFLINE", "UNKNOWN"):
        return 0, total
    if not isinstance(online, int):
        # City not updated yet: cameras that sent a detection in the last 15 minutes.
        online = (
            DetectionEvent.objects.filter(
                location_code=code, created_at__gte=now - timedelta(minutes=15), source_camera_id__isnull=False
            )
            .values("source_camera_id")
            .distinct()
            .count()
        )
    return min(online, total), total


def synced_city_rows(*, with_detail: bool = True) -> list[dict[str, Any]]:
    """Board rows for HQ and every synced city; [] when this server is not the HQ."""
    if not is_hq():
        return []
    from city_sync.models import HqCityStatus, SyncSite
    from city_sync.views import city_health_state
    from ops_central.city_control import display_city_name

    now = timezone.now()
    hq = location_code()
    statuses = {s.location_code: s for s in HqCityStatus.objects.all()}
    entries = [(hq, display_city_name(hq), None)] + [
        (s.location_code, s.name or display_city_name(s.location_code), s) for s in SyncSite.objects.order_by("name")
    ]

    rows: list[dict[str, Any]] = []
    for code, name, site in entries:
        is_hq_row = site is None
        st = statuses.get(code)
        raw = (st.raw if st else None) or {}
        if is_hq_row:
            state, seen = "ONLINE", now
        else:
            state = city_health_state(st, now)[0] if st else "UNKNOWN"
            seen = st.last_heartbeat_at if st else None
        status, connectivity = STATE.get(state, ("Offline", "No Signal"))
        if site is not None and site.is_paused:
            status, connectivity = "Degraded", "Limited"
        online, total = _hq_cameras(code, hq, raw, state, now)
        absolute, relative, iso = _when(seen)
        row = {
            "id": code.lower().replace("_", "-"),
            "location_code": code,
            "city": name,
            "is_hq": is_hq_row,
            "status": status,
            "connectivity": connectivity,
            "sync_state": "PAUSED" if site is not None and site.is_paused else state,
            "cameras_online": online,
            "cameras_total": total,
            "last_sync": absolute,
            "last_sync_relative": relative,
            "last_sync_at": iso,
            "ops_source": "synced",
            "sync_errors": (st.dead_outbox + st.failed_media) if st and not is_hq_row else 0,
            **_city_numbers(code, hq, now),
        }
        if with_detail:
            row["detail"] = _city_detail(code, hq, now)
        rows.append(row)
    return rows


def synced_alerts(rows: list[dict[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    """Logs feed: AI alerts from every location in the last 24h, plus offline / sync problems."""
    from cameras.models import DetectionEvent

    now = timezone.now()
    hq = location_code()
    names_by_code = {r["location_code"]: r["city"] for r in rows}
    alerts: list[dict[str, Any]] = []

    for row in rows:
        stamp = row.get("last_sync_at") or now.isoformat()
        if row["status"] == "Offline":
            alerts.append({"id": f"offline-{row['id']}", "at": stamp, "city": row["city"],
                           "title": "City not connected (no heartbeat)", "severity": "Critical"})
        elif row.get("sync_state") == "PAUSED":
            alerts.append({"id": f"paused-{row['id']}", "at": stamp, "city": row["city"],
                           "title": "Sync paused by head office", "severity": "Medium"})
        if row.get("sync_errors"):
            alerts.append({"id": f"sync-{row['id']}", "at": stamp, "city": row["city"],
                           "title": f"{row['sync_errors']} record(s) / image(s) failed to sync", "severity": "Medium"})

    weapons = Q()
    for name in WEAPONS:
        weapons |= Q(class_name__iexact=name)
    codes = Q()
    for code in names_by_code:
        codes |= _loc_q(code, hq)
    events = list(
        DetectionEvent.objects.filter(codes, Q(is_alert=True) | weapons, created_at__gte=now - timedelta(hours=24))
        .select_related("camera")
        .order_by("-created_at")[:limit]
    )
    names = _camera_names(events)
    for event in events:
        item = _event_row(event, names, hq)
        is_weapon = detection_group(event.class_name) == "Weapon"
        alerts.append({
            "id": f"ai-{event.pk}",
            "at": item["at"],
            "city": names_by_code.get(event.location_code or hq, event.location_code or hq),
            "title": f"AI detection: {item['object'] or 'alert'} · {item['camera']}",
            "severity": "High" if is_weapon else "Info",
            "image": item["image"],
            "camera": item["camera"],
        })

    alerts.sort(key=lambda a: a.get("at") or "", reverse=True)
    for alert in alerts:
        try:
            alert["time"] = timezone.localtime(datetime.fromisoformat(alert["at"])).strftime("%H:%M")
        except (TypeError, ValueError):
            alert["time"] = ""
    return alerts[: limit + 10]
