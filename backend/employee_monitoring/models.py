"""Employee-monitoring data models.

Scope note: this module stores work-session monitoring metadata that comes from the mobile
app and from *approved* sources only. Call metadata and recordings are ingested from an
approved telephony integration (e.g. the company PBX) — nothing here captures call audio or
call logs from the employee's handset. Audio bytes never live in these rows; only a private
storage key and metadata do.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from config.field_crypto import EncryptedCharField


class MonitoringPolicy(models.Model):
    """A versioned statement of what is collected, why, and for how long."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.CharField(max_length=40, unique=True)
    effective_at = models.DateTimeField(default=timezone.now)
    summary = models.TextField(blank=True, help_text="Purpose, who can view records, and how.")
    work_hours = models.CharField(max_length=200, blank=True)
    contact = models.CharField(max_length=200, blank=True)
    # [{key, label, description, retention_days}]
    categories = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_at"]

    def __str__(self) -> str:
        return f"Policy {self.version}"


class MonitoringConsent(models.Model):
    """One acknowledgment or withdrawal event. The latest row per user is the current state."""

    ACKNOWLEDGED = "acknowledged"
    WITHDRAWN = "withdrawn"
    STATUS_CHOICES = [(ACKNOWLEDGED, "Acknowledged"), (WITHDRAWN, "Withdrawn")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="monitoring_consents")
    policy = models.ForeignKey(MonitoringPolicy, on_delete=models.PROTECT, related_name="consents")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    disclosed_categories = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.user_id} {self.status} {self.policy.version}"


class EmployeeCallRecord(models.Model):
    """Call metadata from an approved telephony source — not read from the device."""

    INBOUND, OUTBOUND, MISSED, UNKNOWN = "inbound", "outbound", "missed", "unknown"
    DIRECTION_CHOICES = [(INBOUND, "Inbound"), (OUTBOUND, "Outbound"), (MISSED, "Missed"), (UNKNOWN, "Unknown")]

    AVAILABLE, NOT_RECORDED, PENDING, FAILED, UNAVAILABLE = (
        "available", "not_recorded", "pending", "failed", "unavailable",
    )
    REC_STATUS_CHOICES = [
        (AVAILABLE, "Available"), (NOT_RECORDED, "Not recorded"),
        (PENDING, "Pending"), (FAILED, "Failed"), (UNAVAILABLE, "Unavailable"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="monitoring_calls"
    )
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, default=UNKNOWN)
    # Full number kept encrypted; a masked form is stored for list display.
    number = EncryptedCharField(max_length=64, blank=True, default="")
    masked_number = models.CharField(max_length=40, blank=True, default="")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    source = models.CharField(max_length=60)
    source_label = models.CharField(max_length=120, blank=True, default="")
    source_event_id = models.CharField(max_length=120)
    recording_status = models.CharField(max_length=16, choices=REC_STATUS_CHOICES, default=UNAVAILABLE)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(fields=["source", "source_event_id"], name="uniq_call_source_event"),
        ]
        indexes = [
            models.Index(fields=["user", "-started_at"]),
            models.Index(fields=["-started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.direction} {self.masked_number} @ {self.started_at:%Y-%m-%d %H:%M}"


class EmployeeCallRecording(models.Model):
    """Recording metadata + a private storage key. Audio bytes are never stored in the row."""

    AVAILABLE, PENDING, FAILED, NOT_RECORDED, UNAVAILABLE = (
        "available", "pending", "failed", "not_recorded", "unavailable",
    )
    STATUS_CHOICES = [
        (AVAILABLE, "Available"), (PENDING, "Pending"), (FAILED, "Failed"),
        (NOT_RECORDED, "Not recorded"), (UNAVAILABLE, "Unavailable"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call = models.ForeignKey(
        EmployeeCallRecord, null=True, blank=True, on_delete=models.SET_NULL, related_name="recordings"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="monitoring_recordings"
    )
    source = models.CharField(max_length=60)
    source_label = models.CharField(max_length=120, blank=True, default="")
    source_recording_id = models.CharField(max_length=120)
    storage_key = models.CharField(max_length=300, blank=True, default="")
    content_type = models.CharField(max_length=60, blank=True, default="audio/mpeg")
    size_bytes = models.BigIntegerField(null=True, blank=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True, default="")
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    recorded_at = models.DateTimeField(null=True, blank=True)
    retention_deadline = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["source", "source_recording_id"], name="uniq_recording_source_id"),
        ]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self) -> str:
        return f"Recording {self.source}:{self.source_recording_id} ({self.status})"


class MonitoringAudit(models.Model):
    """Append-only record of sensitive access — playback, export, policy and consent changes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="monitoring_audits"
    )
    action = models.CharField(max_length=60)
    target_type = models.CharField(max_length=60, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    reason = models.CharField(max_length=200, blank=True, default="")
    request_ip = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at"]), models.Index(fields=["actor", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor_id} @ {self.created_at:%Y-%m-%d %H:%M}"
