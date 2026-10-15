"""HQ Sync API application logic (Phase 4) — idempotent, ordered, version-aware."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from city_sync.models import HqConflict, HqEventLog, HqReplicaRow, HqSyncCursor
from city_sync.outbox import payload_hash
from city_sync.syncable import LEGAL_ENTITY_TYPES

logger = logging.getLogger(__name__)

RESULT_APPLIED = "applied"
RESULT_DUPLICATE = "duplicate"
RESULT_STALE = "stale"
RESULT_REJECTED = "rejected"
RESULT_CONFLICT = "conflict"
RESULT_RETRY = "retry"  # schema not yet supported — city must not dead-letter


def _parse_updated_at(payload: dict) -> timezone.datetime:
    raw = payload.get("updated_at") or payload.get("created_at")
    if raw:
        dt = parse_datetime(str(raw)) if not hasattr(raw, "isoformat") else raw
        if dt is not None:
            if timezone.is_naive(dt):
                return timezone.make_aware(dt, timezone.get_current_timezone())
            return dt
    return timezone.now()


def apply_event(event: dict[str, Any], *, credential_location: str) -> dict[str, Any]:
    """
    Apply one Outbox event inside its own transaction.
    Returns {"event_id", "result", "detail"?}.
    """
    event_id = str(event.get("event_id") or "")
    loc = str(event.get("location_code") or "").strip().upper()
    entity_type = str(event.get("entity_type") or "").strip()
    entity_id_raw = event.get("entity_id")
    operation = str(event.get("operation") or "").strip()
    try:
        entity_version = int(event.get("entity_version") or 0)
        schema_ver = int(event.get("schema_version") or 1)
        city_seq = int(event.get("seq") or 0)
    except (TypeError, ValueError):
        return {"event_id": event_id, "result": RESULT_REJECTED, "detail": "invalid_numeric_fields"}

    if not event_id or not loc or not entity_type or not entity_id_raw:
        return {"event_id": event_id, "result": RESULT_REJECTED, "detail": "missing_required_fields"}
    if loc != credential_location.upper():
        return {"event_id": event_id, "result": RESULT_REJECTED, "detail": "location_mismatch"}
    if operation not in {"upsert", "tombstone"}:
        return {"event_id": event_id, "result": RESULT_REJECTED, "detail": "bad_operation"}

    max_schema = int(getattr(settings, "SYNC_SCHEMA_VERSION", 1))
    if schema_ver > max_schema:
        # City must retry without counting toward dead.
        return {
            "event_id": event_id,
            "result": RESULT_RETRY,
            "detail": "schema_unsupported",
            "schema_hold": True,
        }

    try:
        entity_id = entity_id_raw if isinstance(entity_id_raw, UUID) else UUID(str(entity_id_raw))
        event_uuid = UUID(str(event_id))
    except (TypeError, ValueError):
        return {"event_id": event_id, "result": RESULT_REJECTED, "detail": "bad_uuid"}

    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    ph = str(event.get("payload_hash") or "") or payload_hash(payload)

    with transaction.atomic():
        if HqEventLog.objects.filter(location_code=loc, event_id=event_uuid).exists():
            return {"event_id": event_id, "result": RESULT_DUPLICATE, "detail": "event_already_applied"}

        stored = (
            HqReplicaRow.objects.select_for_update()
            .filter(location_code=loc, entity_type=entity_type, entity_id=entity_id)
            .first()
        )

        result = RESULT_APPLIED
        detail = ""

        if stored is None:
            HqReplicaRow.objects.create(
                location_code=loc,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_version=entity_version,
                is_deleted=(operation == "tombstone"),
                payload=payload,
                payload_hash=ph,
                updated_at=_parse_updated_at(payload),
            )
            result = RESULT_APPLIED
        elif entity_version > stored.entity_version:
            # Legal entities: require contiguous version chain when configured.
            if entity_type in LEGAL_ENTITY_TYPES and entity_version != stored.entity_version + 1:
                HqConflict.objects.create(
                    location_code=loc,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    incoming_version=entity_version,
                    stored_version=stored.entity_version,
                    reason="version_gap",
                    payload=payload,
                )
                result = RESULT_CONFLICT
                detail = "version_gap"
            else:
                stored.entity_version = entity_version
                stored.is_deleted = operation == "tombstone"
                stored.payload = payload
                stored.payload_hash = ph
                stored.updated_at = _parse_updated_at(payload)
                stored.save(
                    update_fields=[
                        "entity_version",
                        "is_deleted",
                        "payload",
                        "payload_hash",
                        "updated_at",
                        "received_at",
                    ]
                )
                result = RESULT_APPLIED
        elif entity_version == stored.entity_version:
            if ph and stored.payload_hash and ph != stored.payload_hash:
                HqConflict.objects.create(
                    location_code=loc,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    incoming_version=entity_version,
                    stored_version=stored.entity_version,
                    reason="equal_version_payload_mismatch",
                    payload=payload,
                )
                result = RESULT_CONFLICT
                detail = "equal_version_payload_mismatch"
            else:
                result = RESULT_DUPLICATE
                detail = "same_version"
        else:
            # Incoming older than stored — do not overwrite.
            HqConflict.objects.create(
                location_code=loc,
                entity_type=entity_type,
                entity_id=entity_id,
                incoming_version=entity_version,
                stored_version=stored.entity_version,
                reason="stale",
                payload=payload,
            )
            result = RESULT_STALE
            detail = "older_version"

        # Always record receipt (including stale/conflict) so retries are idempotent.
        HqEventLog.objects.create(
            location_code=loc,
            city_seq=city_seq,
            event_id=event_uuid,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_version=entity_version,
            result=result,
            payload_hash=ph,
        )

        cursor, _ = HqSyncCursor.objects.select_for_update().get_or_create(
            location_code=loc,
            defaults={"last_seq_applied": 0},
        )
        if city_seq > cursor.last_seq_applied:
            cursor.last_seq_applied = city_seq
        cursor.last_success_at = timezone.now()
        cursor.last_event_at = timezone.now()
        cursor.save(update_fields=["last_seq_applied", "last_success_at", "last_event_at"])

    return {"event_id": event_id, "result": result, "detail": detail}


def apply_event_batch(events: list[dict], *, credential_location: str) -> list[dict]:
    """Process events in ascending city seq order (required for correct versions)."""

    def _seq_key(ev: dict) -> int:
        try:
            return int(ev.get("seq") or 0)
        except (TypeError, ValueError):
            return 0

    ordered = sorted(events, key=_seq_key)
    return [apply_event(ev, credential_location=credential_location) for ev in ordered]
