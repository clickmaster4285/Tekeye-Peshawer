"""City Outbox worker — push pending events to HQ (Phase 3)."""

from __future__ import annotations

import logging
import random
from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from city_sync.identity import identity_dict, is_city, location_code
from city_sync.models import SyncOutbox

logger = logging.getLogger(__name__)

BACKOFF_SECONDS = (5, 15, 60, 300, 900)  # then cap 15m


def _backoff(attempts: int) -> timedelta:
    idx = min(max(attempts - 1, 0), len(BACKOFF_SECONDS) - 1)
    base = BACKOFF_SECONDS[idx] if attempts <= len(BACKOFF_SECONDS) else 900
    jitter = base * random.uniform(0, 0.2)
    return timedelta(seconds=base + jitter)


def _load_api_key() -> str:
    path = getattr(settings, "SYNC_API_KEY_FILE", "") or ""
    if path:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError as exc:
            raise RuntimeError(f"Cannot read SYNC_API_KEY_FILE={path}: {exc}") from exc
    key = getattr(settings, "SYNC_API_KEY", "") or ""
    if not key:
        # Fall back to map entry for this location
        raw = getattr(settings, "SYNC_API_KEYS", "") or ""
        loc = location_code()
        for part in str(raw).split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip().upper() == loc:
                    return v.strip()
    return key.strip()


def recover_stuck_sending(*, older_than_seconds: int = 300) -> int:
    cutoff = timezone.now() - timedelta(seconds=older_than_seconds)
    return SyncOutbox.objects.filter(
        status=SyncOutbox.STATUS_SENDING, next_attempt_at__lt=cutoff
    ).update(status=SyncOutbox.STATUS_PENDING, next_attempt_at=timezone.now())


def claim_batch(*, limit: int, min_age_seconds: float) -> list[SyncOutbox]:
    min_created = timezone.now() - timedelta(seconds=min_age_seconds)
    with transaction.atomic():
        qs = (
            SyncOutbox.objects.select_for_update(skip_locked=True)
            .filter(
                status=SyncOutbox.STATUS_PENDING,
                next_attempt_at__lte=timezone.now(),
                created_at__lte=min_created,
            )
            .order_by("seq")[:limit]
        )
        rows = list(qs)
        for row in rows:
            row.status = SyncOutbox.STATUS_SENDING
            row.save(update_fields=["status"])
        return rows


def _serialize_event(row: SyncOutbox) -> dict:
    return {
        "seq": row.seq,
        "event_id": str(row.event_id),
        "location_code": row.location_code,
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id),
        "operation": row.operation,
        "entity_version": row.entity_version,
        "schema_version": row.schema_version,
        "payload": row.payload,
        "payload_hash": row.payload_hash,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _apply_hq_results(rows: list[SyncOutbox], results: list[dict]) -> None:
    by_id = {str(r.event_id): r for r in rows}
    max_attempts = int(getattr(settings, "OUTBOX_MAX_ATTEMPTS_BEFORE_DEAD", 20))
    now = timezone.now()

    for item in results:
        event_id = str(item.get("event_id") or "")
        row = by_id.get(event_id)
        if not row:
            continue
        result = str(item.get("result") or "").lower()
        detail = str(item.get("detail") or "")

        if result in {"applied", "duplicate", "stale", "conflict"}:
            row.status = SyncOutbox.STATUS_DONE
            row.done_at = now
            row.last_error = detail
            row.schema_hold = False
            row.save(update_fields=["status", "done_at", "last_error", "schema_hold"])
            continue

        if result == "rejected":
            row.status = SyncOutbox.STATUS_DEAD
            row.last_error = detail or "rejected"
            row.done_at = now
            row.save(update_fields=["status", "last_error", "done_at"])
            logger.error("Outbox event %s rejected: %s", event_id, detail)
            continue

        if result == "retry" or item.get("schema_hold"):
            # Do NOT increment toward dead.
            row.status = SyncOutbox.STATUS_PENDING
            row.schema_hold = True
            row.next_attempt_at = now + timedelta(minutes=5)
            row.last_error = detail or "schema_hold"
            row.save(update_fields=["status", "schema_hold", "next_attempt_at", "last_error"])
            continue

        # Unknown / retryable
        row.attempts = int(row.attempts or 0) + 1
        row.last_error = detail or result or "retry"
        if row.attempts >= max_attempts and not row.schema_hold:
            row.status = SyncOutbox.STATUS_DEAD
            row.done_at = now
            logger.error("Outbox event %s marked dead after %s attempts", event_id, row.attempts)
        else:
            row.status = SyncOutbox.STATUS_PENDING
            row.next_attempt_at = now + _backoff(row.attempts)
        row.save(update_fields=["attempts", "last_error", "status", "done_at", "next_attempt_at"])


def _requeue_network_failure(rows: list[SyncOutbox], error: str) -> None:
    now = timezone.now()
    max_attempts = int(getattr(settings, "OUTBOX_MAX_ATTEMPTS_BEFORE_DEAD", 20))
    for row in rows:
        row.attempts = int(row.attempts or 0) + 1
        row.last_error = error[:2000]
        if row.attempts >= max_attempts and not row.schema_hold:
            row.status = SyncOutbox.STATUS_DEAD
            row.done_at = now
        else:
            row.status = SyncOutbox.STATUS_PENDING
            row.next_attempt_at = now + _backoff(row.attempts)
        row.save(update_fields=["attempts", "last_error", "status", "done_at", "next_attempt_at"])


def push_once() -> dict:
    """One poll cycle. Returns stats."""
    if not is_city():
        return {"skipped": True, "reason": "not_city"}

    hq_url = (getattr(settings, "HQ_SYNC_URL", "") or "").rstrip("/")
    if not hq_url:
        return {"skipped": True, "reason": "HQ_SYNC_URL empty"}

    recover_stuck_sending()
    batch_size = int(getattr(settings, "OUTBOX_BATCH_SIZE", 200))
    min_age = float(getattr(settings, "OUTBOX_MIN_AGE_SECONDS", 2))
    rows = claim_batch(limit=batch_size, min_age_seconds=min_age)
    if not rows:
        return {"claimed": 0}

    payload = {
        "location_code": location_code(),
        "node": identity_dict(),
        "events": [_serialize_event(r) for r in rows],
    }
    api_key = _load_api_key()
    timeout = float(getattr(settings, "OUTBOX_HTTP_TIMEOUT", 30))
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "X-CIIS-Location": location_code(),
    }
    url = f"{hq_url}/events"
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code >= 500:
            _requeue_network_failure(rows, f"HTTP {resp.status_code}: {resp.text[:500]}")
            return {"claimed": len(rows), "error": f"http_{resp.status_code}"}
        if resp.status_code in {401, 403}:
            _requeue_network_failure(rows, f"auth_failed HTTP {resp.status_code}")
            return {"claimed": len(rows), "error": "auth_failed"}
        data = resp.json() if resp.content else {}
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            _requeue_network_failure(rows, f"bad_response HTTP {resp.status_code}")
            return {"claimed": len(rows), "error": "bad_response"}
        _apply_hq_results(rows, results)
        return {"claimed": len(rows), "results": len(results)}
    except requests.RequestException as exc:
        _requeue_network_failure(rows, str(exc))
        return {"claimed": len(rows), "error": str(exc)}


def outbox_stats() -> dict:
    pending = SyncOutbox.objects.filter(status=SyncOutbox.STATUS_PENDING).count()
    dead = SyncOutbox.objects.filter(status=SyncOutbox.STATUS_DEAD).count()
    oldest = (
        SyncOutbox.objects.filter(status=SyncOutbox.STATUS_PENDING)
        .order_by("created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    age = int((timezone.now() - oldest).total_seconds()) if oldest else 0
    return {
        "pending_outbox": pending,
        "dead_outbox": dead,
        "oldest_pending_age_sec": age,
    }


def send_heartbeat() -> dict:
    if not is_city():
        return {"skipped": True}
    hq_url = (getattr(settings, "HQ_SYNC_URL", "") or "").rstrip("/")
    if not hq_url:
        return {"skipped": True, "reason": "no_url"}

    from city_sync.media_sync import media_stats
    from city_sync.models import BackupRecord, SyncOutbox

    last_backup = (
        BackupRecord.objects.filter(location_code=location_code(), success=True)
        .order_by("-completed_at")
        .values_list("completed_at", flat=True)
        .first()
    )
    last_biz = (
        SyncOutbox.objects.filter(location_code=location_code())
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    disk_percent = None
    try:
        import shutil

        usage = shutil.disk_usage(str(getattr(settings, "MEDIA_ROOT", ".") or "."))
        disk_percent = round((usage.used / usage.total) * 100.0, 2) if usage.total else None
    except Exception:  # noqa: BLE001
        disk_percent = None

    body = {
        **identity_dict(),
        **outbox_stats(),
        **media_stats(),
        "disk_percent": disk_percent,
        "last_backup_at": last_backup.isoformat() if last_backup else None,
        "last_business_event_at": last_biz.isoformat() if last_biz else None,
    }
    api_key = _load_api_key()
    try:
        resp = requests.post(
            f"{hq_url}/heartbeat",
            json=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=10,
        )
        return {"status_code": resp.status_code}
    except requests.RequestException as exc:
        return {"error": str(exc)}
