"""Build the attendance face gallery from trained FaceEnrollment rows."""
from __future__ import annotations

from recognition.models import FaceEnrollment


def vectors_for_enrollment(enrollment: FaceEnrollment) -> list[list[float]]:
    raw = enrollment.embeddings
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, (int, float)):
            return [raw]
        return [v for v in raw if isinstance(v, list) and v]
    if enrollment.embedding:
        return [enrollment.embedding]
    return []


def build_gallery() -> dict[str, list[list[float]]]:
    gallery: dict[str, list[list[float]]] = {}
    for enrollment in FaceEnrollment.objects.filter(is_trained=True).only(
        "staff_id", "embedding", "embeddings"
    ):
        vectors = vectors_for_enrollment(enrollment)
        if vectors:
            gallery[enrollment.gallery_key] = vectors
    return gallery
