"""Create + migrate per-city HQ Postgres DBs; optionally backfill from replicas."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from city_sync.city_databases import (
    city_db_name,
    ensure_all_known_city_databases,
    ensure_city_database,
    hq_city_db_enabled,
    known_city_locations,
    project_all_replicas,
)
from city_sync.identity import is_hq


class Command(BaseCommand):
    help = (
        "HQ only: create TEKEYE_HQ_{LOCATION} databases for connected cities, "
        "migrate schema, optionally project HqReplicaRow into those DBs."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--location",
            default="",
            help="Only one location (default: all from SYNC_API_KEYS)",
        )
        parser.add_argument(
            "--project",
            action="store_true",
            help="Backfill city DB tables from existing HqReplicaRow rows",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max replica rows to project per location (0=all)",
        )

    def handle(self, *args, **options):
        if not is_hq():
            self.stderr.write(self.style.ERROR("SYSTEM_ROLE must be hq"))
            return
        if not hq_city_db_enabled():
            self.stderr.write(
                self.style.ERROR("SYNC_HQ_CITY_DB_ENABLED is False — enable in .env")
            )
            return

        only = (options["location"] or "").strip().upper()
        locations = [only] if only else known_city_locations()
        if not locations:
            self.stderr.write(self.style.WARNING("No city locations found in SYNC_API_KEYS"))
            return

        self.stdout.write(f"Ensuring city DBs for: {', '.join(locations)}")
        for loc in locations:
            try:
                alias = ensure_city_database(loc, migrate=True)
                self.stdout.write(
                    self.style.SUCCESS(f"  {loc}: db={city_db_name(loc)} alias={alias}")
                )
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"  {loc}: {exc}"))

        if options["project"]:
            for loc in locations:
                stats = project_all_replicas(loc, limit=int(options["limit"] or 0))
                self.stdout.write(f"  project {stats}")

        # Also warm any other known keys
        if not only:
            ensure_all_known_city_databases()

        self.stdout.write(self.style.SUCCESS("Done. Replica sync + city DBs both active."))
