"""Collect motion clips recorded by the ML nodes and link each movement to its tracked object.

The ML service records a clip when objects move (pre-roll + motion, 10-30 s) and keeps it
until we collect it: list → download video + poster → store → delete on the ML node.
"""

from __future__ import annotations

import logging
import math
import threading
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from config.db import release_db

from .models import GlobalObject, MotionClip, ObjectCameraTrack, ObjectMovement, ObjectVisit
from .services import _class_group, _iou

logger = logging.getLogger(__name__)

_stop = threading.Event()
_thread: threading.Thread | None = None

# How far around a movement we look for the object's track / visit (polls are 30-40 s apart)
_LINK_SLACK = timedelta(minutes=2)
_STATIONARY_LINK_IOU = 0.3


def _ts(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _center(b: list) -> tuple[float, float]:
    return (float(b[0]) + float(b[2])) / 2.0, (float(b[1]) + float(b[3])) / 2.0


def _size(b: list) -> float:
    return math.sqrt(max(1.0, (float(b[2]) - float(b[0])) * (float(b[3]) - float(b[1]))))


def describe_move(from_bbox: list, to_bbox: list, width: int, height: int) -> tuple[float, float, str]:
    """(distance px, distance % of frame diagonal, direction) between two boxes."""
    if len(from_bbox) < 4 or len(to_bbox) < 4:
        return 0.0, 0.0, ""
    (fx, fy), (tx, ty) = _center(from_bbox), _center(to_bbox)
    dx, dy = tx - fx, ty - fy
    dist = math.hypot(dx, dy)
    diag = math.hypot(width, height) if width and height else 0.0
    pct = round(100.0 * dist / diag, 1) if diag else 0.0
    grow = _size(to_bbox) / _size(from_bbox)
    ref = _size(from_bbox)
    if dist < 0.15 * ref:
        # Barely shifted on screen: it came toward / went away from the camera
        if grow >= 1.3:
            return round(dist, 1), pct, "closer"
        if grow <= 1 / 1.3:
            return round(dist, 1), pct, "farther"
        return round(dist, 1), pct, ""
    # Screen y grows downward; 8 compass-style directions
    angle = math.degrees(math.atan2(-dy, dx)) % 360
    names = ["right", "up-right", "up", "up-left", "left", "down-left", "down", "down-right"]
    return round(dist, 1), pct, names[int(((angle + 22.5) % 360) // 45)]


def _camera_for_key(camera_key: str):
    from cameras.models import Camera

    key = (camera_key or "").strip().lower()
    if key.startswith("cam-") and key[4:].isdigit():
        return Camera.objects.filter(pk=int(key[4:])).first()
    return None


def link_movement(camera, mv: dict[str, Any], started: datetime, ended: datetime) -> tuple[GlobalObject | None, ObjectVisit | None]:
    """Find the tracked object and visit this movement belongs to (None when the backend never saw it)."""
    if camera is None:
        return None, None
    lo, hi = started - _LINK_SLACK, ended + _LINK_SLACK
    obj: GlobalObject | None = None

    # 1) Same ByteTrack id on this camera around that time
    try:
        track_id = int(mv.get("track_id"))
    except (TypeError, ValueError):
        track_id = None
    if track_id is not None:
        track = (
            ObjectCameraTrack.objects.select_related("global_object")
            .filter(camera=camera, local_track_id=track_id, started_at__lte=hi)
            .filter(Q(ended_at__isnull=True) | Q(ended_at__gte=lo))
            .order_by("-started_at")
            .first()
        )
        if track is not None:
            obj = track.global_object

    # 2) ML object code, only if that object was on this camera then (codes restart with ML)
    ml_gid = str(mv.get("global_object_id") or "").strip()
    if obj is None and ml_gid:
        obj = (
            GlobalObject.objects.filter(
                code=ml_gid,
                visits__camera=camera,
                visits__entry_at__lte=hi,
            )
            .filter(Q(visits__exit_at__isnull=True) | Q(visits__exit_at__gte=lo))
            .distinct()
            .first()
        )

    visits = ObjectVisit.objects.filter(camera=camera, entry_at__lte=hi).filter(
        Q(exit_at__isnull=True) | Q(exit_at__gte=lo)
    )

    # 3) Whatever of this class rested where the movement began
    from_bbox = mv.get("from_bbox") or []
    if obj is None and len(from_bbox) >= 4:
        group = _class_group(str(mv.get("class_name") or ""))
        best, best_iou = None, _STATIONARY_LINK_IOU
        for visit in visits.select_related("global_object").order_by("-entry_at")[:50]:
            if _class_group(visit.global_object.class_name or "") != group:
                continue
            score = _iou(visit.bbox or [], from_bbox)
            if score > best_iou:
                best, best_iou = visit, score
        if best is not None:
            return best.global_object, best

    if obj is None:
        return None, None
    visit = visits.filter(global_object=obj).order_by("-entry_at").first()
    return obj, visit


def store_clip(
    meta: dict[str, Any], video: bytes, poster: bytes | None, end_frame: bytes | None = None
) -> MotionClip | None:
    """Save one ML clip with its movements. Returns None when it is already stored."""
    clip_id = str(meta.get("clip_id") or "").strip()
    if not clip_id or MotionClip.objects.filter(ml_clip_id=clip_id).exists():
        return None
    started = _ts(meta.get("started_at")) or timezone.now()
    ended = _ts(meta.get("ended_at")) or started
    camera = _camera_for_key(str(meta.get("camera_key") or ""))
    src_w = int(meta.get("source_width") or 0)
    src_h = int(meta.get("source_height") or 0)

    with transaction.atomic():
        clip = MotionClip(
            ml_clip_id=clip_id,
            camera=camera,
            camera_key=str(meta.get("camera_key") or "")[:64],
            part=max(1, int(meta.get("part") or 1)),
            started_at=started,
            ended_at=ended,
            duration_seconds=float(meta.get("duration_sec") or 0.0),
            source_width=src_w,
            source_height=src_h,
            clip_width=int(meta.get("clip_width") or 0),
            clip_height=int(meta.get("clip_height") or 0),
            fps=float(meta.get("fps") or 0.0),
            size_bytes=len(video),
        )
        clip.video.save(f"{clip_id}.mp4", ContentFile(video), save=False)
        if poster:
            clip.poster.save(f"{clip_id}.jpg", ContentFile(poster), save=False)
        if end_frame:
            clip.end_frame.save(f"{clip_id}.end.jpg", ContentFile(end_frame), save=False)
        clip.save()

        for mv in meta.get("movements") or []:
            mv_start = _ts(mv.get("started_at")) or started
            mv_end = _ts(mv.get("ended_at"))
            obj, visit = link_movement(camera, mv, mv_start, mv_end or ended)
            from_bbox = [float(v) for v in (mv.get("from_bbox") or [])][:4]
            to_bbox = [float(v) for v in (mv.get("to_bbox") or [])][:4]
            dist, pct, direction = describe_move(from_bbox, to_bbox, src_w, src_h)
            try:
                track_id = int(mv.get("track_id"))
            except (TypeError, ValueError):
                track_id = None
            ObjectMovement.objects.create(
                clip=clip,
                global_object=obj,
                visit=visit,
                camera=camera,
                class_name=str(mv.get("class_name") or "")[:80],
                ml_object_id=str(mv.get("global_object_id") or "")[:32],
                local_track_id=track_id if track_id is not None and track_id >= 0 else None,
                started_at=mv_start,
                ended_at=mv_end,
                still_moving=bool(mv.get("still_moving")),
                duration_seconds=max(0.0, ((mv_end or ended) - mv_start).total_seconds()),
                from_bbox=from_bbox,
                to_bbox=to_bbox,
                distance_px=dist,
                distance_pct=pct,
                direction=direction,
            )
    return clip


def pull_from_node(base_url: str, *, limit: int = 20) -> int:
    """Collect finished clips from one ML node. Returns how many were stored."""
    import requests

    base = base_url.rstrip("/")
    res = requests.get(f"{base}/live/motion/clips", params={"limit": limit}, timeout=10)
    if res.status_code == 404:
        return 0  # ML node without motion clips (older code)
    res.raise_for_status()
    stored = 0
    for meta in res.json().get("clips") or []:
        clip_id = str(meta.get("clip_id") or "").strip()
        if not clip_id:
            continue
        if not MotionClip.objects.filter(ml_clip_id=clip_id).exists():
            video = requests.get(f"{base}/live/motion/clips/{clip_id}/video", timeout=60)
            if video.status_code != 200 or not video.content:
                logger.warning("[motion-clips] %s: video download failed (%s)", clip_id, video.status_code)
                continue
            images = {}
            for kind in ("poster", "end"):
                img = requests.get(f"{base}/live/motion/clips/{clip_id}/{kind}", timeout=30)
                images[kind] = img.content if img.status_code == 200 else None
            if store_clip(meta, video.content, images["poster"], images["end"]):
                stored += 1
        # Stored (now or before) → the ML node may drop its copy
        requests.delete(f"{base}/live/motion/clips/{clip_id}", timeout=10)
    return stored


def pull_motion_clips() -> int:
    from ml.client import known_ml_base_urls

    stored = 0
    for base in known_ml_base_urls():
        try:
            stored += pull_from_node(base)
        except Exception as exc:
            logger.debug("[motion-clips] Pull from %s failed: %s", base, exc)
    return stored


def prune_old_clips(*, days: int | None = None, batch: int = 200) -> int:
    """Delete clips (files + rows) older than MOTION_CLIP_RETENTION_DAYS. 0 days = keep forever."""
    keep = int(days if days is not None else getattr(settings, "MOTION_CLIP_RETENTION_DAYS", 14))
    if keep <= 0:
        return 0
    cutoff = timezone.now() - timedelta(days=keep)
    removed = 0
    for clip in MotionClip.objects.filter(started_at__lt=cutoff).order_by("started_at")[:batch]:
        for f in (clip.video, clip.poster, clip.end_frame):
            if f:
                try:
                    f.delete(save=False)
                except OSError:
                    pass
        clip.delete()
        removed += 1
    return removed


def _worker_loop() -> None:
    interval = max(3.0, float(getattr(settings, "MOTION_CLIP_PULL_INTERVAL_SEC", 10)))
    last_prune = 0.0
    while not _stop.is_set():
        close_old_connections()
        try:
            stored = pull_motion_clips()
            if stored:
                logger.info("[motion-clips] Stored %s new clip(s)", stored)
            now = timezone.now().timestamp()
            if now - last_prune > 3600:
                last_prune = now
                pruned = prune_old_clips()
                if pruned:
                    logger.info("[motion-clips] Deleted %s clip(s) past retention", pruned)
        except Exception:
            logger.exception("[motion-clips] Worker error")
        finally:
            release_db()
        _stop.wait(interval)


def start_motion_clip_worker() -> None:
    global _thread
    if not getattr(settings, "MOTION_CLIP_PULL_ENABLED", True):
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_worker_loop, daemon=True, name="motion-clip-pull")
    _thread.start()


def stop_motion_clip_worker() -> None:
    _stop.set()
