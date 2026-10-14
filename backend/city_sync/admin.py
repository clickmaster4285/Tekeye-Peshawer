from django.contrib import admin

from city_sync.models import (
    BackupRecord,
    CityReferenceCache,
    HqCityStatus,
    HqConflict,
    HqEventLog,
    HqMediaObject,
    HqReferenceItem,
    HqReplicaRow,
    HqSyncCursor,
    MediaQueue,
    ReconcileReport,
    ReferenceCursor,
    SyncAuditLog,
    SyncCredential,
    SyncOutbox,
)


@admin.register(SyncOutbox)
class SyncOutboxAdmin(admin.ModelAdmin):
    list_display = (
        "seq",
        "location_code",
        "entity_type",
        "entity_id",
        "entity_version",
        "operation",
        "status",
        "attempts",
        "schema_hold",
        "created_at",
    )
    list_filter = ("status", "entity_type", "location_code", "schema_hold")
    search_fields = ("event_id", "entity_id")
    readonly_fields = ("event_id", "created_at", "payload", "payload_hash")


@admin.register(MediaQueue)
class MediaQueueAdmin(admin.ModelAdmin):
    list_display = (
        "media_id",
        "location_code",
        "path",
        "status",
        "priority",
        "attempts",
        "bytes_uploaded",
        "created_at",
    )
    list_filter = ("status", "location_code")
    search_fields = ("media_id", "sha256", "path")


@admin.register(HqMediaObject)
class HqMediaObjectAdmin(admin.ModelAdmin):
    list_display = (
        "media_id",
        "location_code",
        "status",
        "size_bytes",
        "bytes_received",
        "verified_at",
    )
    list_filter = ("status", "location_code")


@admin.register(HqReferenceItem)
class HqReferenceItemAdmin(admin.ModelAdmin):
    list_display = ("entity_type", "entity_key", "version", "urgent", "is_deleted", "updated_at")
    list_filter = ("entity_type", "urgent", "is_deleted")


@admin.register(CityReferenceCache)
class CityReferenceCacheAdmin(admin.ModelAdmin):
    list_display = ("entity_type", "entity_key", "version", "is_deleted", "updated_at")
    list_filter = ("entity_type", "is_deleted")


@admin.register(ReferenceCursor)
class ReferenceCursorAdmin(admin.ModelAdmin):
    list_display = ("id", "since", "last_success_at", "item_count")


@admin.register(SyncAuditLog)
class SyncAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "location_code", "actor")
    list_filter = ("action", "location_code")
    readonly_fields = ("created_at", "action", "location_code", "actor", "detail")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BackupRecord)
class BackupRecordAdmin(admin.ModelAdmin):
    list_display = ("completed_at", "location_code", "kind", "success", "path_or_label")
    list_filter = ("kind", "success", "location_code")


@admin.register(ReconcileReport)
class ReconcileReportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "location_code", "day", "entity_type", "ok", "city_count", "hq_count")
    list_filter = ("ok", "location_code", "entity_type")


@admin.register(SyncCredential)
class SyncCredentialAdmin(admin.ModelAdmin):
    list_display = ("location_code", "label", "is_active", "revoked_at", "created_at")
    readonly_fields = ("key_hash", "created_at")


@admin.register(HqEventLog)
class HqEventLogAdmin(admin.ModelAdmin):
    list_display = (
        "location_code",
        "city_seq",
        "event_id",
        "entity_type",
        "entity_version",
        "result",
        "received_at",
    )
    list_filter = ("location_code", "result", "entity_type")
    search_fields = ("event_id", "entity_id")


@admin.register(HqSyncCursor)
class HqSyncCursorAdmin(admin.ModelAdmin):
    list_display = ("location_code", "last_seq_applied", "last_success_at", "last_event_at")


@admin.register(HqConflict)
class HqConflictAdmin(admin.ModelAdmin):
    list_display = (
        "location_code",
        "entity_type",
        "entity_id",
        "incoming_version",
        "stored_version",
        "reason",
        "detected_at",
        "resolved_by",
    )
    list_filter = ("reason", "location_code")


@admin.register(HqReplicaRow)
class HqReplicaRowAdmin(admin.ModelAdmin):
    list_display = (
        "location_code",
        "entity_type",
        "entity_id",
        "entity_version",
        "is_deleted",
        "updated_at",
        "received_at",
    )
    list_filter = ("location_code", "entity_type", "is_deleted")
    search_fields = ("entity_id",)


@admin.register(HqCityStatus)
class HqCityStatusAdmin(admin.ModelAdmin):
    list_display = (
        "location_code",
        "node_id",
        "pending_outbox",
        "dead_outbox",
        "pending_media",
        "failed_media",
        "last_heartbeat_at",
        "last_reconcile_ok",
        "app_version",
    )
