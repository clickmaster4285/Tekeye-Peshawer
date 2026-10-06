from rest_framework import serializers

from .models import SupportTicket, TicketComment, TicketEvent


class TicketCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_role = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()
    attachment_size = serializers.SerializerMethodField()

    class Meta:
        model = TicketComment
        fields = [
            "id",
            "author",
            "author_name",
            "author_role",
            "body",
            "attachment",
            "attachment_url",
            "attachment_name",
            "attachment_size",
            "is_internal",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "author",
            "author_name",
            "author_role",
            "attachment_url",
            "attachment_size",
            "created_at",
        ]

    def get_author_name(self, obj):
        u = obj.author
        return getattr(u, "full_name", None) or u.get_full_name() or u.username

    def get_author_role(self, obj):
        return getattr(obj.author, "role", "") or ""

    def get_attachment_url(self, obj):
        if not obj.attachment:
            return None
        request = self.context.get("request")
        url = obj.attachment.url
        if request:
            return request.build_absolute_uri(url)
        return url

    def get_attachment_size(self, obj):
        if not obj.attachment:
            return None
        try:
            return obj.attachment.size
        except Exception:
            return None


class TicketEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = TicketEvent
        fields = [
            "id",
            "actor",
            "actor_name",
            "event_type",
            "from_status",
            "to_status",
            "message",
            "meta",
            "created_at",
        ]

    def get_actor_name(self, obj):
        u = obj.actor
        if not u:
            return "System"
        return getattr(u, "full_name", None) or u.get_full_name() or u.username


class SupportTicketListSerializer(serializers.ModelSerializer):
    requester_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    department_label = serializers.CharField(source="get_department_display", read_only=True)
    is_expired = serializers.SerializerMethodField()
    can_chat = serializers.SerializerMethodField()
    validity_remaining_seconds = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "ticket_number",
            "title",
            "status",
            "status_label",
            "priority",
            "priority_label",
            "category",
            "category_label",
            "department",
            "department_label",
            "site_name",
            "asset_label",
            "camera",
            "infra_site",
            "infra_device",
            "requester",
            "requester_name",
            "assigned_to",
            "assigned_to_name",
            "is_duplicate",
            "duplicate_of",
            "sla_response_due",
            "sla_resolve_due",
            "sla_breached",
            "source",
            "created_at",
            "updated_at",
            "expires_at",
            "is_expired",
            "can_chat",
            "validity_remaining_seconds",
            "resolution_submitted_at",
            "closed_at",
        ]

    def get_requester_name(self, obj):
        u = obj.requester
        return getattr(u, "full_name", None) or u.get_full_name() or u.username

    def get_assigned_to_name(self, obj):
        u = obj.assigned_to
        if not u:
            return None
        return getattr(u, "full_name", None) or u.get_full_name() or u.username

    def get_is_expired(self, obj):
        obj.expire_if_needed()
        return obj.status == "EXPIRED" or obj.is_validity_expired()

    def get_can_chat(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated:
            return obj.can_chat_for_user(user)
        return obj.can_chat()

    def get_validity_remaining_seconds(self, obj):
        return obj.validity_remaining_seconds()


class SupportTicketDetailSerializer(SupportTicketListSerializer):
    comments = serializers.SerializerMethodField()
    events = TicketEventSerializer(many=True, read_only=True)
    suggested_category_label = serializers.CharField(
        source="get_suggested_category_display", read_only=True
    )
    suggested_priority_label = serializers.CharField(
        source="get_suggested_priority_display", read_only=True
    )
    suggested_department_label = serializers.CharField(
        source="get_suggested_department_display", read_only=True
    )

    class Meta(SupportTicketListSerializer.Meta):
        fields = SupportTicketListSerializer.Meta.fields + [
            "description",
            "suggested_category",
            "suggested_category_label",
            "suggested_priority",
            "suggested_priority_label",
            "suggested_department",
            "suggested_department_label",
            "resolution_notes",
            "verification_notes",
            "client_notes",
            "first_response_at",
            "assigned_at",
            "verified_at",
            "client_confirmed_at",
            "reviewed_by",
            "verified_by",
            "comments",
            "events",
        ]

    def get_comments(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        from .permissions import is_support_user, is_handler_user

        qs = obj.comments.select_related("author").all()
        if user and not (is_support_user(user) or is_handler_user(user)):
            qs = qs.filter(is_internal=False)
        return TicketCommentSerializer(qs, many=True, context=self.context).data


class CreateRequestSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    camera = serializers.IntegerField(required=False, allow_null=True)
    infra_site = serializers.IntegerField(required=False, allow_null=True)
    infra_device = serializers.IntegerField(required=False, allow_null=True)
    site_name = serializers.CharField(required=False, allow_blank=True, default="")
    asset_label = serializers.CharField(required=False, allow_blank=True, default="")
    preferred_category = serializers.CharField(required=False, allow_blank=True, default="")
    preferred_priority = serializers.CharField(required=False, allow_blank=True, default="")
    contact_phone = serializers.CharField(required=False, allow_blank=True, default="")
    contact_name = serializers.CharField(required=False, allow_blank=True, default="")
    source = serializers.CharField(required=False, default="portal")
    force_create = serializers.BooleanField(required=False, default=False)


class TriageSerializer(serializers.Serializer):
    category = serializers.CharField()
    priority = serializers.CharField()
    department = serializers.CharField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class AssignSerializer(serializers.Serializer):
    assigned_to = serializers.IntegerField(required=False, allow_null=True)
    department = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ResolutionSerializer(serializers.Serializer):
    resolution_notes = serializers.CharField()


class VerifySerializer(serializers.Serializer):
    verification_notes = serializers.CharField(required=False, allow_blank=True, default="")
    approved = serializers.BooleanField(default=True)


class ClientConfirmSerializer(serializers.Serializer):
    accepted = serializers.BooleanField()
    client_notes = serializers.CharField(required=False, allow_blank=True, default="")


class CommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True, default="")
    is_internal = serializers.BooleanField(required=False, default=False)
    attachment = serializers.FileField(required=False, allow_null=True)
