from django.conf import settings
from django.db import models


class FaceEnrollment(models.Model):
    """InsightFace enrollment state for a Staff member."""

    staff = models.OneToOneField(
        "users.Staff",
        on_delete=models.CASCADE,
        related_name="face_enrollment",
    )
    profile_image = models.ImageField(
        upload_to="recognition/profile/",
        blank=True,
        null=True,
    )
    dataset_folder = models.CharField(max_length=255, unique=True)
    total_images = models.PositiveIntegerField(default=0)
    is_enrolled = models.BooleanField(default=False)
    is_trained = models.BooleanField(default=False)
    model_version = models.CharField(max_length=50, default="InsightFace_v1")
    embedding = models.JSONField(null=True, blank=True)
    embeddings = models.JSONField(
        default=list,
        blank=True,
        help_text="ArcFace vectors from the enrollment photos and lighting variants.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["staff_id"]

    def __str__(self):
        return f"Enrollment staff={self.staff_id} trained={self.is_trained}"

    @property
    def gallery_key(self) -> str:
        """Stable key used in the recognition gallery."""
        return f"staff-{self.staff_id}"


class DetectionSnapshot(models.Model):
    """Annotated JPEG saved when InsightFace matches a staff member on CCTV."""

    staff = models.ForeignKey(
        "users.Staff",
        on_delete=models.CASCADE,
        related_name="detection_snapshots",
    )
    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recognition_snapshots",
    )
    camera_name = models.CharField(max_length=100)
    image = models.ImageField(upload_to="detections/%Y/%m/%d/")
    confidence = models.FloatField(default=0.0)
    attendance_action = models.CharField(max_length=32, blank=True)
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-detected_at"]

    def __str__(self):
        return f"{self.staff_id} @ {self.camera_name} ({self.detected_at})"


class MatchReview(models.Model):
    """A live face that was not punched: unknown, soft miss, or spoof."""

    KIND_UNKNOWN = "unknown"
    KIND_SOFT_MISS = "soft_miss"
    KIND_SPOOF = "spoof"

    kind = models.CharField(max_length=16)
    confidence = models.FloatField(default=0.0)
    source = models.CharField(max_length=16, blank=True, default="")
    camera_id = models.PositiveIntegerField(null=True, blank=True)
    message = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class FaceSample(models.Model):
    """A live CCTV face crop kept for HR review.

    Approved samples join the recognition gallery (closing the gap between
    enrollment photos and CCTV), and every reviewed sample is a labelled
    example for threshold calibration.
    """

    KIND_PUNCH = "punch"
    KIND_UNMATCHED = "unmatched"

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    kind = models.CharField(max_length=16)
    status = models.CharField(max_length=16, default=STATUS_PENDING, db_index=True)
    staff = models.ForeignKey(
        "users.Staff",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="face_samples",
        help_text="Confirmed identity, set on approval.",
    )
    suggested_staff = models.ForeignKey(
        "users.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Closest gallery identity when the sample was taken.",
    )
    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    image = models.ImageField(upload_to="face_samples/%Y/%m/%d/")
    embedding = models.JSONField()
    model_name = models.CharField(max_length=50)
    confidence = models.FloatField(default=0.0)
    quality = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"FaceSample {self.pk} {self.kind} {self.status}"
