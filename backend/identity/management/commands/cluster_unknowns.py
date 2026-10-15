"""Group unknown journey persons into clusters and suggest candidate employees.

    python manage.py cluster_unknowns
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run unknown-person clustering once (also runs periodically in run_background_workers)."

    def handle(self, *args, **opts):
        from identity.services.clustering import run_unknown_clustering

        self.stdout.write(str(run_unknown_clustering()))
