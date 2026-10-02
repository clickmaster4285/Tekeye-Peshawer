"""
Create DDK location + road cameras, then seed random detection logs.

Usage:
  python manage.py seed_ddk_detections
  python manage.py seed_ddk_detections --date 2026-10-01 --total 10000
  python manage.py seed_ddk_detections --month 2026-08 --clear-month
  python manage.py seed_ddk_detections --month 2026-09 --clear-month
"""

from __future__ import annotations

import calendar
import random
from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from cameras.models import (
    Camera,
    CameraPurpose,
    CameraStatus,
    CameraType,
    ClipStatus,
    DetectionEvent,
    Nvr,
    NvrBrand,
    Site,
)

DDK_ROAD_CAMERAS: list[tuple[int, str, str]] = [
    (101, "DDK-CAM-1", "DDK Camera 1"),
    (201, "DDK-CAM-2", "DDK Camera 2"),
    (301, "DDK-CAM-3", "DDK Camera 3"),
    (401, "DDK-CAM-4", "DDK Camera 4"),
]

DETECTION_CLASSES: list[tuple[str, float, bool]] = [
    ("person", 30.0, False),
    ("car", 24.0, False),
    ("motorcycle", 16.0, False),
    ("truck", 12.0, False),
    ("bus", 5.0, False),
    ("handbag", 7.0, False),
    ("backpack", 4.0, False),
    ("suitcase", 2.0, False),
]

DEFAULT_DAY_MIN = 8000
DEFAULT_DAY_MAX = 12000
BATCH_SIZE = 1000


def _pick_class() -> tuple[str, bool]:
    names = [c[0] for c in DETECTION_CLASSES]
    weights = [c[1] for c in DETECTION_CLASSES]
    idx = random.choices(range(len(names)), weights=weights, k=1)[0]
    name = DETECTION_CLASSES[idx][0]
    # Normal road classes are never alerts (fire/weapon/smoke would be).
    return name, False


def _label_for(class_name: str) -> str:
    if class_name == "person":
        return random.choice(["person", "persons", "person"])
    if class_name == "handbag":
        return random.choice(["handbag", "hand bag"])
    if class_name == "car":
        return random.choice(["car", "cars"])
    return class_name


def _random_bbox() -> list[float]:
    x1 = random.uniform(0.05, 0.55)
    y1 = random.uniform(0.1, 0.55)
    w = random.uniform(0.08, 0.35)
    h = random.uniform(0.1, 0.4)
    return [
        round(x1, 4),
        round(y1, 4),
        round(min(0.98, x1 + w), 4),
        round(min(0.98, y1 + h), 4),
    ]


def _split_counts(total: int, parts: int) -> list[int]:
    if parts <= 0:
        return []
    if parts == 1:
        return [total]
    weights = [max(0.15, random.random()) for _ in range(parts)]
    s = sum(weights)
    raw = [int(total * w / s) for w in weights]
    while sum(raw) < total:
        raw[random.randrange(parts)] += 1
    while sum(raw) > total:
        i = random.randrange(parts)
        if raw[i] > 0:
            raw[i] -= 1
    return raw


def _month_days(year: int, month: int) -> list[date]:
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, last + 1)]


class Command(BaseCommand):
    help = "Create DDK site/road cameras and seed detection logs (day or full month)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            default="",
            help="Single day YYYY-MM-DD (default: today if --month not set).",
        )
        parser.add_argument(
            "--month",
            default="",
            help="Full month YYYY-MM (seeds every day; overrides --date).",
        )
        parser.add_argument(
            "--total",
            type=int,
            default=0,
            help=f"Detections per day (default random {DEFAULT_DAY_MIN}-{DEFAULT_DAY_MAX}).",
        )
        parser.add_argument(
            "--clear-day",
            action="store_true",
            help="Clear that single day before seeding.",
        )
        parser.add_argument(
            "--clear-month",
            action="store_true",
            help="Clear the whole month before seeding (with --month).",
        )

    def handle(self, *args, **options):
        cameras, site_created, nvr_created = self._ensure_ddk()

        if options["month"]:
            year_s, month_s = options["month"].split("-", 1)
            year, month = int(year_s), int(month_s)
            days = _month_days(year, month)
            if options["clear_month"] or options["clear_day"]:
                deleted, _ = DetectionEvent.objects.filter(
                    camera__in=cameras,
                    created_at__date__gte=days[0],
                    created_at__date__lte=days[-1],
                ).delete()
                self.stdout.write(
                    self.style.WARNING(
                        f"Cleared {deleted} DDK detections for {year}-{month:02d}"
                    )
                )
            grand = 0
            for day in days:
                n = self._seed_day(cameras, day, options["total"])
                grand += n
                self.stdout.write(f"  {day}: {n} events")
            self.stdout.write(
                self.style.SUCCESS(
                    f"DDK {year}-{month:02d} complete · {len(days)} days · {grand} detections"
                )
            )
            return

        if options["date"]:
            day = datetime.strptime(options["date"], "%Y-%m-%d").date()
        else:
            day = timezone.localdate()

        if options["clear_day"]:
            deleted, _ = DetectionEvent.objects.filter(
                camera__in=cameras,
                created_at__date=day,
            ).delete()
            self.stdout.write(self.style.WARNING(f"Cleared {deleted} DDK detections on {day}"))

        created = self._seed_day(cameras, day, options["total"])
        self.stdout.write(
            self.style.SUCCESS(
                f"DDK site={'created' if site_created else 'ready'} · "
                f"NVR={'created' if nvr_created else 'ready'} · "
                f"{len(cameras)} cameras · {created} detection logs on {day}"
            )
        )
        for cam in cameras:
            n = DetectionEvent.objects.filter(camera=cam, created_at__date=day).count()
            self.stdout.write(f"  {cam.code}: {cam.name} -> {n} events")

    def _ensure_ddk(self) -> tuple[list[Camera], bool, bool]:
        with transaction.atomic():
            site, site_created = Site.objects.get_or_create(
                code="DDK",
                defaults={
                    "name": "DDK Location",
                    "description": "DDK road network cameras and detection coverage.",
                    "is_active": True,
                },
            )
            if not site_created:
                site.name = "DDK Location"
                site.is_active = True
                site.save(update_fields=["name", "is_active", "updated_at"])

            template = Nvr.objects.filter(is_active=True).order_by("id").first()
            nvr, nvr_created = Nvr.objects.get_or_create(
                site=site,
                name="DDK_NVR_1",
                defaults={
                    "ip_address": (template.ip_address if template else "192.168.190.251"),
                    "port": template.port if template else 554,
                    "username": template.username if template else "admin",
                    "password": template.password if template else "",
                    "brand": template.brand if template else NvrBrand.HIKVISION,
                    "is_active": True,
                },
            )
            if not nvr.is_active:
                nvr.is_active = True
                nvr.save(update_fields=["is_active", "updated_at"])

            purposes = [
                CameraPurpose.GENERAL_OBJECTS,
                CameraPurpose.CUSTOM_OBJECTS,
                CameraPurpose.ANPR,
            ]
            cameras: list[Camera] = []
            keep_channels = {ch for ch, _, _ in DDK_ROAD_CAMERAS}
            for channel, code, name in DDK_ROAD_CAMERAS:
                cam, _ = Camera.objects.update_or_create(
                    nvr=nvr,
                    channel=channel,
                    defaults={
                        "code": code,
                        "name": name,
                        "location": "DDK",
                        "zone": "Road Network",
                        "camera_type": CameraType.FIXED,
                        "purpose": CameraPurpose.GENERAL_OBJECTS,
                        "purposes": purposes,
                        "resolution": "1920x1080",
                        "frame_rate": "25",
                        "status": CameraStatus.ONLINE,
                        "is_active": True,
                        "recording": True,
                    },
                )
                cameras.append(cam)

            extras = Camera.objects.filter(nvr=nvr).exclude(channel__in=keep_channels)
            if extras.exists():
                removed, _ = extras.delete()
                self.stdout.write(
                    self.style.WARNING(f"Removed {removed} extra DDK camera row(s)")
                )

        return cameras, site_created, nvr_created

    def _seed_day(self, cameras: list[Camera], day: date, total_opt: int) -> int:
        import json

        from django.db import connection

        tz = timezone.get_current_timezone()
        total = int(total_opt or 0)
        if total <= 0:
            total = random.randint(DEFAULT_DAY_MIN, DEFAULT_DAY_MAX)
        total = max(100, total)

        start = timezone.make_aware(datetime.combine(day, time(6, 0)), tz)
        end = timezone.make_aware(datetime.combine(day, time(22, 0)), tz)
        span_sec = max(1, int((end - start).total_seconds()))
        per_cam = _split_counts(total, len(cameras))

        rows: list[tuple] = []
        for cam, n in zip(cameras, per_cam):
            for _ in range(n):
                class_name, _is_alert = _pick_class()
                offset = random.randint(0, span_sec)
                ts = start + timedelta(seconds=offset)
                rows.append(
                    (
                        cam.id,
                        class_name,
                        _label_for(class_name),
                        "",  # employee_name
                        "",  # personal_number
                        round(random.uniform(0.42, 0.97), 4),
                        json.dumps(_random_bbox()),
                        1920,
                        1080,
                        False,  # is_alert — never for normal road classes
                        "",  # clip
                        ClipStatus.SKIPPED,
                        None,  # video
                        random.randint(1, 400),
                        "",  # person_qr
                        "detection",
                        None,  # person_identity_id
                        ts,
                    )
                )

        sql = """
            INSERT INTO cameras_detectionevent (
                camera_id, class_name, label, employee_name, personal_number,
                confidence, bbox, infer_frame_width, infer_frame_height,
                is_alert, clip, clip_status, video, local_track_id,
                person_qr, track_event, person_identity_id, created_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s::jsonb, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
        """
        with connection.cursor() as cursor:
            for i in range(0, len(rows), BATCH_SIZE):
                chunk = rows[i : i + BATCH_SIZE]
                cursor.executemany(sql, chunk)

        return len(rows)
