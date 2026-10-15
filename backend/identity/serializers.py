from django.conf import settings
from rest_framework import serializers

from identity.models import FaceGalleryEntry, IdentityDecision, IdentityProfile, RecognitionMode, UnknownCluster


def _media_url(path: str) -> str | None:
    if not path:
        return None
    if path.startswith(("/", "http://", "https://")):
        return path
    return f"{settings.MEDIA_URL.rstrip('/')}/{path.lstrip('/')}"


def _journey_snapshot(decision) -> str | None:
    """Journey crops are captured asynchronously onto JourneyEvents — use the closest one."""
    from datetime import timedelta

    from person_journey.models import JourneyEvent
    from person_journey.snapshot_utils import journey_event_snapshot_url

    qs = JourneyEvent.objects.filter(journey_person_id=decision.journey_person_id).exclude(snapshot_path="")
    if decision.camera_id:
        qs = qs.filter(camera_id=decision.camera_id)
    event = (
        qs.filter(created_at__gte=decision.created_at - timedelta(minutes=2)).order_by("created_at").first()
        or qs.order_by("-created_at").first()
    )
    return _media_url(journey_event_snapshot_url(event)) if event else None


class FaceGalleryEntrySerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    camera_name = serializers.CharField(source="camera.name", read_only=True, default=None)
    approved_by_name = serializers.CharField(source="approved_by.username", read_only=True, default=None)

    class Meta:
        model = FaceGalleryEntry
        fields = [
            "id",
            "source",
            "model_name",
            "quality_score",
            "quality",
            "camera",
            "camera_name",
            "image_url",
            "origin_decision",
            "approved_by_name",
            "approved_at",
            "is_active",
            "created_at",
        ]

    def get_image_url(self, obj):
        return _media_url(obj.image_path)


class IdentityProfileSerializer(serializers.ModelSerializer):
    staff_id = serializers.IntegerField(source="staff.id", read_only=True)
    staff_name = serializers.CharField(source="staff.full_name", read_only=True)
    employee_id = serializers.CharField(source="staff.employee_id", read_only=True, default=None)
    mode_changed_by_name = serializers.CharField(source="mode_changed_by.username", read_only=True, default=None)

    class Meta:
        model = IdentityProfile
        fields = [
            "staff_id",
            "staff_name",
            "employee_id",
            "recognition_mode",
            "mode_changed_by_name",
            "mode_changed_at",
            "confirmed_matches",
            "rejected_matches",
            "updated_at",
        ]


class IdentityDecisionSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source="staff.full_name", read_only=True, default=None)
    reviewed_by_name = serializers.CharField(source="reviewed_by.username", read_only=True, default=None)
    snapshot_url = serializers.SerializerMethodField()
    matched_entry_image_url = serializers.SerializerMethodField()
    can_add_to_gallery = serializers.SerializerMethodField()

    class Meta:
        model = IdentityDecision
        fields = [
            "id",
            "created_at",
            "source",
            "camera",
            "camera_name",
            "track_id",
            "journey_person",
            "staff",
            "staff_name",
            "outcome",
            "confidence",
            "face_similarity",
            "second_best_similarity",
            "face_quality",
            "model_name",
            "matched_entry",
            "matched_entry_image_url",
            "factors",
            "reason",
            "policy",
            "snapshot_url",
            "attendance_action",
            "attendance_id",
            "review_status",
            "reviewed_by_name",
            "reviewed_at",
            "review_note",
            "can_add_to_gallery",
        ]

    def get_snapshot_url(self, obj):
        if obj.snapshot_path:
            return _media_url(obj.snapshot_path)
        if obj.journey_person_id:
            return _journey_snapshot(obj)
        return None

    def get_matched_entry_image_url(self, obj):
        return _media_url(obj.matched_entry.image_path) if obj.matched_entry_id and obj.matched_entry else None

    def get_can_add_to_gallery(self, obj):
        return bool(obj.probe_embedding)


class ModeSerializer(serializers.Serializer):
    recognition_mode = serializers.ChoiceField(choices=RecognitionMode.choices)


class ApproveSerializer(serializers.Serializer):
    staff_id = serializers.IntegerField(required=False)
    # Omitted → True, except journey sightings (not attendance cameras).
    mark_attendance = serializers.BooleanField(required=False, allow_null=True, default=None)
    add_to_gallery = serializers.BooleanField(default=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class RejectSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class UnknownClusterSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source="staff.full_name", read_only=True, default=None)
    member_codes = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    candidate = serializers.SerializerMethodField()

    class Meta:
        model = UnknownCluster
        fields = [
            "id",
            "code",
            "status",
            "staff",
            "staff_name",
            "person_count",
            "observation_count",
            "camera_ids",
            "first_seen",
            "last_seen",
            "member_codes",
            "thumbnail_url",
            "candidate",
            "rejected_staff_ids",
            "note",
        ]

    def get_member_codes(self, obj):
        return [m.journey_person.code for m in obj.members.all()]

    def get_thumbnail_url(self, obj):
        from person_journey.snapshot_utils import journey_person_latest_snapshot_url

        for m in obj.members.all():
            url = journey_person_latest_snapshot_url(m.journey_person)
            if url:
                return _media_url(url)
        return None

    def get_candidate(self, obj):
        d = obj.candidate_decision
        if d is None:
            return None
        return {
            "decision_id": d.pk,
            "staff_id": d.staff_id,
            "staff_name": d.staff.full_name if d.staff_id else None,
            "outcome": d.outcome,
            "face_similarity": d.face_similarity,
            "confidence": d.confidence,
            "review_status": d.review_status,
        }


class AssignClusterSerializer(serializers.Serializer):
    staff_id = serializers.IntegerField()
    add_to_gallery = serializers.BooleanField(default=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")
