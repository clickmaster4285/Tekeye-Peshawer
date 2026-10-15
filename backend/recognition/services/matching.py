"""Nearest-neighbor face matching against per-person embedding galleries.

Ported from AIAttendance. Gallery keys are ``staff-<pk>``; each person holds
many vectors (every enrollment photo under several lighting variants) and the
probe is scored against the best one, not an average.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from django.conf import settings


def _f(name: str, default: float) -> float:
    return float(getattr(settings, name, default))


def similarity_threshold() -> float:
    """Webcam / close-range matching."""
    return _f("ATTENDANCE_WEBCAM_SIMILARITY_THRESHOLD", 0.45)


def cctv_similarity_threshold() -> float:
    """CCTV faces are often farther / lower-res — slightly more tolerant."""
    return _f("ATTENDANCE_CCTV_SIMILARITY_THRESHOLD", 0.38)


def review_min_similarity() -> float:
    """Below auto-match but worth a human look."""
    return _f("ATTENDANCE_REVIEW_MIN_SIMILARITY", 0.28)


def match_margin() -> float:
    """Reject if the runner-up person is this close (false identity swaps)."""
    return _f("ATTENDANCE_MATCH_MARGIN", 0.06)


def staff_id_from_key(key: str | None) -> int | None:
    if not key or not str(key).startswith("staff-"):
        return None
    try:
        return int(str(key)[len("staff-"):])
    except ValueError:
        return None


@dataclass(frozen=True)
class MatchResult:
    gallery_key: str | None
    confidence: float
    second_best: float
    ambiguous: bool
    message: str
    candidate_key: str | None = None

    @property
    def matched(self) -> bool:
        return self.gallery_key is not None and not self.ambiguous

    @property
    def staff_id(self) -> int | None:
        return staff_id_from_key(self.gallery_key)

    @property
    def candidate_staff_id(self) -> int | None:
        return staff_id_from_key(self.candidate_key)

    def needs_review(self, review_min: float | None = None) -> bool:
        if self.matched:
            return False
        if not self.candidate_key:
            return False
        if self.ambiguous:
            return True
        return self.confidence >= (review_min_similarity() if review_min is None else review_min)


def l2_normalize(vec) -> np.ndarray | None:
    probe = np.asarray(vec, dtype=np.float32).reshape(-1)
    if probe.size == 0:
        return None
    norm = float(np.linalg.norm(probe))
    if norm == 0:
        return None
    return probe / norm


def as_vector_matrix(stored) -> np.ndarray | None:
    """Accept one vector or a list of vectors; return (K, D) L2-normalized."""
    if stored is None:
        return None
    if isinstance(stored, np.ndarray) and stored.ndim == 1:
        rows = [stored]
    elif isinstance(stored, (list, tuple)):
        if not stored:
            return None
        first = stored[0]
        if isinstance(first, (int, float, np.floating)):
            rows = [stored]
        else:
            rows = list(stored)
    else:
        return None

    mats = []
    for row in rows:
        vec = l2_normalize(row)
        if vec is not None:
            mats.append(vec)
    if not mats:
        return None
    return np.stack(mats, axis=0)


def best_match(
    probe,
    gallery,
    threshold: float | None = None,
    margin: float | None = None,
) -> MatchResult:
    min_sim = similarity_threshold() if threshold is None else threshold
    min_margin = match_margin() if margin is None else margin
    probe_vec = l2_normalize(probe)
    if probe_vec is None or not gallery:
        return MatchResult(None, 0.0, -1.0, False, "Unknown face")

    search = getattr(gallery, "search", None)
    if callable(search):
        scores, row_ids = search(probe_vec)
        per_person: dict[str, float] = {}
        for score, key in zip(scores, row_ids):
            value = float(score)
            prev = per_person.get(key)
            if prev is None or value > prev:
                per_person[key] = value
        ranked = sorted(per_person.items(), key=lambda kv: kv[1], reverse=True)
        best_id, best_sim, second_sim = None, -1.0, -1.0
        if ranked:
            best_id, best_sim = ranked[0]
            if len(ranked) > 1:
                second_sim = ranked[1][1]
        return _finish_match(best_id, best_sim, second_sim, min_sim, min_margin)

    best_id = None
    best_sim = -1.0
    second_sim = -1.0
    for key, stored in gallery.items():
        mat = as_vector_matrix(stored)
        if mat is None or mat.shape[1] != probe_vec.shape[0]:
            continue
        person_best = float(np.max(mat @ probe_vec))
        if person_best > best_sim:
            second_sim = best_sim
            best_sim = person_best
            best_id = str(key)
        elif person_best > second_sim:
            second_sim = person_best

    return _finish_match(best_id, best_sim, second_sim, min_sim, min_margin)


def _finish_match(best_id, best_sim, second_sim, min_sim, min_margin) -> MatchResult:
    if best_id is None:
        return MatchResult(None, 0.0, -1.0, False, "Unknown face", None)

    if best_sim < min_sim:
        return MatchResult(None, best_sim, second_sim, False, "Unknown face", best_id)

    if second_sim >= 0 and (best_sim - second_sim) < min_margin:
        return MatchResult(
            None,
            best_sim,
            second_sim,
            True,
            "Ambiguous match — skipped to avoid a false identity",
            best_id,
        )

    return MatchResult(best_id, best_sim, second_sim, False, "Face recognized", best_id)
