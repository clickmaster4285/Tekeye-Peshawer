"""Attendance is decided here — separately from recognition.

    Ahmed recognized (IdentityResult)
          ↓ identity accepted?            REVIEW  → human confirms identity first
          ↓ attendance camera?            no      → journey sighting only
          ↓ allowed zone?                 no      → journey sighting only
          ↓ inside shift window?          no      → human review
          ↓ employee mode                 MANUAL  → log only, HR marks by hand
                                          ASSISTED→ check-in waits for approval
                                          AUTOMATIC → mark
          ↓ already marked? (AttendanceDecisionEngine: check-in / last-seen check-out)
    Attendance

Direction (entering vs leaving) needs the journey pipeline and is reported as
"not evaluated" until that phase lands.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from identity.models import (
    DecisionOutcome,
    IdentityDecision,
    IdentityProfile,
    RecognitionMode,
    ReviewStatus,
)

logger = logging.getLogger(__name__)


def default_mode() -> str:
    mode = str(getattr(settings, "IDENTITY_DEFAULT_RECOGNITION_MODE", RecognitionMode.ASSISTED)).lower()
    return mode if mode in RecognitionMode.values else RecognitionMode.ASSISTED


def get_profile(staff) -> IdentityProfile:
    profile, _ = IdentityProfile.objects.get_or_create(
        staff=staff, defaults={"recognition_mode": default_mode()}
    )
    return profile


def _attendance_zones() -> set[str]:
    raw = getattr(settings, "IDENTITY_ATTENDANCE_ZONES", "") or ""
    return {z.strip().lower() for z in str(raw).split(",") if z.strip()}


def _in_shift_window(staff, now: datetime) -> tuple[bool | None, str]:
    start, end = staff.work_shift_start, staff.work_shift_end
    if not start or not end:
        return None, "no shift configured"
    local = timezone.localtime(now)
    day = local.date()
    tz = local.tzinfo
    early = timedelta(hours=float(getattr(settings, "IDENTITY_SHIFT_EARLY_HOURS", 2)))
    late = timedelta(hours=float(getattr(settings, "IDENTITY_SHIFT_LATE_HOURS", 4)))
    win_start = datetime.combine(day, start, tzinfo=tz) - early
    win_end = datetime.combine(day, end, tzinfo=tz) + late
    if end <= start:  # overnight shift
        win_end += timedelta(days=1)
    ok = win_start <= local <= win_end or win_start <= local + timedelta(days=1) <= win_end
    return ok, f"window {win_start:%H:%M}–{win_end:%H:%M}"


_unknown_recorded_at: dict[int, float] = {}
_review_recorded_at: dict[tuple, float] = {}


def should_record_unknown(camera_id: int | None) -> bool:
    """Unknown faces are kept as observations, but at most one per camera per interval."""
    key = camera_id or 0
    interval = float(getattr(settings, "IDENTITY_UNKNOWN_RECORD_INTERVAL_SEC", 20))
    now = time.monotonic()
    if now - _unknown_recorded_at.get(key, 0.0) < interval:
        return False
    _unknown_recorded_at[key] = now
    return True


def _review_throttled(staff_id: int, camera_id: int | None) -> bool:
    key = (staff_id, camera_id or 0)
    interval = float(getattr(settings, "IDENTITY_REVIEW_RECORD_INTERVAL_SEC", 300))
    now = time.monotonic()
    if now - _review_recorded_at.get(key, 0.0) < interval:
        return True
    _review_recorded_at[key] = now
    return False


def _pending_checkin_exists(staff, now: datetime) -> bool:
    return IdentityDecision.objects.filter(
        staff=staff,
        review_status=ReviewStatus.PENDING,
        policy__action="assisted_pending",
        created_at__date=timezone.localdate(now),
    ).exists()


def evaluate(result, *, staff, camera, source: str, now: datetime | None = None) -> dict:
    """Decide what to do with a recognition. Does not write anything.

    Returns {"apply": bool, "review": bool, "persist": bool, "action": str,
             "message": str, "gates": [...]}.
    """
    from users.attendance_service import _camera_allows_attendance
    from users.models import Attendance

    now = now or timezone.now()
    gates: list[dict] = []

    def gate(name: str, passed: bool | None, detail: str = ""):
        gates.append({"gate": name, "passed": passed, "detail": detail})

    def out(action: str, message: str, *, apply=False, review=False, persist=True) -> dict:
        return {
            "apply": apply,
            "review": review,
            "persist": persist,
            "action": action,
            "message": message,
            "gates": gates,
        }

    # 1. Identity
    if result.outcome == DecisionOutcome.UNKNOWN:
        gate("identity", False, result.reason)
        return out("unknown", "Unknown person", persist=should_record_unknown(getattr(camera, "pk", None)))
    if result.outcome == DecisionOutcome.REVIEW:
        gate("identity", False, result.reason)
        if staff is None or _review_throttled(staff.pk, getattr(camera, "pk", None)):
            return out("review_throttled", "Identity uncertain (already queued recently)", persist=False)
        return out("identity_review", "Identity uncertain — queued for human review", review=True)
    gate("identity", True, result.reason)

    # 2. Attendance camera
    if source == "webcam" or camera is None:
        gate("attendance_camera", True, "attendance kiosk" if source == "webcam" else "attendance worker camera")
    elif _camera_allows_attendance(camera):
        gate("attendance_camera", True, ", ".join(camera.purpose_list()))
    else:
        gate("attendance_camera", False, "camera purpose is not attendance")
        return out("not_attendance_camera", "Recognized (sighting only — not an attendance camera)")

    # 3. Zone
    zones = _attendance_zones()
    if zones and camera is not None:
        cam_zone = (camera.zone or "").strip().lower()
        if cam_zone not in zones:
            gate("zone", False, f"camera zone '{camera.zone}' not in attendance zones")
            return out("wrong_zone", "Recognized (sighting only — not an attendance zone)")
        gate("zone", True, camera.zone)
    else:
        gate("zone", None, "no attendance zones configured")

    # 4. Direction — requires Person Journey (next phase).
    gate("direction", None, "not evaluated yet")

    # 5. Schedule
    in_shift, detail = _in_shift_window(staff, now)
    gate("schedule", in_shift, detail)
    if in_shift is False:
        return out("outside_shift", "Recognized outside shift window — queued for review", review=True)

    # 6. Mode
    profile = get_profile(staff)
    mode = profile.recognition_mode
    gate("mode", mode == RecognitionMode.AUTOMATIC, mode)
    if mode == RecognitionMode.MANUAL:
        return out("manual_mode", "Recognized — manual mode, HR marks attendance")
    if mode == RecognitionMode.ASSISTED:
        record = (
            Attendance.objects.filter(date=timezone.localdate(now))
            .filter(**({"user": staff.user} if staff.user_id else {"staff": staff}))
            .first()
        )
        if record is None or record.check_in is None:
            if _pending_checkin_exists(staff, now):
                return out("pending_exists", "Check-in already awaiting approval", persist=False)
            return out("assisted_pending", "Check-in suggested — awaiting approval", review=True)
        # Check-in was human-approved today; last-seen check-out updates are safe.
        gate("mode", True, "assisted: check-in approved, updating last seen")

    # 7. Already marked / check-in vs check-out — AttendanceDecisionEngine.
    return out("mark", "Marking attendance", apply=True)


def apply(
    result,
    *,
    staff,
    camera,
    source: str,
    now: datetime | None = None,
    evidence_fn=None,
    **decision_kwargs,
) -> dict:
    """evaluate() + mark attendance + write the audit record. Returns the policy dict,
    plus "decision" (IdentityDecision | None) and "record" (Attendance | None).

    ``evidence_fn`` saves a face crop and returns its media path; it only runs
    when the decision is actually persisted."""
    from identity.services.engine import record_decision
    from users.attendance_service import AttendanceDecisionEngine
    from users.models import Attendance

    policy = evaluate(result, staff=staff, camera=camera, source=source, now=now)
    record = None
    action = policy["action"]
    if policy["apply"]:
        att_source = Attendance.SOURCE_WEBCAM if source == "webcam" else Attendance.SOURCE_CCTV
        decision = AttendanceDecisionEngine.process_recognition(
            staff=staff, confidence=result.face_similarity, source=att_source, now=now
        )
        record = decision["record"]
        action = decision["action"]
        policy["message"] = decision["message"]
    policy["attendance_action"] = action if policy["apply"] else ""

    saved = None
    if policy["persist"]:
        if evidence_fn is not None and not decision_kwargs.get("snapshot_path"):
            decision_kwargs["snapshot_path"] = evidence_fn() or ""
        saved = record_decision(
            result,
            camera=camera,
            policy={k: policy[k] for k in ("action", "message", "gates")},
            attendance_action=policy["attendance_action"],
            attendance_id=record.pk if record else None,
            review_status=ReviewStatus.PENDING if policy["review"] else ReviewStatus.NOT_REQUIRED,
            **decision_kwargs,
        )
    policy["decision"] = saved
    policy["record"] = record
    return policy


# ── human review ─────────────────────────────────────────────────────────


def approve_decision(
    decision: IdentityDecision,
    *,
    user,
    staff=None,
    mark_attendance: bool | None = None,
    add_to_gallery: bool = True,
    note: str = "",
) -> dict:
    """Human confirms who this is. Optionally marks attendance at the original time,
    adds the live face to the employee's gallery (the learning loop) and links the
    journey person to the employee.

    ``mark_attendance`` defaults to True except for journey sightings, which come
    from any camera, not attendance cameras."""
    from identity.services.gallery import INSIGHTFACE_MODEL, add_live_entry
    from users.attendance_service import AttendanceDecisionEngine
    from users.models import Attendance

    staff = staff or decision.staff
    if staff is None:
        raise ValueError("Choose which employee this is.")

    if mark_attendance is None:
        mark_attendance = decision.source not in ("journey", "cluster")
    result: dict = {"attendance": None, "gallery": None, "journey": None}
    with transaction.atomic():
        corrected = decision.staff_id is not None and decision.staff_id != staff.pk
        if corrected:
            IdentityProfile.objects.filter(staff_id=decision.staff_id).update(
                rejected_matches=F("rejected_matches") + 1
            )
        get_profile(staff)
        IdentityProfile.objects.filter(staff=staff).update(confirmed_matches=F("confirmed_matches") + 1)

        if mark_attendance:
            when = decision.created_at
            existing = (
                Attendance.objects.filter(date=timezone.localdate(when))
                .filter(**({"user": staff.user} if staff.user_id else {"staff": staff}))
                .first()
            )
            covered = (
                existing is not None
                and existing.check_in is not None
                and existing.check_in <= when
                and existing.check_out is not None
                and when <= existing.check_out
            )
            if covered:
                result["attendance"] = {"action": "already_covered", "record_id": existing.pk}
            else:
                att_source = Attendance.SOURCE_WEBCAM if decision.source == "webcam" else Attendance.SOURCE_CCTV
                outcome = AttendanceDecisionEngine.process_recognition(
                    staff=staff, confidence=decision.face_similarity, source=att_source, now=when
                )
                rec = outcome["record"]
                result["attendance"] = {"action": outcome["action"], "record_id": rec.pk if rec else None}
                decision.attendance_action = outcome["action"]
                decision.attendance_id = rec.pk if rec else None

        if decision.source == "cluster":
            from identity.services.clustering import approve_cluster

            result["journey"] = approve_cluster(decision, staff=staff, user=user, add_to_gallery=add_to_gallery)
            add_to_gallery = False  # approve_cluster learned from the cluster's own observations
        elif decision.journey_person_id:
            from person_journey.services import merge_person_to_staff

            linked = merge_person_to_staff(
                decision.journey_person,
                staff,
                match_score=decision.face_similarity,
                reason=f"approved by {getattr(user, 'username', 'reviewer')}",
            )
            result["journey"] = {"person_code": linked.code, "person_uuid": str(linked.uuid)}

        decision.staff = staff
        decision.review_status = ReviewStatus.APPROVED
        decision.reviewed_by = user
        decision.reviewed_at = timezone.now()
        decision.review_note = note
        decision.save()

    if add_to_gallery and decision.probe_embedding:
        entry, message = add_live_entry(
            staff=staff,
            embedding=decision.probe_embedding,
            quality=(decision.factors or {}).get("quality_detail") or {"score": decision.face_quality},
            camera=decision.camera,
            image_path=decision.snapshot_path,
            decision=decision,
            approved_by=user,
            model_name=decision.model_name or INSIGHTFACE_MODEL,
        )
        result["gallery"] = {"added": entry is not None, "entry_id": entry.pk if entry else None, "message": message}
    return result


def reject_decision(decision: IdentityDecision, *, user, note: str = "") -> None:
    if decision.source == "cluster":
        from identity.services.clustering import reject_cluster_candidate

        reject_cluster_candidate(decision)
    if decision.staff_id:
        IdentityProfile.objects.filter(staff_id=decision.staff_id).update(
            rejected_matches=F("rejected_matches") + 1
        )
    decision.review_status = ReviewStatus.REJECTED
    decision.reviewed_by = user
    decision.reviewed_at = timezone.now()
    decision.review_note = note
    decision.save(update_fields=["review_status", "reviewed_by", "reviewed_at", "review_note"])


def automatic_readiness(profile: IdentityProfile, gallery_size: int) -> dict:
    """Recommend (never switch) automatic mode."""
    need_gallery = int(getattr(settings, "IDENTITY_AUTO_MIN_GALLERY", 8))
    need_confirmed = int(getattr(settings, "IDENTITY_AUTO_MIN_CONFIRMED", 10))
    max_reject_rate = float(getattr(settings, "IDENTITY_AUTO_MAX_REJECT_RATE", 0.05))
    reviewed = profile.confirmed_matches + profile.rejected_matches
    reject_rate = profile.rejected_matches / reviewed if reviewed else 0.0
    checks = {
        "gallery_size": {"value": gallery_size, "required": need_gallery, "ok": gallery_size >= need_gallery},
        "confirmed_matches": {
            "value": profile.confirmed_matches,
            "required": need_confirmed,
            "ok": profile.confirmed_matches >= need_confirmed,
        },
        "reject_rate": {
            "value": round(reject_rate, 3),
            "max": max_reject_rate,
            "ok": reject_rate <= max_reject_rate,
        },
    }
    return {"ready": all(c["ok"] for c in checks.values()), "checks": checks}
