"""City Outbox + HQ receiver tables (Phases 2 & 4)."""

from __future__ import annotations

import hashlib
import uuid

from django.db import models
from django.utils import timezone


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class SyncOutbox(models.Model):
    """Transactional Outbox — city side (Phase 2 / 3)."""

    STATUS_PENDING = "pending"
    STATUS_SENDING = "sending"
    STATUS_DONE = "done"
    STATUS_DEAD = "dead"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENDING, "Sending"),
        (STATUS_DONE, "Done"),
        (STATUS_DEAD, "Dead"),
    ]

    OP_UPSERT = "upsert"
    OP_TOMBSTONE = "tombstone"
    OP_CHOICES = [
        (OP_UPSERT, "Upsert"),
        (OP_TOMBSTONE, "Tombstone"),
    ]

    seq = models.BigAutoField(primary_key=True)
    event_id = models.UUIDField(default=new_uuid, unique=True, editable=False)
    location_code = models.CharField(max_length=64, db_index=True)
    entity_type = models.CharField(max_length=64, db_index=True)
    entity_id = models.UUIDField(db_index=True)
    operation = models.CharField(max_length=16, choices=OP_CHOICES)
    entity_version = models.PositiveIntegerField()
    schema_version = models.PositiveIntegerField(default=1)
    payload = models.JSONField()
    payload_hash = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_error = models.TextField(blank=True, default="")
    done_at = models.DateTimeField(null=True, blank=True)
    # Schema-unsupported retries must not count toward dead (guide fix).
    schema_hold = models.BooleanField(default=False)

    class Meta:
        ordering = ["seq"]
        indexes = [
            models.Index(
                fields=["status", "next_attempt_at", "seq"],
                name="ix_outbox_pending",
            ),
        ]

    def __str__(self) -> str:
        return f"Outbox seq={self.seq} {self.entity_type}/{self.entity_id} v{self.entity_version}"


class SyncCredential(models.Model):
    """Per-city API key for HQ Sync API (Phase 11)."""

    location_code = models.CharField(max_length=64, unique=True)
    # Store SHA-256 of the raw key only.
    key_hash = models.CharField(max_length=64)
    label = models.CharField(max_length=128, blank=True, default="")
    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["location_code"]

    def __str__(self) -> str:
        return f"SyncCredential({self.location_code})"

    @staticmethod
    def hash_key(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class HqEventLog(models.Model):
    """Permanent HQ receipt log — never delete (Phase 4 / 9)."""

    location_code = models.CharField(max_length=64)
    city_seq = models.BigIntegerField()
    event_id = models.UUIDField()
    entity_type = models.CharField(max_length=64)
    entity_id = models.UUIDField()
    entity_version = models.PositiveIntegerField()
    result = models.CharField(max_length=32)  # applied|duplicate|stale|rejected|conflict
    payload_hash = models.CharField(max_length=64, blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location_code", "event_id"],
                name="ux_hq_event_log_loc_event",
            ),
        ]
        indexes = [
            models.Index(fields=["location_code", "city_seq"], name="ix_hq_event_loc_seq"),
            models.Index(fields=["entity_type", "entity_id"], name="ix_hq_event_entity"),
        ]

    def __str__(self) -> str:
        return f"HqEvent {self.location_code} {self.event_id} → {self.result}"


class HqSyncCursor(models.Model):
    location_code = models.CharField(max_length=64, primary_key=True)
    last_seq_applied = models.BigIntegerField(default=0)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Cursor {self.location_code}@{self.last_seq_applied}"


class HqConflict(models.Model):
    location_code = models.CharField(max_length=64, db_index=True)
    entity_type = models.CharField(max_length=64)
    entity_id = models.UUIDField()
    incoming_version = models.PositiveIntegerField()
    stored_version = models.PositiveIntegerField()
    reason = models.CharField(max_length=64, default="stale_or_mismatch")
    payload = models.JSONField()
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved_by = models.CharField(max_length=128, blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-detected_at"]

    def __str__(self) -> str:
        return f"Conflict {self.entity_type}/{self.entity_id}"


class HqReplicaRow(models.Model):
    """
    Generic HQ replica for synced city entities (Phase 4).
    PK = (location_code, entity_type, entity_id).
    """

    location_code = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=64)
    entity_id = models.UUIDField()
    entity_version = models.PositiveIntegerField()
    is_deleted = models.BooleanField(default=False)
    payload = models.JSONField()
    payload_hash = models.CharField(max_length=64, blank=True, default="")
    updated_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location_code", "entity_type", "entity_id"],
                name="ux_hq_replica_identity",
            ),
        ]
        indexes = [
            models.Index(fields=["location_code", "entity_type"], name="ix_hq_replica_loc_type"),
        ]

    def __str__(self) -> str:
        return f"Replica {self.location_code}/{self.entity_type}/{self.entity_id} v{self.entity_version}"


class HqCityStatus(models.Model):
    """Latest heartbeat snapshot per city (Phase 7)."""

    location_code = models.CharField(max_length=64, primary_key=True)
    node_id = models.CharField(max_length=128, blank=True, default="")
    app_version = models.CharField(max_length=64, blank=True, default="")
    schema_version = models.PositiveIntegerField(default=1)
    pending_outbox = models.PositiveIntegerField(default=0)
    oldest_pending_age_sec = models.PositiveIntegerField(default=0)
    dead_outbox = models.PositiveIntegerField(default=0)
    pending_media = models.PositiveIntegerField(default=0)
    failed_media = models.PositiveIntegerField(default=0)
    disk_percent = models.FloatField(null=True, blank=True)
    last_backup_at = models.DateTimeField(null=True, blank=True)
    last_business_event_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    last_reconcile_at = models.DateTimeField(null=True, blank=True)
    last_reconcile_ok = models.BooleanField(default=True)
    reconcile_mismatch_count = models.PositiveIntegerField(default=0)
    raw = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return f"Status {self.location_code}"


class MediaQueue(models.Model):
    """City-side media upload queue (Phase 5)."""

    STATUS_PENDING = "pending"
    STATUS_UPLOADING = "uploading"
    STATUS_VERIFIED = "verified"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_UPLOADING, "Uploading"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_FAILED, "Failed"),
    ]

    PRIORITY_EVIDENCE = 10
    PRIORITY_ROUTINE = 50

    media_id = models.UUIDField(default=new_uuid, unique=True, editable=False)
    location_code = models.CharField(max_length=64, db_index=True)
    record_entity_type = models.CharField(max_length=64, blank=True, default="")
    record_entity_id = models.UUIDField(null=True, blank=True, db_index=True)
    path = models.CharField(max_length=512)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.BigIntegerField(default=0)
    priority = models.PositiveIntegerField(default=PRIORITY_ROUTINE, db_index=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    attempts = models.PositiveIntegerField(default=0)
    bytes_uploaded = models.BigIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    # Wait until related DB Outbox event is done (Phase 5.1.4).
    wait_outbox_done = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["priority", "created_at"]
        indexes = [
            models.Index(fields=["status", "priority", "created_at"], name="ix_media_queue_poll"),
        ]

    def __str__(self) -> str:
        return f"MediaQueue {self.media_id} {self.status}"


class HqMediaObject(models.Model):
    """HQ verified media store index (Phase 5)."""

    STATUS_PARTIAL = "partial"
    STATUS_VERIFIED = "verified"
    STATUS_FAILED = "failed"

    media_id = models.UUIDField(unique=True)
    location_code = models.CharField(max_length=64, db_index=True)
    record_entity_type = models.CharField(max_length=64, blank=True, default="")
    record_entity_id = models.UUIDField(null=True, blank=True)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.BigIntegerField(default=0)
    bytes_received = models.BigIntegerField(default=0)
    storage_path = models.CharField(max_length=512, blank=True, default="")
    status = models.CharField(max_length=16, default=STATUS_PARTIAL, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["location_code", "status"], name="ix_hq_media_loc_status"),
        ]

    def __str__(self) -> str:
        return f"HqMedia {self.location_code}/{self.media_id} {self.status}"


class HqReferenceItem(models.Model):
    """HQ-owned reference data pushed down to cities (Phase 6)."""

    entity_type = models.CharField(max_length=64, db_index=True)
    entity_key = models.CharField(max_length=128)
    version = models.PositiveIntegerField(default=1)
    is_deleted = models.BooleanField(default=False)
    payload = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
    urgent = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "entity_key"],
                name="ux_hq_reference_identity",
            ),
        ]
        indexes = [
            models.Index(fields=["updated_at"], name="ix_hq_reference_updated"),
        ]

    def __str__(self) -> str:
        return f"Ref {self.entity_type}/{self.entity_key} v{self.version}"


class ReferenceCursor(models.Model):
    """City cursor for last applied reference update."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    since = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    item_count = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"ReferenceCursor since={self.since}"


class CityReferenceCache(models.Model):
    """Read-only cache of HQ reference items at the city."""

    entity_type = models.CharField(max_length=64, db_index=True)
    entity_key = models.CharField(max_length=128)
    version = models.PositiveIntegerField(default=1)
    is_deleted = models.BooleanField(default=False)
    payload = models.JSONField(default=dict)
    updated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "entity_key"],
                name="ux_city_reference_identity",
            ),
        ]

    def __str__(self) -> str:
        return f"CityRef {self.entity_type}/{self.entity_key}"


class SyncAuditLog(models.Model):
    """Append-only audit trail (Phase 9). App code must only INSERT."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.CharField(max_length=128, blank=True, default="system")
    location_code = models.CharField(max_length=64, blank=True, default="", db_index=True)
    action = models.CharField(max_length=64, db_index=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Audit {self.action} @ {self.created_at}"


class BackupRecord(models.Model):
    """Independent backup success log (Phase 8) — reported in heartbeats."""

    KIND_DB = "db"
    KIND_MEDIA = "media"
    KIND_CONFIG = "config"
    KIND_CHOICES = [
        (KIND_DB, "Database"),
        (KIND_MEDIA, "Media"),
        (KIND_CONFIG, "Config"),
    ]

    location_code = models.CharField(max_length=64, db_index=True)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    success = models.BooleanField(default=True)
    path_or_label = models.CharField(max_length=512, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    completed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-completed_at"]

    def __str__(self) -> str:
        return f"Backup {self.kind} {self.location_code} ok={self.success}"


class ReconcileReport(models.Model):
    """Nightly city↔HQ summary compare (Phase 10)."""

    location_code = models.CharField(max_length=64, db_index=True)
    day = models.DateField(db_index=True)
    entity_type = models.CharField(max_length=64)
    city_count = models.PositiveIntegerField(default=0)
    hq_count = models.PositiveIntegerField(default=0)
    city_hash = models.CharField(max_length=64, blank=True, default="")
    hq_hash = models.CharField(max_length=64, blank=True, default="")
    ok = models.BooleanField(default=False)
    mismatched_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["location_code", "day"], name="ix_reconcile_loc_day"),
        ]

    def __str__(self) -> str:
        return f"Reconcile {self.location_code} {self.day} {self.entity_type} ok={self.ok}"
