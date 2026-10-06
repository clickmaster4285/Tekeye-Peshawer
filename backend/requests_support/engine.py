"""
Request Engine — create / classify / priority / asset / site / duplicate / SLA.

Distinct from Support Module (review / assign / verify) and IT/Developer handlers.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    CATEGORY_DEPARTMENT,
    SLA_HOURS,
    TICKET_VALIDITY_HOURS,
    Category,
    Department,
    Priority,
    SupportTicket,
    TicketEvent,
    TicketStatus,
)


class DuplicateRequestError(ValueError):
    def __init__(self, message: str, *, duplicate: SupportTicket):
        super().__init__(message)
        self.duplicate = duplicate

# Keyword → category heuristics
_CATEGORY_KEYWORDS: list[tuple[Category, tuple[str, ...]]] = [
    (Category.VIDEO_EVIDENCE, ("evidence", "footage", "video clip", "export video", "clip request")),
    (Category.MODULE_ACCESS, ("module access", "enable module", "module permission", "grant module")),
    (Category.REPORT, ("report", "data extract", "export data", "excel", "csv")),
    (Category.TRAINING, ("training", "how to", "howto", "tutorial", "guide me")),
    (Category.OPS_POLICY, ("policy", "ops request", "admin request", "procedure")),
    (Category.CAMERA, ("camera", "cctv", "stream", "rtsp", "offline camera", "cam ")),
    (Category.NVR, ("nvr", "recorder", "recording", "playback")),
    (Category.NETWORK, ("network", "switch", "router", "poe", "lan", "wifi", "bandwidth")),
    (Category.SERVER, ("server", "vm ", "host", "disk full", "cpu", "ram")),
    (Category.ACCESS, ("login", "password", "permission", "access denied", "vpn", "account")),
    (Category.HARDWARE, ("hardware", "ups", "inverter", "power", "cable", "port")),
    (Category.INFRASTRUCTURE, ("infrastructure", "site down", "device health")),
    (Category.AI_ML, ("recognition", "attendance", "face", "ml ", "ai ", "model", "detection")),
    (Category.FRONTEND, ("ui ", "button", "page", "frontend", "screen", "dashboard blank")),
    (Category.BACKEND, ("backend", "api error", "500", "exception", "celery")),
    (Category.API, ("api", "endpoint", "webhook", "integration")),
    (Category.DATABASE, ("database", "sql", "postgres", "migration", "query")),
    (Category.BUG, ("bug", "crash", "error", "not working", "broken", "fail")),
    (Category.FEATURE, ("feature", "enhancement", "request for", "add support")),
    (Category.GENERAL, ("general request", "general inquiry")),
]

_PRIORITY_KEYWORDS: list[tuple[Priority, tuple[str, ...]]] = [
    (Priority.P1, ("critical", "down", "outage", "emergency", "all cameras", "site offline")),
    (Priority.P2, ("urgent", "offline", "not working", "cannot", "blocking")),
    (Priority.P4, ("minor", "cosmetic", "nice to have", "enhancement", "when possible")),
]


def _next_ticket_number() -> str:
    year = timezone.now().year
    prefix = f"REQ-{year}-"
    last = (
        SupportTicket.objects.filter(ticket_number__startswith=prefix)
        .order_by("-ticket_number")
        .values_list("ticket_number", flat=True)
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last.rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = SupportTicket.objects.filter(ticket_number__startswith=prefix).count() + 1
    return f"{prefix}{seq:06d}"


def classify_text(title: str, description: str = "") -> Category:
    text = f"{title} {description}".lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(k in text for k in keywords):
            return category
    return Category.OTHER


def suggest_priority(title: str, description: str = "", category: Category | None = None) -> Priority:
    text = f"{title} {description}".lower()
    for priority, keywords in _PRIORITY_KEYWORDS:
        if any(k in text for k in keywords):
            return priority
    if category in (Category.CAMERA, Category.NVR, Category.NETWORK, Category.SERVER):
        if "offline" in text or "down" in text:
            return Priority.P2
    if category in (Category.FEATURE,):
        return Priority.P4
    return Priority.P3


def suggest_department(category: Category) -> Department:
    return CATEGORY_DEPARTMENT.get(category, Department.UNASSIGNED)


def compute_sla_deadlines(priority: str, created_at=None):
    created = created_at or timezone.now()
    response_h, resolve_h = SLA_HOURS.get(priority, SLA_HOURS[Priority.P3])
    return created + timedelta(hours=response_h), created + timedelta(hours=resolve_h)


def find_duplicates(
    *,
    title: str,
    camera_id: int | None = None,
    infra_device_id: int | None = None,
    site_name: str = "",
    hours: int = 48,
) -> SupportTicket | None:
    """Return an open similar ticket if one likely exists."""
    since = timezone.now() - timedelta(hours=hours)
    open_statuses = [
        TicketStatus.NEW,
        TicketStatus.TRIAGED,
        TicketStatus.ASSIGNED,
        TicketStatus.IN_PROGRESS,
        TicketStatus.ON_HOLD,
        TicketStatus.RESOLUTION_SUBMITTED,
        TicketStatus.SUPPORT_VERIFIED,
        TicketStatus.PENDING_CLIENT_CONFIRM,
        TicketStatus.REOPENED,
    ]
    qs = SupportTicket.objects.filter(created_at__gte=since, status__in=open_statuses)
    if camera_id:
        hit = qs.filter(camera_id=camera_id).first()
        if hit:
            return hit
    if infra_device_id:
        hit = qs.filter(infra_device_id=infra_device_id).first()
        if hit:
            return hit

    # Soft title match: shared significant tokens
    tokens = {t for t in re.findall(r"[a-z0-9]+", title.lower()) if len(t) > 3}
    if not tokens:
        return None
    q = Q()
    for token in list(tokens)[:6]:
        q |= Q(title__icontains=token)
    candidates = qs.filter(q)
    if site_name:
        candidates = candidates.filter(site_name__iexact=site_name)
    return candidates.first()


def log_event(
    ticket: SupportTicket,
    *,
    actor,
    event_type: str,
    message: str = "",
    from_status: str = "",
    to_status: str = "",
    meta: dict | None = None,
) -> TicketEvent:
    return TicketEvent.objects.create(
        ticket=ticket,
        actor=actor,
        event_type=event_type,
        message=message,
        from_status=from_status or "",
        to_status=to_status or "",
        meta=meta or {},
    )


@transaction.atomic
def create_request(
    *,
    requester,
    title: str,
    description: str = "",
    camera_id: int | None = None,
    infra_site_id: int | None = None,
    infra_device_id: int | None = None,
    site_name: str = "",
    asset_label: str = "",
    preferred_category: str = "",
    preferred_priority: str = "",
    contact_phone: str = "",
    contact_name: str = "",
    source: str = "portal",
    force_create: bool = False,
) -> tuple[SupportTicket, dict[str, Any]]:
    """
    Request Engine entrypoint.
    Returns (ticket, meta) where meta may include duplicate_warning.
    """
    title = (title or "").strip()
    if not title:
        raise ValueError("Title is required.")

    category = classify_text(title, description)
    if preferred_category and preferred_category in Category.values:
        category = preferred_category
    priority = suggest_priority(title, description, category)
    if preferred_priority and preferred_priority in Priority.values:
        priority = preferred_priority
    department = suggest_department(category)

    # Append contact block when provided (keeps model lean; Support sees it in description)
    contact_bits = []
    if contact_name:
        contact_bits.append(f"Contact: {contact_name}")
    if contact_phone:
        contact_bits.append(f"Phone: {contact_phone}")
    if contact_bits:
        block = "\n".join(contact_bits)
        description = f"{description.rstrip()}\n\n---\n{block}".strip() if description else block

    # Enrich site/asset from linked models when possible
    camera = None
    if camera_id:
        from cameras.models import Camera

        camera = Camera.objects.select_related("nvr", "nvr__site").filter(pk=camera_id).first()
        if camera:
            asset_label = asset_label or f"{camera.code or camera.name}"
            if camera.nvr and camera.nvr.site:
                site_name = site_name or camera.nvr.site.name

    infra_site = None
    infra_device = None
    if infra_device_id:
        from infrastructure_monitoring.models import InfraDevice

        infra_device = (
            InfraDevice.objects.select_related("site").filter(pk=infra_device_id).first()
        )
        if infra_device:
            asset_label = asset_label or infra_device.name
            if infra_device.site:
                infra_site = infra_device.site
                site_name = site_name or infra_site.name
    if infra_site_id and not infra_site:
        from infrastructure_monitoring.models import InfraSite

        infra_site = InfraSite.objects.filter(pk=infra_site_id).first()
        if infra_site:
            site_name = site_name or infra_site.name

    dup = find_duplicates(
        title=title,
        camera_id=camera_id,
        infra_device_id=infra_device_id,
        site_name=site_name,
    )
    if dup and not force_create:
        raise DuplicateRequestError(
            f"Possible duplicate of {dup.ticket_number}.",
            duplicate=dup,
        )

    now = timezone.now()
    response_due, resolve_due = compute_sla_deadlines(priority)
    expires_at = now + timedelta(hours=TICKET_VALIDITY_HOURS)
    ticket = SupportTicket.objects.create(
        ticket_number=_next_ticket_number(),
        title=title,
        description=description or "",
        status=TicketStatus.NEW,
        priority=priority,
        suggested_priority=priority,
        category=category,
        suggested_category=category,
        department=Department.UNASSIGNED,  # Support confirms department
        suggested_department=department,
        site_name=site_name or "",
        asset_label=asset_label or "",
        camera=camera,
        infra_site=infra_site,
        infra_device=infra_device,
        requester=requester,
        duplicate_of=dup,
        is_duplicate=bool(dup),
        sla_response_due=response_due,
        sla_resolve_due=resolve_due,
        expires_at=expires_at,
        source=source or "portal",
    )
    log_event(
        ticket,
        actor=requester,
        event_type="created",
        to_status=TicketStatus.NEW,
        message=f"Ticket created. Valid for {TICKET_VALIDITY_HOURS} hours (until Support closes or it expires).",
        meta={
            "suggested_category": category,
            "suggested_priority": priority,
            "suggested_department": department,
            "duplicate_of": dup.ticket_number if dup else None,
            "expires_at": expires_at.isoformat(),
            "validity_hours": TICKET_VALIDITY_HOURS,
        },
    )
    meta = {
        "duplicate_of": dup.ticket_number if dup else None,
        "duplicate_id": dup.id if dup else None,
        "suggested_category": category,
        "suggested_priority": priority,
        "suggested_department": department,
    }
    return ticket, meta
