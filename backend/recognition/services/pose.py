"""Head pose from InsightFace results, shared by CCTV quality gates and enrollment coverage."""

from __future__ import annotations

import numpy as np

FRONT_YAW_DEG = 12.0


def face_yaw_pitch(face) -> tuple[float, float]:
    """Signed yaw/pitch in degrees: 3D landmark pose when buffalo_l gives one, else a 5-point yaw estimate."""
    pose = getattr(face, "pose", None)
    if pose is not None and len(pose) >= 2:
        return float(pose[1]), float(pose[0])
    kps = getattr(face, "kps", None)
    if kps is None or len(kps) < 3:
        return 0.0, 0.0
    left_eye, right_eye, nose = (np.asarray(p, dtype=np.float32) for p in kps[:3])
    eye_dist = float(np.linalg.norm(right_eye - left_eye))
    if eye_dist < 1.0:
        return 90.0, 0.0
    offset = (float(nose[0]) - (float(left_eye[0]) + float(right_eye[0])) / 2.0) / eye_dist
    # Nose drifts ~0.35 eye-widths off centre at ~30° yaw.
    return offset * 85.0, 0.0


def yaw_bucket(yaw: float) -> str:
    """front / side_a / side_b. Sides are not called left/right: webcam previews are often mirrored."""
    if abs(yaw) < FRONT_YAW_DEG:
        return "front"
    return "side_a" if yaw > 0 else "side_b"
