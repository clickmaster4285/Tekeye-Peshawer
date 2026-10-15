from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from city_sync.identity import is_city
from city_sync.reference_sync import pull_reference_once


class Command(BaseCommand):
    help = "Pull HQ reference data to the city cache (Phase 6)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=None)

    def handle(self, *args, **options):
        if not is_city():
            self.stderr.write(self.style.ERROR("SYSTEM_ROLE must be city"))
            return
        interval = options["interval"]
        if interval is None:
            interval = float(getattr(settings, "SYNC_REFERENCE_POLL_INTERVAL", 300))
        while True:
            result = pull_reference_once()
            self.stdout.write(str(result))
            if options["once"]:
                break
            time.sleep(max(30.0, interval))
