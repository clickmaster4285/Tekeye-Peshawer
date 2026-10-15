"""Backfill the employee face gallery from existing enrollment photos.

    python manage.py build_face_gallery                # all trained staff
    python manage.py build_face_gallery --staff 12     # one employee
    python manage.py build_face_gallery --keep-mode    # don't touch recognition modes

Staff who were already auto-marking attendance before the gallery existed get
AUTOMATIC mode so behaviour doesn't change overnight; switch them down in the UI.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from identity.models import IdentityProfile, RecognitionMode
from identity.services.gallery import rebuild_enrollment_entries


class Command(BaseCommand):
    help = "Create per-photo gallery entries from FaceEnrollment dataset folders."

    def add_arguments(self, parser):
        parser.add_argument("--staff", type=int, help="Only this staff id")
        parser.add_argument("--keep-mode", action="store_true", help="Don't create/adjust identity profiles")

    def handle(self, *args, **opts):
        from recognition.models import FaceEnrollment
        from recognition.services.face_engine import get_face_engine

        qs = FaceEnrollment.objects.select_related("staff").filter(is_enrolled=True)
        if opts.get("staff"):
            qs = qs.filter(staff_id=opts["staff"])
        engine = get_face_engine()
        total = 0
        for enrollment in qs:
            if not opts.get("keep_mode"):
                IdentityProfile.objects.get_or_create(
                    staff=enrollment.staff,
                    defaults={
                        "recognition_mode": RecognitionMode.AUTOMATIC
                        if enrollment.is_trained
                        else RecognitionMode.MANUAL
                    },
                )
            folder = Path(settings.MEDIA_ROOT) / enrollment.dataset_folder
            if not folder.is_dir():
                self.stdout.write(self.style.WARNING(f"staff {enrollment.staff_id}: no folder {folder}"))
                continue
            n = rebuild_enrollment_entries(enrollment.staff, engine, folder)
            total += n
            self.stdout.write(f"staff {enrollment.staff_id} {enrollment.staff.full_name}: {n} gallery entries")
        self.stdout.write(self.style.SUCCESS(f"InsightFace: {total} entries."))

        # SFace (journey) gallery mirrors Staff.face_embeddings, one entry per staff photo.
        from identity.services.gallery import sync_sface_enrollment_entries
        from users.models import Staff

        sface_staff = Staff.objects.exclude(face_embeddings=[]).exclude(face_embeddings__isnull=True)
        if opts.get("staff"):
            sface_staff = sface_staff.filter(pk=opts["staff"])
        sface_total = 0
        for staff in sface_staff:
            n = sync_sface_enrollment_entries(staff)
            sface_total += n
            self.stdout.write(f"staff {staff.pk} {staff.full_name}: {n} SFace entries")
        self.stdout.write(self.style.SUCCESS(f"SFace: {sface_total} entries."))
