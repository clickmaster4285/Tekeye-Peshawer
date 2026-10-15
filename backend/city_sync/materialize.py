"""HQ: copy received city rows into the real business tables (Stage 3).

HqReplicaRow keeps the raw city payload. For entity types registered here, HQ also
writes a normal row (Staff, Attendance, ...) tagged with location_code=<city>, so the
existing pages and APIs show city data with no extra joins.

Rules:
- Rows are written with bulk_create / queryset.update, so no business signals run
  (no outbox, no ML push, no notifications) for copied city data.
- A city row that matches a row HQ already owns (same entity_id, or same CNIC for
  staff) is linked, never overwritten: Peshawar wins.
- City foreign keys are city pks; they are resolved through HqEntityMap. A parent
  that has not arrived yet becomes an HqPendingLink and is filled in later. When the
  link is required (NOT NULL), the whole row waits and is copied when the parent arrives.
- Links to tables that are not synced (cameras, user accounts, ...) are left empty.
- File fields point at the HQ copy of the media file once it is verified.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction

from city_sync.models import HqConflict, HqEntityMap, HqMediaObject, HqPendingLink
from city_sync.syncable import (
    MEDIA_URL_FIELDS,
    SYNC_MEDIA_FIELDS,
    SYNCED_ENTITY_TYPES,
    entity_type_for_model,
    media_url_to_path,
    resolve_model,
)

logger = logging.getLogger(__name__)

SYNC_FIELDS = {"entity_id", "location_code", "version", "is_deleted"}

# HqPendingLink.field prefix for a row that cannot be written until a required parent arrives.
WAITING_ROW = "__row__:"


class Materializer:
    entity_type: str = ""
    # fields forced to a value on HQ copies (e.g. city user accounts do not exist at HQ)
    overrides: dict[str, Any] = {}
    # unique fields cleared (and reported) when they clash with an existing HQ row
    clear_on_clash: tuple[str, ...] = ()
    # unique text fields prefixed with "<CITY>:" (and reported) when they clash
    prefix_on_clash: tuple[str, ...] = ()

    def __init__(self, entity_type: str = ""):
        if entity_type:
            self.entity_type = entity_type

    @property
    def model(self):
        return resolve_model(SYNCED_ENTITY_TYPES[self.entity_type])

    @property
    def foreign_keys(self) -> dict[str, str]:
        """FK field name -> entity_type of its parent, for parents that are synced too."""
        out = {}
        for field in self.model._meta.concrete_fields:
            if field.is_relation and field.name not in self.overrides:
                target = entity_type_for_model(field.related_model)
                if target:
                    out[field.name] = target
        return out

    def find_hq_owned(self, values: dict) -> Any | None:
        """An existing HQ row that is the same real-world record (Peshawar wins)."""
        return None

    def adjust(self, values: dict, payload: dict, loc: str) -> None:
        """Last changes to the HQ copy before it is written."""


class StaffMaterializer(Materializer):
    entity_type = "staff"
    overrides = {
        "user": None,
        # City face vectors must not enter Peshawar's recognition / ML matching.
        "face_embedding": None,
        "face_embeddings": [],
        "face_embedding_dim": 0,
        "face_embedding_model": "",
        "face_identity_label": "",
        "face_embedding_profile_key": "",
        "staff_photos": [],
        # Documents are not synced; city paths would point at missing files.
        "resume_file": None,
        "joining_letter_file": None,
        "contract_file": None,
        "id_proof_file": None,
        "tax_form_file": None,
        "certificates_file": None,
    }
    clear_on_clash = ("employee_id",)

    def find_hq_owned(self, values: dict):
        cnic = (values.get("cnic") or "").strip()
        if not cnic:
            return None
        return self.model.objects.filter(cnic=cnic).first()


class AttendanceMaterializer(Materializer):
    entity_type = "attendance"
    overrides = {"user": None, "video": None}
    # (staff, date) is unique: on a clash keep the record but leave staff empty.
    clear_on_clash = ("staff",)


class DetectionEventMaterializer(Materializer):
    entity_type = "detection_event"
    # City cameras are not at HQ; camera stays empty (city copies are skipped by HQ workers).
    overrides = {"camera": None, "person_identity_id": None}

    def adjust(self, values: dict, payload: dict, loc: str) -> None:
        from cameras.models import ClipStatus

        # Never let HQ's snapshot worker pick up a city event.
        values["clip_status"] = ClipStatus.READY if values.get("clip") else ClipStatus.SKIPPED
        values["source_camera_id"] = _int_or_none(payload.get("camera"))


class LeaveRequestMaterializer(Materializer):
    entity_type = "leave_request"
    overrides = {"approved_by": None}

    def adjust(self, values: dict, payload: dict, loc: str) -> None:
        values["leave_type_id"] = _hq_leave_type_id(payload.get("_ref_leave_type") or {})


class JourneyPersonMaterializer(Materializer):
    entity_type = "journey_person"
    # Embeddings are cleared so HQ's live matching can never pick a city person.
    overrides = {"face_embedding": [], "reid_embedding": [], "latest_camera": None}

    def adjust(self, values: dict, payload: dict, loc: str) -> None:
        # Every city numbers people from PJ-00001 too; "ABBOTTABAD:PJ-00042" keeps codes unique.
        code = str(values.get("code") or "")
        if code and not code.startswith(f"{loc}:"):
            values["code"] = f"{loc}:{code}"[:32]
        values["metadata"] = _with_source_camera(values.get("metadata"), payload.get("latest_camera"))


class JourneyEventMaterializer(Materializer):
    entity_type = "journey_event"
    overrides = {"camera": None, "track": None}
    # Plain id columns that point at other synced rows.
    id_links = {
        "detection_event_id": "detection_event",
        "zone_access_log_id": "zone_access_log",
        "attendance_id": "attendance",
    }

    def adjust(self, values: dict, payload: dict, loc: str) -> None:
        for field, target in self.id_links.items():
            values[field] = _local_pk(loc, target, payload.get(field))
        values["metadata"] = _with_source_camera(values.get("metadata"), payload.get("camera"))


class NoteSheetMaterializer(Materializer):
    entity_type = "note_sheet"
    # City user ids mean nothing at HQ.
    overrides = {"forward_to_user_id": None}
    # One note sheet per detention memo.
    clear_on_clash = ("detention_memo",)


class VisitorMaterializer(Materializer):
    entity_type = "visitor"
    overrides = {"registered_by_user_id": None}


class MemoDistributionMaterializer(Materializer):
    entity_type = "memo_distribution"
    # City camera ids mean nothing at HQ.
    overrides = {"camera_ids": []}


class DestructionAlertMaterializer(Materializer):
    entity_type = "destruction_alert"
    # City user ids would show the alert to unrelated HQ users.
    overrides = {"notified_user_ids": []}


class VmsListRecordMaterializer(Materializer):
    entity_type = "vms_list_record"
    # (module, record_id) is unique; a city id that HQ already uses becomes "ABBOTTABAD:<id>".
    prefix_on_clash = ("record_id",)


# Parents first, so a full-history push links children on arrival.
ENTITY_ORDER = [
    "staff",
    "attendance",
    "leave_request",
    "detection_event",
    "visitor",
    "vehicle",
    "security_alert",
    "zone_access_log",
    "journey_person",
    "journey_event",
    "vms_list_record",
    "detention_memo",
    "detention_goods_line",
    "detention_goods_image",
    "detention_attachment",
    "deposit_account_entry",
    "note_sheet",
    "note_sheet_item",
    "note_sheet_item_image",
    "note_sheet_attachment",
    "detention_assessment",
    "detention_assessment_attachment",
    "recovery_memo",
    "seizure_report",
    "warehouse_stock_item",
    "memo_distribution",
    "destruction_alert",
]

_CUSTOM = {
    m.entity_type: m
    for m in (
        StaffMaterializer(),
        AttendanceMaterializer(),
        DetectionEventMaterializer(),
        NoteSheetMaterializer(),
        VisitorMaterializer(),
        MemoDistributionMaterializer(),
        DestructionAlertMaterializer(),
        VmsListRecordMaterializer(),
        LeaveRequestMaterializer(),
        JourneyPersonMaterializer(),
        JourneyEventMaterializer(),
    )
}

MATERIALIZERS: dict[str, Materializer] = {t: _CUSTOM.get(t) or Materializer(t) for t in ENTITY_ORDER}


def _int_or_none(raw) -> int | None:
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _local_pk(loc: str, entity_type: str, origin_pk) -> int | None:
    """HQ pk of a copied city row, from the city's pk (None if it has not arrived)."""
    if origin_pk in (None, ""):
        return None
    link = HqEntityMap.objects.filter(location_code=loc, entity_type=entity_type, origin_pk=str(origin_pk)).first()
    return _int_or_none(link.local_pk) if link else None


def _with_source_camera(metadata, camera_id) -> dict:
    """Keep the city's camera id in metadata (its name comes from CityCamera)."""
    meta = dict(metadata) if isinstance(metadata, dict) else {}
    cam = _int_or_none(camera_id)
    if cam is not None:
        meta["source_camera_id"] = cam
    return meta


def _hq_leave_type_id(ref: dict) -> int:
    """HQ leave type with the city's code (or name); created inactive if HQ has none."""
    from users.models import LeaveType

    code = str(ref.get("code") or "").strip()
    name = str(ref.get("name") or "").strip()
    found = None
    if code:
        found = LeaveType.objects.filter(code__iexact=code).first()
    if found is None and name:
        found = LeaveType.objects.filter(name__iexact=name).first()
    if found is None:
        # Inactive: shown on city leave requests but not offered in HQ forms. code is unique.
        new_code = (code or re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "CITY_LEAVE")[:20]
        found, _ = LeaveType.objects.get_or_create(
            code=new_code, defaults={"name": (name or new_code)[:80], "is_active": False}
        )
    return found.pk


def _media_ref(entity_type: str, field: str, rel: str) -> str:
    """Value to store for a media field: the path, or a /media/ URL for URL-string fields."""
    if field in MEDIA_URL_FIELDS.get(entity_type, ()):
        return f"{settings.MEDIA_URL.rstrip('/')}/{rel}"
    return rel


def hq_media_relative_path(storage_path: str) -> str | None:
    """Storage path under MEDIA_ROOT as a FileField value, or None if outside it."""
    try:
        rel = Path(storage_path).resolve().relative_to(Path(settings.MEDIA_ROOT).resolve())
    except (ValueError, OSError):
        return None
    return str(rel).replace("\\", "/")


def _media_value(loc: str, entity_id: UUID, city_path: str | None) -> str | None:
    city_path = media_url_to_path(city_path or "")
    if not city_path:
        return None
    obj = (
        HqMediaObject.objects.filter(
            location_code=loc,
            record_entity_id=entity_id,
            source_path=city_path,
            status=HqMediaObject.STATUS_VERIFIED,
        )
        .order_by("-verified_at")
        .first()
    )
    return hq_media_relative_path(obj.storage_path) if obj else None


def _conflict(loc: str, entity_type: str, entity_id: UUID, version: int, reason: str, payload: dict) -> None:
    HqConflict.objects.create(
        location_code=loc,
        entity_type=entity_type,
        entity_id=entity_id,
        incoming_version=version,
        stored_version=version,
        reason=reason[:64],
        payload=payload,
    )


def _build_values(
    mat: Materializer, *, loc: str, entity_id: UUID, version: int, payload: dict, is_deleted: bool
) -> tuple[dict, dict[str, str], dict[str, str]]:
    """(field values for the HQ row, {fk field: missing parent origin pk}, same for NOT NULL fks)."""
    model = mat.model
    media_fields = set(SYNC_MEDIA_FIELDS.get(mat.entity_type) or [])
    foreign_keys = mat.foreign_keys
    values: dict[str, Any] = {}
    pending: dict[str, str] = {}
    required: dict[str, str] = {}

    for field in model._meta.concrete_fields:
        name = field.name
        if field.primary_key or name in SYNC_FIELDS:
            continue
        if name in mat.overrides:
            values[name] = mat.overrides[name]
            continue
        if name not in payload:
            continue
        raw = payload[name]
        if field.is_relation:
            target = foreign_keys.get(name)
            local = None
            if target and raw not in (None, ""):
                link = HqEntityMap.objects.filter(
                    location_code=loc, entity_type=target, origin_pk=str(raw)
                ).first()
                if link:
                    local = link.local_pk
                elif field.null:
                    pending[name] = str(raw)
                else:
                    required[name] = str(raw)
            values[field.attname] = local
            continue
        if name in media_fields:
            rel = _media_value(loc, entity_id, raw)
            if rel:
                values[name] = _media_ref(mat.entity_type, name, rel)
            else:
                # Not received yet; attach_media fills it in when the file arrives.
                values[name] = "" if name in MEDIA_URL_FIELDS.get(mat.entity_type, ()) else None
            continue
        if field.get_internal_type() in {"FileField", "ImageField"}:
            values[name] = None
            continue
        values[name] = field.to_python(raw) if raw is not None else None

    values.update(
        entity_id=entity_id,
        location_code=loc,
        version=version,
        is_deleted=is_deleted or bool(payload.get("is_deleted")),
    )
    mat.adjust(values, payload, loc)
    return values, pending, required


def _same_uuid_pk(model, payload: dict) -> dict:
    """UUID primary keys are kept, so plain-id references (e.g. detention_memo_id) still match."""
    pk = model._meta.pk
    if pk.get_internal_type() != "UUIDField":
        return {}
    try:
        value = UUID(str(payload.get("_pk") or ""))
    except ValueError:
        return {}
    if model._base_manager.filter(pk=value).exists():
        return {}
    return {pk.attname: value}


def _write(model, local_pk, values: dict, mat: Materializer, *, loc, entity_id, version, payload) -> Any:
    """Insert (local_pk None) or update one row; clear clashing unique fields if needed."""
    for attempt in range(2):
        try:
            with transaction.atomic():
                if local_pk is None:
                    # bulk_create: no save() signals for copied city rows.
                    obj = model(**values, **_same_uuid_pk(model, payload))
                    model._base_manager.bulk_create([obj])
                    local_pk = obj.pk
                else:
                    model._base_manager.filter(pk=local_pk).update(**values)
            break
        except IntegrityError:
            keys = [model._meta.get_field(f).attname for f in mat.clear_on_clash]
            cleared = [k for k in keys if values.get(k) not in (None, "")]
            prefixed = [k for k in mat.prefix_on_clash if values.get(k) and not str(values[k]).startswith(f"{loc}:")]
            if attempt or not (cleared or prefixed):
                raise
            for f in cleared:
                values[f] = None
            for f in prefixed:
                values[f] = f"{loc}:{values[f]}"[: model._meta.get_field(f).max_length]
            reason = "cleared_on_clash" if cleared else "prefixed_on_clash"
            _conflict(loc, mat.entity_type, entity_id, version, f"{reason}:{','.join(cleared + prefixed)}", payload)

    # auto_now / auto_now_add were stamped with "now"; keep the city's timestamps.
    stamps = {}
    for field in model._meta.concrete_fields:
        if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            raw = payload.get(field.name)
            if raw:
                stamps[field.name] = field.to_python(raw)
    if stamps:
        model._base_manager.filter(pk=local_pk).update(**stamps)
    return local_pk


def _resolve_pending(loc: str, entity_type: str, origin_pk: str, local_pk: str) -> None:
    """A parent arrived: fill in children that were waiting for it."""
    for link in HqPendingLink.objects.filter(
        location_code=loc, target_entity_type=entity_type, target_origin_pk=origin_pk
    ):
        if link.field.startswith(WAITING_ROW):
            link.delete()
            _copy_waiting_row(loc, link.entity_type, link.local_pk)
            continue
        mat = MATERIALIZERS.get(link.entity_type)
        if mat is not None:
            attname = mat.model._meta.get_field(link.field).attname
            try:
                with transaction.atomic():
                    mat.model._base_manager.filter(pk=link.local_pk).update(**{attname: local_pk})
            except IntegrityError:
                logger.warning(
                    "Could not link %s#%s.%s to %s#%s (unique clash)",
                    link.entity_type, link.local_pk, link.field, entity_type, local_pk,
                )
        link.delete()


def _copy_waiting_row(loc: str, entity_type: str, entity_id: str) -> None:
    """A required parent arrived: copy the row that was waiting for it (from its replica)."""
    from city_sync.models import HqReplicaRow

    row = HqReplicaRow.objects.filter(location_code=loc, entity_type=entity_type, entity_id=entity_id).first()
    if row is None:
        return
    with transaction.atomic():
        materialize_event(
            loc=loc,
            entity_type=entity_type,
            entity_id=row.entity_id,
            version=row.entity_version,
            payload=row.payload,
            tombstone=row.is_deleted,
        )


def materialize_event(
    *, loc: str, entity_type: str, entity_id: UUID, version: int, payload: dict, tombstone: bool
) -> str | None:
    """Copy one applied city event into its business table. Returns 'created' / 'updated' / 'linked'."""
    mat = MATERIALIZERS.get(entity_type)
    if mat is None:
        return None
    model = mat.model
    origin_pk = str(payload.get("_pk") or "")
    if not origin_pk:
        return None

    values, pending, required = _build_values(
        mat, loc=loc, entity_id=entity_id, version=version, payload=payload, is_deleted=tombstone
    )

    link = HqEntityMap.objects.filter(location_code=loc, entity_type=entity_type, entity_id=entity_id).first()
    if link is None:
        link = HqEntityMap.objects.filter(
            location_code=loc, entity_type=entity_type, origin_pk=origin_pk
        ).first()

    if link is not None and link.hq_owned:
        return "linked"  # Peshawar wins

    if link is None:
        owned = model._base_manager.filter(entity_id=entity_id).first() or mat.find_hq_owned(values)
        if owned is not None:
            HqEntityMap.objects.create(
                location_code=loc,
                entity_type=entity_type,
                origin_pk=origin_pk,
                entity_id=entity_id,
                local_pk=str(owned.pk),
                hq_owned=True,
            )
            _resolve_pending(loc, entity_type, origin_pk, str(owned.pk))
            return "linked"

    foreign_keys = mat.foreign_keys
    if required:
        if link is None:
            # A NOT NULL parent is missing: wait for it (the replica row keeps the data).
            waiting_key = str(entity_id)
            HqPendingLink.objects.filter(entity_type=entity_type, local_pk=waiting_key).delete()
            for field, target_origin in required.items():
                HqPendingLink.objects.create(
                    location_code=loc,
                    entity_type=entity_type,
                    local_pk=waiting_key,
                    field=f"{WAITING_ROW}{field}",
                    target_entity_type=foreign_keys[field],
                    target_origin_pk=target_origin,
                )
            return "waiting"
        # Already copied: keep its current parent.
        for field in required:
            values.pop(model._meta.get_field(field).attname, None)

    local_pk = _write(
        model,
        link.local_pk if link else None,
        values,
        mat,
        loc=loc,
        entity_id=entity_id,
        version=version,
        payload=payload,
    )
    if link is None:
        HqEntityMap.objects.create(
            location_code=loc,
            entity_type=entity_type,
            origin_pk=origin_pk,
            entity_id=entity_id,
            local_pk=str(local_pk),
        )
    elif link.origin_pk != origin_pk:
        link.origin_pk = origin_pk
        link.save(update_fields=["origin_pk", "updated_at"])

    HqPendingLink.objects.filter(entity_type=entity_type, local_pk__in=[str(local_pk), str(entity_id)]).delete()
    for field, target_origin in pending.items():
        HqPendingLink.objects.create(
            location_code=loc,
            entity_type=entity_type,
            local_pk=str(local_pk),
            field=field,
            target_entity_type=foreign_keys[field],
            target_origin_pk=target_origin,
        )
    _resolve_pending(loc, entity_type, origin_pk, str(local_pk))
    return "updated" if link else "created"


def attach_media(media: HqMediaObject) -> bool:
    """A media file was verified: point the copied record's file field at it."""
    mat = MATERIALIZERS.get(media.record_entity_type)
    if mat is None or not media.record_entity_id or not media.source_path:
        return False
    link = HqEntityMap.objects.filter(
        location_code=media.location_code,
        entity_type=media.record_entity_type,
        entity_id=media.record_entity_id,
        hq_owned=False,
    ).first()
    rel = hq_media_relative_path(media.storage_path)
    if link is None or rel is None:
        return False
    from city_sync.models import HqReplicaRow

    replica = HqReplicaRow.objects.filter(
        location_code=media.location_code,
        entity_type=media.record_entity_type,
        entity_id=media.record_entity_id,
    ).first()
    payload = replica.payload if replica else {}
    updates = {
        name: _media_ref(media.record_entity_type, name, rel)
        for name in SYNC_MEDIA_FIELDS.get(media.record_entity_type) or []
        if media_url_to_path(str(payload.get(name) or "")) == media.source_path
    }
    if not updates:
        return False
    mat.model._base_manager.filter(pk=link.local_pk).update(**updates)
    return True


def rematerialize(*, loc: str = "", entity_type: str = "") -> int:
    """Re-copy every stored replica (e.g. after enabling a new entity type). HQ only."""
    from city_sync.models import HqReplicaRow

    types = [t for t in ENTITY_ORDER if not entity_type or t == entity_type]
    done = 0
    for t in types:
        qs = HqReplicaRow.objects.filter(entity_type=t).order_by("received_at")
        if loc:
            qs = qs.filter(location_code=loc.upper())
        for row in qs.iterator(chunk_size=200):
            try:
                with transaction.atomic():
                    materialize_event(
                        loc=row.location_code,
                        entity_type=t,
                        entity_id=row.entity_id,
                        version=row.entity_version,
                        payload=row.payload,
                        tombstone=row.is_deleted,
                    )
                done += 1
            except Exception:  # noqa: BLE001
                logger.exception("rematerialize failed %s/%s/%s", row.location_code, t, row.entity_id)
    for media in HqMediaObject.objects.filter(status=HqMediaObject.STATUS_VERIFIED).exclude(source_path=""):
        attach_media(media)
    return done
