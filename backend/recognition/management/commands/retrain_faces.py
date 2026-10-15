from django.core.management.base import BaseCommand

from recognition.models import FaceEnrollment
from recognition.services.training import TrainingError, train_enrollment


class Command(BaseCommand):
    help = "Re-train every enrolled staff face into the multi-light gallery (all photos x lighting variants)."

    def add_arguments(self, parser):
        parser.add_argument("--staff", type=int, nargs="*", help="Only these staff ids")

    def handle(self, *args, **options):
        qs = FaceEnrollment.objects.filter(is_enrolled=True).select_related("staff")
        if options.get("staff"):
            qs = qs.filter(staff_id__in=options["staff"])
        ok = failed = 0
        for enrollment in qs:
            try:
                result = train_enrollment(enrollment)
            except TrainingError as exc:
                failed += 1
                self.stdout.write(self.style.WARNING(f"staff {enrollment.staff_id}: {exc}"))
                continue
            ok += 1
            self.stdout.write(
                f"staff {enrollment.staff_id} ({enrollment.staff}): "
                f"{result['images_used']} photos -> {result['embeddings_stored']} embeddings"
            )
        self.stdout.write(self.style.SUCCESS(f"Retrained {ok}, failed {failed}"))
