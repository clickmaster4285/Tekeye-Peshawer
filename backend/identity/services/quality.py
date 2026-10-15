"""Face quality for CCTV frames — decides whether a frame is a *useful observation*.

Score in [0, 1] from detection confidence, face size, sharpness, pose and
lighting. The identity engine discounts low-quality faces, and only faces
above ``IDENTITY_GALLERY_MIN_QUALITY`` may ever be added to a gallery.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import cv2
import numpy as np
from django.conf import settings


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def min_face_px() -> int:
    return int(getattr(settings, "IDENTITY_MIN_FACE_PX", 40))


@dataclass
class FaceQuality:
    score: float
    det_score: float
    face_px: int
    blur: float
    yaw: float | None
    pitch: float | None
    brightness: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        for k in ("score", "det_score", "blur", "brightness"):
            d[k] = round(float(d[k]), 3)
        for k in ("yaw", "pitch"):
            if d[k] is not None:
                d[k] = round(float(d[k]), 1)
        return d


def _yaw_from_kps(kps) -> float | None:
    """Approximate yaw in degrees from 5 landmarks (eyes, nose, mouth corners)."""
    try:
        pts = np.asarray(kps, dtype=np.float32).reshape(-1, 2)
        if len(pts) < 3:
            return None
        left_eye, right_eye, nose = pts[0], pts[1], pts[2]
        eye_dist = float(np.linalg.norm(right_eye - left_eye))
        if eye_dist < 1:
            return None
        mid = (left_eye + right_eye) / 2.0
        offset = float(nose[0] - mid[0]) / eye_dist  # ~0 frontal, ±0.5 ≈ strong profile
        return float(np.degrees(np.arcsin(_clamp(offset * 1.6, -1.0, 1.0))))
    except Exception:
        return None


def assess_face(frame: np.ndarray, face) -> FaceQuality:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
    face_w, face_h = max(x2 - x1, 0), max(y2 - y1, 0)
    face_px = min(face_w, face_h)
    det_score = float(getattr(face, "det_score", 0.0))

    crop = frame[y1:y2, x1:x2] if face_w and face_h else None
    if crop is not None and crop.size:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
    else:
        blur, brightness = 0.0, 0.0

    yaw = pitch = None
    pose = getattr(face, "pose", None)  # buffalo_l landmark_3d_68 → [pitch, yaw, roll]
    if pose is not None and len(pose) >= 2:
        pitch, yaw = float(pose[0]), float(pose[1])
    else:
        yaw = _yaw_from_kps(getattr(face, "kps", None))

    reasons: list[str] = []
    s_det = _clamp((det_score - 0.5) / 0.35)
    s_size = _clamp((face_px - min_face_px()) / 80.0)
    # Laplacian variance on small CCTV crops: <30 very soft, >150 sharp.
    s_blur = _clamp((blur - 30.0) / 120.0)
    s_pose = 1.0 if yaw is None else _clamp(1.0 - (abs(yaw) - 15.0) / 35.0)
    if pitch is not None:
        s_pose *= _clamp(1.0 - (abs(pitch) - 15.0) / 30.0)
    s_light = _clamp(1.0 - abs(brightness - 125.0) / 95.0)

    if s_det < 0.3:
        reasons.append("low detection confidence")
    if s_size < 0.3:
        reasons.append("face too small")
    if s_blur < 0.3:
        reasons.append("blurry")
    if s_pose < 0.4:
        reasons.append("turned away from camera")
    if s_light < 0.3:
        reasons.append("poor lighting")

    # Weighted geometric mean — one very bad factor drags the whole score down.
    parts = ((s_det, 0.2), (s_size, 0.25), (s_blur, 0.2), (s_pose, 0.25), (s_light, 0.1))
    score = float(np.exp(sum(wt * np.log(max(v, 0.02)) for v, wt in parts)))

    return FaceQuality(
        score=score,
        det_score=det_score,
        face_px=face_px,
        blur=blur,
        yaw=yaw,
        pitch=pitch,
        brightness=brightness,
        reasons=reasons,
    )
