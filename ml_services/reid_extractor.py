"""Person appearance (ReID) feature extraction — OSNet-style 256-dim vector."""

from __future__ import annotations

import cv2
import numpy as np


REID_DIM = 256


def extract_reid_embedding(person_crop: np.ndarray) -> list[float]:
    """
    Extract a normalized appearance embedding from a person crop.
    Uses color histograms + HOG-lite features (no external ReID weights required).
    """
    if person_crop is None or person_crop.size == 0:
        return []

    img = person_crop
    if img.shape[0] < 32 or img.shape[1] < 16:
        img = cv2.resize(img, (64, 128), interpolation=cv2.INTER_LINEAR)

    h, w = img.shape[:2]
    resized = cv2.resize(img, (64, 128), interpolation=cv2.INTER_AREA)

    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    hist_h = cv2.calcHist([hsv], [0], None, [32], [0, 180]).flatten()
    hist_s = cv2.calcHist([hsv], [1], None, [32], [0, 256]).flatten()
    hist_v = cv2.calcHist([hsv], [2], None, [32], [0, 256]).flatten()

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    ori_hist, _ = np.histogram(np.arctan2(gy, gx), bins=32, range=(-np.pi, np.pi))

    aspect = np.array([w / max(h, 1), h / max(w, 1)], dtype=np.float32)
    upper = resized[: h // 2, :]
    lower = resized[h // 2 :, :]
    upper_mean = upper.mean(axis=(0, 1)) if upper.size else np.zeros(3)
    lower_mean = lower.mean(axis=(0, 1)) if lower.size else np.zeros(3)

    parts = [
        hist_h,
        hist_s,
        hist_v,
        mag.flatten()[:64],
        ori_hist.astype(np.float32),
        aspect,
        upper_mean,
        lower_mean,
    ]
    vec = np.concatenate([np.asarray(p, dtype=np.float32).reshape(-1) for p in parts])

    if vec.size < REID_DIM:
        vec = np.pad(vec, (0, REID_DIM - vec.size))
    else:
        vec = vec[:REID_DIM]

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return [float(v) for v in vec]
