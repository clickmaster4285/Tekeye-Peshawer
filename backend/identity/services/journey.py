"""Person Journey → identity engine.

    Track ID ─► SFace embedding ─► identity engine (gallery + margin + track votes)
                                        │
                     accepted ──────────┼──► journey person = that employee
                     review   ──────────┼──► stays unknown, queued for a human
                     unknown  ──────────┘

The ML service's own ``face_label`` is recorded as evidence but no longer
decides identity on its own. Without an embedding (older ML builds) callers
fall back to the label.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from identity.models import DecisionOutcome, IdentityDecision, ReviewStatus
from identity.services.engine import IdentityResult, get_identity_engine, record_decision
from identity.services.gallery import SFACE_MODEL

logger = logging.getLogger(__name__)

SFACE_DIM = 128

# One audited decision per (camera, track, staff, outcome) — tracks report every frame.
_recorded: dict[tuple, float] = {}
_recorded_lock = threading.Lock()
_RECORD_TTL_SEC = 30 * 60


def _first_time(key: tuple) -> bool:
    now = time.monotonic()
    with _recorded_lock:
        if len(_recorded) > 5000:
            for k in [k for k, t in _recorded.items() if now - t > _RECORD_TTL_SEC]:
                _recorded.pop(k, None)
        if key in _recorded and now - _recorded[key] < _RECORD_TTL_SEC:
            return False
        _recorded[key] = now
        return True


@dataclass
class JourneyIdentity:
    result: IdentityResult
    staff_id: int | None
    staff_name: str
    camera_id: int
    track_id: int | None
    face_label: str

    def record(self, *, camera, journey_person=None, snapshot_path: str = "") -> IdentityDecision | None:
        """Persist the decision once per track/outcome. Review → pending human check."""
        r = self.result
        if r.outcome == DecisionOutcome.UNKNOWN:
            return None  # the journey itself tracks unknown people (U-codes)
        key = (self.camera_id, self.track_id or 0, r.staff_id, r.outcome)
        if not _first_time(key):
            return None
        try:
            return record_decision(
                r,
                camera=camera,
                track_id=self.track_id,
                journey_person=journey_person,
                snapshot_path=snapshot_path,
                policy={
                    "action": "journey_identified" if r.accepted else "identity_review",
                    "message": (
                        f"Journey person identified as {self.staff_name}"
                        if r.accepted
                        else "Possible employee on journey track — confirm to link the journey"
                    ),
                    "gates": [],
                },
                review_status=ReviewStatus.PENDING if r.outcome == DecisionOutcome.REVIEW else ReviewStatus.NOT_REQUIRED,
            )
        except Exception:
            logger.exception("[identity] Could not record journey decision")
            return None


def identify_journey_face(
    *,
    face_embedding,
    face_label: str,
    camera,
    track_id: int | None,
) -> JourneyIdentity | None:
    if not face_embedding or len(face_embedding) != SFACE_DIM:
        return None
    from person_journey.matching import resolve_staff_from_face_label
    from users.models import Staff

    result = get_identity_engine(SFACE_MODEL).identify(
        face_embedding,
        quality=None,
        source="journey",
        camera_id=camera.pk,
        track_id=track_id or None,
    )
    label_staff_id, _ = resolve_staff_from_face_label(face_label) if face_label else (None, "")
    result.factors["ml_label"] = face_label or None
    result.factors["ml_label_staff_id"] = label_staff_id
    if label_staff_id and result.staff_id and label_staff_id != result.staff_id:
        result.reasons.append("ML service label disagrees with gallery match")

    staff_id = result.staff_id if result.accepted else None
    staff_name = ""
    if result.staff_id:
        staff_name = Staff.objects.filter(pk=result.staff_id).values_list("full_name", flat=True).first() or ""
    return JourneyIdentity(
        result=result,
        staff_id=staff_id,
        staff_name=staff_name,
        camera_id=camera.pk,
        track_id=track_id,
        face_label=face_label,
    )
