"""City Outbox worker loop (Phase 3)."""

from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from city_sync.identity import is_city, location_code
from city_sync.worker import push_once


class Command(BaseCommand):
    help = "Push pending sync_outbox events to HQ_SYNC_URL (city role only)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run a single poll cycle and exit")
        parser.add_argument(
            "--interval",
            type=float,
            default=None,
            help="Poll interval seconds (default OUTBOX_POLL_INTERVAL)",
        )

    def handle(self, *args, **options):
        if not is_city():
            self.stderr.write(self.style.ERROR("SYSTEM_ROLE is not city — refusing to run Outbox worker."))
            return
        self.stdout.write(self.style.SUCCESS(f"Outbox worker starting for {location_code()}"))
        interval = options["interval"]
        if interval is None:
            interval = float(getattr(settings, "OUTBOX_POLL_INTERVAL", 2))
        while True:
            stats = push_once()
            if stats.get("claimed"):
                self.stdout.write(str(stats))
            if options["once"]:
                break
            time.sleep(max(0.5, interval))
