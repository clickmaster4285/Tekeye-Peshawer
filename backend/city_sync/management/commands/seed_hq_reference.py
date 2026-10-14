from django.core.management.base import BaseCommand

from city_sync.identity import is_hq
from city_sync.reference_sync import seed_default_reference


class Command(BaseCommand):
    help = "Seed HQ reference catalog (roles/config/hotlist) for cities to pull."

    def handle(self, *args, **options):
        if not is_hq():
            self.stderr.write(self.style.WARNING("Running on non-HQ node (DEBUG seed allowed)."))
        n = seed_default_reference()
        self.stdout.write(self.style.SUCCESS(f"Reference items now: {n}"))
