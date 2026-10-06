from django.contrib import admin

from .models import SupportTicket, TicketComment, TicketEvent


class TicketCommentInline(admin.TabularInline):
    model = TicketComment
    extra = 0
    readonly_fields = ("author", "body", "is_internal", "created_at")


class TicketEventInline(admin.TabularInline):
    model = TicketEvent
    extra = 0
    readonly_fields = (
        "actor",
        "event_type",
        "from_status",
        "to_status",
        "message",
        "created_at",
    )


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = (
        "ticket_number",
        "title",
        "status",
        "priority",
        "department",
        "category",
        "requester",
        "assigned_to",
        "sla_breached",
        "created_at",
    )
    list_filter = ("status", "priority", "department", "category", "sla_breached")
    search_fields = ("ticket_number", "title", "site_name", "asset_label")
    readonly_fields = ("ticket_number", "created_at", "updated_at")
    inlines = [TicketCommentInline, TicketEventInline]


@admin.register(TicketComment)
class TicketCommentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "is_internal", "created_at")


@admin.register(TicketEvent)
class TicketEventAdmin(admin.ModelAdmin):
    list_display = ("ticket", "event_type", "actor", "from_status", "to_status", "created_at")
    list_filter = ("event_type",)
