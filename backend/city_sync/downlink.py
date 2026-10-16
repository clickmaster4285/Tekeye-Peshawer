"""HQ -> city HR changes (Stage 4).

Peshawar enrolls staff (and their faces) for a city, edits city staff, transfers staff
between cities, corrects attendance and files leave. Each change becomes an HqDownlink
row for the target city. The heartbeat tells the city the newest seq; the city pulls
everything after its cursor, applies it in order (Peshawar wins), downloads the photo
files and acks. Applied rows are saved normally at the city, so the city's Outbox echoes
them back and HQ links the echo to its own row (same entity_id).

Face data is sent only for staff whose face was enrolled at HQ; editing a city's own
staff at HQ never wipes the face data the city enrolled itself.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import requests
from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from city_sync.identity import is_city, is_hq, location_code
from city_sync.models import CityControlState, HqDownlink, SyncSite
from city_sync.outbox import model_to_payload

logger = logging.getLogger(__name__)

DOWNLINK_TYPES = ("staff", "attendance", "leave_request")

# Never sent: city logins are created at the city; documents are not synced.
STAFF_SKIP = {
    "id",
    "user",
    "resume_file",
    "joining_letter_file",
    "contract_file",
    "id_proof_file",
    "tax_form_file",
    "certificates_file",
}
STAFF_FACE_FIELDS = (
    "face_embedding",
    "face_embedding_dim",
    "face_embedding_model",
    "face_identity_label",
    "face_embedding_profile_key",
    "face_embeddings",
    "staff_photos",
    "profile_image",
)
ENROLLMENT_FIELDS = ("total_images", "is_enrolled", "is_trained", "model_version", "embedding", "embeddings")
# Fields the receiving city always sets itself.
SYNC_FIELDS = ("location_code", "version", "is_deleted")


# ---------------------------------------------------------------------------
# HQ side
# ---------------------------------------------------------------------------


def is_city_code(code: str | None) -> bool:
    """A location that is not this HQ (records with it are delivered to that city)."""
    code = (code or "").strip().upper()
    return bool(code) and code != location_code()


def location_choices() -> list[str]:
    """Codes a record can be assigned to: this HQ and every connected city."""
    return [location_code(), *SyncSite.objects.values_list("location_code", flat=True)]


def _media_path(value) -> str:
    name = getattr(value, "name", value) or ""
    return str(name).replace("\\", "/").lstrip("/")


def _hq_has_face(staff) -> bool:
    from recognition.models import FaceEnrollment

    if staff.face_embeddings or staff.face_embedding:
        return True
    return FaceEnrollment.objects.filter(staff=staff, embedding__isnull=False).exists()


def staff_downlink(staff) -> tuple[dict, list[dict]]:
    """(payload, media) for one staff member. Face fields only when HQ holds the face."""
    payload = {k: v for k, v in model_to_payload(staff).items() if k not in STAFF_SKIP}
    media: list[dict] = []
    if _hq_has_face(staff):
        for path in staff.staff_photos or []:
            if _media_path(path):
                media.append({"field": "staff_photos", "path": _media_path(path)})
        if staff.profile_image:
            media.append({"field": "profile_image", "path": _media_path(staff.profile_image)})
        from recognition.models import FaceEnrollment

        enrollment = FaceEnrollment.objects.filter(staff=staff).first()
        if enrollment is not None:
            payload["_face_enrollment"] = {f: getattr(enrollment, f) for f in ENROLLMENT_FIELDS}
            if enrollment.profile_image:
                path = _media_path(enrollment.profile_image)
                payload["_face_enrollment"]["profile_image"] = path
                media.append({"field": "enrollment.profile_image", "path": path})
    else:
        for name in STAFF_FACE_FIELDS:
            payload.pop(name, None)
    return payload, media


def _queue(loc: str, entity_type: str, obj, operation: str, payload: dict, media: list | None = None, by: str = ""):
    return HqDownlink.objects.create(
        location_code=loc.upper(),
        entity_type=entity_type,
        entity_id=obj.entity_id,
        operation=operation,
        payload=payload,
        media=media or [],
        created_by=by[:150],
    )


def queue_staff(staff, *, by: str = "") -> HqDownlink | None:
    if not is_hq() or not is_city_code(staff.location_code) or not staff.entity_id:
        return None
    payload, media = staff_downlink(staff)
    return _queue(staff.location_code, "staff", staff, HqDownlink.OP_UPSERT, payload, media, by)


def queue_transfer_out(staff, old_location: str, *, by: str = "") -> HqDownlink | None:
    """Tell the old city the staff member left: keep the record, drop its face data."""
    if not is_hq() or not is_city_code(old_location) or not staff.entity_id:
        return None
    payload = {
        "entity_id": str(staff.entity_id),
        "cnic": staff.cnic,
        "transferred_to": staff.location_code or location_code(),
    }
    return _queue(old_location, "staff", staff, HqDownlink.OP_RETIRE, payload, by=by)


def _staff_ref(obj) -> str | None:
    staff = getattr(obj, "staff", None)
    return str(staff.entity_id) if staff is not None and staff.entity_id else None


def queue_attendance(att, *, by: str = "") -> HqDownlink | None:
    if not is_hq() or not is_city_code(att.location_code) or not att.entity_id:
        return None
    payload = model_to_payload(att)
    payload.pop("user", None)
    payload.pop("video", None)
    payload["_staff_entity_id"] = _staff_ref(att)
    media = [{"field": "image", "path": _media_path(att.image)}] if att.image else []
    return _queue(att.location_code, "attendance", att, HqDownlink.OP_UPSERT, payload, media, by)


def queue_leave_request(req, *, by: str = "") -> HqDownlink | None:
    if not is_hq() or not is_city_code(req.location_code) or not req.entity_id:
        return None
    payload = model_to_payload(req)
    payload.pop("approved_by", None)
    payload["_staff_entity_id"] = _staff_ref(req)
    return _queue(req.location_code, "leave_request", req, HqDownlink.OP_UPSERT, payload, by=by)


# One delivery per record per transaction, built from the saved state at commit time.
_scheduled = threading.local()


def _schedule(key: tuple, build) -> None:
    keys = getattr(_scheduled, "keys", None)
    if keys is None:
        keys = _scheduled.keys = set()
    if key in keys:
        return
    keys.add(key)

    def run():
        keys.discard(key)
        try:
            build()
        except Exception:  # noqa: BLE001
            logger.exception("Could not queue HQ change %s for the city", key)

    transaction.on_commit(run)


def on_hq_pre_save(sender, instance, **kwargs) -> None:
    """HQ: remember a staff member's location before the save (transfer detection)."""
    if not is_hq() or kwargs.get("raw") or getattr(instance, "_from_city", False):
        return
    if sender._meta.label == "users.Staff" and instance.pk:
        instance._downlink_old_location = (
            sender._base_manager.filter(pk=instance.pk).values_list("location_code", flat=True).first() or ""
        )


def on_hq_post_save(sender, instance, **kwargs) -> None:
    """HQ: queue edits of city HR records (and HQ enrollments for a city) for that city."""
    if not is_hq() or kwargs.get("raw") or getattr(instance, "_from_city", False):
        return
    label = sender._meta.label
    by = getattr(instance, "_downlink_by", "")
    if label == "users.Staff":
        old = getattr(instance, "_downlink_old_location", "")
        if old and old != instance.location_code:
            queue_transfer_out(instance, old, by=by)
        if is_city_code(instance.location_code):
            _schedule(("staff", instance.pk), lambda: _queue_saved_staff(instance.pk, by))
    elif label == "recognition.FaceEnrollment":
        staff = instance.staff
        if is_city_code(staff.location_code):
            _schedule(("staff", staff.pk), lambda: _queue_saved_staff(staff.pk, by))
    elif label == "users.Attendance" and is_city_code(instance.location_code):
        _schedule(("attendance", instance.pk), lambda: queue_attendance(type(instance)._base_manager.get(pk=instance.pk), by=by))
    elif label == "users.LeaveRequest" and is_city_code(instance.location_code):
        _schedule(("leave_request", instance.pk), lambda: queue_leave_request(type(instance)._base_manager.get(pk=instance.pk), by=by))


def _queue_saved_staff(pk, by: str) -> None:
    from users.models import Staff

    staff = Staff._base_manager.filter(pk=pk).first()
    if staff is not None:
        queue_staff(staff, by=by)


def default_location_for(instance) -> str:
    """HQ: attendance / leave filed for a city's staff member belongs to that city."""
    if not is_hq() or instance.pk:
        return ""
    staff = getattr(instance, "staff", None) if getattr(instance, "staff_id", None) else None
    code = getattr(staff, "location_code", "") if staff is not None else ""
    return code if is_city_code(code) else ""


def latest_seq(loc: str) -> int:
    row = HqDownlink.objects.filter(location_code=loc.upper()).order_by("-seq").values_list("seq", flat=True).first()
    return int(row or 0)


def items_after(loc: str, after: int, limit: int = 100) -> list[dict]:
    rows = HqDownlink.objects.filter(location_code=loc.upper(), seq__gt=after).order_by("seq")[:limit]
    return [
        {
            "seq": r.seq,
            "entity_type": r.entity_type,
            "entity_id": str(r.entity_id),
            "operation": r.operation,
            "payload": r.payload,
            "media": r.media,
        }
        for r in rows
    ]


def record_acks(loc: str, results: list) -> int:
    done = 0
    for res in results:
        if not isinstance(res, dict):
            continue
        ok = res.get("status") == HqDownlink.STATUS_APPLIED
        done += HqDownlink.objects.filter(location_code=loc.upper(), seq=res.get("seq")).update(
            status=HqDownlink.STATUS_APPLIED if ok else HqDownlink.STATUS_FAILED,
            error="" if ok else str(res.get("error") or "")[:2000],
            applied_at=timezone.now() if ok else None,
        )
    return done


def media_allowed(loc: str, seq, path: str) -> bool:
    """A city may download only files listed on one of its own downlink rows."""
    row = HqDownlink.objects.filter(location_code=loc.upper(), seq=seq).values_list("media", flat=True).first()
    return bool(row) and any(isinstance(m, dict) and m.get("path") == path for m in row)


# ---------------------------------------------------------------------------
# City side
# ---------------------------------------------------------------------------


def _hq_get(path: str, **params):
    from city_sync.worker import _load_api_key

    base = (getattr(settings, "HQ_SYNC_URL", "") or "").rstrip("/")
    return requests.get(
        f"{base}/{path}", params=params, headers={"Authorization": f"Bearer {_load_api_key()}"}, timeout=60
    )


def _hq_post(path: str, body: dict):
    from city_sync.worker import _load_api_key

    base = (getattr(settings, "HQ_SYNC_URL", "") or "").rstrip("/")
    return requests.post(
        f"{base}/{path}", json=body, headers={"Authorization": f"Bearer {_load_api_key()}"}, timeout=30
    )


def _download(seq: int, path: str) -> None:
    """Fetch one file from HQ into the same MEDIA_ROOT-relative path."""
    if not path or default_storage.exists(path):
        return
    resp = _hq_get("downlink/media", seq=seq, path=path)
    resp.raise_for_status()
    target = Path(settings.MEDIA_ROOT) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(resp.content)


def _set_fields(obj, payload: dict, skip: set[str]) -> None:
    for field in obj._meta.concrete_fields:
        name = field.name
        if field.primary_key or field.is_relation or name in skip or name in SYNC_FIELDS or name not in payload:
            continue
        raw = payload[name]
        if field.get_internal_type() in {"FileField", "ImageField"}:
            setattr(obj, name, raw or None)
        else:
            setattr(obj, name, field.to_python(raw) if raw is not None else None)


def _find_staff(entity_id, cnic: str | None = None):
    from users.models import Staff

    staff = Staff._base_manager.filter(entity_id=entity_id).first() if entity_id else None
    if staff is None and cnic:
        staff = Staff._base_manager.filter(cnic=cnic).first()
    return staff


def _refresh_faces() -> None:
    try:
        from recognition.services.gallery_index import invalidate_gallery

        invalidate_gallery()
    except Exception:  # noqa: BLE001
        logger.exception("Could not refresh the attendance face gallery")
    try:
        from ml.face_sync import push_face_embeddings_to_ml

        push_face_embeddings_to_ml()
    except Exception:  # noqa: BLE001
        logger.exception("Could not reload faces in the ML service")


def _apply_staff(item: dict) -> bool:
    """Create or update the staff member. Returns True when face data changed."""
    from recognition.models import FaceEnrollment
    from users.models import Staff

    payload = item["payload"]
    staff = _find_staff(item["entity_id"], payload.get("cnic"))
    if staff is None:
        staff = Staff(entity_id=item["entity_id"])
    _set_fields(staff, payload, STAFF_SKIP | {"entity_id"})
    staff.location_code = location_code()
    staff.is_deleted = False
    staff.save()

    face = payload.get("_face_enrollment")
    if face is None:
        return "face_embeddings" in payload
    enrollment = FaceEnrollment.objects.filter(staff=staff).first() or FaceEnrollment(
        staff=staff, dataset_folder=f"hq/{staff.entity_id}"
    )
    for name in ENROLLMENT_FIELDS:
        if name in face:
            setattr(enrollment, name, face[name])
    enrollment.profile_image = face.get("profile_image") or None
    enrollment.save()
    return True


def _apply_retire(item: dict) -> bool:
    from recognition.models import FaceEnrollment

    payload = item["payload"]
    staff = _find_staff(item["entity_id"], payload.get("cnic"))
    if staff is None:
        return False
    staff.transferred_to = str(payload.get("transferred_to") or "")[:255]
    staff.face_embedding = None
    staff.face_embeddings = []
    staff.face_identity_label = ""
    staff.face_embedding_profile_key = ""
    staff.staff_photos = []
    staff.save()
    FaceEnrollment.objects.filter(staff=staff).update(is_trained=False, embedding=None, embeddings=[])
    return True


def _apply_attendance(item: dict) -> bool:
    from users.models import Attendance

    payload = item["payload"]
    staff = _find_staff(payload.get("_staff_entity_id"))
    if staff is None:
        raise ValueError("staff for this attendance is not at this city yet")
    date = Attendance._meta.get_field("date").to_python(payload.get("date"))
    att = (
        Attendance._base_manager.filter(entity_id=item["entity_id"]).first()
        or Attendance._base_manager.filter(staff=staff, date=date).first()
        or Attendance(entity_id=item["entity_id"])
    )
    _set_fields(att, payload, {"entity_id"})
    att.staff = staff
    att.location_code = location_code()
    att.is_deleted = False
    att.save()
    return False


def _apply_leave_request(item: dict) -> bool:
    from users.models import LeaveRequest, LeaveType

    payload = item["payload"]
    staff = _find_staff(payload.get("_staff_entity_id"))
    if staff is None:
        raise ValueError("staff for this leave request is not at this city yet")
    ref = payload.get("_ref_leave_type") or {}
    code = str(ref.get("code") or "").strip()
    leave_type = LeaveType.objects.filter(code__iexact=code).first() if code else None
    if leave_type is None:
        leave_type, _ = LeaveType.objects.get_or_create(
            code=(code or "HQ_LEAVE")[:20], defaults={"name": str(ref.get("name") or code or "HQ leave")[:80]}
        )
    req = LeaveRequest._base_manager.filter(entity_id=item["entity_id"]).first() or LeaveRequest(
        entity_id=item["entity_id"]
    )
    _set_fields(req, payload, {"entity_id"})
    req.staff = staff
    req.leave_type = leave_type
    req.location_code = location_code()
    req.is_deleted = False
    req.save()
    return False


APPLIERS = {
    ("staff", HqDownlink.OP_UPSERT): _apply_staff,
    ("staff", HqDownlink.OP_RETIRE): _apply_retire,
    ("attendance", HqDownlink.OP_UPSERT): _apply_attendance,
    ("leave_request", HqDownlink.OP_UPSERT): _apply_leave_request,
}


def apply_item(item: dict) -> bool:
    """Apply one HQ change (files first, then the row). Returns True when faces changed."""
    applier = APPLIERS.get((item.get("entity_type"), item.get("operation")))
    if applier is None:
        raise ValueError(f"unknown downlink {item.get('entity_type')}/{item.get('operation')}")
    for media in item.get("media") or []:
        _download(item["seq"], media.get("path") or "")
    with transaction.atomic():
        return applier(item)


def pull_downlink(target_seq: int) -> dict[str, Any]:
    """City: fetch and apply HQ changes up to target_seq; ack each one."""
    if not is_city():
        return {"skipped": "not_city"}
    state = CityControlState.load()
    applied = failed = 0
    faces_changed = False
    while state.downlink_seq < target_seq:
        resp = _hq_get("downlink", after=state.downlink_seq)
        resp.raise_for_status()
        items = (resp.json() or {}).get("items") or []
        if not items:
            break
        results = []
        for item in items:
            try:
                faces_changed |= bool(apply_item(item))
                results.append({"seq": item["seq"], "status": HqDownlink.STATUS_APPLIED})
                applied += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("Downlink #%s failed", item.get("seq"))
                results.append({"seq": item["seq"], "status": HqDownlink.STATUS_FAILED, "error": str(exc)})
                failed += 1
            # Move on either way: HQ shows the failure and can send the record again.
            state.downlink_seq = int(item["seq"])
            state.save(update_fields=["downlink_seq", "updated_at"])
        try:
            _hq_post("downlink/ack", {"results": results})
        except requests.RequestException:
            logger.warning("Downlink ack failed; HQ will show these as pending")
    if faces_changed:
        _refresh_faces()
    return {"applied": applied, "failed": failed, "cursor": state.downlink_seq}
