from datetime import date

from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from city_sync.reconcile import run_reconcile_all, run_reconcile_for_location


class Command(BaseCommand):
    help = "Compare city vs HQ attendance summaries (Phase 10)."

    def add_arguments(self, parser):
        parser.add_argument("--location", default="")
        parser.add_argument("--day", default="")  # YYYY-MM-DD

    def handle(self, *args, **options):
        day = parse_date(options["day"]) if options["day"] else None
        loc = (options["location"] or "").strip().upper()
        if loc:
            reports = run_reconcile_for_location(loc, day=day)
        else:
            reports = run_reconcile_all(day=day)
        for r in reports:
            flag = "OK" if r.ok else "MISMATCH"
            self.stdout.write(
                f"{flag} {r.location_code} {r.day} {r.entity_type} "
                f"city={r.city_count} hq={r.hq_count}"
            )
