from django.contrib import admin

from identity.models import FaceGalleryEntry, IdentityDecision, IdentityProfile


@admin.register(IdentityProfile)
class IdentityProfileAdmin(admin.ModelAdmin):
    list_display = ("staff", "recognition_mode", "confirmed_matches", "rejected_matches", "mode_changed_at")
    list_filter = ("recognition_mode",)
    search_fields = ("staff__full_name", "staff__employee_id")


@admin.register(FaceGalleryEntry)
class FaceGalleryEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "staff", "source", "quality_score", "is_active", "created_at")
    list_filter = ("source", "is_active", "model_name")
    search_fields = ("staff__full_name",)
    exclude = ("embedding",)


@admin.register(IdentityDecision)
class IdentityDecisionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "created_at",
        "source",
        "camera_name",
        "staff",
        "outcome",
        "face_similarity",
        "confidence",
        "attendance_action",
        "review_status",
    )
    list_filter = ("outcome", "review_status", "source")
    search_fields = ("staff__full_name", "camera_name", "reason")
    exclude = ("probe_embedding",)
