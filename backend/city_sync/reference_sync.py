"""Phase 6 — HQ-owned reference data → cities (read-only at city)."""

from __future__ import annotations

import logging
from datetime import datetime

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from city_sync.audit import audit
from city_sync.identity import identity_dict, is_city, is_hq, location_code
from city_sync.models import CityReferenceCache, HqReferenceItem, ReferenceCursor
from city_sync.worker import _load_api_key

logger = logging.getLogger(__name__)


def publish_reference(
    *,
    entity_type: str,
    entity_key: str,
    payload: dict,
    urgent: bool = False,
) -> HqReferenceItem:
    if not is_hq() and not getattr(settings, "DEBUG", False):
        raise PermissionError("Only HQ publishes reference data")
    item, created = HqReferenceItem.objects.get_or_create(
        entity_type=entity_type,
        entity_key=entity_key,
        defaults={"payload": payload, "version": 1, "urgent": urgent},
    )
    if not created:
        item.version = int(item.version or 0) + 1
        item.payload = payload
        item.urgent = urgent
        item.is_deleted = False
        item.save(update_fields=["version", "payload", "urgent", "is_deleted", "updated_at"])
    audit("reference_published", detail={"entity_type": entity_type, "entity_key": entity_key, "version": item.version})
    return item


def seed_default_reference() -> int:
    """Seed basic HQ config / role catalog for cities."""
    from users.models import User

    roles = [{"value": v, "label": lbl} for v, lbl in User.ROLE_CHOICES]
    publish_reference(
        entity_type="config",
        entity_key="role_catalog",
        payload={"roles": roles, "source": "hq"},
    )
    publish_reference(
        entity_type="config",
        entity_key="sync_policy",
        payload={
            "rpo_db_minutes": 15,
            "rpo_media_hours": 24,
            "rto_service_hours": 8,
            "forbid_hard_delete": True,
        },
    )
    publish_reference(
        entity_type="hotlist",
        entity_key="empty",
        payload={"items": [], "note": "Replace with operational hotlist"},
        urgent=False,
    )
    return HqReferenceItem.objects.count()


def reference_changes_since(since: datetime | None) -> list[dict]:
    qs = HqReferenceItem.objects.all().order_by("updated_at", "id")
    if since is not None:
        qs = qs.filter(updated_at__gt=since)
    out = []
    for item in qs[:2000]:
        out.append(
            {
                "entity_type": item.entity_type,
                "entity_key": item.entity_key,
                "version": item.version,
                "is_deleted": item.is_deleted,
                "payload": item.payload,
                "updated_at": item.updated_at.isoformat(),
                "urgent": item.urgent,
            }
        )
    return out


def pull_reference_once() -> dict:
    if not is_city():
        return {"skipped": True, "reason": "not_city"}
    if not getattr(settings, "SYNC_REFERENCE_ENABLED", True):
        return {"skipped": True, "reason": "disabled"}
    base = (getattr(settings, "HQ_SYNC_URL", "") or "").rstrip("/")
    if not base:
        return {"skipped": True, "reason": "no_url"}

    cursor, _ = ReferenceCursor.objects.get_or_create(pk=1)
    params = {}
    if cursor.since:
        params["since"] = cursor.since.isoformat()

    api_key = _load_api_key()
    resp = requests.get(
        f"{base}/reference",
        params=params,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}", "body": resp.text[:300]}
    data = resp.json() if resp.content else {}
    items = data.get("items") or []
    if not items:
        return {"applied": 0}

    latest = cursor.since
    with transaction.atomic():
        for item in items:
            updated = parse_datetime(str(item.get("updated_at") or "")) or timezone.now()
            if timezone.is_naive(updated):
                updated = timezone.make_aware(updated, timezone.get_current_timezone())
            CityReferenceCache.objects.update_or_create(
                entity_type=item["entity_type"],
                entity_key=item["entity_key"],
                defaults={
                    "version": int(item.get("version") or 1),
                    "is_deleted": bool(item.get("is_deleted")),
                    "payload": item.get("payload") or {},
                    "updated_at": updated,
                },
            )
            if latest is None or updated > latest:
                latest = updated
        cursor.since = latest
        cursor.last_success_at = timezone.now()
        cursor.item_count = CityReferenceCache.objects.filter(is_deleted=False).count()
        cursor.save(update_fields=["since", "last_success_at", "item_count"])

    audit("reference_pulled", detail={"applied": len(items), "location": location_code()})
    return {"applied": len(items), "cursor": latest.isoformat() if latest else None}
