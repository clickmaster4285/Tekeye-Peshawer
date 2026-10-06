"""Role helpers for Requests & Support module panels.

Super Admin / Location Admin = requesters only (create + own tickets).
Support Agent = triage, assign, verify, and all operational control.
IT / Developer = handle tickets assigned to their department.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission, SAFE_METHODS

MODULE_LABEL = "Requests & Support"

# Only Support Agents operate the Support module (not Super Admin).
SUPPORT_ROLES = frozenset({"SUPPORT"})
# Requesters may create tickets and confirm their own resolutions.
REQUESTER_ROLES = frozenset({"ADMIN", "LOCATION_ADMIN"})
IT_ROLES = frozenset({"IT_ADMIN", "IT_SUPERADMIN"})
DEVELOPER_ROLES = frozenset({"DEVELOPER"})
HANDLER_ROLES = IT_ROLES | DEVELOPER_ROLES


def _role(user) -> str:
    return (getattr(user, "role", None) or "").strip().upper()


def has_module_grant(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    modules = getattr(user, "allowed_modules", None) or []
    return MODULE_LABEL in modules


def is_requester_user(user) -> bool:
    """Super Admin / Location Admin — create requests only."""
    return bool(user and user.is_authenticated and _role(user) in REQUESTER_ROLES)


def is_support_user(user) -> bool:
    return bool(user and user.is_authenticated and _role(user) in SUPPORT_ROLES)


def is_it_user(user) -> bool:
    return bool(user and user.is_authenticated and _role(user) in IT_ROLES)


def is_developer_user(user) -> bool:
    return bool(user and user.is_authenticated and _role(user) in DEVELOPER_ROLES)


def is_handler_user(user) -> bool:
    return is_it_user(user) or is_developer_user(user)


def can_access_support_module(user) -> bool:
    """Support, IT, Developer, fixed requesters, or module grant."""
    if not user or not user.is_authenticated:
        return False
    if is_support_user(user) or is_handler_user(user) or is_requester_user(user):
        return True
    return has_module_grant(user)


def capabilities_for(user) -> dict:
    role = _role(user)
    support = is_support_user(user)
    requester = is_requester_user(user) or (
        not support and not is_handler_user(user) and can_access_support_module(user)
    )
    return {
        "role": role,
        "can_create": is_requester_user(user),
        "can_support_triage": support,
        "can_handle_it": is_it_user(user) or support,
        "can_handle_developer": is_developer_user(user) or support,
        "can_view_all": support,
        "can_chat": support or is_requester_user(user) or is_handler_user(user),
        "is_requester_only": requester and not support and not is_handler_user(user),
        "is_admin": role == "ADMIN",
        "is_location_admin": role == "LOCATION_ADMIN",
        "ticket_validity_hours": 24,
    }


class HasSupportModuleAccess(BasePermission):
    def has_permission(self, request, view):
        return can_access_support_module(request.user)


class IsSupportAgent(BasePermission):
    def has_permission(self, request, view):
        return is_support_user(request.user)


class IsTicketHandler(BasePermission):
    """IT or Developer can act on assigned work."""

    def has_permission(self, request, view):
        return is_handler_user(request.user) or is_support_user(request.user)


class IsSupportOrReadOwn(BasePermission):
    def has_permission(self, request, view):
        return can_access_support_module(request.user)

    def has_object_permission(self, request, view):
        if is_support_user(request.user):
            return True
        if request.method in SAFE_METHODS:
            return True
        return True
