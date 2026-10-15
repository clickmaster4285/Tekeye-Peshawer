"""Tek Eye Person Identity Engine — one place that decides "who is this?".

Every face model (InsightFace attendance, SFace journey) reports into these
tables instead of marking attendance on its own:

  IdentityProfile   per-employee recognition mode (manual → assisted → automatic)
  FaceGalleryEntry  individual embeddings (enrollment photos + human-approved live faces)
  IdentityDecision  audit trail: every accept / review / unknown, with the evidence
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class RecognitionMode(models.TextChoices):
    MANUAL = "manual", "Manual"
    ASSISTED = "assisted", "Assisted"
    AUTOMATIC = "automatic", "Automatic"


class GallerySource(models.TextChoices):
    ENROLLMENT = "enrollment", "Enrollment photo"
    APPROVED_LIVE = "approved_live", "Approved live observation"


class DecisionOutcome(models.TextChoices):
    ACCEPTED = "accepted", "Accepted"
    REVIEW = "review", "Needs review"
    UNKNOWN = "unknown", "Unknown"


class ReviewStatus(models.TextChoices):
    NOT_REQUIRED = "not_required", "Not required"
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class IdentityProfile(models.Model):
    staff = models.OneToOneField(
        "users.Staff",
        on_delete=models.CASCADE,
        related_name="identity_profile",
    )
    recognition_mode = models.CharField(
        max_length=16,
        choices=RecognitionMode.choices,
        default=RecognitionMode.MANUAL,
        db_index=True,
    )
    mode_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    mode_changed_at = models.DateTimeField(null=True, blank=True)
    # Counters feed the "ready for automatic" recommendation.
    confirmed_matches = models.PositiveIntegerField(default=0)
    rejected_matches = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["staff_id"]

    def __str__(self):
        return f"staff={self.staff_id} mode={self.recognition_mode}"


class FaceGalleryEntry(models.Model):
    """One face embedding of one employee. The gallery is the set of active entries."""

    staff = models.ForeignKey(
        "users.Staff",
        on_delete=models.CASCADE,
        related_name="face_gallery",
    )
    model_name = models.CharField(max_length=48, default="insightface_buffalo_l", db_index=True)
    embedding = models.JSONField()
    source = models.CharField(max_length=16, choices=GallerySource.choices, db_index=True)
    quality_score = models.FloatField(null=True, blank=True)  # None = not scored (e.g. SFace photos)
    quality = models.JSONField(default=dict, blank=True)
    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    image_path = models.CharField(max_length=512, blank=True, default="")
    origin_decision = models.ForeignKey(
        "IdentityDecision",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gallery_entries",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["staff_id", "-created_at"]
        indexes = [models.Index(fields=["staff", "is_active", "model_name"])]

    def __str__(self):
        q = "—" if self.quality_score is None else f"{self.quality_score:.2f}"
        return f"staff={self.staff_id} {self.model_name} {self.source} q={q}"


class IdentityDecision(models.Model):
    """Why the system said a face was (or was not) a given employee."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    source = models.CharField(max_length=24, db_index=True)  # cctv / webcam / journey
    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    camera_name = models.CharField(max_length=150, blank=True, default="")
    track_id = models.IntegerField(null=True, blank=True)
    journey_person = models.ForeignKey(
        "person_journey.JourneyPerson",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="identity_decisions",
    )
    # Best candidate — set for accepted and review outcomes.
    staff = models.ForeignKey(
        "users.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="identity_decisions",
    )
    outcome = models.CharField(max_length=16, choices=DecisionOutcome.choices, db_index=True)
    confidence = models.FloatField(default=0.0)
    face_similarity = models.FloatField(default=0.0)
    second_best_similarity = models.FloatField(null=True, blank=True)
    face_quality = models.FloatField(null=True, blank=True)
    model_name = models.CharField(max_length=48, blank=True, default="")
    matched_entry = models.ForeignKey(
        FaceGalleryEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    factors = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True, default="")
    # Kept for review / unknown outcomes so an approval can grow the gallery.
    probe_embedding = models.JSONField(null=True, blank=True)
    snapshot_path = models.CharField(max_length=512, blank=True, default="")

    attendance_action = models.CharField(max_length=32, blank=True, default="")
    attendance_id = models.PositiveIntegerField(null=True, blank=True)
    policy = models.JSONField(default=dict, blank=True)

    review_status = models.CharField(
        max_length=16,
        choices=ReviewStatus.choices,
        default=ReviewStatus.NOT_REQUIRED,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["review_status", "-created_at"]),
            models.Index(fields=["staff", "-created_at"]),
            models.Index(fields=["outcome", "-created_at"]),
        ]

    def __str__(self):
        return f"#{self.pk} {self.outcome} staff={self.staff_id} sim={self.face_similarity:.2f}"


class PersonObservation(models.Model):
    """A *useful* sighting of a journey person — time-separated, not a near-duplicate.

    1000 video frames → quality/diversity filtering → ≤50 observations per person.
    Embeddings from here feed unknown-person clustering and gallery learning.
    """

    journey_person = models.ForeignKey(
        "person_journey.JourneyPerson",
        on_delete=models.CASCADE,
        related_name="observations",
    )
    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    track_id = models.IntegerField(null=True, blank=True)
    face_embedding = models.JSONField(null=True, blank=True)  # SFace 128-d
    reid_embedding = models.JSONField(null=True, blank=True)
    snapshot_path = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["journey_person", "-created_at"])]


class ClusterStatus(models.TextChoices):
    OPEN = "open", "Open"
    IDENTIFIED = "identified", "Identified"
    DISMISSED = "dismissed", "Dismissed"


class UnknownCluster(models.Model):
    """Several unknown journey persons (U-codes) that are the same real person."""

    code = models.CharField(max_length=16, unique=True)
    status = models.CharField(max_length=16, choices=ClusterStatus.choices, default=ClusterStatus.OPEN, db_index=True)
    staff = models.ForeignKey(
        "users.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="identified_clusters",
    )
    face_centroid = models.JSONField(default=list, blank=True)
    person_count = models.PositiveIntegerField(default=0)
    observation_count = models.PositiveIntegerField(default=0)
    camera_ids = models.JSONField(default=list, blank=True)
    first_seen = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True, db_index=True)
    candidate_decision = models.ForeignKey(
        IdentityDecision,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # Employees a reviewer already said this is NOT — never suggested again.
    rejected_staff_ids = models.JSONField(default=list, blank=True)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen"]

    def __str__(self):
        return f"{self.code} ({self.status}, {self.person_count} persons)"


class UnknownClusterMember(models.Model):
    cluster = models.ForeignKey(UnknownCluster, on_delete=models.CASCADE, related_name="members")
    journey_person = models.OneToOneField(
        "person_journey.JourneyPerson",
        on_delete=models.CASCADE,
        related_name="unknown_cluster_membership",
    )
    added_at = models.DateTimeField(auto_now_add=True)
