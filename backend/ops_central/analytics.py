"""
Analytics Dashboard - every number comes from this HQ's database (its own rows plus what
cities synced here). Scope: all locations, HQ only, or one city.
"""

from __future__ import annotations

import shutil
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any

from django.conf import settings
from django.db.models import Avg, Count, Q
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay, TruncDate, TruncHour
from django.utils import timezone

from city_sync.identity import location_code

from .synced_board import (
    PEOPLE,
    PLATES,
    VEHICLES,
    WEAPONS,
    _camera_names,
    _event_row,
    _loc_q,
    detection_group,
    synced_city_rows,
)

ALL = "ALL"
SEVERITIES = ("Critical", "High", "Medium", "Low")
TYPE_SETS = {"Person": PEOPLE, "Vehicle": VEHICLES, "Weapon": WEAPONS, "License Plate": PLATES}
GROUP_KEYS = {"Person": "people", "Vehicle": "vehicles", "Weapon": "weapons", "License Plate": "plates"}


def _names_q(names: set[str]) -> Q:
    q = Q()
    for name in names:
        q |= Q(class_name__iexact=name)
    return q


def _type_q(kind: str) -> Q:
    if kind == "Other":
        q = Q()
        for names in TYPE_SETS.values():
            q |= _names_q(names)
        return ~q
    return _names_q(TYPE_SETS[kind])


def _severity_q(level: str) -> Q:
    """Weapon = Critical, other AI alerts = High, plates = Medium, everything else = Low."""
    weapon, plate = _names_q(WEAPONS), _names_q(PLATES)
    if level == "Critical":
        return weapon
    if level == "High":
        return Q(is_alert=True) & ~weapon
    if level == "Medium":
        return plate & ~Q(is_alert=True)
    return ~weapon & ~Q(is_alert=True) & ~plate


def _severity_from(class_name: str | None, is_alert: bool) -> str:
    group = detection_group(class_name)
    if group == "Weapon":
        return "Critical"
    if is_alert:
        return "High"
    if group == "License Plate":
        return "Medium"
    return "Low"


def severity_of(event) -> str:
    return _severity_from(event.class_name, event.is_alert)


def scope_q(scope: str, prefix: str = "") -> Q:
    hq = location_code()
    return Q() if scope == ALL else _loc_q(scope, hq, prefix)


def parse_range(raw_from: str | None, raw_to: str | None) -> tuple[datetime, datetime, date, date]:
    """Inclusive local dates -> aware [start, end). Defaults to the last 7 days."""
    today = timezone.localdate()

    def parse(raw, fallback: date) -> date:
        try:
            return date.fromisoformat(str(raw)) if raw else fallback
        except ValueError:
            return fallback

    d_to = min(parse(raw_to, today), today)
    d_from = parse(raw_from, d_to - timedelta(days=6))
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    d_from = max(d_from, d_to - timedelta(days=365))
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(d_from, time.min), tz)
    end = timezone.make_aware(datetime.combine(d_to + timedelta(days=1), time.min), tz)
    return start, end, d_from, d_to


def _overview(scope: str, rows: list[dict]) -> dict[str, Any]:
    from cameras.models import DetectionEvent
    from visitors.models import SecurityAlert

    hq = location_code()
    picked = [r for r in rows if scope == ALL or r["location_code"] == scope]
    online = sum(r["cameras_online"] for r in picked)
    total = sum(r["cameras_total"] for r in picked)
    cities_online = sum(1 for r in picked if r["status"] != "Offline")

    day_start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
    severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for r in (
        DetectionEvent.objects.filter(scope_q(scope), created_at__gte=day_start)
        .values("class_name", "is_alert")
        .annotate(n=Count("pk"))
    ):
        level = _severity_from(r["class_name"], r["is_alert"])
        if level != "Low":  # every plain detection is "Low"; only alerts are counted here
            severity[level.lower()] += r["n"]
    security = SecurityAlert.objects.filter(scope_q(scope), created_at__gte=day_start)
    for level in ("critical", "high", "medium", "low"):
        severity[level] = severity.get(level, 0) + security.filter(severity__iexact=level).count()

    # AI processing: the ML server answers (HQ) / the city reports ML-based camera counts.
    ml_up = []
    for r in picked:
        if r["location_code"] == hq:
            from cameras.live_status import camera_counts

            ml_up.append(camera_counts().get("cameras_online_source") == "ml")
        elif r["status"] != "Offline":
            ml_up.append(True)
    ai_ok = bool(ml_up) and all(ml_up)

    if scope in (ALL, hq):
        try:
            usage = shutil.disk_usage(str(settings.MEDIA_ROOT))
            storage = round(100 * usage.used / usage.total) if usage.total else None
        except OSError:
            storage = None
    else:
        from city_sync.models import HqCityStatus

        st = HqCityStatus.objects.filter(location_code=scope).first()
        disk = (st.disk_percent if st else None)
        storage = round(disk) if disk is not None else None

    parts = []
    if total:
        parts.append(online / total)
    if picked:
        parts.append(cities_online / len(picked))
    parts.append(1.0 if ai_ok else 0.0)
    health = round(100 * sum(parts) / len(parts)) if parts else None

    return {
        "alerts_by_severity": severity,
        "incidents_today": severity["critical"] + severity["high"],
        "cameras_online": online,
        "cameras_offline": max(0, total - online),
        "cameras_total": total,
        "locations_online": cities_online,
        "locations_total": len(picked),
        "ai_processing": "online" if ai_ok else "offline",
        "storage_percent": storage,
        "system_health": health,
    }


def _stats(scope: str, by_class: list[dict], start, end) -> dict[str, int]:
    from users.models import Attendance
    from visitors.models import SecurityAlert

    groups = {key: 0 for key in GROUP_KEYS.values()}
    for r in by_class:
        group = detection_group(r["class_name"])
        if group:
            groups[GROUP_KEYS[group]] += r["n"]
    return {
        **groups,
        "total": sum(r["n"] for r in by_class),
        "face_matches": Attendance.objects.filter(
            scope_q(scope), is_deleted=False, check_in__gte=start, check_in__lt=end
        )
        .exclude(source="manual")
        .count(),
        "blacklist_encounters": SecurityAlert.objects.filter(scope_q(scope), created_at__gte=start, created_at__lt=end).count(),
    }


def build_dashboard(*, scope: str, raw_from: str | None, raw_to: str | None) -> dict[str, Any]:
    from cameras.models import DetectionEvent

    now = timezone.now()
    hq = location_code()
    scope = (scope or ALL).upper()
    rows = synced_city_rows(with_detail=False)
    if scope != ALL and scope not in {r["location_code"] for r in rows}:
        scope = ALL
    start, end, d_from, d_to = parse_range(raw_from, raw_to)
    events = DetectionEvent.objects.filter(scope_q(scope), created_at__gte=start, created_at__lt=end)

    # Detections by object class (top 8 + Other).
    by_class = list(events.values("class_name").annotate(n=Count("pk")).order_by("-n"))
    top = [{"name": r["class_name"] or "unknown", "count": r["n"]} for r in by_class[:8]]
    rest = sum(r["n"] for r in by_class[8:])
    if rest:
        top.append({"name": "Other", "count": rest})

    # Top alert cameras.
    alert_q = Q(is_alert=True) | _names_q(WEAPONS)
    cams = list(
        events.filter(alert_q)
        .values("location_code", "camera_id", "camera__name", "source_camera_id")
        .annotate(n=Count("pk"))
        .order_by("-n")[:5]
    )
    names = _camera_names(
        [SimpleNamespace(location_code=c["location_code"], source_camera_id=c["source_camera_id"]) for c in cams]
    )
    city_names = {r["location_code"]: r["city"] for r in rows}
    top_cameras = [
        {
            "camera": c["camera__name"]
            or names.get((c["location_code"], c["source_camera_id"]))
            or f"Camera {c['camera_id'] or c['source_camera_id']}",
            "location": city_names.get(c["location_code"] or hq, c["location_code"] or hq),
            "count": c["n"],
        }
        for c in cams
    ]

    # Over time: hourly for ranges up to 2 days, else daily; one row per bucket.
    hourly = (d_to - d_from).days < 2
    trunc = TruncHour("created_at") if hourly else TruncDate("created_at")
    series: dict[Any, dict[str, Any]] = {}
    if hourly:
        cursor = start
        while cursor < end:
            series[cursor] = {"label": timezone.localtime(cursor).strftime("%H:%M"), "people": 0, "vehicles": 0, "weapons": 0, "plates": 0, "other": 0}
            cursor += timedelta(hours=1)
    else:
        day = d_from
        while day <= d_to:
            series[day] = {"label": day.strftime("%b %d"), "people": 0, "vehicles": 0, "weapons": 0, "plates": 0, "other": 0}
            day += timedelta(days=1)
    for r in events.annotate(b=trunc).values("b", "class_name").annotate(n=Count("pk")):
        key = timezone.localtime(r["b"]).replace(minute=0, second=0, microsecond=0) if hourly else r["b"]
        if key in series:
            group = detection_group(r["class_name"])
            series[key][GROUP_KEYS.get(group, "other")] += r["n"]

    # Activity by hour of day and weekday (Mon=1).
    by_hour = {r["h"]: r["n"] for r in events.annotate(h=ExtractHour("created_at")).values("h").annotate(n=Count("pk"))}
    by_weekday = {r["d"]: r["n"] for r in events.annotate(d=ExtractIsoWeekDay("created_at")).values("d").annotate(n=Count("pk"))}

    confidence = [
        {"label": r["d"].strftime("%b %d"), "avg_confidence": round(float(r["c"] or 0) * 100, 1), "count": r["n"]}
        for r in events.annotate(d=TruncDate("created_at")).values("d").annotate(c=Avg("confidence"), n=Count("pk")).order_by("d")
    ]

    recent = list(
        DetectionEvent.objects.filter(scope_q(scope), alert_q, created_at__gte=now - timedelta(hours=24))
        .select_related("camera")
        .order_by("-created_at")[:20]
    )
    recent_names = _camera_names(recent)
    alerts = []
    for event in recent:
        item = _event_row(event, recent_names, hq)
        alerts.append(
            {
                **item,
                "location": city_names.get(item["location_code"], item["location_code"]),
                "severity": severity_of(event),
            }
        )

    return {
        "generated_at": now.isoformat(),
        "scope": scope,
        "range": {"from": d_from.isoformat(), "to": d_to.isoformat(), "bucket": "hour" if hourly else "day"},
        "locations": [
            {"code": r["location_code"], "name": r["city"], "status": r["status"], "is_hq": r["is_hq"]} for r in rows
        ],
        "overview": _overview(scope, rows),
        "stats": _stats(scope, by_class, start, end),
        "by_class": top,
        "top_alert_cameras": top_cameras,
        "over_time": list(series.values()),
        "activity_by_hour": [{"label": f"{h:02d}", "count": by_hour.get(h, 0)} for h in range(24)],
        "activity_by_weekday": [
            {"label": label, "count": by_weekday.get(i, 0)}
            for i, label in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), start=1)
        ],
        "confidence_trend": confidence,
        "alerts": alerts,
        "map": [
            {
                "code": r["location_code"],
                "name": r["city"],
                "status": r["status"],
                "cameras_online": r["cameras_online"],
                "cameras_total": r["cameras_total"],
                "ai_detections_24h": r["ai_detections_24h"],
                "is_hq": r["is_hq"],
            }
            for r in rows
        ],
    }


def event_log(
    *, scope: str, raw_from: str | None, raw_to: str | None, q: str = "", severities=(), types=(), page: int = 1, page_size: int = 25
) -> dict[str, Any]:
    """Searchable detection log for the dashboard."""
    from cameras.models import DetectionEvent

    hq = location_code()
    scope = (scope or ALL).upper()
    start, end, _f, _t = parse_range(raw_from, raw_to)
    events = DetectionEvent.objects.filter(scope_q(scope), created_at__gte=start, created_at__lt=end)
    sev = [s for s in severities if s in SEVERITIES]
    if sev:
        cond = Q()
        for level in sev:
            cond |= _severity_q(level)
        events = events.filter(cond)
    kinds = [t for t in types if t in TYPE_SETS or t == "Other"]
    if kinds:
        cond = Q()
        for kind in kinds:
            cond |= _type_q(kind)
        events = events.filter(cond)
    q = (q or "").strip()
    if q:
        events = events.filter(
            Q(class_name__icontains=q) | Q(label__icontains=q) | Q(camera__name__icontains=q) | Q(employee_name__icontains=q)
        )
    total = events.count()
    page = max(1, page)
    page_size = max(5, min(100, page_size))
    rows = list(events.select_related("camera").order_by("-created_at")[(page - 1) * page_size : page * page_size])
    names = _camera_names(rows)
    city_names = {r["location_code"]: r["city"] for r in synced_city_rows(with_detail=False)} if rows else {}
    results = []
    for event in rows:
        item = _event_row(event, names, hq)
        results.append(
            {
                **item,
                "time": timezone.localtime(event.created_at).strftime("%b %d, %H:%M:%S"),
                "location": city_names.get(item["location_code"], item["location_code"]),
                "severity": severity_of(event),
                "confidence": round(float(event.confidence or 0) * 100, 1),
            }
        )
    return {"count": total, "page": page, "page_size": page_size, "results": results}
