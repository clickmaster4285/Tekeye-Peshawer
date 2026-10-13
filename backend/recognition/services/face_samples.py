"""CCTV face crops held for HR review. Approved crops join the gallery; all reviews label calibration data."""

from __future__ import annotations

import logging
import time

import cv2
import numpy as np
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import close_old_connections
from django.utils import timezone

from config.db import release_db

logger = logging.getLogger(__name__)

# Unreviewed samples beyond this are not saved; the queue would only grow stale.
MAX_PENDING = 300
UNMATCHED_COOLDOWN_SECONDS = 60.0
_last_unmatched: dict[int, float] = {}


def crop_face(frame: np.ndarray, bbox, pad: float = 0.35) -> np.ndarray | None:
    """Face box plus margin, so reviewers see hair, glasses and context."""
    if bbox is None:
        return None
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    pad_x = int(max(x2 - x1, 1) * pad)
    pad_y = int(max(y2 - y1, 1) * pad)
    crop = frame[max(0, y1 - pad_y):min(height, y2 + pad_y), max(0, x1 - pad_x):min(width, x2 + pad_x)]
    return crop.copy() if crop.size else None


def _staff_id(gallery_key: str | None) -> int | None:
    if gallery_key and str(gallery_key).startswith("staff-"):
        return int(str(gallery_key)[len("staff-"):])
    return None


def save_sample(
    *,
    kind: str,
    camera_id: int,
    crop: np.ndarray | None,
    embedding,
    suggested_key: str | None,
    confidence: float,
    quality: float,
) -> None:
    """Store one crop for review. Punches: at most one per person per day. Unmatched: one per camera per minute."""
    from recognition.models import FaceSample

    if crop is None or embedding is None:
        return
    suggested_id = _staff_id(suggested_key)
    if kind == FaceSample.KIND_UNMATCHED:
        now = time.monotonic()
        if now - _last_unmatched.get(camera_id, 0.0) < UNMATCHED_COOLDOWN_SECONDS:
            return
        _last_unmatched[camera_id] = now
    close_old_connections()
    try:
        if FaceSample.objects.filter(status=FaceSample.STATUS_PENDING).count() >= MAX_PENDING:
            return
        if kind == FaceSample.KIND_PUNCH and FaceSample.objects.filter(
            kind=FaceSample.KIND_PUNCH,
            suggested_staff_id=suggested_id,
            created_at__date=timezone.localdate(),
        ).exists():
            return
        ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            return
        from cameras.models import Camera

        sample = FaceSample(
            kind=kind,
            suggested_staff_id=suggested_id,
            camera=Camera.objects.filter(pk=camera_id).first(),
            embedding=[float(v) for v in np.asarray(embedding, dtype=np.float32).reshape(-1)],
            model_name=getattr(settings, "ATTENDANCE_INSIGHTFACE_MODEL", "buffalo_l"),
            confidence=round(float(confidence), 4),
            quality=round(float(quality), 4),
        )
        stamp = timezone.localtime().strftime("%H%M%S")
        sample.image.save(f"{kind}_cam{camera_id}_{stamp}.jpg", ContentFile(buf.tobytes()), save=True)
    except Exception:
        logger.exception("Face sample was not saved")
    finally:
        release_db()


def review_sample(sample, *, approve: bool, staff=None, user=None) -> None:
    """Approve as ``staff`` (defaults to the suggestion) or reject; refresh the gallery either way."""
    from recognition.models import FaceSample
    from recognition.services.gallery_index import invalidate_gallery

    if approve:
        sample.staff = staff or sample.suggested_staff
        if sample.staff is None:
            raise ValueError("Choose who this is before approving")
        sample.status = FaceSample.STATUS_APPROVED
    else:
        sample.staff = None
        sample.status = FaceSample.STATUS_REJECTED
    sample.reviewed_at = timezone.now()
    sample.reviewed_by = user if getattr(user, "is_authenticated", False) else None
    sample.save(update_fields=["staff", "status", "reviewed_at", "reviewed_by"])
    # An approval can also be undone by a later reject, so always rebuild.
    invalidate_gallery()
