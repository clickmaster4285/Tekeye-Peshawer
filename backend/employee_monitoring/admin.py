from django.contrib import admin

from .models import (
    EmployeeCallRecord,
    EmployeeCallRecording,
    MonitoringAudit,
    MonitoringConsent,
    MonitoringPolicy,
)


@admin.register(MonitoringPolicy)
class MonitoringPolicyAdmin(admin.ModelAdmin):
    list_display = ("version", "is_active", "effective_at", "created_at")
    list_filter = ("is_active",)
    search_fields = ("version",)


@admin.register(MonitoringConsent)
class MonitoringConsentAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "policy", "created_at")
    list_filter = ("status",)
    search_fields = ("user__username",)
    raw_id_fields = ("user", "policy")


@admin.register(EmployeeCallRecord)
class EmployeeCallRecordAdmin(admin.ModelAdmin):
    # Full number is encrypted and intentionally not listed; only the masked form shows.
    list_display = ("masked_number", "direction", "user", "started_at", "duration_seconds", "source", "recording_status")
    list_filter = ("direction", "recording_status", "source")
    search_fields = ("masked_number", "user__username", "source_event_id")
    readonly_fields = ("received_at",)


@admin.register(EmployeeCallRecording)
class EmployeeCallRecordingAdmin(admin.ModelAdmin):
    list_display = ("source_recording_id", "user", "status", "source", "recorded_at", "retention_deadline")
    list_filter = ("status", "source")
    search_fields = ("source_recording_id", "user__username")


@admin.register(MonitoringAudit)
class MonitoringAuditAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "target_type", "target_id", "created_at")
    list_filter = ("action",)
    search_fields = ("actor__username", "action", "target_id")
    readonly_fields = ("actor", "action", "target_type", "target_id", "reason", "request_ip", "metadata", "created_at")

    def has_add_permission(self, request):
        return False
