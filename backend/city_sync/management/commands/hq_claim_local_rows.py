"""HQ: label every synced row that did not come from a city as this HQ's own location."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import QuerySet

from city_sync.identity import is_hq, location_code
from city_sync.models import HqEntityMap
from city_sync.syncable import SYNCED_ENTITY_TYPES, resolve_model


class Command(BaseCommand):
    help = (
        "HQ only. Set location_code to this HQ's LOCATION_CODE on every synced row that was not "
        "copied from a city. Use once on a database that ran with another LOCATION_CODE "
        "(e.g. a copy of a city database). Safe to run again."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not is_hq():
            self.stderr.write(self.style.ERROR("SYSTEM_ROLE must be hq"))
            return
        hq = location_code()
        dry = options["dry_run"]
        total = 0
        for entity_type, label in sorted(SYNCED_ENTITY_TYPES.items()):
            model = resolve_model(label)
            to_pk = model._meta.pk.to_python
            city_pks = [
                to_pk(pk)
                for pk in HqEntityMap.objects.filter(entity_type=entity_type, hq_owned=False).values_list(
                    "local_pk", flat=True
                )
            ]
            # Plain QuerySet: include rows hidden by soft-delete managers.
            qs = QuerySet(model=model).exclude(pk__in=city_pks).exclude(location_code=hq)
            count = qs.count() if dry else qs.update(location_code=hq)
            if count:
                self.stdout.write(f"{entity_type}: {count}")
            total += count
        verb = "would be relabelled" if dry else "relabelled"
        self.stdout.write(self.style.SUCCESS(f"{total} rows {verb} as {hq}"))
