"""Employee face gallery — many embeddings per employee instead of one average.

    Employee
     └── Face Gallery
          ├── Enrollment 01..N      (from the enrollment photos)
          └── Approved Live 01..N   (CCTV faces a human confirmed)

Matching scores a probe against every entry of every employee and blends the
best entry with the employee's centroid, so one odd photo cannot carry a match
on its own. The in-memory copy refreshes when the DB changes (any process).

One gallery per face model — embeddings from different models are not
comparable:
  insightface_buffalo_l (512-d)  attendance CCTV worker + webcam kiosk
  sface_2021dec         (128-d)  ML service journey pipeline / live detections
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from django.conf import settings
from django.db.models import Count, Max
from django.utils import timezone

from identity.models import FaceGalleryEntry, GallerySource

logger = logging.getLogger(__name__)

INSIGHTFACE_MODEL = "insightface_buffalo_l"
SFACE_MODEL = "sface_2021dec"


def _setting(name: str, default):
    return type(default)(getattr(settings, name, default))


def gallery_min_quality() -> float:
    return _setting("IDENTITY_GALLERY_MIN_QUALITY", 0.55)


def gallery_max_entries() -> int:
    return _setting("IDENTITY_GALLERY_MAX_ENTRIES", 60)


def near_duplicate_similarity() -> float:
    # Faces this similar to an existing entry add nothing — the "50 observations,
    # not 50 frames of someone standing still" rule.
    return _setting("IDENTITY_GALLERY_DUPLICATE_SIMILARITY", 0.93)


def _normalize(vec) -> np.ndarray | None:
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(arr))
    if norm == 0 or not np.isfinite(norm):
        return None
    return arr / norm


@dataclass
class StaffGallery:
    staff_id: int
    entry_ids: list[int | None]
    matrix: np.ndarray  # (n, d) unit rows
    centroid: np.ndarray


@dataclass
class Candidate:
    staff_id: int
    score: float
    best_entry_similarity: float
    centroid_similarity: float
    best_entry_id: int | None
    gallery_size: int


class FaceGalleryIndex:
    _REFRESH_CHECK_SEC = 15.0

    def __init__(self, model_name: str = INSIGHTFACE_MODEL):
        self.model_name = model_name
        self._lock = threading.Lock()
        self._galleries: dict[int, StaffGallery] = {}
        self._signature: tuple | None = None
        self._checked_at = 0.0

    # ── loading ──────────────────────────────────────────────────────────
    def _db_signature(self) -> tuple:
        agg = FaceGalleryEntry.objects.filter(model_name=self.model_name, is_active=True).aggregate(
            n=Count("id"), last=Max("id")
        )
        if self.model_name == SFACE_MODEL:
            from users.models import Staff

            legacy = (Staff.objects.exclude(face_embeddings=[]).exclude(face_embeddings__isnull=True).count(), "")
        else:
            from recognition.models import FaceEnrollment

            agg_l = FaceEnrollment.objects.filter(is_trained=True).aggregate(n=Count("id"), last=Max("updated_at"))
            legacy = (agg_l["n"], str(agg_l["last"]))
        return (agg["n"], agg["last"], *legacy)

    def _legacy_vectors(self) -> list[tuple[int, list]]:
        """Pre-gallery vectors, used only for staff that have no gallery entries yet."""
        if self.model_name == SFACE_MODEL:
            from users.models import Staff

            out = []
            for staff_id, entries in (
                Staff.objects.exclude(face_embeddings=[])
                .exclude(face_embeddings__isnull=True)
                .values_list("id", "face_embeddings")
            ):
                for item in entries or []:
                    if isinstance(item, dict) and item.get("embedding"):
                        out.append((staff_id, item["embedding"]))
            return out
        from recognition.models import FaceEnrollment

        return list(
            FaceEnrollment.objects.filter(is_trained=True, embedding__isnull=False).values_list(
                "staff_id", "embedding"
            )
        )

    def _load(self) -> dict[int, StaffGallery]:
        rows: dict[int, list[tuple[int | None, np.ndarray]]] = {}
        for entry_id, staff_id, emb in FaceGalleryEntry.objects.filter(
            model_name=self.model_name, is_active=True
        ).values_list("id", "staff_id", "embedding"):
            vec = _normalize(emb)
            if vec is not None:
                rows.setdefault(staff_id, []).append((entry_id, vec))

        # Staff enrolled before the gallery existed: use their legacy vectors
        # until `build_face_gallery` backfills real entries.
        with_entries = set(rows)
        for staff_id, emb in self._legacy_vectors():
            if staff_id in with_entries:
                continue
            vec = _normalize(emb)
            if vec is not None:
                rows.setdefault(staff_id, []).append((None, vec))

        galleries: dict[int, StaffGallery] = {}
        for staff_id, items in rows.items():
            matrix = np.stack([v for _, v in items])
            centroid = _normalize(matrix.mean(axis=0))
            if centroid is None:
                continue
            galleries[staff_id] = StaffGallery(
                staff_id=staff_id,
                entry_ids=[i for i, _ in items],
                matrix=matrix,
                centroid=centroid,
            )
        return galleries

    def refresh(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._checked_at < self._REFRESH_CHECK_SEC and self._signature is not None:
            return
        with self._lock:
            self._checked_at = now
            signature = self._db_signature()
            if not force and signature == self._signature:
                return
            self._galleries = self._load()
            self._signature = signature
            logger.info(
                "[identity] %s gallery loaded: %s staff, %s embeddings",
                self.model_name,
                len(self._galleries),
                sum(len(g.entry_ids) for g in self._galleries.values()),
            )

    @property
    def size(self) -> int:
        return len(self._galleries)

    # ── matching ─────────────────────────────────────────────────────────
    def match(self, probe, top_k: int = 3) -> list[Candidate]:
        self.refresh()
        vec = _normalize(probe)
        if vec is None:
            return []
        galleries = self._galleries
        out: list[Candidate] = []
        for staff_id, g in galleries.items():
            if g.matrix.shape[1] != vec.shape[0]:
                continue
            sims = g.matrix @ vec
            best_idx = int(np.argmax(sims))
            best = float(sims[best_idx])
            centroid_sim = float(g.centroid @ vec)
            # Single-entry galleries: centroid == entry, blend is a no-op.
            score = 0.7 * best + 0.3 * centroid_sim
            out.append(
                Candidate(
                    staff_id=staff_id,
                    score=score,
                    best_entry_similarity=best,
                    centroid_similarity=centroid_sim,
                    best_entry_id=g.entry_ids[best_idx],
                    gallery_size=len(g.entry_ids),
                )
            )
        out.sort(key=lambda c: c.score, reverse=True)
        return out[:top_k]


_indexes: dict[str, FaceGalleryIndex] = {}
_index_lock = threading.Lock()


def get_gallery_index(model_name: str = INSIGHTFACE_MODEL) -> FaceGalleryIndex:
    index = _indexes.get(model_name)
    if index is None:
        with _index_lock:
            index = _indexes.get(model_name)
            if index is None:
                index = _indexes[model_name] = FaceGalleryIndex(model_name)
    return index


# ── writing ──────────────────────────────────────────────────────────────


def add_live_entry(
    *,
    staff,
    embedding,
    quality: dict,
    camera=None,
    image_path: str = "",
    decision=None,
    approved_by=None,
    model_name: str = INSIGHTFACE_MODEL,
    push_ml: bool = True,
) -> tuple[FaceGalleryEntry | None, str]:
    """Add a human-approved live face. Returns (entry, message).

    Faces without a quality score (journey/SFace) are accepted: a human
    reviewed the crop. Scored faces must clear the gallery minimum."""
    vec = _normalize(embedding)
    if vec is None:
        return None, "Empty embedding"
    raw_q = (quality or {}).get("score")
    q = float(raw_q) if raw_q is not None else None
    if q is not None and q < gallery_min_quality():
        return None, f"Face quality {q:.2f} below gallery minimum {gallery_min_quality():.2f}"

    existing = list(
        FaceGalleryEntry.objects.filter(staff=staff, model_name=model_name, is_active=True).values_list(
            "id", "embedding", "source", "quality_score"
        )
    )
    for _, emb, _, _ in existing:
        other = _normalize(emb)
        if other is not None and other.shape == vec.shape and float(other @ vec) >= near_duplicate_similarity():
            return None, "Near-duplicate of an existing gallery face — not added"

    live = [(i, qs) for i, _, src, qs in existing if src == GallerySource.APPROVED_LIVE]
    if len(existing) >= gallery_max_entries() and live:
        # Gallery full: replace the weakest approved-live face if the new one is better.
        weakest_id, weakest_q = min(live, key=lambda t: t[1] or 0.0)
        if (weakest_q or 0.0) >= (q or 0.0):
            return None, "Gallery full and new face is not better than existing ones"
        FaceGalleryEntry.objects.filter(pk=weakest_id).update(is_active=False)

    entry = FaceGalleryEntry.objects.create(
        staff=staff,
        model_name=model_name,
        embedding=[round(float(v), 6) for v in vec],
        source=GallerySource.APPROVED_LIVE,
        quality_score=q,
        quality=quality or {},
        camera=camera,
        image_path=image_path,
        origin_decision=decision,
        approved_by=approved_by,
        approved_at=timezone.now(),
    )
    get_gallery_index(model_name).refresh(force=True)
    if model_name == SFACE_MODEL and push_ml:
        push_sface_gallery_to_ml_async()
    return entry, "Added to gallery"


def rebuild_enrollment_entries(staff, engine, folder: Path) -> int:
    """Replace a staff member's enrollment entries with one per dataset photo."""
    from identity.services.quality import assess_face

    new_rows = []
    for img_path in sorted(folder.glob("*.jpg")):
        image = cv2.imread(str(img_path))
        if image is None:
            continue
        image = engine.resize_max(image, 640)
        face, error = engine.get_single_face(image, allow_largest=True)
        if error or face is None:
            continue
        vec = _normalize(face.embedding)
        if vec is None:
            continue
        quality = assess_face(image, face)
        try:
            rel = img_path.relative_to(settings.MEDIA_ROOT).as_posix()
        except ValueError:
            rel = str(img_path)
        new_rows.append(
            FaceGalleryEntry(
                staff=staff,
                model_name=INSIGHTFACE_MODEL,
                embedding=[round(float(v), 6) for v in vec],
                source=GallerySource.ENROLLMENT,
                quality_score=quality.score,
                quality=quality.as_dict(),
                image_path=rel,
            )
        )
    if new_rows:
        FaceGalleryEntry.objects.filter(
            staff=staff, source=GallerySource.ENROLLMENT, model_name=INSIGHTFACE_MODEL
        ).delete()
        FaceGalleryEntry.objects.bulk_create(new_rows)
        get_gallery_index().refresh(force=True)
    return len(new_rows)


def sync_sface_enrollment_entries(staff) -> int:
    """Mirror Staff.face_embeddings (SFace, one per staff photo) into gallery entries."""
    rows = []
    for item in getattr(staff, "face_embeddings", None) or []:
        if not isinstance(item, dict):
            continue
        vec = _normalize(item.get("embedding") or [])
        if vec is None:
            continue
        rows.append(
            FaceGalleryEntry(
                staff=staff,
                model_name=SFACE_MODEL,
                embedding=[round(float(v), 6) for v in vec],
                source=GallerySource.ENROLLMENT,
                quality_score=None,
                quality={"note": "staff photo (SFace, not scored)"},
                image_path=str(item.get("image_key") or ""),
            )
        )
    FaceGalleryEntry.objects.filter(staff=staff, source=GallerySource.ENROLLMENT, model_name=SFACE_MODEL).delete()
    if rows:
        FaceGalleryEntry.objects.bulk_create(rows)
    get_gallery_index(SFACE_MODEL).refresh(force=True)
    return len(rows)


def push_sface_gallery_to_ml_async() -> None:
    """ML service keeps its own SFace gallery for labels — push the updated one."""

    def _push():
        from django.db import connection

        try:
            from ml.face_sync import push_face_embeddings_to_ml

            push_face_embeddings_to_ml()
        except Exception:
            logger.warning("[identity] Could not push SFace gallery to ML", exc_info=True)
        finally:
            connection.close()  # thread-local connection — don't leak it

    from django.db import transaction

    # After commit: the push thread uses its own connection and must see the new rows.
    transaction.on_commit(
        lambda: threading.Thread(target=_push, daemon=True, name="identity-sface-push").start()
    )
