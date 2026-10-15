"""Phase 2.4 — one-time upsert Outbox events for existing synced rows."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from city_sync.identity import is_city, location_code
from city_sync.outbox import enqueue_outbox, model_to_payload
from city_sync.syncable import SYNCED_ENTITY_TYPES, new_entity_id, resolve_model


class Command(BaseCommand):
    help = "Bootstrap Outbox upserts for all existing synced entity rows (city only)."

    def add_arguments(self, parser):
        parser.add_argument("--entity", default="", help="Limit to one entity_type")
        parser.add_argument("--limit", type=int, default=0, help="Max rows per entity (0=all)")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not is_city():
            self.stderr.write(self.style.ERROR("SYSTEM_ROLE must be city to bootstrap Outbox"))
            return
        only = (options["entity"] or "").strip()
        limit = int(options["limit"] or 0)
        dry = options["dry_run"]
        loc = location_code()
        total = 0

        for entity_type, label in sorted(SYNCED_ENTITY_TYPES.items()):
            if only and entity_type != only:
                continue
            model = resolve_model(label)
            qs = model.objects.all().order_by("pk")
            if limit:
                qs = qs[:limit]
            count = 0
            for obj in qs.iterator(chunk_size=200):
                if not getattr(obj, "entity_id", None):
                    obj.entity_id = obj.pk if hasattr(getattr(obj, "pk", None), "hex") else new_entity_id()
                if not getattr(obj, "location_code", None):
                    obj.location_code = loc
                if not getattr(obj, "version", None):
                    obj.version = 1
                if dry:
                    count += 1
                    continue
                with transaction.atomic():
                    # Avoid signal recursion mark
                    setattr(obj, "_city_sync_skip_outbox", True)
                    obj.save(
                        update_fields=[
                            f
                            for f in ("entity_id", "location_code", "version", "is_deleted")
                            if hasattr(obj, f)
                        ]
                    )
                    enqueue_outbox(
                        entity_type=entity_type,
                        entity_id=obj.entity_id,
                        entity_version=int(obj.version or 1),
                        operation="tombstone" if getattr(obj, "is_deleted", False) else "upsert",
                        payload=model_to_payload(obj),
                        location=getattr(obj, "location_code", None) or loc,
                    )
                count += 1
            total += count
            self.stdout.write(f"{entity_type}: {count}")
        self.stdout.write(self.style.SUCCESS(f"Bootstrap complete rows={total} dry_run={dry}"))
