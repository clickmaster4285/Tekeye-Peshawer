"""Employee-monitoring REST API.

Mounted at /api/v1/employee-monitor/. Every endpoint requires authentication (the project's
ExpiringTokenAuthentication) and returns 501 when the deployment has monitoring disabled, so the
mobile client can show an honest "not set up" state instead of guessing.
"""

from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from rest_framework import permissions, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from users.permissions import can_view_all_staff

from .models import (
    EmployeeCallRecord,
    EmployeeCallRecording,
    MonitoringConsent,
    MonitoringPolicy,
)
from .serializers import (
    CallMetadataBatchSerializer,
    ConsentInSerializer,
    RecordingUploadRequestSerializer,
    call_payload,
    policy_payload,
    recording_payload,
)
from .services import (
    deployment_id,
    feature_enabled,
    mask_number,
    playback_expiry,
    record_audit,
    retention_days,
    scope_queryset,
    sign_playback,
    storage_path,
    unsign_playback,
)

User = get_user_model()


class FeatureDisabled(APIException):
    status_code = status.HTTP_501_NOT_IMPLEMENTED
    default_detail = "Employee monitoring is not enabled on this deployment."
    default_code = "feature_disabled"


class MonitorView(APIView):
    """Base: authenticated + feature-flag gate shared by every endpoint."""

    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        # Deployment-wide switch; raising here keeps DRF's renderer/exception handling intact.
        if not feature_enabled():
            raise FeatureDisabled()


class IngestView(MonitorView):
    """Endpoints that accept data from an approved source — restricted to overview roles."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not can_view_all_staff(request.user):
            self.permission_denied(request, message="Not permitted to ingest monitoring data.")


class MeView(MonitorView):
    def get(self, request):
        overview = can_view_all_staff(request.user)
        return Response({
            "username": request.user.get_username(),
            "deployment_id": deployment_id(),
            "is_overview": overview,
            "allowed_features": {
                "work_location": True,
                "call_metadata": True,
                "recording_playback": True,
                "activity_summary": False,
            },
        })


class PolicyCurrentView(MonitorView):
    def get(self, request):
        policy = MonitoringPolicy.objects.filter(is_active=True).order_by("-effective_at").first()
        if not policy:
            return Response(
                {"error": {"code": "NO_POLICY", "message": "No active monitoring policy is published."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(policy_payload(policy))


class ConsentView(MonitorView):
    """GET current consent state; POST acknowledge/withdraw."""

    def get(self, request):
        latest = MonitoringConsent.objects.filter(user=request.user).select_related("policy").first()
        if not latest:
            return Response({"consent_id": None, "status": "none", "policy_version": None, "effective_at": None})
        return Response({
            "consent_id": str(latest.id),
            "status": latest.status,
            "policy_version": latest.policy.version,
            "effective_at": latest.created_at.isoformat(),
        })

    def post(self, request):
        ser = ConsentInSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        policy = MonitoringPolicy.objects.filter(id=data["policy_id"]).first()
        if not policy:
            return Response(
                {"error": {"code": "NO_POLICY", "message": "Unknown policy."}}, status=status.HTTP_404_NOT_FOUND
            )
        consent = MonitoringConsent.objects.create(
            user=request.user,
            policy=policy,
            status=MonitoringConsent.ACKNOWLEDGED if data["action"] == "acknowledge" else MonitoringConsent.WITHDRAWN,
            disclosed_categories=data.get("disclosed_categories") or [],
        )
        record_audit(
            request,
            action=f"consent_{data['action']}",
            target_type="policy",
            target_id=policy.version,
        )
        return Response(
            {
                "consent_id": str(consent.id),
                "status": consent.status,
                "policy_version": policy.version,
                "effective_at": consent.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


class DataCategoriesView(MonitorView):
    def get(self, request):
        policy = MonitoringPolicy.objects.filter(is_active=True).order_by("-effective_at").first()
        categories = []
        for c in (policy.categories if policy else []) or []:
            categories.append({
                "key": c.get("key", ""),
                "label": c.get("label", ""),
                "purpose": c.get("description", ""),
                "collected": c.get("collected", True),
                "retention_days": c.get("retention_days"),
                "measurement": c.get("measurement"),
            })
        return Response({"categories": categories})


class CallsView(MonitorView):
    def get(self, request):
        qs = scope_queryset(EmployeeCallRecord.objects.all(), request.user)
        date = (request.query_params.get("date") or "").strip()
        if date:
            qs = qs.filter(started_at__date=date)
        username = (request.query_params.get("username") or "").strip()
        if username and can_view_all_staff(request.user):
            qs = qs.filter(user__username=username)
        qs = qs.prefetch_related("recordings")[:200]
        return Response({"results": [call_payload(c) for c in qs], "count": len(qs), "next_cursor": None})


class CallMetadataBatchView(IngestView):
    def post(self, request):
        ser = CallMetadataBatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        source = ser.validated_data["source"]
        source_label = ser.validated_data.get("source_label", "")
        accepted, duplicates = [], []
        for ev in ser.validated_data["events"]:
            user = User.objects.filter(username=ev["username"]).first() if ev.get("username") else None
            try:
                with transaction.atomic():
                    EmployeeCallRecord.objects.create(
                        user=user,
                        direction=ev["direction"],
                        number=ev.get("number", ""),
                        masked_number=mask_number(ev.get("number", "")),
                        started_at=ev["started_at"],
                        ended_at=ev.get("ended_at"),
                        duration_seconds=ev.get("duration_seconds"),
                        source=source,
                        source_label=source_label,
                        source_event_id=ev["source_event_id"],
                        recording_status=ev["recording_status"],
                    )
                accepted.append(ev["source_event_id"])
            except IntegrityError:
                duplicates.append(ev["source_event_id"])
        record_audit(request, action="call_metadata_ingest", target_type="call_batch",
                     reason=source, accepted=len(accepted), duplicates=len(duplicates))
        return Response({"accepted": accepted, "duplicates": duplicates, "rejected": []},
                        status=status.HTTP_201_CREATED)


class RecordingsView(MonitorView):
    def get(self, request):
        qs = scope_queryset(EmployeeCallRecording.objects.all(), request.user)
        date = (request.query_params.get("date") or "").strip()
        if date:
            qs = qs.filter(recorded_at__date=date)
        username = (request.query_params.get("username") or "").strip()
        if username and can_view_all_staff(request.user):
            qs = qs.filter(user__username=username)
        qs = list(qs[:200])
        overview = can_view_all_staff(request.user)
        results = [recording_payload(r, can_play=overview or r.user_id == request.user.id) for r in qs]
        return Response({"results": results, "count": len(results), "next_cursor": None})


class RecordingUploadRequestView(IngestView):
    """Authorize a single private upload. The app never receives storage credentials."""

    def post(self, request):
        ser = RecordingUploadRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        user = User.objects.filter(username=data["username"]).first() if data.get("username") else None
        call = None
        if data.get("source_call_event_id"):
            call = EmployeeCallRecord.objects.filter(
                source=data["source"], source_event_id=data["source_call_event_id"]
            ).first()
        storage_key = f"{data['source']}/{data['source_recording_id']}"
        rec, _ = EmployeeCallRecording.objects.update_or_create(
            source=data["source"],
            source_recording_id=data["source_recording_id"],
            defaults={
                "user": user or (call.user if call else None),
                "call": call,
                "content_type": data.get("content_type", "audio/mpeg"),
                "size_bytes": data.get("size_bytes"),
                "checksum_sha256": data.get("checksum_sha256", ""),
                "duration_seconds": data.get("duration_seconds"),
                "storage_key": storage_key,
                "status": EmployeeCallRecording.PENDING,
                "retention_deadline": playback_expiry(retention_days() * 86400) if retention_days() else None,
            },
        )
        record_audit(request, action="recording_upload_requested", target_type="recording", target_id=rec.id)
        return Response({
            "upload_id": str(rec.id),
            "status": "upload_authorized",
            "upload_method": "server_side_ingest",
            "storage_key": storage_key,
        }, status=status.HTTP_201_CREATED)


class RecordingUploadCompleteView(IngestView):
    def post(self, request, recording_id):
        rec = EmployeeCallRecording.objects.filter(id=recording_id).first()
        if not rec:
            raise Http404
        path = storage_path(rec.storage_key) if rec.storage_key else ""
        exists = bool(path) and os.path.exists(path)
        rec.status = EmployeeCallRecording.AVAILABLE if exists else EmployeeCallRecording.FAILED
        rec.save(update_fields=["status"])
        if rec.call_id and exists:
            EmployeeCallRecord.objects.filter(id=rec.call_id).update(recording_status=EmployeeCallRecord.AVAILABLE)
        record_audit(request, action="recording_upload_completed", target_type="recording",
                     target_id=rec.id, verified=exists)
        return Response({"id": str(rec.id), "status": rec.status})


class RecordingPlaybackView(MonitorView):
    """Issue a short-lived signed URL. Playback itself is audited at stream time."""

    def get(self, request, recording_id):
        rec = EmployeeCallRecording.objects.filter(id=recording_id).first()
        if not rec:
            raise Http404
        allowed = can_view_all_staff(request.user) or rec.user_id == request.user.id
        if not allowed:
            self.permission_denied(request, message="Not permitted to play this recording.")
        if rec.status != EmployeeCallRecording.AVAILABLE:
            return Response(
                {"error": {"code": "RECORDING_UNAVAILABLE", "message": "Recording is not available."}},
                status=status.HTTP_409_CONFLICT,
            )
        token = sign_playback(str(rec.id))
        record_audit(request, action="recording_playback_authorized", target_type="recording", target_id=rec.id)
        url = request.build_absolute_uri(f"/api/v1/employee-monitor/recordings/stream/?t={token}")
        return Response({"url": url, "expires_at": playback_expiry().isoformat()})


class RecordingStreamView(MonitorView):
    """Stream the audio for a valid, unexpired signed token belonging to a permitted user."""

    def get(self, request):
        token = request.query_params.get("t", "")
        rec_id = unsign_playback(token)
        if not rec_id:
            raise Http404
        rec = EmployeeCallRecording.objects.filter(id=rec_id).first()
        if not rec or rec.status != EmployeeCallRecording.AVAILABLE:
            raise Http404
        if not (can_view_all_staff(request.user) or rec.user_id == request.user.id):
            self.permission_denied(request, message="Not permitted.")
        path = storage_path(rec.storage_key) if rec.storage_key else ""
        if not path or not os.path.exists(path):
            raise Http404
        record_audit(request, action="recording_streamed", target_type="recording", target_id=rec.id)
        return FileResponse(open(path, "rb"), content_type=rec.content_type or "audio/mpeg")
