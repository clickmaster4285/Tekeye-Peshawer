"""City heartbeat to HQ (Phase 7)."""

from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from city_sync.identity import is_city, location_code
from city_sync.worker import send_heartbeat


class Command(BaseCommand):
    help = "Send city heartbeat to HQ every SYNC_HEARTBEAT_INTERVAL seconds."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        if not is_city():
            self.stderr.write(self.style.ERROR("SYSTEM_ROLE is not city — refusing heartbeat worker."))
            return
        interval = float(getattr(settings, "SYNC_HEARTBEAT_INTERVAL", 30))
        self.stdout.write(self.style.SUCCESS(f"Heartbeat worker for {location_code()} every {interval}s"))
        while True:
            result = send_heartbeat()
            self.stdout.write(str(result))
            if options["once"]:
                break
            time.sleep(max(5.0, interval))
