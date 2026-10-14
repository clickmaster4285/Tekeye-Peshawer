from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from city_sync.identity import is_city, location_code
from city_sync.media_sync import push_media_once


class Command(BaseCommand):
    help = "Upload pending MediaQueue files to HQ (Phase 5)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=None)

    def handle(self, *args, **options):
        if not is_city():
            self.stderr.write(self.style.ERROR("SYSTEM_ROLE must be city"))
            return
        interval = options["interval"]
        if interval is None:
            interval = float(getattr(settings, "SYNC_MEDIA_POLL_INTERVAL", 5))
        self.stdout.write(self.style.SUCCESS(f"Media worker for {location_code()}"))
        while True:
            stats = push_media_once()
            if stats.get("attempted") or stats.get("verified"):
                self.stdout.write(str(stats))
            if options["once"]:
                self.stdout.write(str(stats))
                break
            time.sleep(max(1.0, interval))
