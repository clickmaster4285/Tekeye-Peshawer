"""Turn a stream of journey frames into a small set of useful observations.

A person standing in front of one camera for 30 s must not become "50
observations". An observation is kept only when it is:
  - spaced in time (per camera; a new camera counts sooner — camera diversity),
  - visibly different from the last one kept on that camera (embedding diversity),
  - under the per-person cap.

The ML pipeline already drops blurry / turned-away faces before SFace runs, so
every face embedding that reaches here passed its quality gate.
"""

from __future__ import annotations

import threading
import time

import numpy as np
from django.conf import settings

from identity.models import PersonObservation


def _f(name: str, default: float) -> float:
    return float(getattr(settings, name, default))


def _empty(v) -> bool:
    return v is None or len(v) == 0


def _unit(v) -> np.ndarray | None:
    if _empty(v):
        return None
    a = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(a))
    return a / n if n > 0 else None


_last: dict[tuple[int, int], tuple[float, np.ndarray | None]] = {}
_counts: dict[int, int] = {}
_lock = threading.Lock()


def record_observation(
    *,
    person,
    camera,
    track_id: int | None,
    face_embedding=None,
    reid_embedding=None,
    snapshot_path: str = "",
) -> PersonObservation | None:
    if _empty(face_embedding) and _empty(reid_embedding):
        return None
    face = _unit(face_embedding)
    cam_id = getattr(camera, "pk", None) or 0
    now = time.monotonic()
    same_cam_gap = _f("IDENTITY_OBS_MIN_INTERVAL_SEC", 20)
    new_cam_gap = _f("IDENTITY_OBS_NEW_CAMERA_INTERVAL_SEC", 5)
    max_obs = int(_f("IDENTITY_OBS_MAX_PER_PERSON", 50))

    with _lock:
        count = _counts.get(person.pk)
        if count is not None and count >= max_obs:
            return None
        prev = _last.get((person.pk, cam_id))
        if prev is not None:
            prev_t, prev_face = prev
            if now - prev_t < same_cam_gap:
                return None
            if face is not None and prev_face is not None and float(face @ prev_face) >= _f(
                "IDENTITY_OBS_DUPLICATE_SIMILARITY", 0.95
            ):
                _last[(person.pk, cam_id)] = (now, prev_face)
                return None
        else:
            recent_other = [t for (pid, _), (t, _) in _last.items() if pid == person.pk]
            if recent_other and now - max(recent_other) < new_cam_gap:
                return None
        _last[(person.pk, cam_id)] = (now, face)
        if len(_last) > 20000:
            cutoff = now - 3600
            for k in [k for k, (t, _) in _last.items() if t < cutoff]:
                _last.pop(k, None)

    if count is None:
        count = PersonObservation.objects.filter(journey_person=person).count()
        if count >= max_obs:
            with _lock:
                _counts[person.pk] = count
            return None

    obs = PersonObservation.objects.create(
        journey_person=person,
        camera=camera if getattr(camera, "pk", None) else None,
        track_id=track_id,
        face_embedding=[round(float(v), 6) for v in face] if face is not None else None,
        reid_embedding=[float(v) for v in reid_embedding] if not _empty(reid_embedding) else None,
        snapshot_path=snapshot_path or "",
    )
    with _lock:
        _counts[person.pk] = count + 1
    return obs
