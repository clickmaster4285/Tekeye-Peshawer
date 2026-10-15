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
  that has not arrived yet becomes an HqPendingLink and is filled in later.
- File fields point at the HQ copy of the media file once it is verified.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction

from city_sync.models import HqConflict, HqEntityMap, HqMediaObject, HqPendingLink
from city_sync.syncable import SYNC_MEDIA_FIELDS, SYNCED_ENTITY_TYPES, resolve_model

logger = logging.getLogger(__name__)

SYNC_FIELDS = {"entity_id", "location_code", "version", "is_deleted"}


class Materializer:
    entity_type: str = ""
    # field name -> entity_type of the parent (resolved through HqEntityMap)
    foreign_keys: dict[str, str] = {}
    # fields forced to a value on HQ copies (e.g. city user accounts do not exist at HQ)
    overrides: dict[str, Any] = {}
    # unique fields cleared (and reported) when they clash with an existing HQ row
    clear_on_clash: tuple[str, ...] = ()

    @property
    def model(self):
        return resolve_model(SYNCED_ENTITY_TYPES[self.entity_type])

    def find_hq_owned(self, values: dict) -> Any | None:
        """An existing HQ row that is the same real-world record (Peshawar wins)."""
        return None


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
    foreign_keys = {"staff": "staff"}
    overrides = {"user": None, "video": None}
    # (staff, date) is unique: on a clash keep the record but leave staff empty.
    clear_on_clash = ("staff",)


MATERIALIZERS: dict[str, Materializer] = {
    m.entity_type: m for m in (StaffMaterializer(), AttendanceMaterializer())
}

# Parents first, so a full-history push links children on arrival.
ENTITY_ORDER = ["staff", "attendance"]


def hq_media_relative_path(storage_path: str) -> str | None:
    """Storage path under MEDIA_ROOT as a FileField value, or None if outside it."""
    try:
        rel = Path(storage_path).resolve().relative_to(Path(settings.MEDIA_ROOT).resolve())
    except (ValueError, OSError):
        return None
    return str(rel).replace("\\", "/")


def _media_value(loc: str, entity_id: UUID, city_path: str | None) -> str | None:
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
) -> tuple[dict, dict[str, str]]:
    """(field values for the HQ row, {fk field: parent origin pk still missing})."""
    model = mat.model
    media_fields = set(SYNC_MEDIA_FIELDS.get(mat.entity_type) or [])
    values: dict[str, Any] = {}
    pending: dict[str, str] = {}

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
            target = mat.foreign_keys.get(name)
            local = None
            if target and raw not in (None, ""):
                link = HqEntityMap.objects.filter(
                    location_code=loc, entity_type=target, origin_pk=str(raw)
                ).first()
                if link:
                    local = link.local_pk
                else:
                    pending[name] = str(raw)
            values[field.attname] = local
            continue
        if name in media_fields:
            values[name] = _media_value(loc, entity_id, raw)
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
    return values, pending


def _write(model, local_pk, values: dict, mat: Materializer, *, loc, entity_id, version, payload) -> Any:
    """Insert (local_pk None) or update one row; clear clashing unique fields if needed."""
    for attempt in range(2):
        try:
            with transaction.atomic():
                if local_pk is None:
                    # bulk_create: no save() signals for copied city rows.
                    obj = model(**values)
                    model.objects.bulk_create([obj])
                    local_pk = obj.pk
                else:
                    model.objects.filter(pk=local_pk).update(**values)
            break
        except IntegrityError:
            keys = [model._meta.get_field(f).attname for f in mat.clear_on_clash]
            cleared = [k for k in keys if values.get(k) not in (None, "")]
            if attempt or not cleared:
                raise
            for f in cleared:
                values[f] = None
            _conflict(loc, mat.entity_type, entity_id, version, f"cleared_on_clash:{','.join(cleared)}", payload)

    # auto_now / auto_now_add were stamped with "now"; keep the city's timestamps.
    stamps = {}
    for field in model._meta.concrete_fields:
        if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            raw = payload.get(field.name)
            if raw:
                stamps[field.name] = field.to_python(raw)
    if stamps:
        model.objects.filter(pk=local_pk).update(**stamps)
    return local_pk


def _resolve_pending(loc: str, entity_type: str, origin_pk: str, local_pk: str) -> None:
    """A parent arrived: fill in children that were waiting for it."""
    for link in HqPendingLink.objects.filter(
        location_code=loc, target_entity_type=entity_type, target_origin_pk=origin_pk
    ):
        mat = MATERIALIZERS.get(link.entity_type)
        if mat is not None:
            attname = mat.model._meta.get_field(link.field).attname
            try:
                with transaction.atomic():
                    mat.model.objects.filter(pk=link.local_pk).update(**{attname: local_pk})
            except IntegrityError:
                logger.warning(
                    "Could not link %s#%s.%s to %s#%s (unique clash)",
                    link.entity_type, link.local_pk, link.field, entity_type, local_pk,
                )
        link.delete()


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

    values, pending = _build_values(
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
        owned = model.objects.filter(entity_id=entity_id).first() or mat.find_hq_owned(values)
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

    HqPendingLink.objects.filter(entity_type=entity_type, local_pk=str(local_pk)).delete()
    for field, target_origin in pending.items():
        HqPendingLink.objects.create(
            location_code=loc,
            entity_type=entity_type,
            local_pk=str(local_pk),
            field=field,
            target_entity_type=mat.foreign_keys[field],
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
        name: rel
        for name in SYNC_MEDIA_FIELDS.get(media.record_entity_type) or []
        if payload.get(name) == media.source_path
    }
    if not updates:
        return False
    mat.model.objects.filter(pk=link.local_pk).update(**updates)
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
