from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from identity.models import (
    ClusterStatus,
    FaceGalleryEntry,
    IdentityDecision,
    PersonObservation,
    ReviewStatus,
    UnknownCluster,
)
from identity.serializers import (
    ApproveSerializer,
    AssignClusterSerializer,
    FaceGalleryEntrySerializer,
    IdentityDecisionSerializer,
    IdentityProfileSerializer,
    ModeSerializer,
    RejectSerializer,
    UnknownClusterSerializer,
    _media_url,
)
from identity.services.attendance_policy import (
    approve_decision,
    automatic_readiness,
    get_profile,
    reject_decision,
)
from identity.services.clustering import assign_cluster, run_unknown_clustering
from identity.services.gallery import INSIGHTFACE_MODEL, SFACE_MODEL, get_gallery_index
from users.models import Staff
from users.permissions import IsAdminOrHR


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _gallery_sizes(staff_ids=None) -> dict[tuple[int, str], int]:
    qs = FaceGalleryEntry.objects.filter(is_active=True)
    if staff_ids is not None:
        qs = qs.filter(staff_id__in=staff_ids)
    return {
        (row["staff_id"], row["model_name"]): row["n"]
        for row in qs.values("staff_id", "model_name").annotate(n=Count("id"))
    }


def _profile_data(profile, sizes: dict, pending: int | None = None) -> dict:
    data = IdentityProfileSerializer(profile).data
    # Attendance readiness is judged on the InsightFace (attendance) gallery.
    data["gallery_size"] = sizes.get((profile.staff_id, INSIGHTFACE_MODEL), 0)
    data["journey_gallery_size"] = sizes.get((profile.staff_id, SFACE_MODEL), 0)
    if pending is not None:
        data["pending_reviews"] = pending
    data["automatic_readiness"] = automatic_readiness(profile, data["gallery_size"])
    return data


def _profile_payload(staff: Staff) -> dict:
    return _profile_data(get_profile(staff), _gallery_sizes([staff.pk]))


class IdentityProfileListView(APIView):
    """All employees with identity mode, gallery size and readiness."""

    permission_classes = [IsAdminOrHR]

    def get(self, request):
        staff_qs = Staff.objects.filter(
            Q(face_enrollment__is_trained=True) | Q(face_gallery__is_active=True)
        ).distinct()
        sizes = _gallery_sizes()
        pending = dict(
            IdentityDecision.objects.filter(review_status=ReviewStatus.PENDING)
            .values("staff_id")
            .annotate(n=Count("id"))
            .values_list("staff_id", "n")
        )
        rows = []
        for staff in staff_qs.order_by("full_name"):
            rows.append(_profile_data(get_profile(staff), sizes, pending.get(staff.pk, 0)))
        loaded = {}
        for model in (INSIGHTFACE_MODEL, SFACE_MODEL):
            index = get_gallery_index(model)
            index.refresh()
            loaded[model] = index.size
        return Response({"results": rows, "gallery_loaded_staff": loaded})


class StaffIdentityView(APIView):
    """Profile + gallery for one employee."""

    permission_classes = [IsAdminOrHR]

    def get(self, request, staff_id):
        staff = get_object_or_404(Staff, pk=staff_id)
        entries = FaceGalleryEntry.objects.filter(staff=staff).select_related("camera", "approved_by")
        if request.query_params.get("include_inactive") not in ("1", "true"):
            entries = entries.filter(is_active=True)
        return Response(
            {
                "profile": _profile_payload(staff),
                "gallery": FaceGalleryEntrySerializer(entries, many=True).data,
            }
        )


class StaffModeView(APIView):
    """Manual → Assisted → Automatic is always a human decision."""

    permission_classes = [IsAdminOrHR]

    def post(self, request, staff_id):
        staff = get_object_or_404(Staff, pk=staff_id)
        ser = ModeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        profile = get_profile(staff)
        profile.recognition_mode = ser.validated_data["recognition_mode"]
        profile.mode_changed_by = request.user if request.user.is_authenticated else None
        profile.mode_changed_at = timezone.now()
        profile.save(update_fields=["recognition_mode", "mode_changed_by", "mode_changed_at", "updated_at"])
        return Response(_profile_payload(staff))


class GalleryEntryView(APIView):
    permission_classes = [IsAdminOrHR]

    def delete(self, request, entry_id):
        """Deactivate (never hard-delete — the audit trail may reference it)."""
        entry = get_object_or_404(FaceGalleryEntry, pk=entry_id)
        entry.is_active = False
        entry.save(update_fields=["is_active"])
        get_gallery_index().refresh(force=True)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def post(self, request, entry_id):
        entry = get_object_or_404(FaceGalleryEntry, pk=entry_id)
        entry.is_active = True
        entry.save(update_fields=["is_active"])
        get_gallery_index().refresh(force=True)
        return Response(FaceGalleryEntrySerializer(entry).data)


class DecisionListView(APIView):
    """Audit trail + review queue. Filters: outcome, review_status, staff, camera, source, date."""

    permission_classes = [IsAdminOrHR]

    def get(self, request):
        qs = IdentityDecision.objects.select_related("staff", "reviewed_by", "matched_entry")
        p = request.query_params
        for field in ("outcome", "review_status", "source"):
            if p.get(field):
                qs = qs.filter(**{field: p[field]})
        if p.get("staff"):
            qs = qs.filter(staff_id=_int(p["staff"], 0))
        if p.get("camera"):
            qs = qs.filter(camera_id=_int(p["camera"], 0))
        if p.get("date"):
            qs = qs.filter(created_at__date=p["date"])
        limit = min(max(_int(p.get("limit"), 50), 1), 200)
        offset = max(_int(p.get("offset"), 0), 0)
        total = qs.count()
        rows = qs[offset: offset + limit]
        return Response(
            {
                "count": total,
                "pending_total": IdentityDecision.objects.filter(review_status=ReviewStatus.PENDING).count(),
                "results": IdentityDecisionSerializer(rows, many=True).data,
            }
        )


class DecisionDetailView(APIView):
    """"Why did TekEye identify this person as Ahmed?" — the full evidence."""

    permission_classes = [IsAdminOrHR]

    def get(self, request, decision_id):
        decision = get_object_or_404(
            IdentityDecision.objects.select_related("staff", "reviewed_by", "matched_entry"), pk=decision_id
        )
        data = IdentityDecisionSerializer(decision).data
        if decision.staff_id:
            data["candidate_gallery"] = FaceGalleryEntrySerializer(
                FaceGalleryEntry.objects.filter(staff_id=decision.staff_id, is_active=True)[:12], many=True
            ).data
        return Response(data)


class DecisionApproveView(APIView):
    permission_classes = [IsAdminOrHR]

    def post(self, request, decision_id):
        decision = get_object_or_404(IdentityDecision, pk=decision_id)
        if decision.review_status in (ReviewStatus.APPROVED, ReviewStatus.REJECTED):
            return Response({"detail": f"Already {decision.review_status}."}, status=status.HTTP_409_CONFLICT)
        ser = ApproveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        staff = None
        if ser.validated_data.get("staff_id"):
            staff = get_object_or_404(Staff.objects.select_related("user"), pk=ser.validated_data["staff_id"])
        try:
            result = approve_decision(
                decision,
                user=request.user,
                staff=staff,
                mark_attendance=ser.validated_data["mark_attendance"],
                add_to_gallery=ser.validated_data["add_to_gallery"],
                note=ser.validated_data["note"],
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        decision.refresh_from_db()
        return Response({**result, "decision": IdentityDecisionSerializer(decision).data})


class DecisionRejectView(APIView):
    permission_classes = [IsAdminOrHR]

    def post(self, request, decision_id):
        decision = get_object_or_404(IdentityDecision, pk=decision_id)
        if decision.review_status in (ReviewStatus.APPROVED, ReviewStatus.REJECTED):
            return Response({"detail": f"Already {decision.review_status}."}, status=status.HTTP_409_CONFLICT)
        ser = RejectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        reject_decision(decision, user=request.user, note=ser.validated_data["note"])
        decision.refresh_from_db()
        return Response(IdentityDecisionSerializer(decision).data)


# ── unknown-person clusters ──────────────────────────────────────────────


class ClusterListView(APIView):
    """Unknown-person clusters (UP-codes). ?status=open|identified|dismissed|all"""

    permission_classes = [IsAdminOrHR]

    def get(self, request):
        qs = UnknownCluster.objects.select_related("staff", "candidate_decision__staff").prefetch_related(
            "members__journey_person"
        )
        status_filter = request.query_params.get("status") or ClusterStatus.OPEN
        if status_filter != "all":
            qs = qs.filter(status=status_filter)
        limit = min(max(_int(request.query_params.get("limit"), 60), 1), 200)
        return Response({"count": qs.count(), "results": UnknownClusterSerializer(qs[:limit], many=True).data})


class ClusterDetailView(APIView):
    permission_classes = [IsAdminOrHR]

    def get(self, request, cluster_id):
        from person_journey.snapshot_utils import journey_person_latest_snapshot_url

        cluster = get_object_or_404(
            UnknownCluster.objects.select_related("staff", "candidate_decision__staff").prefetch_related(
                "members__journey_person__latest_camera"
            ),
            pk=cluster_id,
        )
        data = UnknownClusterSerializer(cluster).data
        data["members"] = [
            {
                "code": m.journey_person.code,
                "uuid": str(m.journey_person.uuid),
                "person_type": m.journey_person.person_type,
                "latest_camera": getattr(m.journey_person.latest_camera, "name", None),
                "latest_seen_at": m.journey_person.latest_seen_at,
                "snapshot_url": _media_url(journey_person_latest_snapshot_url(m.journey_person) or ""),
                "observations": m.journey_person.observations.count(),
            }
            for m in cluster.members.all()
        ]
        obs = (
            PersonObservation.objects.filter(journey_person__unknown_cluster_membership__cluster=cluster)
            .select_related("camera", "journey_person")
            .order_by("-created_at")[:40]
        )
        data["observations"] = [
            {
                "id": o.pk,
                "at": o.created_at,
                "camera": getattr(o.camera, "name", None),
                "track_id": o.track_id,
                "person_code": o.journey_person.code,
                "has_face": bool(o.face_embedding),
                "snapshot_url": _media_url(o.snapshot_path),
            }
            for o in obs
        ]
        return Response(data)


class ClusterAssignView(APIView):
    """Reviewer says who this unknown person is: merges journeys and learns faces."""

    permission_classes = [IsAdminOrHR]

    def post(self, request, cluster_id):
        cluster = get_object_or_404(UnknownCluster, pk=cluster_id)
        if cluster.status != ClusterStatus.OPEN:
            return Response({"detail": f"Cluster already {cluster.status}."}, status=status.HTTP_409_CONFLICT)
        ser = AssignClusterSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        staff = get_object_or_404(Staff, pk=ser.validated_data["staff_id"])
        result = assign_cluster(
            cluster,
            staff=staff,
            user=request.user,
            note=ser.validated_data["note"],
            add_to_gallery=ser.validated_data["add_to_gallery"],
        )
        return Response(result)


class ClusterDismissView(APIView):
    """Not an employee (visitor, contractor, noise) — stop suggesting."""

    permission_classes = [IsAdminOrHR]

    def post(self, request, cluster_id):
        cluster = get_object_or_404(UnknownCluster.objects.select_related("candidate_decision"), pk=cluster_id)
        cluster.status = ClusterStatus.DISMISSED
        cluster.note = str(request.data.get("note") or "")
        cluster.save(update_fields=["status", "note", "updated_at"])
        pending = cluster.candidate_decision
        if pending is not None and pending.review_status == ReviewStatus.PENDING:
            reject_decision(pending, user=request.user, note="cluster dismissed")
        return Response({"status": cluster.status})


class ClusterRunView(APIView):
    permission_classes = [IsAdminOrHR]

    def post(self, request):
        return Response(run_unknown_clustering())
