"""One process: outbox + media + heartbeat + reference pull (city only)."""

from __future__ import annotations

import logging
import signal
import threading
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from city_sync.identity import is_city, location_code

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Run ALL city sync workers in one process: outbox, media, heartbeat, "
        "reference pull. Prefer this over four separate run_*_worker commands."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run one cycle of each enabled worker and exit",
        )
        parser.add_argument(
            "--no-outbox",
            action="store_true",
            help="Disable outbox push",
        )
        parser.add_argument(
            "--no-media",
            action="store_true",
            help="Disable media upload",
        )
        parser.add_argument(
            "--no-heartbeat",
            action="store_true",
            help="Disable heartbeat",
        )
        parser.add_argument(
            "--no-reference",
            action="store_true",
            help="Disable reference pull",
        )

    def handle(self, *args, **options):
        if not is_city():
            self.stderr.write(
                self.style.ERROR("SYSTEM_ROLE must be city — refusing run_city_sync.")
            )
            return

        stop = threading.Event()

        def _stop(*_a):
            stop.set()

        try:
            signal.signal(signal.SIGINT, _stop)
            signal.signal(signal.SIGTERM, _stop)
        except (ValueError, OSError):
            # Not on main thread / unsupported platform
            pass

        enabled = []
        if not options["no_outbox"] and getattr(settings, "SYNC_OUTBOX_ENABLED", True):
            enabled.append("outbox")
        if not options["no_media"] and getattr(settings, "SYNC_MEDIA_ENABLED", True):
            enabled.append("media")
        if not options["no_heartbeat"]:
            enabled.append("heartbeat")
        if not options["no_reference"] and getattr(settings, "SYNC_REFERENCE_ENABLED", True):
            enabled.append("reference")

        if not enabled:
            self.stderr.write(self.style.ERROR("Nothing enabled to run."))
            return

        loc = location_code()
        self.stdout.write(
            self.style.SUCCESS(
                f"City sync supervisor for {loc}: {', '.join(enabled)}"
            )
        )

        if options["once"]:
            self._run_once(enabled)
            return

        threads: list[threading.Thread] = []
        if "outbox" in enabled:
            threads.append(
                threading.Thread(
                    target=self._loop_outbox,
                    args=(stop,),
                    name="sync-outbox",
                    daemon=True,
                )
            )
        if "media" in enabled:
            threads.append(
                threading.Thread(
                    target=self._loop_media,
                    args=(stop,),
                    name="sync-media",
                    daemon=True,
                )
            )
        if "heartbeat" in enabled:
            threads.append(
                threading.Thread(
                    target=self._loop_heartbeat,
                    args=(stop,),
                    name="sync-heartbeat",
                    daemon=True,
                )
            )
        if "reference" in enabled:
            threads.append(
                threading.Thread(
                    target=self._loop_reference,
                    args=(stop,),
                    name="sync-reference",
                    daemon=True,
                )
            )

        for t in threads:
            t.start()

        try:
            while not stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            stop.set()

        self.stdout.write("Stopping city sync supervisor...")
        stop.set()
        for t in threads:
            t.join(timeout=10)
        self.stdout.write(self.style.SUCCESS("City sync supervisor stopped."))

    def _run_once(self, enabled: list[str]) -> None:
        close_old_connections()
        if "outbox" in enabled:
            from city_sync.worker import push_once

            self.stdout.write(f"outbox: {push_once()}")
        if "media" in enabled:
            from city_sync.media_sync import push_media_once

            self.stdout.write(f"media: {push_media_once()}")
        if "heartbeat" in enabled:
            from city_sync.worker import send_heartbeat

            self.stdout.write(f"heartbeat: {send_heartbeat()}")
        if "reference" in enabled:
            from city_sync.reference_sync import pull_reference_once

            self.stdout.write(f"reference: {pull_reference_once()}")

    def _loop_outbox(self, stop: threading.Event) -> None:
        from city_sync.worker import push_once

        interval = float(getattr(settings, "OUTBOX_POLL_INTERVAL", 2))
        while not stop.is_set():
            try:
                close_old_connections()
                stats = push_once()
                if stats.get("claimed"):
                    self.stdout.write(f"[outbox] {stats}")
            except Exception:  # noqa: BLE001
                logger.exception("outbox loop error")
            stop.wait(max(0.5, interval))

    def _loop_media(self, stop: threading.Event) -> None:
        from city_sync.media_sync import push_media_once

        interval = float(getattr(settings, "SYNC_MEDIA_POLL_INTERVAL", 5))
        while not stop.is_set():
            try:
                close_old_connections()
                stats = push_media_once()
                if stats.get("attempted") or stats.get("verified"):
                    self.stdout.write(f"[media] {stats}")
            except Exception:  # noqa: BLE001
                logger.exception("media loop error")
            stop.wait(max(1.0, interval))

    def _loop_heartbeat(self, stop: threading.Event) -> None:
        from city_sync.worker import send_heartbeat

        interval = float(getattr(settings, "SYNC_HEARTBEAT_INTERVAL", 30))
        while not stop.is_set():
            try:
                close_old_connections()
                result = send_heartbeat()
                self.stdout.write(f"[heartbeat] {result}")
            except Exception:  # noqa: BLE001
                logger.exception("heartbeat loop error")
            stop.wait(max(5.0, interval))

    def _loop_reference(self, stop: threading.Event) -> None:
        from city_sync.reference_sync import pull_reference_once

        interval = float(getattr(settings, "SYNC_REFERENCE_POLL_INTERVAL", 300))
        while not stop.is_set():
            try:
                close_old_connections()
                result = pull_reference_once()
                self.stdout.write(f"[reference] {result}")
            except Exception:  # noqa: BLE001
                logger.exception("reference loop error")
            stop.wait(max(30.0, interval))
