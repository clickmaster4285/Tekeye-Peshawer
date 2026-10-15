"""Train ArcFace galleries from saved enrollment photos (ported from AIAttendance)."""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

from recognition.services.face_engine import get_face_engine
from recognition.services.gallery_index import invalidate_gallery

logger = logging.getLogger(__name__)

MODEL_VERSION = "InsightFace_v1_multi_light"


class TrainingError(ValueError):
    pass


def min_enrollment_images() -> int:
    return max(3, int(getattr(settings, "ATTENDANCE_MIN_ENROLLMENT_IMAGES", 5)))


def train_enrollment(enrollment) -> dict:
    required = min_enrollment_images()
    if enrollment.total_images < required:
        raise TrainingError(
            f"Need at least {required} images, currently have {enrollment.total_images}"
        )

    engine = get_face_engine()
    folder = Path(settings.MEDIA_ROOT) / enrollment.dataset_folder
    embeddings, source_count = engine.generate_embeddings_from_folder(folder)

    if source_count < required:
        raise TrainingError(
            f"Only {source_count} valid faces found in dataset. Recapture with better quality."
        )

    mean_embedding = engine.average_embedding(embeddings)
    enrollment.embedding = mean_embedding
    enrollment.embeddings = [[round(float(v), 6) for v in vec] for vec in embeddings]
    enrollment.is_trained = True
    enrollment.is_enrolled = True
    enrollment.model_version = MODEL_VERSION
    enrollment.save(
        update_fields=["embedding", "embeddings", "is_trained", "is_enrolled", "model_version", "updated_at"]
    )
    invalidate_gallery()

    # Keep the identity app's per-photo gallery in step (journey / review screens).
    try:
        from identity.services.gallery import rebuild_enrollment_entries

        rebuild_enrollment_entries(enrollment.staff, engine, folder)
    except Exception:
        logger.warning("Identity gallery rebuild skipped for staff %s", enrollment.staff_id, exc_info=True)

    return {
        "trained": True,
        "embedding_dim": len(mean_embedding),
        "images_used": source_count,
        "embeddings_stored": len(enrollment.embeddings),
        "model_version": MODEL_VERSION,
        "enrollment": enrollment,
    }
