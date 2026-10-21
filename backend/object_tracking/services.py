"""Resolve / persist global object identities, visits, and exits."""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

import numpy as np
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from cameras.models import Camera

from .models import (
    GlobalObject,
    ObjectCameraTrack,
    ObjectType,
    ObjectVisit,
    TrackStatus,
    VisitStatus,
)

logger = logging.getLogger(__name__)

VEHICLE_CLASSES = frozenset({"car", "truck", "bus", "motorcycle", "bicycle", "vehicle"})
PERSON_CLASSES = frozenset({"person", "face"})
EXCLUDED_MODELS = frozenset({"smoke", "weapon"})
EXCLUDED_CLASS_NAMES = frozenset({"smoke", "fire", "flame", "weapon", "gun", "pistol", "rifle"})
REID_MATCH_THRESHOLD = 0.94
PERSON_REID_MATCH_THRESHOLD = 0.95
VEHICLE_REID_MATCH_THRESHOLD = 0.93
REID_EMA_MIN_SCORE = 0.96
TRACK_REUSE_WINDOW = timedelta(minutes=30)
_CODE_ALLOC_ATTEMPTS = 12
# Classes the detector flips between for one physical object (stationary matching only).
_STATIONARY_CLASS_GROUPS = {"truck": "car", "bus": "car", "vehicle": "car", "face": "person"}


def _setting_number(name: str, default: float) -> float:
    try:
        return float(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _exit_missed_polls() -> int:
    return max(1, int(_setting_number("OBJECT_EXIT_MISSED_POLLS", 3)))


def _exit_min_gone() -> timedelta:
    return timedelta(seconds=max(0.0, _setting_number("OBJECT_EXIT_MIN_SECONDS", 60)))


def _stale_visit_window() -> timedelta:
    return timedelta(minutes=max(1.0, _setting_number("OBJECT_STALE_VISIT_MINUTES", 10)))


def object_type_for_class(class_name: str) -> str:
    name = (class_name or "").strip().lower()
    if name in PERSON_CLASSES:
        return ObjectType.PERSON
    if name in VEHICLE_CLASSES:
        return ObjectType.VEHICLE
    return ObjectType.OBJECT


def _types_compatible(object_type: str, class_name: str) -> bool:
    """True when class_name belongs to the given object_type bucket."""
    expected = object_type_for_class(class_name)
    return expected == object_type


def _normalize_class(class_name: str) -> str:
    return (class_name or "").strip().lower()


def _same_identity_class(stored_class: str, new_class: str) -> bool:
    """Require exact class match so car/motorcycle/person never share one global ID."""
    a = _normalize_class(stored_class)
    b = _normalize_class(new_class)
    if not a or not b:
        return False
    if a == b:
        return True
    # Tiny aliases only
    aliases = {
        "face": "person",
        "vehicle": "car",
    }
    return aliases.get(a, a) == aliases.get(b, b)


def is_excluded_detection(det: dict[str, Any]) -> bool:
    model = str(det.get("model") or det.get("model_tag") or "").strip().lower()
    if model in EXCLUDED_MODELS:
        return True
    cls = str(det.get("class_name") or det.get("label") or "").strip().lower()
    if cls in EXCLUDED_CLASS_NAMES:
        return True
    if "smoke" in cls or "fire" in cls or "flame" in cls:
        return True
    return False


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na <= 0 or nb <= 0:
        return 0.0
    return float(np.dot(va / na, vb / nb))


def _iou(a: list, b: list) -> float:
    if len(a or []) < 4 or len(b or []) < 4:
        return 0.0
    try:
        ax1, ay1, ax2, ay2 = (float(v) for v in a[:4])
        bx1, by1, bx2, by2 = (float(v) for v in b[:4])
    except (TypeError, ValueError):
        return 0.0
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1) + max(0.0, bx2 - bx1) * max(0.0, by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def _class_group(class_name: str) -> str:
    name = _normalize_class(class_name)
    return _STATIONARY_CLASS_GROUPS.get(name, name)


def _find_stationary_visit(
    camera: Camera,
    *,
    class_name: str,
    bbox: list,
    embedding: list,
    face_key: str,
    now,
    only_object: GlobalObject | None = None,
    exclude_visit_ids: set[int] | None = None,
) -> ObjectVisit | None:
    """
    Recent visit on this camera whose box sits where this detection is.

    Catches a stationary object the tracker re-identified under a new local ID
    (flicker, occlusion) so it is not counted — and photographed — as new.
    """
    if len(bbox or []) < 4:
        return None
    window = timedelta(minutes=max(1.0, _setting_number("OBJECT_STATIONARY_WINDOW_MIN", 10)))
    min_iou = _setting_number("OBJECT_STATIONARY_IOU", 0.6)
    min_reid = _setting_number("OBJECT_STATIONARY_MIN_REID", 0.75)
    group = _class_group(class_name)

    qs = ObjectVisit.objects.filter(camera=camera, last_seen_at__gte=now - window)
    if only_object is not None:
        qs = qs.filter(global_object=only_object)
    best: ObjectVisit | None = None
    best_iou = min_iou
    for visit in qs.select_related("global_object").order_by("-last_seen_at")[:100]:
        if exclude_visit_ids and visit.pk in exclude_visit_ids:
            continue
        obj = visit.global_object
        if _class_group(obj.class_name or "") != group:
            continue
        stored_face = str((obj.metadata or {}).get("face_key") or "").strip()
        if face_key and stored_face and stored_face != face_key:
            continue
        overlap = _iou(bbox, visit.bbox or [])
        if overlap < best_iou:
            continue
        # Same spot but clearly different appearance → another object took the place.
        if embedding and obj.reid_embedding and _cosine(embedding, obj.reid_embedding) < min_reid:
            continue
        best, best_iou = visit, overlap
    return best


def _visit_confirmed(visit: ObjectVisit, det: dict[str, Any]) -> bool:
    """Seen in enough polls, or ML has tracked it long enough — not a one-frame flicker."""
    seen = int((visit.metadata or {}).get("seen_polls") or 0)
    if seen >= max(1, int(_setting_number("OBJECT_ENTER_CONFIRM_POLLS", 2))):
        return True
    try:
        ml_age = float(det.get("last_seen")) - float(det.get("first_seen"))
    except (TypeError, ValueError):
        return False
    return ml_age >= _setting_number("OBJECT_ENTER_CONFIRM_SECONDS", 1.0)


def _code_prefix(object_type: str) -> str:
    return {
        ObjectType.PERSON: "GP",
        ObjectType.VEHICLE: "GV",
        ObjectType.OBJECT: "GO",
    }.get(object_type, "GO")


def _next_code(object_type: str) -> str:
    """Allocate next GP/GV/GO code from the max numeric suffix (not latest id)."""
    prefix = _code_prefix(object_type)
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$", re.IGNORECASE)
    max_n = 0
    for code in GlobalObject.objects.filter(code__istartswith=prefix).values_list("code", flat=True).iterator():
        match = pattern.match(str(code or "").strip())
        if match:
            try:
                max_n = max(max_n, int(match.group(1)))
            except ValueError:
                continue
    return f"{prefix}{max_n + 1}"


def _create_global_object(
    *,
    object_type: str,
    class_name: str,
    label: str,
    embedding: list,
    camera: Camera,
    now,
    preferred_code: str = "",
) -> tuple[GlobalObject, bool]:
    """
    Insert a GlobalObject with a unique code.

    Returns (object, created). On a concurrent code race, returns the existing
    compatible row with created=False instead of raising IntegrityError.
    """
    preferred = (preferred_code or "").strip()
    last_error: Exception | None = None

    for attempt in range(_CODE_ALLOC_ATTEMPTS):
        if attempt == 0 and preferred:
            existing = GlobalObject.objects.filter(code=preferred).first()
            if existing is not None:
                if (
                    existing.object_type == object_type
                    and _same_identity_class(existing.class_name or "", class_name)
                ):
                    return existing, False
                # Preferred code already owned by incompatible object — mint a new one.
                code = _next_code(object_type)
            else:
                code = preferred
        else:
            code = _next_code(object_type)

        try:
            # Savepoint so IntegrityError does not abort the outer atomic block.
            with transaction.atomic():
                obj = GlobalObject.objects.create(
                    code=code,
                    object_type=object_type,
                    class_name=class_name[:80],
                    label=label[:120],
                    reid_embedding=embedding or [],
                    first_seen_at=now,
                    last_seen_at=now,
                    entry_at=now,
                    latest_camera=camera,
                    camera_history=[{
                        "camera_id": camera.pk,
                        "camera_name": (camera.name or "").strip(),
                        "camera_code": (camera.code or "").strip(),
                        "at": now.isoformat(),
                    }],
                    track_history=[],
                    metadata={"source": "object_tracking"},
                )
                return obj, True
        except IntegrityError as exc:
            last_error = exc
            raced = GlobalObject.objects.filter(code=code).first()
            if (
                raced is not None
                and raced.object_type == object_type
                and _same_identity_class(raced.class_name or "", class_name)
            ):
                return raced, False
            logger.debug(
                "GlobalObject code conflict on %s (attempt %s); retrying",
                code,
                attempt + 1,
            )
            continue

    raise IntegrityError(
        f"Unable to allocate unique GlobalObject code for {object_type}"
    ) from last_error


def _reid_threshold(object_type: str) -> float:
    if object_type == ObjectType.PERSON:
        return PERSON_REID_MATCH_THRESHOLD
    if object_type == ObjectType.VEHICLE:
        return VEHICLE_REID_MATCH_THRESHOLD
    return REID_MATCH_THRESHOLD


def _match_by_face(face_key: str) -> GlobalObject | None:
    key = (face_key or "").strip()
    if not key:
        return None
    # metadata JSON contains face_key written by ML / prior visits
    return (
        GlobalObject.objects.filter(object_type=ObjectType.PERSON, metadata__face_key=key)
        .order_by("-last_seen_at")
        .first()
    )


def _match_by_reid(
    object_type: str,
    class_name: str,
    embedding: list[float],
) -> tuple[GlobalObject | None, float]:
    if not embedding:
        return None, 0.0
    threshold = _reid_threshold(object_type)
    qs = GlobalObject.objects.filter(object_type=object_type).order_by("-last_seen_at")[:400]
    best: GlobalObject | None = None
    best_score = threshold
    for obj in qs:
        # Never merge different classes under one global ID (car ≠ motorcycle ≠ person).
        if not _same_identity_class(obj.class_name or "", class_name):
            continue
        score = _cosine(embedding, obj.reid_embedding or [])
        if score >= best_score:
            best_score = score
            best = obj
    return best, (best_score if best is not None else 0.0)


def _append_history(history: list, entry: dict, *, limit: int = 40) -> list:
    items = list(history or [])
    items.append(entry)
    return items[-limit:]


def _active_visit(obj: GlobalObject) -> ObjectVisit | None:
    return (
        ObjectVisit.objects.filter(global_object=obj, status=VisitStatus.ACTIVE)
        .order_by("-entry_at")
        .first()
    )


def _close_visit(visit: ObjectVisit, *, exited_at=None) -> None:
    visit.finalize_exit(exited_at=exited_at)
    visit.save(
        update_fields=[
            "exit_at",
            "last_seen_at",
            "status",
            "duration_seconds",
            "updated_at",
        ]
    )
    obj = visit.global_object
    obj.exit_at = visit.exit_at
    obj.last_seen_at = visit.last_seen_at
    obj.save(update_fields=["exit_at", "last_seen_at", "updated_at"])


def _finish_track(track: ObjectCameraTrack, *, ended_at=None) -> None:
    end = ended_at or timezone.now()
    track.status = TrackStatus.FINISHED
    track.ended_at = end
    track.save(update_fields=["status", "ended_at"])


def _open_visit(
    obj: GlobalObject,
    camera: Camera,
    *,
    track_id: int | None,
    bbox: list,
    confidence: float | None,
    now,
) -> ObjectVisit:
    visit = ObjectVisit.objects.create(
        global_object=obj,
        camera=camera,
        local_track_id=track_id,
        status=VisitStatus.ACTIVE,
        entry_at=now,
        last_seen_at=now,
        bbox=bbox or [],
        confidence=confidence,
        metadata={"source": "object_tracking", "seen_polls": 1, "missed_polls": 0},
    )
    obj.entry_at = now
    obj.exit_at = None
    obj.last_seen_at = now
    obj.latest_camera = camera
    obj.save(update_fields=["entry_at", "exit_at", "last_seen_at", "latest_camera", "updated_at"])
    return visit


def _reopen_visit(visit: ObjectVisit) -> ObjectVisit:
    """Object is back in the same spot shortly after its visit closed — continue that visit."""
    visit.status = VisitStatus.ACTIVE
    visit.exit_at = None
    visit.save(update_fields=["status", "exit_at", "updated_at"])
    return visit


def _end_visit(visit: ObjectVisit, *, exited_at) -> None:
    """Close a visit whose object really left; drop it if it was never confirmed."""
    obj = visit.global_object
    for track in ObjectCameraTrack.objects.filter(
        global_object=obj,
        camera_id=visit.camera_id,
        status=TrackStatus.ACTIVE,
    ):
        _finish_track(track, ended_at=exited_at)

    if visit.detection_event_id is not None:
        _close_visit(visit, exited_at=exited_at)
        return

    # Never confirmed (one-frame flicker / false box): leave no ghost visit or object behind.
    visit.delete()
    if obj.first_detection_event_id is None and not ObjectVisit.objects.filter(global_object=obj).exists():
        obj.delete()
    else:
        obj.exit_at = exited_at
        obj.save(update_fields=["exit_at", "updated_at"])


@transaction.atomic
def upsert_global_object(
    camera: Camera,
    det: dict[str, Any],
    *,
    claimed_visit_ids: set[int] | None = None,
) -> tuple[GlobalObject | None, ObjectVisit | None, bool]:
    """
    Create/update GlobalObject + visit + camera track.

    Returns (global_object, visit, should_create_detection_event).
    should_create_detection_event is True once per visit, when the visit is first
    confirmed (seen in enough polls) — never again while the object stays.
    claimed_visit_ids: visits already matched by other boxes in this poll.
    """
    if is_excluded_detection(det):
        return None, None, False

    class_name = str(det.get("class_name") or det.get("label") or "object").strip()
    label = str(det.get("label") or class_name).strip()
    object_type = str(det.get("object_type") or object_type_for_class(class_name)).strip().lower()
    if object_type not in {ObjectType.PERSON, ObjectType.VEHICLE, ObjectType.OBJECT}:
        object_type = object_type_for_class(class_name)

    embedding = det.get("reid_embedding") or []
    if embedding and not isinstance(embedding, list):
        embedding = list(embedding)

    now = timezone.now()
    track_id = det.get("track_id")
    try:
        track_id_i = int(track_id) if track_id is not None else None
    except (TypeError, ValueError):
        track_id_i = None

    try:
        confidence = float(det.get("confidence")) if det.get("confidence") is not None else None
    except (TypeError, ValueError):
        confidence = None

    bbox = det.get("bbox") or []
    ml_gid = str(det.get("global_object_id") or "").strip()
    face_key = str(det.get("face_identity_key") or "").strip()
    obj: GlobalObject | None = None
    stationary: ObjectVisit | None = None
    reid_score = 0.0

    # 1) Active local track bind (only if type still matches this detection)
    if track_id_i is not None:
        track = (
            ObjectCameraTrack.objects.select_related("global_object")
            .filter(
                camera=camera,
                local_track_id=track_id_i,
                status=TrackStatus.ACTIVE,
                started_at__gte=now - TRACK_REUSE_WINDOW,
            )
            .order_by("-started_at")
            .first()
        )
        if track is not None:
            bound = track.global_object
            bound_face = str((bound.metadata or {}).get("face_key") or "").strip()
            if (
                bound.object_type == object_type
                and _types_compatible(bound.object_type, class_name)
                and _same_identity_class(bound.class_name or "", class_name)
                and not (face_key and bound_face and face_key != bound_face)
            ):
                obj = bound
                reid_score = 1.0
            else:
                # ByteTrack ID switch / class flip / face flip — split identity.
                _finish_track(track, ended_at=now)
                visit_old = _active_visit(bound)
                if visit_old is not None and visit_old.local_track_id == track_id_i:
                    _close_visit(visit_old, exited_at=now)

    # 2) Face identity (strongest for persons)
    if obj is None and face_key and object_type == ObjectType.PERSON:
        obj = _match_by_face(face_key)
        if obj is not None:
            reid_score = 0.99

    # 3) Prefer ML-assigned code if already persisted and class-compatible
    if obj is None and ml_gid:
        candidate = GlobalObject.objects.filter(code=ml_gid).first()
        if (
            candidate is not None
            and candidate.object_type == object_type
            and _same_identity_class(candidate.class_name or "", class_name)
        ):
            cand_face = str((candidate.metadata or {}).get("face_key") or "").strip()
            if not (face_key and cand_face and face_key != cand_face):
                obj = candidate
                reid_score = 1.0

    # 4) Stationary memory: something of this class sat in this exact spot on this camera
    if obj is None:
        stationary = _find_stationary_visit(
            camera,
            class_name=class_name,
            bbox=bbox,
            embedding=embedding,
            face_key=face_key,
            now=now,
            exclude_visit_ids=claimed_visit_ids,
        )
        if stationary is not None:
            obj = stationary.global_object

    # 5) Strict ReID gallery match (leave / return) — same type only
    if obj is None:
        obj, reid_score = _match_by_reid(object_type, class_name, embedding)
        if obj is not None and face_key:
            cand_face = str((obj.metadata or {}).get("face_key") or "").strip()
            if cand_face and cand_face != face_key:
                obj = None
                reid_score = 0.0

    created = False
    if obj is None:
        obj, created = _create_global_object(
            object_type=object_type,
            class_name=class_name,
            label=label,
            embedding=embedding,
            camera=camera,
            now=now,
            preferred_code=ml_gid,
        )
        reid_score = 1.0

    if created:
        if face_key:
            meta = dict(obj.metadata or {})
            meta["face_key"] = face_key
            obj.metadata = meta
            obj.save(update_fields=["metadata", "updated_at"])
        visit = _open_visit(
            obj,
            camera,
            track_id=track_id_i,
            bbox=bbox,
            confidence=confidence,
            now=now,
        )
    else:
        # Keep type + class stable; only refresh label when class still matches
        if _same_identity_class(obj.class_name or "", class_name):
            obj.class_name = class_name[:80]
            obj.label = label[:120]
        obj.latest_camera = camera
        obj.last_seen_at = now
        if embedding:
            prev = obj.reid_embedding or []
            if prev and len(prev) == len(embedding) and reid_score >= REID_EMA_MIN_SCORE:
                merged = [0.85 * float(a) + 0.15 * float(b) for a, b in zip(prev, embedding)]
                norm = float(np.linalg.norm(np.asarray(merged, dtype=np.float32)))
                obj.reid_embedding = [float(v) / norm for v in merged] if norm > 0 else list(embedding)
            elif not prev:
                obj.reid_embedding = list(embedding)
        if face_key:
            meta = dict(obj.metadata or {})
            if not meta.get("face_key"):
                meta["face_key"] = face_key
                obj.metadata = meta
        hist = list(obj.camera_history or [])
        if not hist or hist[-1].get("camera_id") != camera.pk:
            obj.camera_history = _append_history(
                hist,
                {
                    "camera_id": camera.pk,
                    "camera_name": (camera.name or "").strip(),
                    "camera_code": (camera.code or "").strip(),
                    "at": now.isoformat(),
                },
            )
        obj.save()

        visit = _active_visit(obj)
        if visit is None:
            # Back in the same spot shortly after its visit closed (occluded, missed polls)
            # → same visit, no new snapshot.
            recent = stationary
            if recent is None or recent.global_object_id != obj.pk:
                recent = _find_stationary_visit(
                    camera,
                    class_name=class_name,
                    bbox=bbox,
                    embedding=embedding,
                    face_key=face_key,
                    now=now,
                    only_object=obj,
                )
            if recent is not None and recent.detection_event_id is not None:
                visit = _reopen_visit(recent)
        if visit is None:
            # Object returned after exit (or first visit after legacy rows) → new visit
            visit = _open_visit(
                obj,
                camera,
                track_id=track_id_i,
                bbox=bbox,
                confidence=confidence,
                now=now,
            )
        else:
            meta = dict(visit.metadata or {})
            meta["seen_polls"] = int(meta.get("seen_polls") or 0) + 1
            meta["missed_polls"] = 0
            visit.metadata = meta
            visit.last_seen_at = now
            visit.bbox = bbox or visit.bbox
            if confidence is not None:
                visit.confidence = confidence
            if track_id_i is not None:
                visit.local_track_id = track_id_i
            if visit.camera_id != camera.pk:
                visit.camera = camera
            visit.save(
                update_fields=[
                    "last_seen_at",
                    "bbox",
                    "confidence",
                    "local_track_id",
                    "camera",
                    "metadata",
                    "updated_at",
                ]
            )
            obj.exit_at = None
            obj.entry_at = visit.entry_at
            obj.save(update_fields=["exit_at", "entry_at", "updated_at"])

    # Bind / refresh local ByteTrack session
    if track_id_i is not None:
        track = (
            ObjectCameraTrack.objects.filter(
                camera=camera,
                local_track_id=track_id_i,
                status=TrackStatus.ACTIVE,
            )
            .order_by("-started_at")
            .first()
        )
        if track is None:
            ObjectCameraTrack.objects.create(
                global_object=obj,
                camera=camera,
                local_track_id=track_id_i,
                status=TrackStatus.ACTIVE,
                started_at=now,
                last_bbox=bbox,
                metadata={"missed_polls": 0},
            )
            obj.track_history = _append_history(
                obj.track_history or [],
                {
                    "camera_id": camera.pk,
                    "local_track_id": track_id_i,
                    "started_at": now.isoformat(),
                },
            )
            obj.save(update_fields=["track_history", "updated_at"])
        else:
            if track.global_object_id != obj.pk:
                track.global_object = obj
            track.last_bbox = bbox
            track.metadata = {**(track.metadata or {}), "missed_polls": 0}
            track.save(update_fields=["global_object", "last_bbox", "metadata"])

    # Capture once per visit, as soon as the visit is confirmed real
    should_capture = bool(
        visit is not None and visit.detection_event_id is None and _visit_confirmed(visit, det)
    )
    return obj, visit, should_capture


def mark_detection_captured(
    obj: GlobalObject,
    detection_event_id: int,
    snapshot_path: str = "",
    visit: ObjectVisit | None = None,
) -> None:
    updates = ["updated_at"]
    if obj.first_detection_event_id is None:
        obj.first_detection_event_id = detection_event_id
        updates.append("first_detection_event_id")
    if snapshot_path and not obj.snapshot_path:
        obj.snapshot_path = snapshot_path
        updates.append("snapshot_path")
    obj.save(update_fields=updates)

    if visit is None:
        visit = _active_visit(obj)
    if visit is not None:
        visit.detection_event_id = detection_event_id
        v_updates = ["detection_event_id", "updated_at"]
        if snapshot_path and not visit.snapshot_path:
            visit.snapshot_path = snapshot_path
            v_updates.append("snapshot_path")
        visit.save(update_fields=v_updates)


@transaction.atomic
def record_camera_poll(
    camera: Camera,
    *,
    seen_visit_ids: set[int],
    active_track_ids: set[int],
) -> int:
    """
    One detection poll of this camera finished: count misses, close what really left.

    A visit ends only after it is missing in OBJECT_EXIT_MISSED_POLLS polls of its own
    camera AND has not been seen for OBJECT_EXIT_MIN_SECONDS — so a slow poll cycle
    (many cameras round-robin) never closes a visit for an object that did not move.
    Returns the number of visits closed.
    """
    now = timezone.now()
    missed_limit = _exit_missed_polls()
    gone_cutoff = now - _exit_min_gone()
    closed = 0

    active_visits = (
        ObjectVisit.objects.filter(camera=camera, status=VisitStatus.ACTIVE)
        .exclude(pk__in=seen_visit_ids)
        .select_related("global_object")
    )
    for visit in active_visits:
        meta = dict(visit.metadata or {})
        meta["missed_polls"] = int(meta.get("missed_polls") or 0) + 1
        if meta["missed_polls"] >= missed_limit and visit.last_seen_at <= gone_cutoff:
            _end_visit(visit, exited_at=visit.last_seen_at)
            closed += 1
        else:
            visit.metadata = meta
            visit.save(update_fields=["metadata", "updated_at"])

    # Local ByteTrack sessions that stopped appearing (ID switch or object left)
    stale_tracks = ObjectCameraTrack.objects.filter(camera=camera, status=TrackStatus.ACTIVE).exclude(
        local_track_id__in=active_track_ids
    )
    for track in stale_tracks:
        meta = dict(track.metadata or {})
        meta["missed_polls"] = int(meta.get("missed_polls") or 0) + 1
        track.metadata = meta
        if meta["missed_polls"] >= missed_limit:
            track.status = TrackStatus.FINISHED
            track.ended_at = now
            track.save(update_fields=["status", "ended_at", "metadata"])
        else:
            track.save(update_fields=["metadata"])

    return closed


def finalize_stale_visits_globally(*, limit: int = 200) -> int:
    """Safety net for cameras that stopped reporting: close visits not refreshed for minutes."""
    now = timezone.now()
    cutoff = now - _stale_visit_window()
    closed = 0
    qs = (
        ObjectVisit.objects.filter(status=VisitStatus.ACTIVE, last_seen_at__lt=cutoff)
        .select_related("global_object")
        .order_by("last_seen_at")[:limit]
    )
    for visit in qs:
        _end_visit(visit, exited_at=visit.last_seen_at or now)
        closed += 1
    return closed
