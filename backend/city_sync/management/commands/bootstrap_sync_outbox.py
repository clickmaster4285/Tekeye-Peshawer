"""Phase 2.4 — one-time upsert Outbox events for existing synced rows."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from city_sync.control import bootstrap_outbox
from city_sync.identity import is_city


class Command(BaseCommand):
    help = "Bootstrap Outbox upserts (and media) for all existing synced entity rows (city only)."

    def add_arguments(self, parser):
        parser.add_argument("--entity", default="", help="Limit to one entity_type")
        parser.add_argument("--limit", type=int, default=0, help="Max rows per entity (0=all)")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not is_city():
            self.stderr.write(self.style.ERROR("SYSTEM_ROLE must be city to bootstrap Outbox"))
            return
        bootstrap_outbox(
            only=(options["entity"] or "").strip(),
            limit=int(options["limit"] or 0),
            dry_run=options["dry_run"],
            log=self.stdout.write,
        )
