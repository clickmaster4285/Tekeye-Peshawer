from __future__ import annotations

from rest_framework import serializers

from .models import EmployeeCallRecord, EmployeeCallRecording, MonitoringPolicy


def policy_payload(policy: MonitoringPolicy) -> dict:
    return {
        "policy_id": str(policy.id),
        "policy_version": policy.version,
        "effective_at": policy.effective_at.isoformat(),
        "summary": policy.summary,
        "work_hours": policy.work_hours,
        "contact": policy.contact,
        "categories": policy.categories or [],
    }


def call_payload(call: EmployeeCallRecord) -> dict:
    return {
        "id": str(call.id),
        "direction": call.direction,
        "masked_number": call.masked_number or None,
        "started_at": call.started_at.isoformat() if call.started_at else None,
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
        "duration_seconds": call.duration_seconds,
        "source": call.source,
        "source_label": call.source_label,
        "recording_status": call.recording_status,
        "recording_id": str(call.recordings.first().id) if call.recordings.exists() else None,
    }


def recording_payload(rec: EmployeeCallRecording, *, can_play: bool) -> dict:
    return {
        "id": str(rec.id),
        "call_id": str(rec.call_id) if rec.call_id else None,
        "source": rec.source,
        "source_label": rec.source_label,
        "recorded_at": rec.recorded_at.isoformat() if rec.recorded_at else None,
        "duration_seconds": rec.duration_seconds,
        "status": rec.status,
        "can_play": bool(can_play and rec.status == EmployeeCallRecording.AVAILABLE),
    }


class ConsentInSerializer(serializers.Serializer):
    policy_id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=["acknowledge", "withdraw"])
    disclosed_categories = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class CallMetadataEventSerializer(serializers.Serializer):
    source_event_id = serializers.CharField(max_length=120)
    direction = serializers.ChoiceField(
        choices=[c[0] for c in EmployeeCallRecord.DIRECTION_CHOICES], default=EmployeeCallRecord.UNKNOWN
    )
    number = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    username = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    started_at = serializers.DateTimeField()
    ended_at = serializers.DateTimeField(required=False, allow_null=True)
    duration_seconds = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    recording_status = serializers.ChoiceField(
        choices=[c[0] for c in EmployeeCallRecord.REC_STATUS_CHOICES], default=EmployeeCallRecord.UNAVAILABLE
    )


class CallMetadataBatchSerializer(serializers.Serializer):
    source = serializers.CharField(max_length=60)
    source_label = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    events = CallMetadataEventSerializer(many=True)


class RecordingUploadRequestSerializer(serializers.Serializer):
    source = serializers.CharField(max_length=60)
    source_recording_id = serializers.CharField(max_length=120)
    source_call_event_id = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    username = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    content_type = serializers.CharField(max_length=60, required=False, default="audio/mpeg")
    size_bytes = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    checksum_sha256 = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    duration_seconds = serializers.IntegerField(required=False, allow_null=True, min_value=0)
