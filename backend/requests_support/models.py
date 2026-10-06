from django.conf import settings
from django.db import models
from django.utils import timezone


class Priority(models.TextChoices):
    P1 = "P1", "Critical (P1)"
    P2 = "P2", "High (P2)"
    P3 = "P3", "Medium (P3)"
    P4 = "P4", "Low (P4)"


class Department(models.TextChoices):
    IT = "IT", "IT"
    DEVELOPER = "DEVELOPER", "Developer"
    SUPPORT = "SUPPORT", "Support"
    OPERATIONS = "OPERATIONS", "Operations"
    ADMIN = "ADMIN", "Admin"
    UNASSIGNED = "UNASSIGNED", "Unassigned"


class Category(models.TextChoices):
    # Field / IT
    CAMERA = "CAMERA", "Camera / CCTV"
    NVR = "NVR", "NVR / Recording"
    NETWORK = "NETWORK", "Network / PoE"
    HARDWARE = "HARDWARE", "Hardware / Power"
    SERVER = "SERVER", "Server / Infrastructure"
    INFRASTRUCTURE = "INFRASTRUCTURE", "Infrastructure"
    # Access & modules
    ACCESS = "ACCESS", "Access / Login"
    MODULE_ACCESS = "MODULE_ACCESS", "Module Access"
    # Evidence & ops
    VIDEO_EVIDENCE = "VIDEO_EVIDENCE", "Video / Evidence"
    REPORT = "REPORT", "Report / Data Extract"
    TRAINING = "TRAINING", "Training / How-to"
    OPS_POLICY = "OPS_POLICY", "Ops / Admin / Policy"
    # Software
    BACKEND = "BACKEND", "Backend / API"
    FRONTEND = "FRONTEND", "UI / Frontend"
    AI_ML = "AI_ML", "AI / ML"
    API = "API", "API"
    DATABASE = "DATABASE", "Database"
    BUG = "BUG", "Bug / Error"
    FEATURE = "FEATURE", "Feature Request"
    GENERAL = "GENERAL", "General Request"
    OTHER = "OTHER", "Other"


class TicketStatus(models.TextChoices):
    NEW = "NEW", "New"
    TRIAGED = "TRIAGED", "Triaged"
    ASSIGNED = "ASSIGNED", "Assigned"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    ON_HOLD = "ON_HOLD", "On Hold"
    RESOLUTION_SUBMITTED = "RESOLUTION_SUBMITTED", "Resolution Submitted"
    SUPPORT_VERIFIED = "SUPPORT_VERIFIED", "Support Verified"
    PENDING_CLIENT_CONFIRM = "PENDING_CLIENT_CONFIRM", "Waiting Client"
    CLOSED = "CLOSED", "Closed"
    REOPENED = "REOPENED", "Reopened"
    CANCELLED = "CANCELLED", "Cancelled"
    EXPIRED = "EXPIRED", "Expired"

# Tickets created by Super Admin / Location Admin are valid for this window.
TICKET_VALIDITY_HOURS = 24


# Suggested department by category (Request Engine)
CATEGORY_DEPARTMENT = {
    Category.CAMERA: Department.IT,
    Category.NVR: Department.IT,
    Category.NETWORK: Department.IT,
    Category.HARDWARE: Department.IT,
    Category.SERVER: Department.IT,
    Category.INFRASTRUCTURE: Department.IT,
    Category.ACCESS: Department.SUPPORT,
    Category.MODULE_ACCESS: Department.ADMIN,
    Category.VIDEO_EVIDENCE: Department.SUPPORT,
    Category.REPORT: Department.SUPPORT,
    Category.TRAINING: Department.SUPPORT,
    Category.OPS_POLICY: Department.OPERATIONS,
    Category.BACKEND: Department.DEVELOPER,
    Category.FRONTEND: Department.DEVELOPER,
    Category.AI_ML: Department.DEVELOPER,
    Category.API: Department.DEVELOPER,
    Category.DATABASE: Department.DEVELOPER,
    Category.BUG: Department.DEVELOPER,
    Category.FEATURE: Department.DEVELOPER,
    Category.GENERAL: Department.SUPPORT,
    Category.OTHER: Department.SUPPORT,
}

# Default SLA response/resolve hours by priority
SLA_HOURS = {
    Priority.P1: (1, 4),
    Priority.P2: (4, 24),
    Priority.P3: (8, 72),
    Priority.P4: (24, 168),
}


class SupportTicket(models.Model):
    """Client/officer request managed by Support → IT/Developer → Client confirm."""

    ticket_number = models.CharField(max_length=32, unique=True, db_index=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=32,
        choices=TicketStatus.choices,
        default=TicketStatus.NEW,
        db_index=True,
    )
    priority = models.CharField(
        max_length=8,
        choices=Priority.choices,
        default=Priority.P3,
        db_index=True,
    )
    suggested_priority = models.CharField(
        max_length=8,
        choices=Priority.choices,
        default=Priority.P3,
    )
    category = models.CharField(
        max_length=32,
        choices=Category.choices,
        default=Category.OTHER,
        db_index=True,
    )
    suggested_category = models.CharField(
        max_length=32,
        choices=Category.choices,
        default=Category.OTHER,
    )
    department = models.CharField(
        max_length=16,
        choices=Department.choices,
        default=Department.UNASSIGNED,
        db_index=True,
    )
    suggested_department = models.CharField(
        max_length=16,
        choices=Department.choices,
        default=Department.UNASSIGNED,
    )

    site_name = models.CharField(max_length=200, blank=True, default="")
    asset_label = models.CharField(max_length=200, blank=True, default="")
    camera = models.ForeignKey(
        "cameras.Camera",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_tickets",
    )
    infra_site = models.ForeignKey(
        "infrastructure_monitoring.InfraSite",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_tickets",
    )
    infra_device = models.ForeignKey(
        "infrastructure_monitoring.InfraDevice",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_tickets",
    )

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="support_tickets_created",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_tickets_assigned",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_tickets_reviewed",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_tickets_verified",
    )

    duplicate_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="duplicates",
    )
    is_duplicate = models.BooleanField(default=False)

    resolution_notes = models.TextField(blank=True, default="")
    verification_notes = models.TextField(blank=True, default="")
    client_notes = models.TextField(blank=True, default="")

    sla_response_due = models.DateTimeField(null=True, blank=True)
    sla_resolve_due = models.DateTimeField(null=True, blank=True)
    sla_breached = models.BooleanField(default=False, db_index=True)
    first_response_at = models.DateTimeField(null=True, blank=True)

    source = models.CharField(
        max_length=32,
        default="portal",
        help_text="portal | mobile | alert | admin",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Ticket validity window end (default 24 hours from creation).",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    resolution_submitted_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    client_confirmed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "department"]),
            models.Index(fields=["status", "priority"]),
            models.Index(fields=["requester", "status"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["expires_at", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.ticket_number} — {self.title}"

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            TicketStatus.CLOSED,
            TicketStatus.CANCELLED,
            TicketStatus.EXPIRED,
        )

    def is_validity_expired(self) -> bool:
        if self.is_terminal:
            return self.status == TicketStatus.EXPIRED
        if not self.expires_at:
            return False
        return timezone.now() >= self.expires_at

    def validity_remaining_seconds(self) -> int:
        if self.is_terminal or not self.expires_at:
            return 0
        delta = self.expires_at - timezone.now()
        return max(0, int(delta.total_seconds()))

    def can_chat(self) -> bool:
        """Chat window for requesters — open while ticket is active and within 24h."""
        self.expire_if_needed()
        return not self.is_terminal and not self.is_validity_expired()

    def can_chat_for_user(self, user) -> bool:
        """
        Who may send chat messages.
        - Support / IT / Developer: may chat until EXPIRED or CANCELLED (including CLOSED).
        - Requester: only while ticket is still active within the 24h window.
        """
        self.expire_if_needed()
        if self.status in (TicketStatus.EXPIRED, TicketStatus.CANCELLED):
            return False
        from .permissions import is_handler_user, is_support_user

        if is_support_user(user) or is_handler_user(user):
            return True
        return self.can_chat()

    def expire_if_needed(self) -> bool:
        """Mark ticket EXPIRED when the 24h window elapses. Returns True if expired now."""
        if self.status in (TicketStatus.CLOSED, TicketStatus.CANCELLED, TicketStatus.EXPIRED):
            return self.status == TicketStatus.EXPIRED
        if not self.expires_at or timezone.now() < self.expires_at:
            return False
        from_status = self.status
        self.status = TicketStatus.EXPIRED
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "closed_at", "updated_at"])
        try:
            from .engine import log_event

            log_event(
                self,
                actor=None,
                event_type="expired",
                from_status=from_status,
                to_status=TicketStatus.EXPIRED,
                message="Ticket expired after 24-hour validity window.",
            )
        except Exception:
            pass
        return True

    def refresh_sla_breach(self) -> bool:
        if self.is_terminal:
            return self.sla_breached
        self.expire_if_needed()
        if self.status == TicketStatus.EXPIRED:
            return self.sla_breached
        now = timezone.now()
        breached = False
        if self.sla_response_due and not self.first_response_at and now > self.sla_response_due:
            breached = True
        if self.sla_resolve_due and self.status != TicketStatus.CLOSED and now > self.sla_resolve_due:
            breached = True
        if breached != self.sla_breached:
            self.sla_breached = breached
            self.save(update_fields=["sla_breached", "updated_at"])
        return self.sla_breached


class TicketComment(models.Model):
    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="support_ticket_comments",
    )
    body = models.TextField(blank=True, default="")
    attachment = models.FileField(
        upload_to="support_chat/%Y/%m/",
        null=True,
        blank=True,
    )
    attachment_name = models.CharField(max_length=255, blank=True, default="")
    is_internal = models.BooleanField(
        default=False,
        help_text="Internal notes hidden from the client requester.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Comment on {self.ticket.ticket_number}"


class TicketEvent(models.Model):
    """Audit trail for Request Engine + Support + IT/Dev actions."""

    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_ticket_events",
    )
    event_type = models.CharField(max_length=64, db_index=True)
    from_status = models.CharField(max_length=32, blank=True, default="")
    to_status = models.CharField(max_length=32, blank=True, default="")
    message = models.TextField(blank=True, default="")
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.ticket.ticket_number}: {self.event_type}"
