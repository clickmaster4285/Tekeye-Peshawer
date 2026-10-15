"""Enqueue Outbox rows in the same DB transaction as the business write."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.duration import duration_iso_string

from city_sync.identity import location_code, schema_version
from city_sync.models import SyncOutbox

logger = logging.getLogger(__name__)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(obj, "total_seconds"):
        try:
            return duration_iso_string(obj)
        except Exception:  # noqa: BLE001
            pass
    return str(obj)


def payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=_json_default, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def model_to_payload(instance) -> dict:
    """Serialize concrete field values (no binary file contents)."""
    data: dict[str, Any] = {}
    for field in instance._meta.concrete_fields:
        name = field.name
        if name in {"password"}:
            continue
        value = getattr(instance, field.attname if hasattr(field, "attname") else name)
        # File/Image fields → store path only
        if field.get_internal_type() in {"FileField", "ImageField"}:
            data[name] = value.name if value else None
            continue
        data[name] = value
    data["_model"] = f"{instance._meta.app_label}.{instance._meta.object_name}"
    data["_pk"] = instance.pk
    return json.loads(json.dumps(data, default=_json_default))


def enqueue_outbox(
    *,
    entity_type: str,
    entity_id: UUID | str,
    entity_version: int,
    operation: str,
    payload: dict,
    location: str | None = None,
) -> SyncOutbox:
    """
    Insert an Outbox row. Must be called inside the same transaction.atomic()
    as the business write (or from post_save during that write).
    """
    loc = (location or location_code()).strip().upper()
    if not loc:
        raise RuntimeError("Cannot enqueue Outbox without LOCATION_CODE")
    if operation not in {SyncOutbox.OP_UPSERT, SyncOutbox.OP_TOMBSTONE}:
        raise ValueError(f"Invalid operation {operation}")

    body = dict(payload)
    ph = payload_hash(body)
    row = SyncOutbox.objects.create(
        location_code=loc,
        entity_type=entity_type,
        entity_id=entity_id if isinstance(entity_id, UUID) else UUID(str(entity_id)),
        operation=operation,
        entity_version=int(entity_version),
        schema_version=schema_version(),
        payload=body,
        payload_hash=ph,
        status=SyncOutbox.STATUS_PENDING,
        next_attempt_at=timezone.now(),
    )
    logger.debug(
        "Outbox enqueued seq=%s type=%s id=%s v=%s op=%s",
        row.seq,
        entity_type,
        entity_id,
        entity_version,
        operation,
    )
    return row


def enqueue_from_instance(instance, *, entity_type: str, created: bool = False) -> SyncOutbox | None:
    """Bump is handled by caller/pre_save; this only writes Outbox."""
    if not getattr(settings, "SYNC_OUTBOX_ENABLED", True):
        return None
    # Cities produce Outbox; HQ does not push its own city writes for other cities.
    from city_sync.identity import is_city

    if not is_city():
        return None
    if not getattr(instance, "entity_id", None):
        return None

    operation = (
        SyncOutbox.OP_TOMBSTONE
        if getattr(instance, "is_deleted", False)
        else SyncOutbox.OP_UPSERT
    )
    return enqueue_outbox(
        entity_type=entity_type,
        entity_id=instance.entity_id,
        entity_version=int(getattr(instance, "version", 1) or 1),
        operation=operation,
        payload=model_to_payload(instance),
        location=getattr(instance, "location_code", None) or location_code(),
    )


@transaction.atomic
def soft_delete_instance(instance) -> None:
    """Preferred delete path for synced models — tombstone via save()+signal."""
    instance.is_deleted = True
    instance.save()
