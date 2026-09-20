"""Poll ML live detections and record every visible person into Person Journey."""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from django.db import close_old_connections
from django.db.utils import OperationalError

from config.db import release_db

logger = logging.getLogger(__name__)

_stop = threading.Event()
_thread: threading.Thread | None = None


def _enabled() -> bool:
    return bool(getattr(settings, "PERSON_JOURNEY_LIVE_INGEST_ENABLED", True))


def _interval() -> float:
    return max(1.0, float(getattr(settings, "PERSON_JOURNEY_LIVE_INGEST_INTERVAL_SEC", 2)))


def _camera_refresh() -> int:
    return max(15, int(getattr(settings, "PERSON_JOURNEY_LIVE_CAMERA_REFRESH_SEC", 60)))


def _active_camera_ids() -> list[int]:
    from cameras.models import Camera

    return list(
        Camera.objects.filter(
            is_active=True,
            nvr__is_active=True,
            nvr__site__is_active=True,
            ml_server_id__isnull=False,
        )
        .order_by("id")
        .values_list("id", flat=True)
    )


def _poll_camera(camera_id: int) -> int:
    from ml.client import MLServiceError, ml_live_detections_for_camera, ml_service_enabled

    from .live_ingest import ingest_camera_detections

    if not ml_service_enabled():
        return 0

    from cameras.models import Camera

    try:
        camera = Camera.objects.select_related("nvr", "nvr__site", "ml_server").get(pk=camera_id)
    except Camera.DoesNotExist:
        return 0

    if not camera.ml_server_id:
        return 0

    try:
        result = ml_live_detections_for_camera(camera)
    except MLServiceError as exc:
        logger.debug("Journey live poll skipped camera %s: %s", camera_id, exc)
        return 0

    detections = result.get("detections") or []
    if not detections:
        return 0
    return ingest_camera_detections(camera, detections)


def _poll_camera_safe(camera_id: int) -> int:
    """Entry point for worker-pool threads: each thread owns its own DB connection."""
    close_old_connections()
    try:
        return _poll_camera(camera_id)
    finally:
        release_db()


def _max_concurrency() -> int:
    return max(1, int(getattr(settings, "PERSON_JOURNEY_LIVE_MAX_CONCURRENCY", 10)))


def _worker_loop() -> None:
    """Poll all active cameras concurrently each cycle (was one camera per tick
    round-robin, which meant each camera's effective refresh interval scaled with the
    total camera count instead of staying fixed)."""
    camera_ids: list[int] = []
    last_refresh = 0.0
    refresh_sec = _camera_refresh()
    interval = _interval()
    max_workers = _max_concurrency()

    logger.info(
        "Person journey live ingest started (interval=%.1fs, cameras refresh=%ss, concurrency=%s)",
        interval,
        refresh_sec,
        max_workers,
    )

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="journeywrk") as pool:
        while not _stop.is_set():
            close_old_connections()
            backoff = False
            try:
                now = time.monotonic()
                if not camera_ids or now - last_refresh >= refresh_sec:
                    camera_ids = _active_camera_ids()
                    last_refresh = now
                    if camera_ids:
                        logger.info("Journey live ingest tracking %s camera(s)", len(camera_ids))

                if camera_ids:
                    futures = {pool.submit(_poll_camera_safe, cam_id): cam_id for cam_id in camera_ids}
                    for future in as_completed(futures):
                        cam_id = futures[future]
                        try:
                            count = future.result()
                            if count:
                                logger.debug("Journey live ingest camera %s: %s persons", cam_id, count)
                        except OperationalError:
                            logger.warning("Journey live ingest: Postgres full; backing off 15s")
                            backoff = True
                        except Exception:
                            logger.exception("Journey live ingest failed for camera %s", cam_id)
            finally:
                release_db()

            if backoff:
                _stop.wait(15)
                continue

            from config.worker_throttle import maybe_pause_for_cpu

            maybe_pause_for_cpu(logger, label="journey-live-ingest")
            _stop.wait(interval)


def start_live_ingest_worker() -> None:
    global _thread
    if not _enabled():
        logger.info("Person journey live ingest disabled")
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_worker_loop, daemon=True, name="person-journey-live-ingest")
    _thread.start()
