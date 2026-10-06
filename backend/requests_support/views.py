from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .engine import DuplicateRequestError, create_request, log_event
from .models import (
    Category,
    Department,
    Priority,
    SupportTicket,
    TicketComment,
    TicketStatus,
)
from .permissions import (
    HasSupportModuleAccess,
    capabilities_for,
    is_developer_user,
    is_handler_user,
    is_it_user,
    is_requester_user,
    is_support_user,
)
from .serializers import (
    AssignSerializer,
    ClientConfirmSerializer,
    CommentCreateSerializer,
    CreateRequestSerializer,
    ResolutionSerializer,
    SupportTicketDetailSerializer,
    SupportTicketListSerializer,
    TicketCommentSerializer,
    TriageSerializer,
    VerifySerializer,
)


def _mark_first_response(ticket: SupportTicket):
    if not ticket.first_response_at:
        ticket.first_response_at = timezone.now()


def _ensure_active(ticket: SupportTicket):
    """Expire if needed; return error Response when ticket is no longer actionable."""
    ticket.expire_if_needed()
    if ticket.status == TicketStatus.EXPIRED:
        return Response(
            {
                "detail": "This ticket expired after 24 hours and is no longer valid.",
                "status": ticket.status,
                "expires_at": ticket.expires_at,
            },
            status=status.HTTP_410_GONE,
        )
    if ticket.status in (TicketStatus.CLOSED, TicketStatus.CANCELLED):
        return Response(
            {"detail": f"Ticket is {ticket.status} and cannot be updated.", "status": ticket.status},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


def _can_chat_on_ticket(user, ticket: SupportTicket) -> bool:
    if is_support_user(user):
        return True
    if ticket.requester_id == getattr(user, "id", None):
        return True
    if is_handler_user(user) and (
        ticket.assigned_to_id == user.id
        or ticket.department
        in (
            Department.IT if is_it_user(user) else "",
            Department.DEVELOPER if is_developer_user(user) else "",
        )
    ):
        return True
    return False


class SupportMeView(APIView):
    permission_classes = [IsAuthenticated, HasSupportModuleAccess]

    def get(self, request):
        return Response(capabilities_for(request.user))


class SupportDashboardView(APIView):
    permission_classes = [IsAuthenticated, HasSupportModuleAccess]

    def get(self, request):
        user = request.user
        caps = capabilities_for(user)
        base = SupportTicket.objects.all()

        if caps["can_view_all"]:
            qs = base
        elif caps["can_handle_it"] and not caps["can_handle_developer"]:
            qs = base.filter(Q(department=Department.IT) | Q(assigned_to=user))
        elif caps["can_handle_developer"] and not caps["can_handle_it"]:
            qs = base.filter(Q(department=Department.DEVELOPER) | Q(assigned_to=user))
        elif caps["can_handle_it"] and caps["can_handle_developer"]:
            qs = base.filter(
                Q(department__in=[Department.IT, Department.DEVELOPER]) | Q(assigned_to=user)
            )
        else:
            qs = base.filter(requester=user)

        # Refresh SLA flags lightly for open tickets in dashboard scope
        for t in qs.filter(sla_breached=False).exclude(
            status__in=[TicketStatus.CLOSED, TicketStatus.CANCELLED]
        )[:200]:
            t.refresh_sla_breach()

        terminal = [TicketStatus.CLOSED, TicketStatus.CANCELLED, TicketStatus.EXPIRED]
        open_qs = qs.exclude(status__in=terminal)

        def _count_metric(key: str, queryset):
            return queryset.count()

        metrics = {
            "total_open": open_qs,
            "new": qs.filter(status__in=[TicketStatus.NEW, TicketStatus.TRIAGED, TicketStatus.REOPENED]),
            "unassigned": qs.filter(
                status__in=[TicketStatus.NEW, TicketStatus.TRIAGED],
                assigned_to__isnull=True,
            ),
            "assigned": qs.filter(status=TicketStatus.ASSIGNED),
            "in_progress": qs.filter(status=TicketStatus.IN_PROGRESS),
            "resolution_submitted": qs.filter(status=TicketStatus.RESOLUTION_SUBMITTED),
            "waiting_client": qs.filter(status=TicketStatus.PENDING_CLIENT_CONFIRM),
            "sla_breached": qs.filter(sla_breached=True).exclude(status__in=terminal),
            "it_queue": qs.filter(department=Department.IT).exclude(status__in=terminal),
            "developer_queue": qs.filter(department=Department.DEVELOPER).exclude(
                status__in=terminal
            ),
            "my_assigned": qs.filter(assigned_to=user).exclude(status__in=terminal),
            "my_requests": base.filter(requester=user).exclude(status__in=terminal),
            "closed": qs.filter(status=TicketStatus.CLOSED),
        }

        counts = {k: _count_metric(k, v) for k, v in metrics.items()}
        counts["by_priority"] = dict(
            open_qs.values("priority").annotate(c=Count("id")).values_list("priority", "c")
        )

        # Trends vs previous 7-day window + 7-day sparkline (created tickets)
        now = timezone.now()
        this_start = now - timedelta(days=7)
        prev_start = now - timedelta(days=14)

        def _trend_pct(this_n: int, prev_n: int) -> float:
            if prev_n == 0:
                return 100.0 if this_n > 0 else 0.0
            return round(((this_n - prev_n) / prev_n) * 100.0, 1)

        # Sparkline: tickets created per day in last 7 days (scoped qs)
        day_rows = (
            qs.filter(created_at__gte=this_start)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(c=Count("id"))
        )
        by_day = {row["day"]: row["c"] for row in day_rows}
        sparkline = []
        for i in range(6, -1, -1):
            d = (now - timedelta(days=i)).date()
            sparkline.append(by_day.get(d, 0))

        this_created = qs.filter(created_at__gte=this_start).count()
        prev_created = qs.filter(
            created_at__gte=prev_start, created_at__lt=this_start
        ).count()
        overall_trend = _trend_pct(this_created, prev_created)

        # Per-metric trend: compare open items created in windows (approximation)
        trends = {}
        for key, mq in metrics.items():
            this_n = mq.filter(created_at__gte=this_start).count()
            prev_n = mq.filter(created_at__gte=prev_start, created_at__lt=this_start).count()
            trends[key] = {
                "pct": _trend_pct(this_n, prev_n),
                "sparkline": sparkline,
            }
        # Use overall sparkline for all cards (activity trend); pct per metric

        recent = (
            qs.select_related("requester", "assigned_to")
            .order_by("-created_at")[:8]
        )
        return Response(
            {
                "capabilities": caps,
                "counts": counts,
                "trends": trends,
                "activity_trend_pct": overall_trend,
                "sparkline": sparkline,
                "recent": SupportTicketListSerializer(recent, many=True).data,
            }
        )


class SupportTicketViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasSupportModuleAccess]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return SupportTicketDetailSerializer
        if self.action == "create":
            return CreateRequestSerializer
        return SupportTicketListSerializer

    def retrieve(self, request, *args, **kwargs):
        ticket = self.get_object()
        ticket.expire_if_needed()
        return Response(
            SupportTicketDetailSerializer(ticket, context={"request": request}).data
        )

    def get_queryset(self):
        user = self.request.user
        caps = capabilities_for(user)
        # Lazily expire due tickets in the common open set
        due = SupportTicket.objects.filter(
            expires_at__lte=timezone.now(),
        ).exclude(
            status__in=[
                TicketStatus.CLOSED,
                TicketStatus.CANCELLED,
                TicketStatus.EXPIRED,
            ]
        )[:100]
        for t in due:
            t.expire_if_needed()

        qs = SupportTicket.objects.select_related(
            "requester",
            "assigned_to",
            "camera",
            "infra_site",
            "infra_device",
        ).prefetch_related("comments", "events")

        if not caps["can_view_all"]:
            if caps["can_handle_it"] and caps["can_handle_developer"]:
                qs = qs.filter(
                    Q(department__in=[Department.IT, Department.DEVELOPER])
                    | Q(assigned_to=user)
                    | Q(requester=user)
                )
            elif caps["can_handle_it"]:
                qs = qs.filter(
                    Q(department=Department.IT) | Q(assigned_to=user) | Q(requester=user)
                )
            elif caps["can_handle_developer"]:
                qs = qs.filter(
                    Q(department=Department.DEVELOPER)
                    | Q(assigned_to=user)
                    | Q(requester=user)
                )
            else:
                qs = qs.filter(requester=user)

        # Query filters
        params = self.request.query_params
        queue = (params.get("queue") or "").strip().lower()
        status_filter = (params.get("status") or "").strip()
        department = (params.get("department") or "").strip()
        priority = (params.get("priority") or "").strip()
        category = (params.get("category") or "").strip()
        search = (params.get("search") or "").strip()
        mine = params.get("mine") in ("1", "true", "yes")
        assigned_to_me = params.get("assigned_to_me") in ("1", "true", "yes")

        if queue == "new":
            qs = qs.filter(status=TicketStatus.NEW)
        elif queue == "review":
            qs = qs.filter(status__in=[TicketStatus.NEW, TicketStatus.TRIAGED, TicketStatus.REOPENED])
        elif queue == "unassigned":
            qs = qs.filter(assigned_to__isnull=True).exclude(
                status__in=[TicketStatus.CLOSED, TicketStatus.CANCELLED]
            )
        elif queue == "it":
            qs = qs.filter(department=Department.IT).exclude(
                status__in=[TicketStatus.CLOSED, TicketStatus.CANCELLED]
            )
        elif queue == "developer":
            qs = qs.filter(department=Department.DEVELOPER).exclude(
                status__in=[TicketStatus.CLOSED, TicketStatus.CANCELLED]
            )
        elif queue == "sla":
            qs = qs.filter(sla_breached=True).exclude(
                status__in=[TicketStatus.CLOSED, TicketStatus.CANCELLED]
            )
        elif queue == "waiting_client":
            qs = qs.filter(status=TicketStatus.PENDING_CLIENT_CONFIRM)
        elif queue == "resolution_submitted":
            qs = qs.filter(status=TicketStatus.RESOLUTION_SUBMITTED)
        elif queue == "resolved":
            qs = qs.filter(
                status__in=[
                    TicketStatus.RESOLUTION_SUBMITTED,
                    TicketStatus.SUPPORT_VERIFIED,
                    TicketStatus.PENDING_CLIENT_CONFIRM,
                ]
            )
        elif queue == "closed":
            qs = qs.filter(status=TicketStatus.CLOSED)
        elif queue == "in_progress":
            qs = qs.filter(status=TicketStatus.IN_PROGRESS)
        elif queue == "on_hold":
            qs = qs.filter(status=TicketStatus.ON_HOLD)
        elif queue == "bugs":
            qs = qs.filter(category=Category.BUG)
        elif queue == "features":
            qs = qs.filter(category=Category.FEATURE)
        elif queue == "ai_ml":
            qs = qs.filter(category=Category.AI_ML)
        elif queue == "backend":
            qs = qs.filter(category__in=[Category.BACKEND, Category.API, Category.DATABASE])
        elif queue == "my_requests":
            qs = qs.filter(requester=user)
        elif queue == "assigned_to_me":
            qs = qs.filter(assigned_to=user).exclude(
                status__in=[TicketStatus.CLOSED, TicketStatus.CANCELLED]
            )

        if status_filter:
            qs = qs.filter(status=status_filter)
        if department:
            qs = qs.filter(department=department)
        if priority:
            qs = qs.filter(priority=priority)
        if category:
            qs = qs.filter(category=category)
        if mine:
            qs = qs.filter(requester=user)
        if assigned_to_me:
            qs = qs.filter(assigned_to=user)
        if search:
            qs = qs.filter(
                Q(ticket_number__icontains=search)
                | Q(title__icontains=search)
                | Q(site_name__icontains=search)
                | Q(asset_label__icontains=search)
            )
        return qs.order_by("-created_at")

    def create(self, request, *args, **kwargs):
        # Super Admin / Location Admin create tickets; Support operates & chats on them.
        if not is_requester_user(request.user):
            return Response(
                {"detail": "Only Super Admin or Location Admin can create tickets."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ser = CreateRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            ticket, meta = create_request(
                requester=request.user,
                title=data["title"],
                description=data.get("description") or "",
                camera_id=data.get("camera"),
                infra_site_id=data.get("infra_site"),
                infra_device_id=data.get("infra_device"),
                site_name=data.get("site_name") or "",
                asset_label=data.get("asset_label") or "",
                preferred_category=data.get("preferred_category") or "",
                preferred_priority=data.get("preferred_priority") or "",
                contact_phone=data.get("contact_phone") or "",
                contact_name=data.get("contact_name") or "",
                source=data.get("source") or "portal",
                force_create=bool(data.get("force_create")),
            )
        except DuplicateRequestError as exc:
            return Response(
                {
                    "detail": str(exc),
                    "duplicate_of": exc.duplicate.ticket_number,
                    "duplicate_id": exc.duplicate.id,
                    "force_create_required": True,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        out = SupportTicketDetailSerializer(ticket, context={"request": request}).data
        return Response({**out, "engine": meta}, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        # Only support/admin may freely edit fields; others use actions
        if not is_support_user(request.user):
            return Response(
                {"detail": "Use workflow actions to update this ticket."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ticket = self.get_object()
        allowed = {"title", "description", "site_name", "asset_label"}
        changed = []
        for key in allowed:
            if key in request.data:
                setattr(ticket, key, request.data[key])
                changed.append(key)
        if changed:
            ticket.save(update_fields=changed + ["updated_at"])
            log_event(
                ticket,
                actor=request.user,
                event_type="updated",
                message=f"Updated fields: {', '.join(changed)}",
            )
        return Response(SupportTicketDetailSerializer(ticket, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def triage(self, request, pk=None):
        if not is_support_user(request.user):
            return Response({"detail": "Support only."}, status=status.HTTP_403_FORBIDDEN)
        ticket = self.get_object()
        blocked = _ensure_active(ticket)
        if blocked:
            return blocked
        ser = TriageSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if data["category"] not in Category.values:
            return Response({"detail": "Invalid category."}, status=400)
        if data["priority"] not in Priority.values:
            return Response({"detail": "Invalid priority."}, status=400)
        if data["department"] not in Department.values:
            return Response({"detail": "Invalid department."}, status=400)

        from_status = ticket.status
        ticket.category = data["category"]
        ticket.priority = data["priority"]
        ticket.department = data["department"]
        ticket.reviewed_by = request.user
        _mark_first_response(ticket)
        if ticket.status in (TicketStatus.NEW, TicketStatus.REOPENED):
            ticket.status = TicketStatus.TRIAGED
        # Recompute SLA if priority changed
        from .engine import compute_sla_deadlines

        ticket.sla_response_due, ticket.sla_resolve_due = compute_sla_deadlines(
            ticket.priority, ticket.created_at
        )
        ticket.save()
        log_event(
            ticket,
            actor=request.user,
            event_type="triaged",
            from_status=from_status,
            to_status=ticket.status,
            message=data.get("notes") or "Reviewed and classified by Support.",
            meta={
                "category": ticket.category,
                "priority": ticket.priority,
                "department": ticket.department,
            },
        )
        return Response(SupportTicketDetailSerializer(ticket, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        if not is_support_user(request.user):
            return Response({"detail": "Support only."}, status=status.HTTP_403_FORBIDDEN)
        ticket = self.get_object()
        blocked = _ensure_active(ticket)
        if blocked:
            return blocked
        ser = AssignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        from django.contrib.auth import get_user_model

        User = get_user_model()
        assignee = None
        if data.get("assigned_to"):
            assignee = get_object_or_404(User, pk=data["assigned_to"], is_active=True)

        if data.get("department"):
            if data["department"] not in Department.values:
                return Response({"detail": "Invalid department."}, status=400)
            ticket.department = data["department"]

        if ticket.department == Department.UNASSIGNED:
            return Response(
                {
                    "detail": "Set department (IT, Developer, Support, Operations, or Admin) before assigning."
                },
                status=400,
            )

        from_status = ticket.status
        ticket.assigned_to = assignee
        ticket.assigned_at = timezone.now()
        ticket.status = TicketStatus.ASSIGNED
        _mark_first_response(ticket)
        ticket.save()
        log_event(
            ticket,
            actor=request.user,
            event_type="assigned",
            from_status=from_status,
            to_status=ticket.status,
            message=data.get("notes")
            or f"Assigned to {assignee.username if assignee else ticket.department + ' queue'}.",
            meta={"assigned_to": assignee.id if assignee else None, "department": ticket.department},
        )
        return Response(SupportTicketDetailSerializer(ticket, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        """Handler starts work → IN_PROGRESS."""
        ticket = self.get_object()
        blocked = _ensure_active(ticket)
        if blocked:
            return blocked
        if not self._can_handle(request.user, ticket):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        if ticket.status not in (
            TicketStatus.ASSIGNED,
            TicketStatus.ON_HOLD,
            TicketStatus.REOPENED,
            TicketStatus.TRIAGED,
        ):
            return Response({"detail": f"Cannot start from {ticket.status}."}, status=400)
        from_status = ticket.status
        if not ticket.assigned_to:
            ticket.assigned_to = request.user
            ticket.assigned_at = timezone.now()
        ticket.status = TicketStatus.IN_PROGRESS
        ticket.save()
        log_event(
            ticket,
            actor=request.user,
            event_type="started",
            from_status=from_status,
            to_status=ticket.status,
            message="Work started.",
        )
        return Response(SupportTicketDetailSerializer(ticket, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="hold")
    def hold(self, request, pk=None):
        ticket = self.get_object()
        blocked = _ensure_active(ticket)
        if blocked:
            return blocked
        if not (is_support_user(request.user) or self._can_handle(request.user, ticket)):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        from_status = ticket.status
        ticket.status = TicketStatus.ON_HOLD
        ticket.save(update_fields=["status", "updated_at"])
        log_event(
            ticket,
            actor=request.user,
            event_type="on_hold",
            from_status=from_status,
            to_status=ticket.status,
            message=request.data.get("notes") or "Ticket placed on hold.",
        )
        return Response(SupportTicketDetailSerializer(ticket, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="submit-resolution")
    def submit_resolution(self, request, pk=None):
        """IT/Developer submits solution — does NOT close the ticket."""
        ticket = self.get_object()
        blocked = _ensure_active(ticket)
        if blocked:
            return blocked
        if not self._can_handle(request.user, ticket):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        ser = ResolutionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from_status = ticket.status
        ticket.resolution_notes = ser.validated_data["resolution_notes"]
        ticket.resolution_submitted_at = timezone.now()
        ticket.status = TicketStatus.RESOLUTION_SUBMITTED
        if not ticket.assigned_to:
            ticket.assigned_to = request.user
        ticket.save()
        log_event(
            ticket,
            actor=request.user,
            event_type="resolution_submitted",
            from_status=from_status,
            to_status=ticket.status,
            message=ticket.resolution_notes,
        )
        return Response(SupportTicketDetailSerializer(ticket, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        """Support verification after resolution submitted."""
        if not is_support_user(request.user):
            return Response({"detail": "Support only."}, status=status.HTTP_403_FORBIDDEN)
        ticket = self.get_object()
        blocked = _ensure_active(ticket)
        if blocked:
            return blocked
        if ticket.status != TicketStatus.RESOLUTION_SUBMITTED:
            return Response(
                {"detail": "Ticket must be RESOLUTION_SUBMITTED."},
                status=400,
            )
        ser = VerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        from_status = ticket.status
        if data.get("approved", True):
            ticket.verification_notes = data.get("verification_notes") or ""
            ticket.verified_by = request.user
            ticket.verified_at = timezone.now()
            ticket.status = TicketStatus.PENDING_CLIENT_CONFIRM
            ticket.save()
            log_event(
                ticket,
                actor=request.user,
                event_type="support_verified",
                from_status=from_status,
                to_status=ticket.status,
                message=ticket.verification_notes or "Verified by Support. Awaiting client.",
            )
        else:
            ticket.verification_notes = data.get("verification_notes") or "Rejected by Support."
            ticket.status = TicketStatus.ASSIGNED
            ticket.save()
            log_event(
                ticket,
                actor=request.user,
                event_type="verification_rejected",
                from_status=from_status,
                to_status=ticket.status,
                message=ticket.verification_notes,
            )
        return Response(SupportTicketDetailSerializer(ticket, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="client-confirm")
    def client_confirm(self, request, pk=None):
        ticket = self.get_object()
        blocked = _ensure_active(ticket)
        if blocked:
            return blocked
        if ticket.requester_id != request.user.id and not is_support_user(request.user):
            return Response({"detail": "Only the requester or Support can confirm."}, status=403)
        if ticket.status != TicketStatus.PENDING_CLIENT_CONFIRM:
            return Response({"detail": "Ticket is not waiting for client confirmation."}, status=400)
        ser = ClientConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        from_status = ticket.status
        ticket.client_notes = data.get("client_notes") or ""
        if data["accepted"]:
            ticket.client_confirmed_at = timezone.now()
            ticket.closed_at = timezone.now()
            ticket.status = TicketStatus.CLOSED
            ticket.save()
            log_event(
                ticket,
                actor=request.user,
                event_type="client_confirmed",
                from_status=from_status,
                to_status=ticket.status,
                message=ticket.client_notes or "Client accepted resolution. Closed.",
            )
        else:
            ticket.status = TicketStatus.REOPENED
            ticket.save()
            log_event(
                ticket,
                actor=request.user,
                event_type="client_rejected",
                from_status=from_status,
                to_status=ticket.status,
                message=ticket.client_notes or "Client rejected resolution. Reopened.",
            )
        return Response(SupportTicketDetailSerializer(ticket, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        ticket = self.get_object()
        if not (
            is_support_user(request.user) or ticket.requester_id == request.user.id
        ):
            return Response({"detail": "Not allowed."}, status=403)
        if ticket.status == TicketStatus.CLOSED:
            return Response({"detail": "Already closed."}, status=400)
        from_status = ticket.status
        ticket.status = TicketStatus.CANCELLED
        ticket.closed_at = timezone.now()
        ticket.save()
        log_event(
            ticket,
            actor=request.user,
            event_type="cancelled",
            from_status=from_status,
            to_status=ticket.status,
            message=request.data.get("notes") or "Cancelled.",
        )
        return Response(SupportTicketDetailSerializer(ticket, context={"request": request}).data)

    @action(detail=True, methods=["get", "post"], url_path="chat")
    def chat(self, request, pk=None):
        """Ticket chat thread — Support (and requester) while ticket is valid (24h)."""
        ticket = self.get_object()
        ticket.expire_if_needed()

        if request.method == "GET":
            qs = ticket.comments.select_related("author").all()
            if not (is_support_user(request.user) or is_handler_user(request.user)):
                qs = qs.filter(is_internal=False)
            after_id = request.query_params.get("after")
            if after_id:
                try:
                    qs = qs.filter(id__gt=int(after_id))
                except ValueError:
                    pass
            return Response(
                {
                    "ticket_id": ticket.id,
                    "ticket_number": ticket.ticket_number,
                    "status": ticket.status,
                    "can_chat": ticket.can_chat_for_user(request.user)
                    and _can_chat_on_ticket(request.user, ticket),
                    "expires_at": ticket.expires_at,
                    "validity_remaining_seconds": ticket.validity_remaining_seconds(),
                    "messages": TicketCommentSerializer(
                        qs, many=True, context={"request": request}
                    ).data,
                }
            )

        # POST — send chat message
        if not _can_chat_on_ticket(request.user, ticket):
            return Response({"detail": "Not allowed to chat on this ticket."}, status=403)
        if not ticket.can_chat_for_user(request.user):
            return Response(
                {
                    "detail": "Chat is closed. This ticket expired or was cancelled.",
                    "status": ticket.status,
                    "expires_at": ticket.expires_at,
                },
                status=status.HTTP_410_GONE,
            )
        # Support JSON or multipart (with attachment)
        data = request.data
        ser = CommentCreateSerializer(data=data)
        ser.is_valid(raise_exception=True)
        body = (ser.validated_data.get("body") or "").strip()
        attachment = ser.validated_data.get("attachment")
        if not body and not attachment:
            return Response(
                {"detail": "Message text or attachment is required."},
                status=400,
            )
        is_internal = bool(ser.validated_data.get("is_internal"))
        # Requesters cannot post internal notes; Support chat is public by default
        if is_internal and not (is_support_user(request.user) or is_handler_user(request.user)):
            return Response({"detail": "Cannot post internal notes."}, status=403)
        if ticket.requester_id == request.user.id and not is_support_user(request.user):
            is_internal = False
        comment = TicketComment(
            ticket=ticket,
            author=request.user,
            body=body,
            is_internal=is_internal,
        )
        if attachment:
            comment.attachment = attachment
            comment.attachment_name = getattr(attachment, "name", "") or ""
        comment.save()
        _mark_first_response(ticket)
        ticket.save(update_fields=["first_response_at", "updated_at"])
        log_event(
            ticket,
            actor=request.user,
            event_type="chat",
            message=(body or comment.attachment_name or "Attachment")[:200],
            meta={
                "comment_id": comment.id,
                "is_internal": is_internal,
                "has_attachment": bool(attachment),
            },
        )
        return Response(
            TicketCommentSerializer(comment, context={"request": request}).data,
            status=201,
        )

    @action(detail=True, methods=["post"])
    def comments(self, request, pk=None):
        """Legacy alias — prefer /chat/."""
        return self.chat(request, pk=pk)

    @action(detail=False, methods=["get"])
    def meta(self, request):
        return Response(
            {
                "statuses": [{"value": c.value, "label": c.label} for c in TicketStatus],
                "priorities": [{"value": c.value, "label": c.label} for c in Priority],
                "categories": [{"value": c.value, "label": c.label} for c in Category],
                "departments": [{"value": c.value, "label": c.label} for c in Department],
                "capabilities": capabilities_for(request.user),
            }
        )

    def _can_handle(self, user, ticket: SupportTicket) -> bool:
        # Support owns operations after intake; IT/Dev handle their assigned work.
        if is_support_user(user):
            return True
        if ticket.department == Department.IT and is_it_user(user):
            return True
        if ticket.department == Department.DEVELOPER and is_developer_user(user):
            return True
        if ticket.assigned_to_id == user.id and is_handler_user(user):
            return True
        return False


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSupportModuleAccess])
def assignable_users(request):
    """List users for Support assignment dropdown by department."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    dept = (request.query_params.get("department") or "").upper()
    role_map = {
        Department.IT: ["IT_ADMIN", "IT_SUPERADMIN"],
        Department.DEVELOPER: ["DEVELOPER"],
        Department.SUPPORT: ["SUPPORT"],
        Department.OPERATIONS: ["ADMIN", "LOCATION_ADMIN", "SUPPORT"],
        Department.ADMIN: ["ADMIN", "LOCATION_ADMIN"],
    }
    roles = role_map.get(
        dept,
        ["IT_ADMIN", "IT_SUPERADMIN", "DEVELOPER", "SUPPORT", "ADMIN", "LOCATION_ADMIN"],
    )
    users = User.objects.filter(is_active=True, role__in=roles).order_by("username")[:200]
    return Response(
        [
            {
                "id": u.id,
                "username": u.username,
                "full_name": getattr(u, "full_name", "") or u.get_full_name(),
                "role": u.role,
            }
            for u in users
        ]
    )
