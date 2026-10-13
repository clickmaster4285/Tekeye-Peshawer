"""ArcFace gallery search. FAISS inner-product when installed, otherwise numpy."""

from __future__ import annotations

import logging
import threading

import numpy as np

logger = logging.getLogger(__name__)

MATCH_MARGIN = 0.06
SOFT_MISS = 0.28
# A person's score is the mean of their best few vectors: one stray vector cannot carry a match alone.
TOP_PER_IDENTITY = 3
# Newest approved CCTV samples per person that join the gallery.
MAX_SAMPLES_PER_STAFF = 10


def _normalize(vector) -> np.ndarray:
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(arr))
    if norm <= 0:
        return arr
    return arr / norm


class GalleryIndex:
    def __init__(self, entries: list[tuple[str, np.ndarray]]):
        self.keys = [key for key, _ in entries]
        if entries:
            self.matrix = np.stack([vec for _, vec in entries]).astype(np.float32)
        else:
            self.matrix = np.zeros((0, 512), dtype=np.float32)
        self._faiss = None
        if len(self.keys) > 0:
            try:
                import faiss

                index = faiss.IndexFlatIP(self.matrix.shape[1])
                index.add(np.ascontiguousarray(self.matrix))
                self._faiss = index
            except Exception:
                self._faiss = None

    def __len__(self) -> int:
        return len(self.keys)

    def search(self, probe, k: int = 8) -> list[tuple[str, float]]:
        if not self.keys:
            return []
        query = _normalize(probe).reshape(1, -1).astype(np.float32)
        if self._faiss is not None:
            scores, ids = self._faiss.search(np.ascontiguousarray(query), min(k, len(self.keys)))
            hits = []
            for score, idx in zip(scores[0], ids[0]):
                if idx < 0:
                    continue
                hits.append((self.keys[int(idx)], float(score)))
            return hits
        scores = (self.matrix @ query.reshape(-1)).astype(np.float32)
        order = np.argsort(-scores)[:k]
        return [(self.keys[int(i)], float(scores[int(i)])) for i in order]


def identity_scores(hits) -> dict[str, float]:
    """(key, similarity) hits -> per-identity score: mean of that identity's top TOP_PER_IDENTITY hits."""
    grouped: dict[str, list[float]] = {}
    for key, score in hits:
        grouped.setdefault(key, []).append(float(score))
    return {
        key: float(np.mean(sorted(scores, reverse=True)[:TOP_PER_IDENTITY]))
        for key, scores in grouped.items()
    }


def decide(scores: dict[str, float], *, threshold: float) -> dict:
    """Best identity from per-identity scores. Ambiguous when the runner-up is within MATCH_MARGIN."""
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ordered:
        return {
            "gallery_key": None,
            "best_key": None,
            "confidence": 0.0,
            "second": 0.0,
            "ambiguous": False,
            "soft_miss": False,
        }
    best_key, best_score = ordered[0]
    second = ordered[1][1] if len(ordered) > 1 else -1.0
    ambiguous = best_score >= threshold and second >= 0 and (best_score - second) < MATCH_MARGIN
    matched = not ambiguous and best_score >= threshold
    return {
        "gallery_key": best_key if matched else None,
        "best_key": best_key,
        "confidence": best_score,
        "second": second,
        "ambiguous": ambiguous,
        "soft_miss": not matched and not ambiguous and best_score >= SOFT_MISS,
    }


def best_match(probe, index: GalleryIndex, *, threshold: float) -> dict:
    # Wide search so runner-up identities also get TOP_PER_IDENTITY hits for a fair margin.
    return decide(identity_scores(index.search(probe, k=256)), threshold=threshold)


_lock = threading.Lock()
_index: GalleryIndex | None = None


def _load_index() -> GalleryIndex:
    from recognition.models import FaceEnrollment

    entries: list[tuple[str, np.ndarray]] = []
    enrollments = FaceEnrollment.objects.filter(is_trained=True, embedding__isnull=False).only(
        "staff_id", "embedding", "embeddings"
    )
    trained_staff = set()
    for enrollment in enrollments:
        trained_staff.add(enrollment.staff_id)
        vectors = []
        if enrollment.embedding:
            vectors.append(enrollment.embedding)
        for extra in getattr(enrollment, "embeddings", None) or []:
            if extra:
                vectors.append(extra)
        for vector in vectors:
            arr = _normalize(vector)
            if arr.size == 0 or float(np.linalg.norm(arr)) == 0:
                continue
            entries.append((enrollment.gallery_key, arr))
    entries.extend(_approved_sample_entries(trained_staff))
    index = GalleryIndex(entries)
    logger.info("Attendance gallery index loaded (%d vectors, faiss=%s)", len(index), index._faiss is not None)
    return index


def _approved_sample_entries(trained_staff: set[int]) -> list[tuple[str, np.ndarray]]:
    """Approved CCTV crops for staff who also have trained photos, from the current model only."""
    from django.conf import settings

    from recognition.models import FaceSample

    model_name = getattr(settings, "ATTENDANCE_INSIGHTFACE_MODEL", "buffalo_l")
    per_staff: dict[int, int] = {}
    entries: list[tuple[str, np.ndarray]] = []
    samples = FaceSample.objects.filter(
        status=FaceSample.STATUS_APPROVED,
        model_name=model_name,
        staff_id__in=trained_staff,
    ).only("staff_id", "embedding").order_by("-created_at")
    for sample in samples:
        if per_staff.get(sample.staff_id, 0) >= MAX_SAMPLES_PER_STAFF:
            continue
        arr = _normalize(sample.embedding or [])
        if arr.size == 0 or float(np.linalg.norm(arr)) == 0:
            continue
        per_staff[sample.staff_id] = per_staff.get(sample.staff_id, 0) + 1
        entries.append((f"staff-{sample.staff_id}", arr))
    return entries


def get_gallery_index() -> GalleryIndex:
    global _index
    with _lock:
        if _index is None:
            _index = _load_index()
        return _index


def invalidate_gallery() -> None:
    global _index
    with _lock:
        _index = None
