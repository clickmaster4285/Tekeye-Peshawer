"""Delete monitoring data past its retention deadline. Run from cron / a scheduled task."""

from __future__ import annotations

import os

from django.core.management.base import BaseCommand
from django.utils import timezone

from employee_monitoring.models import EmployeeCallRecording
from employee_monitoring.services import storage_path


class Command(BaseCommand):
    help = "Delete recordings (and their audio files) past their retention deadline."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted without deleting.")

    def handle(self, *args, **options):
        now = timezone.now()
        expired = EmployeeCallRecording.objects.filter(retention_deadline__isnull=False, retention_deadline__lt=now)
        count = expired.count()
        if options["dry_run"]:
            self.stdout.write(f"Would delete {count} expired recording(s).")
            return
        removed_files = 0
        for rec in expired.iterator():
            if rec.storage_key:
                path = storage_path(rec.storage_key)
                try:
                    if os.path.exists(path):
                        os.remove(path)
                        removed_files += 1
                except OSError:
                    pass
        deleted, _ = expired.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} recording row(s); removed {removed_files} audio file(s)."))
