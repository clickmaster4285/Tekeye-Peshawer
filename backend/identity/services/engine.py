"""Person Identity Engine — multi-factor "who is this?" with an explanation.

    face similarity (best gallery entry + centroid)
  + margin over the runner-up employee
  + face quality
  + track consistency (same track kept voting for the same person)
        ↓
  ACCEPTED  — strong on every factor
  REVIEW    — plausible, but something is weak → human decides
  UNKNOWN   — no employee is close enough

Face models never mark attendance themselves; callers pass the result to
``identity.services.attendance_policy``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from django.conf import settings
from django.utils import timezone

from identity.models import DecisionOutcome, IdentityDecision, ReviewStatus
from identity.services.gallery import INSIGHTFACE_MODEL, SFACE_MODEL, Candidate, get_gallery_index
from identity.services.quality import FaceQuality

logger = logging.getLogger(__name__)


def _f(name: str, default: float) -> float:
    return float(getattr(settings, name, default))


def accept_similarity(source: str, model_name: str = INSIGHTFACE_MODEL) -> float:
    if model_name == SFACE_MODEL:
        return _f("IDENTITY_SFACE_ACCEPT_SIMILARITY", 0.36)
    if source == "webcam":
        return _f("ATTENDANCE_WEBCAM_SIMILARITY_THRESHOLD", 0.45)
    return _f("ATTENDANCE_CCTV_SIMILARITY_THRESHOLD", 0.38)


def review_similarity(source: str, model_name: str = INSIGHTFACE_MODEL) -> float:
    band = _f("IDENTITY_SFACE_REVIEW_BAND", 0.06) if model_name == SFACE_MODEL else _f("IDENTITY_REVIEW_BAND", 0.08)
    return accept_similarity(source, model_name) - band


def accept_confidence() -> float:
    return _f("IDENTITY_ACCEPT_CONFIDENCE", 0.55)


def min_margin() -> float:
    return _f("IDENTITY_MIN_MARGIN", 0.05)


def min_quality() -> float:
    return _f("IDENTITY_MIN_QUALITY", 0.30)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


# ── track consistency ────────────────────────────────────────────────────


class _TrackVotes:
    """Recent identity votes per (camera, track). Tracks idle >2 min are dropped."""

    _TTL = 120.0

    def __init__(self):
        self._lock = threading.Lock()
        self._votes: dict[tuple, tuple[float, deque]] = {}

    def vote(self, key: tuple, staff_id: int | None) -> float | None:
        now = time.monotonic()
        with self._lock:
            if len(self._votes) > 2000:
                self._votes = {k: v for k, v in self._votes.items() if now - v[0] < self._TTL}
            _, votes = self._votes.get(key, (now, deque(maxlen=15)))
            prior = list(votes)
            votes.append(staff_id)
            self._votes[key] = (now, votes)
        if not prior or staff_id is None:
            return None
        return Counter(prior)[staff_id] / len(prior)


_track_votes = _TrackVotes()


# ── result ───────────────────────────────────────────────────────────────


@dataclass
class IdentityResult:
    outcome: str
    staff_id: int | None
    confidence: float
    face_similarity: float
    second_best_similarity: float | None
    quality: FaceQuality | None
    best_entry_id: int | None
    factors: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    source: str = ""
    model_name: str = INSIGHTFACE_MODEL

    @property
    def accepted(self) -> bool:
        return self.outcome == DecisionOutcome.ACCEPTED

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)


class PersonIdentityEngine:
    def __init__(self, model_name: str = INSIGHTFACE_MODEL):
        self.model_name = model_name
        self.gallery = get_gallery_index(model_name)

    def identify(
        self,
        embedding,
        *,
        quality: FaceQuality | None,
        source: str,
        camera_id: int | None = None,
        track_id: int | None = None,
    ) -> IdentityResult:
        candidates: list[Candidate] = self.gallery.match(embedding)
        best = candidates[0] if candidates else None
        runner_up = candidates[1] if len(candidates) > 1 else None
        emb_list = [round(float(v), 6) for v in np.asarray(embedding, dtype=np.float32).reshape(-1)]

        sim = best.score if best else 0.0
        second = runner_up.score if runner_up else None
        margin = sim - (second if second is not None else 0.0)
        q = quality.score if quality else None

        acc_sim = accept_similarity(source, self.model_name)
        rev_sim = review_similarity(source, self.model_name)

        # Normalized factor scores, each in [0, 1].
        # 0 at the review floor, 0.5 exactly at the accept threshold, 1.0 at +0.20 above it.
        if sim < acc_sim:
            face_factor = _clamp(0.5 * (sim - rev_sim) / max(acc_sim - rev_sim, 1e-6))
        else:
            face_factor = _clamp(0.5 + 0.5 * (sim - acc_sim) / 0.20)
        margin_factor = _clamp(margin / 0.15) if runner_up else 1.0
        track_factor = None
        if track_id is not None and camera_id is not None:
            track_factor = _track_votes.vote(
                (camera_id, track_id), best.staff_id if best and sim >= rev_sim else None
            )

        weights = {"face": 0.55, "margin": 0.15, "quality": 0.15, "track": 0.15}
        values = {"face": face_factor, "margin": margin_factor, "quality": q, "track": track_factor}
        used = {k: w for k, w in weights.items() if values[k] is not None}
        confidence = sum(values[k] * w for k, w in used.items()) / sum(used.values())

        factors = {
            "face_similarity": round(sim, 4),
            "best_entry_similarity": round(best.best_entry_similarity, 4) if best else None,
            "centroid_similarity": round(best.centroid_similarity, 4) if best else None,
            "second_best_similarity": round(second, 4) if second is not None else None,
            "runner_up_staff_id": runner_up.staff_id if runner_up else None,
            "margin": round(margin, 4),
            "quality": round(q, 3) if q is not None else None,
            "track_consistency": round(track_factor, 3) if track_factor is not None else None,
            "gallery_size": best.gallery_size if best else 0,
            "thresholds": {
                "accept_similarity": acc_sim,
                "review_similarity": round(rev_sim, 4),
                "accept_confidence": accept_confidence(),
                "min_margin": min_margin(),
                "min_quality": min_quality(),
            },
            "weights": used,
        }

        reasons: list[str] = []
        if best is None or sim < rev_sim:
            outcome = DecisionOutcome.UNKNOWN
            reasons.append(
                "No enrolled employee close enough"
                + (f" (best {sim:.2f} < review {rev_sim:.2f})" if best else " (empty gallery)")
            )
        else:
            weak: list[str] = []
            if sim < acc_sim:
                weak.append(f"similarity {sim:.2f} below accept {acc_sim:.2f}")
            if runner_up and margin < min_margin():
                weak.append(f"too close to another employee (margin {margin:.2f})")
            if q is not None and q < min_quality():
                weak.append(
                    f"face quality {q:.2f} low"
                    + (f" ({', '.join(quality.reasons)})" if quality and quality.reasons else "")
                )
            if track_factor is not None and track_factor < 0.5:
                weak.append(f"track identity inconsistent ({track_factor:.0%} agreement)")
            if confidence < accept_confidence():
                weak.append(f"combined confidence {confidence:.2f} below {accept_confidence():.2f}")

            if weak:
                outcome = DecisionOutcome.REVIEW
                reasons.extend(weak)
            else:
                outcome = DecisionOutcome.ACCEPTED
                reasons.append(
                    f"Face {sim:.2f} ≥ {acc_sim:.2f}, margin {margin:.2f}, "
                    + (f"quality {q:.2f}, " if q is not None else "quality not scored, ")
                    + f"confidence {confidence:.2f}"
                )

        return IdentityResult(
            outcome=outcome,
            staff_id=best.staff_id if best and outcome != DecisionOutcome.UNKNOWN else None,
            confidence=round(confidence, 4),
            face_similarity=round(sim, 4),
            second_best_similarity=round(second, 4) if second is not None else None,
            quality=quality,
            best_entry_id=best.best_entry_id if best and outcome != DecisionOutcome.UNKNOWN else None,
            factors=factors,
            reasons=reasons,
            embedding=emb_list,
            source=source,
            model_name=self.model_name,
        )


_engines: dict[str, PersonIdentityEngine] = {}
_engine_lock = threading.Lock()


def get_identity_engine(model_name: str = INSIGHTFACE_MODEL) -> PersonIdentityEngine:
    engine = _engines.get(model_name)
    if engine is None:
        with _engine_lock:
            engine = _engines.get(model_name)
            if engine is None:
                engine = _engines[model_name] = PersonIdentityEngine(model_name)
    return engine


# ── persistence / evidence ───────────────────────────────────────────────


def save_face_evidence(frame: np.ndarray, bbox, prefix: str = "face") -> str:
    """Save a padded face crop for human review. Returns a MEDIA-relative path."""
    try:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in bbox]
        pad = int(max(x2 - x1, y2 - y1) * 0.6)
        crop = frame[max(0, y1 - pad): min(h, y2 + pad), max(0, x1 - pad): min(w, x2 + pad)]
        if crop.size == 0:
            return ""
        day = timezone.localtime().strftime("%Y/%m/%d")
        rel = Path("identity") / "evidence" / day / f"{prefix}_{int(time.time() * 1000)}.jpg"
        abs_path = Path(settings.MEDIA_ROOT) / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(abs_path), crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return rel.as_posix()
    except Exception:
        logger.debug("[identity] Could not save evidence crop", exc_info=True)
        return ""


def record_decision(
    result: IdentityResult,
    *,
    camera=None,
    camera_name: str = "",
    track_id: int | None = None,
    journey_person=None,
    snapshot_path: str = "",
    policy: dict | None = None,
    attendance_action: str = "",
    attendance_id: int | None = None,
    review_status: str = ReviewStatus.NOT_REQUIRED,
) -> IdentityDecision:
    keep_probe = review_status == ReviewStatus.PENDING or result.outcome != DecisionOutcome.ACCEPTED
    return IdentityDecision.objects.create(
        source=result.source,
        camera=camera,
        camera_name=camera_name or (getattr(camera, "name", "") if camera else ""),
        track_id=track_id,
        journey_person=journey_person,
        staff_id=result.staff_id,
        outcome=result.outcome,
        confidence=result.confidence,
        face_similarity=result.face_similarity,
        second_best_similarity=result.second_best_similarity,
        face_quality=result.quality.score if result.quality else None,
        model_name=result.model_name,
        matched_entry_id=result.best_entry_id,
        factors={**result.factors, "quality_detail": result.quality.as_dict() if result.quality else None},
        reason=result.reason,
        probe_embedding=result.embedding if keep_probe else None,
        snapshot_path=snapshot_path,
        attendance_action=attendance_action,
        attendance_id=attendance_id,
        policy=policy or {},
        review_status=review_status,
    )


def identify_image(image: np.ndarray, *, source: str = "webcam", record: bool = True) -> dict:
    """Kiosk/webcam identification through the engine. Same shape as the legacy
    ``FaceEngine.identify_from_image`` so existing callers keep working."""
    from identity.services.quality import assess_face
    from recognition.services.face_engine import get_face_engine

    face_engine = get_face_engine()
    face, error = face_engine.get_single_face(image)
    if error:
        return {"matched": False, "message": error, "confidence": 0.0}

    quality = assess_face(image, face)
    result = get_identity_engine().identify(face.embedding, quality=quality, source=source)
    decision = None
    if record:
        try:
            decision = record_decision(
                result,
                camera_name="Webcam" if source == "webcam" else source,
                snapshot_path=save_face_evidence(image, face.bbox, source)
                if result.outcome != DecisionOutcome.ACCEPTED
                else "",
            )
        except Exception:
            logger.exception("[identity] Could not record %s decision", source)

    out = {
        "confidence": result.face_similarity,
        "identity_confidence": result.confidence,
        "outcome": result.outcome,
        "reason": result.reason,
        "decision_id": decision.pk if decision else None,
    }
    if result.accepted:
        out.update(
            matched=True,
            gallery_key=f"staff-{result.staff_id}",
            staff_id=result.staff_id,
            message="Face recognized",
        )
    elif result.outcome == DecisionOutcome.REVIEW:
        out.update(matched=False, message="Not confident enough — look straight at the camera and try again")
    else:
        out.update(matched=False, message="Unknown face")
    return out
