"""HQ Sync HTTP API (Phases 1, 4, 5, 6, 7)."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from city_sync.auth import SyncApiKeyAuthentication, SyncPrincipal
from city_sync.hq_receiver import apply_event_batch
from city_sync.identity import identity_dict, is_hq, location_code, system_role
from city_sync.media_sync import hq_media_chunk, hq_media_complete, hq_media_init
from city_sync.models import BackupRecord, HqCityStatus, HqMediaObject, HqSyncCursor, ReconcileReport
from city_sync.reference_sync import reference_changes_since


class IsSyncPrincipal(BasePermission):
    def has_permission(self, request, view):
        return isinstance(getattr(request, "user", None), SyncPrincipal)


class IsHqRole(BasePermission):
    def has_permission(self, request, view):
        return is_hq()


class NodeIdentityView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(identity_dict())


class SyncEventsView(APIView):
    authentication_classes = [SyncApiKeyAuthentication]
    permission_classes = [IsHqRole, IsSyncPrincipal]

    def post(self, request):
        principal: SyncPrincipal = request.user
        body = request.data if isinstance(request.data, dict) else {}
        req_loc = str(body.get("location_code") or "").strip().upper()
        if req_loc and req_loc != principal.location_code.upper():
            return Response(
                {"detail": "location_code does not match credential"},
                status=status.HTTP_403_FORBIDDEN,
            )
        events = body.get("events")
        if not isinstance(events, list):
            return Response({"detail": "events must be a list"}, status=status.HTTP_400_BAD_REQUEST)
        max_batch = int(getattr(settings, "SYNC_MAX_BATCH_SIZE_ACCEPTED", 500))
        if len(events) > max_batch:
            return Response(
                {"detail": f"batch too large (max {max_batch})"},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        results = apply_event_batch(events, credential_location=principal.location_code)
        return Response({"results": results})


class SyncHeartbeatView(APIView):
    authentication_classes = [SyncApiKeyAuthentication]
    permission_classes = [IsHqRole, IsSyncPrincipal]

    def post(self, request):
        principal: SyncPrincipal = request.user
        body = request.data if isinstance(request.data, dict) else {}
        loc = principal.location_code.upper()
        row, _ = HqCityStatus.objects.get_or_create(location_code=loc)
        row.node_id = str(body.get("node_id") or "")[:128]
        row.app_version = str(body.get("app_version") or "")[:64]
        try:
            row.schema_version = int(body.get("schema_version") or 1)
        except (TypeError, ValueError):
            row.schema_version = 1
        for field, key in (
            ("pending_outbox", "pending_outbox"),
            ("oldest_pending_age_sec", "oldest_pending_age_sec"),
            ("dead_outbox", "dead_outbox"),
            ("pending_media", "pending_media"),
            ("failed_media", "failed_media"),
        ):
            try:
                setattr(row, field, int(body.get(key) or 0))
            except (TypeError, ValueError):
                setattr(row, field, 0)
        try:
            row.disk_percent = float(body["disk_percent"]) if body.get("disk_percent") is not None else None
        except (TypeError, ValueError):
            row.disk_percent = None
        raw_backup = body.get("last_backup_at")
        if raw_backup:
            dt = parse_datetime(str(raw_backup))
            if dt is not None:
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                row.last_backup_at = dt
        raw_biz = body.get("last_business_event_at")
        if raw_biz:
            dt = parse_datetime(str(raw_biz))
            if dt is not None:
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                row.last_business_event_at = dt
        row.last_heartbeat_at = timezone.now()
        row.raw = body
        row.save()
        return Response({"ok": True, "location_code": loc})


class SyncCursorView(APIView):
    authentication_classes = [SyncApiKeyAuthentication]
    permission_classes = [IsHqRole, IsSyncPrincipal]

    def get(self, request):
        principal: SyncPrincipal = request.user
        loc = principal.location_code.upper()
        cursor = HqSyncCursor.objects.filter(location_code=loc).first()
        return Response(
            {
                "location_code": loc,
                "last_seq_applied": cursor.last_seq_applied if cursor else 0,
                "last_success_at": cursor.last_success_at if cursor else None,
            }
        )


class ReferencePullView(APIView):
    """GET /reference?since= — cities pull HQ-owned reference data (Phase 6)."""

    authentication_classes = [SyncApiKeyAuthentication]
    permission_classes = [IsHqRole, IsSyncPrincipal]

    def get(self, request):
        since_raw = request.query_params.get("since")
        since = parse_datetime(since_raw) if since_raw else None
        if since and timezone.is_naive(since):
            since = timezone.make_aware(since, timezone.get_current_timezone())
        items = reference_changes_since(since)
        return Response({"items": items, "count": len(items)})


class MediaInitView(APIView):
    authentication_classes = [SyncApiKeyAuthentication]
    permission_classes = [IsHqRole, IsSyncPrincipal]

    def post(self, request):
        principal: SyncPrincipal = request.user
        body = request.data if isinstance(request.data, dict) else {}
        loc = principal.location_code.upper()
        if str(body.get("location_code") or loc).upper() != loc:
            return Response({"detail": "location mismatch"}, status=status.HTTP_403_FORBIDDEN)
        try:
            with transaction.atomic():
                result = hq_media_init(
                    loc=loc,
                    media_id=str(body.get("media_id")),
                    sha256=str(body.get("sha256") or ""),
                    size_bytes=int(body.get("size_bytes") or 0),
                    entity_type=str(body.get("record_entity_type") or ""),
                    entity_id=body.get("record_entity_id"),
                )
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class MediaChunkView(APIView):
    authentication_classes = [SyncApiKeyAuthentication]
    permission_classes = [IsHqRole, IsSyncPrincipal]

    def put(self, request, media_id: str):
        principal: SyncPrincipal = request.user
        loc = principal.location_code.upper()
        try:
            offset = int(request.META.get("HTTP_X_CIIS_OFFSET") or 0)
        except ValueError:
            return Response({"detail": "bad offset"}, status=status.HTTP_400_BAD_REQUEST)
        data = request.body or b""
        try:
            with transaction.atomic():
                result = hq_media_chunk(loc=loc, media_id=media_id, offset=offset, data=data)
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class MediaCompleteView(APIView):
    authentication_classes = [SyncApiKeyAuthentication]
    permission_classes = [IsHqRole, IsSyncPrincipal]

    def post(self, request, media_id: str):
        principal: SyncPrincipal = request.user
        body = request.data if isinstance(request.data, dict) else {}
        loc = principal.location_code.upper()
        try:
            with transaction.atomic():
                result = hq_media_complete(
                    loc=loc,
                    media_id=media_id,
                    sha256=str(body.get("sha256") or ""),
                )
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        code = status.HTTP_200_OK if result.get("verified") else status.HTTP_409_CONFLICT
        return Response(result, status=code)


class CityStatusListView(APIView):
    """HQ Grid — HQ tables only (Phase 7)."""

    permission_classes = [AllowAny]

    def get(self, request):
        if not is_hq() and not getattr(settings, "DEBUG", False):
            return Response({"detail": "HQ only"}, status=status.HTTP_403_FORBIDDEN)
        now = timezone.now()
        offline_after = int(getattr(settings, "SYNC_GRID_OFFLINE_AFTER_SEC", 90))
        backup_stale_h = float(getattr(settings, "SYNC_BACKUP_STALE_HOURS", 26))
        rows = []
        for st in HqCityStatus.objects.all().order_by("location_code"):
            age = None
            state = "UNKNOWN"
            if st.last_heartbeat_at:
                age = int((now - st.last_heartbeat_at).total_seconds())
                if age > 1800:
                    state = "LONG_OFFLINE"
                elif age > offline_after:
                    state = "OFFLINE"
                elif (
                    st.dead_outbox > 0
                    or st.oldest_pending_age_sec > 300
                    or st.failed_media > 0
                    or not st.last_reconcile_ok
                ):
                    state = "DEGRADED"
                else:
                    state = "ONLINE"
            backup_state = "UNKNOWN"
            if st.last_backup_at:
                bak_age_h = (now - st.last_backup_at).total_seconds() / 3600.0
                backup_state = "STALE-BACKUP" if bak_age_h > backup_stale_h else "OK"
            media_verified = HqMediaObject.objects.filter(
                location_code=st.location_code, status=HqMediaObject.STATUS_VERIFIED
            ).count()
            rows.append(
                {
                    "location_code": st.location_code,
                    "state": state,
                    "backup_state": backup_state,
                    "heartbeat_age_sec": age,
                    "pending_outbox": st.pending_outbox,
                    "dead_outbox": st.dead_outbox,
                    "oldest_pending_age_sec": st.oldest_pending_age_sec,
                    "pending_media": st.pending_media,
                    "failed_media": st.failed_media,
                    "media_verified": media_verified,
                    "app_version": st.app_version,
                    "schema_version": st.schema_version,
                    "last_heartbeat_at": st.last_heartbeat_at,
                    "last_backup_at": st.last_backup_at,
                    "last_reconcile_at": st.last_reconcile_at,
                    "last_reconcile_ok": st.last_reconcile_ok,
                    "reconcile_mismatch_count": st.reconcile_mismatch_count,
                    "disk_percent": st.disk_percent,
                }
            )
        latest_reconcile = list(
            ReconcileReport.objects.order_by("-created_at")[:20].values(
                "location_code", "day", "entity_type", "ok", "city_count", "hq_count", "created_at"
            )
        )
        return Response(
            {
                "hq_location": location_code(),
                "hq_role": system_role(),
                "cities": rows,
                "recent_reconcile": latest_reconcile,
                "backup_records_24h": BackupRecord.objects.filter(
                    completed_at__gte=now - timedelta(hours=24)
                ).count(),
            }
        )
