from django.core.management.base import BaseCommand
from django.utils import timezone

from city_sync.audit import audit
from city_sync.identity import location_code
from city_sync.models import BackupRecord


class Command(BaseCommand):
    help = "Record an independent backup success/failure (Phase 8) for heartbeats."

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=["db", "media", "config"], default="db")
        parser.add_argument("--path", default="")
        parser.add_argument("--notes", default="")
        parser.add_argument("--fail", action="store_true")

    def handle(self, *args, **options):
        loc = location_code()
        row = BackupRecord.objects.create(
            location_code=loc,
            kind=options["kind"],
            success=not options["fail"],
            path_or_label=options["path"],
            notes=options["notes"],
            completed_at=timezone.now(),
        )
        audit(
            "backup_recorded",
            detail={"kind": row.kind, "success": row.success, "path": row.path_or_label},
            loc=loc,
        )
        self.stdout.write(self.style.SUCCESS(f"Recorded backup id={row.pk} success={row.success}"))
