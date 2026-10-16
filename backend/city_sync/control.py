"""HQ → city commands carried on the heartbeat (Stage 2).

The city already calls HQ every SYNC_HEARTBEAT_INTERVAL seconds, so HQ answers
each heartbeat with a small "control" dict instead of calling into the city:

    {"paused": bool, "full_history_request_id": str, "camera_directory_hash": str}

The city stores it in CityControlState. Workers skip pushing while paused, and a
new full_history_request_id starts a one-time bootstrap of all existing rows
(and their media). The city reports the finished id back on the next heartbeat.

Camera names travel the other way: when the city's camera list differs from the
hash HQ last stored, the next heartbeat carries the list (no NVR address/password).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Callable

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from city_sync.identity import is_city, location_code
from city_sync.models import CityCamera, CityControlState, MediaQueue, SyncSite
from city_sync.outbox import enqueue_outbox, model_to_payload
from city_sync.syncable import (
    EVIDENCE_ENTITY_TYPES,
    SYNC_MEDIA_FIELDS,
    SYNCED_ENTITY_TYPES,
    media_field_path,
    new_entity_id,
    resolve_model,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HQ side
# ---------------------------------------------------------------------------


def control_for_location(loc: str) -> dict:
    site = SyncSite.objects.filter(location_code=loc.upper()).first()
    from city_sync.downlink import latest_seq

    if site is None:
        return {"paused": False, "full_history_request_id": "", "camera_directory_hash": "", "downlink_seq": 0}
    return {
        "paused": site.is_paused,
        "full_history_request_id": site.full_history_request_id,
        "camera_directory_hash": site.camera_directory_hash,
        # Newest HQ HR change for this city; the city pulls when it is behind.
        "downlink_seq": latest_seq(site.location_code),
    }


def record_heartbeat_ack(loc: str, body: dict) -> None:
    """Mark the full-history request done when the city echoes its id back; store camera names."""
    loc = loc.upper()
    cameras = body.get("camera_directory")
    if isinstance(cameras, list):
        _store_camera_directory(loc, cameras, str(body.get("camera_directory_hash") or ""))
    done_id = str(body.get("full_history_done_id") or "")
    if not done_id:
        return
    SyncSite.objects.filter(
        location_code=loc,
        full_history_request_id=done_id,
        full_history_done_at__isnull=True,
    ).update(full_history_done_at=timezone.now())


def _store_camera_directory(loc: str, cameras: list, digest: str) -> None:
    rows = {}
    for cam in cameras:
        if not isinstance(cam, dict):
            continue
        try:
            origin_pk = int(cam.get("id"))
        except (TypeError, ValueError):
            continue
        channel = cam.get("channel")
        rows[origin_pk] = CityCamera(
            location_code=loc,
            origin_pk=origin_pk,
            code=str(cam.get("code") or "")[:64],
            name=str(cam.get("name") or "")[:255],
            zone=str(cam.get("zone") or "")[:128],
            location=str(cam.get("location") or "")[:128],
            channel=channel if isinstance(channel, int) and 0 <= channel < 32768 else None,
            site_code=str(cam.get("site_code") or "")[:64],
            site_name=str(cam.get("site_name") or "")[:255],
        )
    with transaction.atomic():
        CityCamera.objects.filter(location_code=loc).delete()
        CityCamera.objects.bulk_create(rows.values())
        SyncSite.objects.filter(location_code=loc).update(camera_directory_hash=digest[:64])


def is_location_paused(loc: str) -> bool:
    return SyncSite.objects.filter(location_code=loc.upper(), is_paused=True).exists()


# ---------------------------------------------------------------------------
# City side
# ---------------------------------------------------------------------------


def city_is_paused() -> bool:
    if not is_city():
        return False
    return CityControlState.objects.filter(pk=1, is_paused=True).exists()


# Camera-list hash HQ reported on the last heartbeat (None until HQ answers once).
_hq_camera_hash: str | None = None


def camera_directory() -> tuple[list[dict], str]:
    """This city's cameras as names only, and a hash of the list."""
    from cameras.models import Camera

    cameras = [
        {
            "id": c.pk,
            "code": c.code,
            "name": c.name,
            "zone": c.zone,
            "location": c.location,
            "channel": c.channel,
            "site_code": c.nvr.site.code if c.nvr_id and c.nvr.site_id else "",
            "site_name": c.nvr.site.name if c.nvr_id and c.nvr.site_id else "",
        }
        for c in Camera.objects.select_related("nvr__site").order_by("pk")
    ]
    digest = hashlib.sha256(json.dumps(cameras, sort_keys=True).encode()).hexdigest()
    return cameras, digest


def heartbeat_extras() -> dict:
    state = CityControlState.objects.filter(pk=1).first()
    extras = {"full_history_done_id": state.full_history_done_id if state else ""}
    try:
        from cameras.live_status import camera_counts

        # Live camera numbers for HQ's City Control Grid.
        extras.update(camera_counts())
    except Exception:  # noqa: BLE001
        logger.exception("Could not count live cameras for HQ")
    try:
        cameras, digest = camera_directory()
    except Exception:  # noqa: BLE001
        logger.exception("Could not build camera list for HQ")
        return extras
    if digest != _hq_camera_hash:
        extras["camera_directory"] = cameras
        extras["camera_directory_hash"] = digest
    return extras


def apply_hq_control(control: dict) -> None:
    """Save HQ's commands from a heartbeat response and start full history if asked."""
    global _hq_camera_hash
    if not isinstance(control, dict):
        return
    if "camera_directory_hash" in control:
        _hq_camera_hash = str(control.get("camera_directory_hash") or "")
    state = CityControlState.load()
    state.is_paused = bool(control.get("paused"))
    state.full_history_request_id = str(control.get("full_history_request_id") or "")[:64]
    state.last_hq_contact_at = timezone.now()
    state.save(
        update_fields=["is_paused", "full_history_request_id", "last_hq_contact_at", "updated_at"]
    )

    request_id = state.full_history_request_id
    if request_id and request_id != state.full_history_done_id and not state.full_history_running:
        _start_full_history(request_id)

    target = int(control.get("downlink_seq") or 0)
    if target > state.downlink_seq and not state.is_paused:
        from city_sync.downlink import pull_downlink

        try:
            result = pull_downlink(target)
            logger.info("HQ changes applied: %s", result)
        except Exception:  # noqa: BLE001
            logger.exception("Could not pull HQ changes; will retry on the next heartbeat")


_full_history_lock = threading.Lock()


def _start_full_history(request_id: str) -> None:
    # Claim the run in the DB so a second heartbeat (or process) does not start it again.
    claimed = CityControlState.objects.filter(pk=1, full_history_running=False).update(
        full_history_running=True
    )
    if not claimed:
        return

    def run():
        close_old_connections()
        try:
            with _full_history_lock:
                total = bootstrap_outbox(log=lambda m: logger.info("full history: %s", m))
            CityControlState.objects.filter(pk=1).update(
                full_history_done_id=request_id, full_history_running=False
            )
            logger.info("Full history %s finished: %s rows queued", request_id, total)
        except Exception:  # noqa: BLE001
            logger.exception("Full history %s failed", request_id)
            CityControlState.objects.filter(pk=1).update(full_history_running=False)
        finally:
            close_old_connections()

    threading.Thread(target=run, name="city-sync-full-history", daemon=True).start()


def _enqueue_existing_media(obj, entity_type: str) -> int:
    if not getattr(settings, "SYNC_MEDIA_ENABLED", True):
        return 0
    fields = SYNC_MEDIA_FIELDS.get(entity_type) or []
    if not fields:
        return 0
    from city_sync.media_sync import enqueue_media_file

    priority = (
        MediaQueue.PRIORITY_EVIDENCE
        if entity_type in EVIDENCE_ENTITY_TYPES
        else MediaQueue.PRIORITY_ROUTINE
    )
    queued = 0
    for fname in fields:
        name = media_field_path(obj, fname)
        if not name:
            continue
        # Running full history twice must not upload the same file twice.
        if MediaQueue.objects.filter(record_entity_id=obj.entity_id, path=name.replace("\\", "/")).exists():
            continue
        if enqueue_media_file(
            absolute_or_media_path=name,
            record_entity_type=entity_type,
            record_entity_id=obj.entity_id,
            priority=priority,
            wait_outbox_done=True,
        ):
            queued += 1
    return queued


def bootstrap_outbox(
    *,
    only: str = "",
    limit: int = 0,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> int:
    """Queue every existing synced row (and its media files) for upload to HQ. City only."""
    if not is_city():
        raise RuntimeError("SYSTEM_ROLE must be city to bootstrap Outbox")
    loc = location_code()
    total = 0

    from city_sync.materialize import ENTITY_ORDER

    def parents_first(item):
        name = item[0]
        return (ENTITY_ORDER.index(name) if name in ENTITY_ORDER else len(ENTITY_ORDER), name)

    for entity_type, label in sorted(SYNCED_ENTITY_TYPES.items(), key=parents_first):
        if only and entity_type != only:
            continue
        model = resolve_model(label)
        qs = model.objects.all().order_by("pk")
        if limit:
            qs = qs[:limit]
        count = 0
        media = 0
        for obj in qs.iterator(chunk_size=200):
            if not getattr(obj, "entity_id", None):
                obj.entity_id = obj.pk if hasattr(getattr(obj, "pk", None), "hex") else new_entity_id()
            if not getattr(obj, "location_code", None):
                obj.location_code = loc
            if not getattr(obj, "version", None):
                obj.version = 1
            if dry_run:
                count += 1
                continue
            with transaction.atomic():
                # Avoid signal recursion mark
                setattr(obj, "_city_sync_skip_outbox", True)
                obj.save(
                    update_fields=[
                        f
                        for f in ("entity_id", "location_code", "version", "is_deleted")
                        if hasattr(obj, f)
                    ]
                )
                enqueue_outbox(
                    entity_type=entity_type,
                    entity_id=obj.entity_id,
                    entity_version=int(obj.version or 1),
                    operation="tombstone" if getattr(obj, "is_deleted", False) else "upsert",
                    payload=model_to_payload(obj),
                    location=getattr(obj, "location_code", None) or loc,
                )
            media += _enqueue_existing_media(obj, entity_type)
            count += 1
        total += count
        log(f"{entity_type}: {count} rows, {media} media files")
    log(f"Bootstrap complete rows={total} dry_run={dry_run}")
    return total
