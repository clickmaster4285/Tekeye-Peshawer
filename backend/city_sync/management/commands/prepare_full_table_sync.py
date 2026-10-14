"""Add sync columns to every business table and refresh the outbox registry."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from city_sync.full_registry import ensure_all_db_sync_columns, ensure_all_orm_sync_fields
from city_sync.signals import connect_signals, reset_signal_connections
from city_sync.syncable import refresh_synced_registry


class Command(BaseCommand):
    help = (
        "Prepare FULL table sync: ADD sync columns on all business tables, "
        "register every model in SYNCED_ENTITY_TYPES, reconnect signals."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--orm-only",
            action="store_true",
            help="Only inject ORM fields + registry (no ALTER TABLE)",
        )

    def handle(self, *args, **options):
        if not options["orm_only"]:
            altered = ensure_all_db_sync_columns()
            self.stdout.write(f"DB columns added on {len(altered)} tables")
            for label, cols in sorted(altered.items()):
                self.stdout.write(f"  {label}: {', '.join(cols)}")
        n = ensure_all_orm_sync_fields()
        self.stdout.write(f"ORM fields ensured on {n} models (newly contributed)")
        registry = refresh_synced_registry()
        self.stdout.write(f"Registry size: {len(registry)} entity types")
        reset_signal_connections()
        connect_signals()
        self.stdout.write(self.style.SUCCESS("Full table sync prepared. Run bootstrap_sync_outbox on city."))
        for et, label in sorted(registry.items()):
            self.stdout.write(f"  {et} -> {label}")
