"""HQ: copy stored city replicas into the business tables again (retry / backfill)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from city_sync.identity import is_hq
from city_sync.materialize import rematerialize


class Command(BaseCommand):
    help = "HQ only. Re-copy received city records (staff, attendance, ...) into the normal tables."

    def add_arguments(self, parser):
        parser.add_argument("--location", default="", help="Only this LOCATION_CODE")
        parser.add_argument("--entity", default="", help="Only this entity_type (e.g. staff)")

    def handle(self, *args, **options):
        if not is_hq():
            self.stderr.write(self.style.ERROR("SYSTEM_ROLE must be hq"))
            return
        done = rematerialize(loc=options["location"], entity_type=options["entity"])
        self.stdout.write(self.style.SUCCESS(f"Re-copied {done} records"))
