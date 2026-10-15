"""Phase 10 — city↔HQ reconciliation summaries for all synced entity types."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta

from django.apps import apps
from django.utils import timezone

from city_sync.audit import audit
from city_sync.identity import location_code
from city_sync.models import HqCityStatus, HqReplicaRow, ReconcileReport
from city_sync.syncable import SYNCED_ENTITY_TYPES, resolve_model

logger = logging.getLogger(__name__)


def _hash_pairs(pairs: list[tuple[str, int]]) -> str:
    raw = "|".join(f"{eid}:{ver}" for eid, ver in pairs)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def city_entity_summary(entity_type: str, day: date | None = None) -> tuple[int, str, list[str]]:
    label = SYNCED_ENTITY_TYPES.get(entity_type)
    if not label:
        return 0, "", []
    try:
        model = resolve_model(label)
    except LookupError:
        return 0, "", []

    qs = model.objects.all()
    if hasattr(model, "is_deleted"):
        qs = qs.filter(is_deleted=False)
    qs = qs.exclude(entity_id__isnull=True)

    # Optional day filter when model has date/created_at
    if day is not None:
        if hasattr(model, "date"):
            qs = qs.filter(date=day)
        elif hasattr(model, "created_at"):
            qs = qs.filter(created_at__date=day)

    rows = qs.order_by("entity_id").values_list("entity_id", "version")
    pairs = [(str(eid), int(ver or 1)) for eid, ver in rows]
    return len(pairs), _hash_pairs(pairs), [p[0] for p in pairs]


def hq_entity_summary(loc: str, entity_type: str, day: date | None = None) -> tuple[int, str, list[str]]:
    qs = HqReplicaRow.objects.filter(
        location_code=loc.upper(),
        entity_type=entity_type,
        is_deleted=False,
    )
    pairs: list[tuple[str, int]] = []
    for row in qs.order_by("entity_id"):
        if day is not None:
            payload = row.payload or {}
            payload_date = str(payload.get("date") or "")[:10]
            created = str(payload.get("created_at") or "")[:10]
            if payload_date and payload_date != day.isoformat():
                if not created or created != day.isoformat():
                    continue
            elif created and created != day.isoformat() and not payload_date:
                continue
        pairs.append((str(row.entity_id), int(row.entity_version)))
    pairs.sort(key=lambda x: x[0])
    return len(pairs), _hash_pairs(pairs), [p[0] for p in pairs]


def run_reconcile_for_location(loc: str, day: date | None = None) -> list[ReconcileReport]:
    day = day or (timezone.localdate() - timedelta(days=1))
    reports: list[ReconcileReport] = []
    total_mismatch = 0
    all_ok = True

    for entity_type in sorted(SYNCED_ENTITY_TYPES.keys()):
        city_count, city_hash, city_ids = city_entity_summary(entity_type, day=None)
        hq_count, hq_hash, hq_ids = hq_entity_summary(loc, entity_type, day=None)
        # Skip empty-empty (entity never used)
        if city_count == 0 and hq_count == 0:
            continue
        ok = city_count == hq_count and city_hash == hq_hash
        missing = sorted(set(city_ids) - set(hq_ids))
        extra = sorted(set(hq_ids) - set(city_ids))
        total_mismatch += len(missing) + len(extra)
        all_ok = all_ok and ok
        reports.append(
            ReconcileReport.objects.create(
                location_code=loc.upper(),
                day=day,
                entity_type=entity_type,
                city_count=city_count,
                hq_count=hq_count,
                city_hash=city_hash,
                hq_hash=hq_hash,
                ok=ok,
                mismatched_ids={"missing_at_hq": missing[:200], "extra_at_hq": extra[:200]},
            )
        )

    status, _ = HqCityStatus.objects.get_or_create(location_code=loc.upper())
    status.last_reconcile_at = timezone.now()
    status.last_reconcile_ok = all_ok
    status.reconcile_mismatch_count = total_mismatch
    status.save(update_fields=["last_reconcile_at", "last_reconcile_ok", "reconcile_mismatch_count"])
    audit(
        "reconcile_finished",
        detail={"location": loc, "day": day.isoformat(), "ok": all_ok, "mismatch": total_mismatch},
        loc=loc,
    )
    return reports


def run_reconcile_all(day: date | None = None) -> list[ReconcileReport]:
    locs = set(HqReplicaRow.objects.values_list("location_code", flat=True))
    locs |= set(HqCityStatus.objects.values_list("location_code", flat=True))
    if not locs:
        locs = {location_code()} if location_code() else set()
    out: list[ReconcileReport] = []
    for loc in sorted(locs):
        out.extend(run_reconcile_for_location(loc, day=day))
    return out
