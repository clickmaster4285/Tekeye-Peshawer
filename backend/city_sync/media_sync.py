"""Phase 5 — city media queue + HQ chunked upload / verify."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from uuid import UUID

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from city_sync.audit import audit
from city_sync.identity import identity_dict, is_city, is_hq, location_code
from city_sync.models import HqMediaObject, MediaQueue, SyncOutbox
from city_sync.worker import _load_api_key

logger = logging.getLogger(__name__)


def sha256_file(path: str | Path, chunk: int = 1024 * 1024) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
            size += len(block)
    return h.hexdigest(), size


def enqueue_media_file(
    *,
    absolute_or_media_path: str,
    record_entity_type: str = "",
    record_entity_id: UUID | str | None = None,
    priority: int = MediaQueue.PRIORITY_ROUTINE,
    wait_outbox_done: bool = True,
) -> MediaQueue | None:
    """Register a local file for upload to HQ (city only)."""
    if not is_city() or not getattr(settings, "SYNC_MEDIA_ENABLED", True):
        return None

    path = Path(absolute_or_media_path)
    if not path.is_file():
        # Try MEDIA_ROOT-relative
        media_root = Path(getattr(settings, "MEDIA_ROOT", "") or "")
        candidate = media_root / absolute_or_media_path
        if candidate.is_file():
            path = candidate
        else:
            logger.warning("enqueue_media_file: missing file %s", absolute_or_media_path)
            return None

    digest, size = sha256_file(path)
    rel = str(absolute_or_media_path)
    if str(path).startswith(str(getattr(settings, "MEDIA_ROOT", ""))):
        try:
            rel = str(path.relative_to(settings.MEDIA_ROOT)).replace("\\", "/")
        except Exception:  # noqa: BLE001
            rel = str(path)

    row = MediaQueue.objects.create(
        location_code=location_code(),
        record_entity_type=record_entity_type or "",
        record_entity_id=UUID(str(record_entity_id)) if record_entity_id else None,
        path=rel,
        sha256=digest,
        size_bytes=size,
        priority=priority,
        wait_outbox_done=wait_outbox_done,
    )
    audit("media_enqueued", detail={"media_id": str(row.media_id), "path": rel, "sha256": digest})
    return row


def _resolve_local_path(rel: str) -> Path | None:
    p = Path(rel)
    if p.is_file():
        return p
    media_root = Path(getattr(settings, "MEDIA_ROOT", "") or "")
    candidate = media_root / rel
    return candidate if candidate.is_file() else None


def _outbox_ready(row: MediaQueue) -> bool:
    if not row.wait_outbox_done or not row.record_entity_id:
        return True
    pending = SyncOutbox.objects.filter(
        entity_id=row.record_entity_id,
        status__in=[SyncOutbox.STATUS_PENDING, SyncOutbox.STATUS_SENDING],
    ).exists()
    return not pending


def _hq_media_base() -> str:
    return (getattr(settings, "HQ_SYNC_URL", "") or "").rstrip("/")


def push_media_once(*, limit: int = 5) -> dict:
    if not is_city():
        return {"skipped": True, "reason": "not_city"}
    if not getattr(settings, "SYNC_MEDIA_ENABLED", True):
        return {"skipped": True, "reason": "disabled"}
    base = _hq_media_base()
    if not base:
        return {"skipped": True, "reason": "no_url"}

    chunk_size = int(getattr(settings, "SYNC_MEDIA_CHUNK_SIZE", 4 * 1024 * 1024))
    max_attempts = int(getattr(settings, "SYNC_MEDIA_MAX_ATTEMPTS", 30))
    api_key = _load_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}

    qs = (
        MediaQueue.objects.filter(status__in=[MediaQueue.STATUS_PENDING, MediaQueue.STATUS_UPLOADING])
        .order_by("priority", "created_at")[:limit]
    )
    stats = {"attempted": 0, "verified": 0, "failed": 0, "waiting_outbox": 0}

    for row in qs:
        if not _outbox_ready(row):
            stats["waiting_outbox"] += 1
            continue
        local = _resolve_local_path(row.path)
        if local is None:
            row.status = MediaQueue.STATUS_FAILED
            row.last_error = "local_file_missing"
            row.attempts += 1
            row.save(update_fields=["status", "last_error", "attempts"])
            stats["failed"] += 1
            continue

        stats["attempted"] += 1
        row.status = MediaQueue.STATUS_UPLOADING
        row.save(update_fields=["status"])
        try:
            init = requests.post(
                f"{base}/media/init",
                json={
                    "media_id": str(row.media_id),
                    "location_code": row.location_code,
                    "sha256": row.sha256,
                    "size_bytes": row.size_bytes,
                    "record_entity_type": row.record_entity_type,
                    "record_entity_id": str(row.record_entity_id) if row.record_entity_id else None,
                },
                headers=headers,
                timeout=30,
            )
            if init.status_code >= 400:
                raise RuntimeError(f"init HTTP {init.status_code}: {init.text[:300]}")
            offset = int((init.json() or {}).get("offset") or 0)

            with open(local, "rb") as fh:
                fh.seek(offset)
                pos = offset
                while pos < row.size_bytes:
                    chunk = fh.read(chunk_size)
                    if not chunk:
                        break
                    put = requests.put(
                        f"{base}/media/{row.media_id}/chunk",
                        data=chunk,
                        headers={
                            **headers,
                            "Content-Type": "application/octet-stream",
                            "X-CIIS-Offset": str(pos),
                            "X-CIIS-Location": row.location_code,
                        },
                        timeout=120,
                    )
                    if put.status_code >= 400:
                        raise RuntimeError(f"chunk HTTP {put.status_code}: {put.text[:300]}")
                    pos += len(chunk)
                    row.bytes_uploaded = pos
                    row.save(update_fields=["bytes_uploaded"])

            complete = requests.post(
                f"{base}/media/{row.media_id}/complete",
                json={"sha256": row.sha256, "location_code": row.location_code},
                headers=headers,
                timeout=60,
            )
            body = complete.json() if complete.content else {}
            if complete.status_code >= 400 or not body.get("verified"):
                raise RuntimeError(f"complete failed: HTTP {complete.status_code} {body}")

            row.status = MediaQueue.STATUS_VERIFIED
            row.verified_at = timezone.now()
            row.last_error = ""
            row.save(update_fields=["status", "verified_at", "last_error"])
            stats["verified"] += 1
            audit("media_verified", detail={"media_id": str(row.media_id)})
        except Exception as exc:  # noqa: BLE001
            row.attempts += 1
            row.last_error = str(exc)[:2000]
            if row.attempts >= max_attempts:
                row.status = MediaQueue.STATUS_FAILED
                stats["failed"] += 1
            else:
                row.status = MediaQueue.STATUS_PENDING
            row.save(update_fields=["attempts", "last_error", "status"])
            logger.warning("media upload failed media_id=%s: %s", row.media_id, exc)

    return stats


def hq_media_root_for(loc: str) -> Path:
    root = Path(getattr(settings, "SYNC_HQ_MEDIA_ROOT", "") or (Path(settings.MEDIA_ROOT) / "hq_sync_media"))
    root.mkdir(parents=True, exist_ok=True)
    now = timezone.now()
    dest = root / loc.upper() / f"{now.year:04d}" / f"{now.month:02d}"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def hq_media_init(*, loc: str, media_id: str, sha256: str, size_bytes: int, entity_type: str, entity_id) -> dict:
    if not is_hq():
        raise PermissionError("HQ only")
    mid = UUID(str(media_id))
    obj, created = HqMediaObject.objects.get_or_create(
        media_id=mid,
        defaults={
            "location_code": loc.upper(),
            "sha256": sha256,
            "size_bytes": int(size_bytes),
            "record_entity_type": entity_type or "",
            "record_entity_id": UUID(str(entity_id)) if entity_id else None,
            "status": HqMediaObject.STATUS_PARTIAL,
        },
    )
    if obj.status == HqMediaObject.STATUS_VERIFIED:
        return {"offset": obj.size_bytes, "verified": True}
    if not created and obj.sha256 != sha256:
        # Restart
        if obj.storage_path and Path(obj.storage_path).exists():
            Path(obj.storage_path).unlink(missing_ok=True)
        obj.sha256 = sha256
        obj.size_bytes = int(size_bytes)
        obj.bytes_received = 0
        obj.status = HqMediaObject.STATUS_PARTIAL
        obj.storage_path = ""
        obj.save()
    if not obj.storage_path:
        dest = hq_media_root_for(loc) / f"{mid}.partial"
        dest.touch(exist_ok=True)
        obj.storage_path = str(dest)
        obj.save(update_fields=["storage_path"])
    offset = int(obj.bytes_received or 0)
    if obj.storage_path and Path(obj.storage_path).exists():
        offset = Path(obj.storage_path).stat().st_size
        obj.bytes_received = offset
        obj.save(update_fields=["bytes_received"])
    return {"offset": offset, "verified": False}


def hq_media_chunk(*, loc: str, media_id: str, offset: int, data: bytes) -> dict:
    obj = HqMediaObject.objects.select_for_update().get(media_id=UUID(str(media_id)), location_code=loc.upper())
    if obj.status == HqMediaObject.STATUS_VERIFIED:
        return {"bytes_received": obj.size_bytes}
    path = Path(obj.storage_path)
    current = path.stat().st_size if path.exists() else 0
    if int(offset) != current:
        raise ValueError(f"offset mismatch expected={current} got={offset}")
    with open(path, "ab") as fh:
        fh.write(data)
    obj.bytes_received = current + len(data)
    obj.save(update_fields=["bytes_received"])
    return {"bytes_received": obj.bytes_received}


def hq_media_complete(*, loc: str, media_id: str, sha256: str) -> dict:
    obj = HqMediaObject.objects.select_for_update().get(media_id=UUID(str(media_id)), location_code=loc.upper())
    path = Path(obj.storage_path)
    if not path.exists():
        obj.status = HqMediaObject.STATUS_FAILED
        obj.save(update_fields=["status"])
        return {"verified": False, "detail": "missing_file"}
    digest, size = sha256_file(path)
    if digest != sha256 or digest != obj.sha256:
        path.unlink(missing_ok=True)
        obj.bytes_received = 0
        obj.storage_path = ""
        obj.status = HqMediaObject.STATUS_FAILED
        obj.save(update_fields=["bytes_received", "storage_path", "status"])
        audit("media_checksum_mismatch", detail={"media_id": str(media_id), "got": digest}, loc=loc)
        return {"verified": False, "detail": "checksum_mismatch"}

    final = path.with_suffix("")  # drop .partial
    if final.exists():
        final.unlink()
    path.replace(final)
    # Best-effort immutability on Windows may fail — ignore.
    try:
        os.chmod(final, 0o444)
    except Exception:  # noqa: BLE001
        pass
    obj.storage_path = str(final)
    obj.size_bytes = size
    obj.bytes_received = size
    obj.status = HqMediaObject.STATUS_VERIFIED
    obj.verified_at = timezone.now()
    obj.save()
    audit("hq_media_verified", detail={"media_id": str(media_id), "path": str(final)}, loc=loc)
    return {"verified": True, "storage_path": str(final)}


def media_stats() -> dict:
    return {
        "pending_media": MediaQueue.objects.filter(
            status__in=[MediaQueue.STATUS_PENDING, MediaQueue.STATUS_UPLOADING]
        ).count(),
        "failed_media": MediaQueue.objects.filter(status=MediaQueue.STATUS_FAILED).count(),
    }
