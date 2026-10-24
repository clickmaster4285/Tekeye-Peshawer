"""Helpers shared by the monitoring views: masking, audit, scoping, storage keys."""

from __future__ import annotations

import os
import re
from datetime import timedelta

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.utils import timezone

from users.permissions import can_view_all_staff, get_location_scope

from .models import MonitoringAudit

_SIGNER_SALT = "employee_monitoring.recording.playback"


def feature_enabled() -> bool:
    return str(getattr(settings, "EMPLOYEE_MONITORING_ENABLED", "")).lower() in ("true", "1", "yes")


def deployment_id() -> str:
    return getattr(settings, "TEKEYE_DEPLOYMENT_ID", "") or "unknown"


def retention_days() -> int:
    try:
        return int(getattr(settings, "MONITORING_RETENTION_DAYS", 0) or 0)
    except (TypeError, ValueError):
        return 0


def mask_number(raw: str | None) -> str:
    """+923001234567 -> "+92 3** *** **67". Keeps country prefix and last two digits only."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 4:
        return "***"
    plus = "+" if raw.strip().startswith("+") else ""
    head = digits[:2]
    tail = digits[-2:]
    middle = "*" * max(0, len(digits) - 4)
    return f"{plus}{head}{middle}{tail}"


def client_ip(request) -> str | None:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def record_audit(request, action: str, *, target_type: str = "", target_id: str = "", reason: str = "", **metadata) -> None:
    MonitoringAudit.objects.create(
        actor=getattr(request, "user", None) if getattr(request, "user", None) and request.user.is_authenticated else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        reason=reason,
        request_ip=client_ip(request),
        metadata=metadata or {},
    )


def scope_queryset(qs, user, *, own_field: str = "user", location_field: str = "user__location"):
    """Own records for ordinary staff; location-scoped (or all) records for overview roles."""
    if not can_view_all_staff(user):
        return qs.filter(**{own_field: user})
    loc = get_location_scope(user)
    if loc:
        return qs.filter(**{location_field: loc})
    return qs


# --- recording storage (private, local by default) -----------------------------------------

def recording_root() -> str:
    root = getattr(settings, "MONITORING_RECORDING_ROOT", "") or os.path.join(settings.BASE_DIR, "private_media", "monitoring")
    os.makedirs(root, exist_ok=True)
    return root


def storage_path(storage_key: str) -> str:
    # storage_key is a server-chosen relative name; never a client path.
    safe = os.path.normpath(storage_key).lstrip(os.sep).replace("..", "")
    return os.path.join(recording_root(), safe)


def sign_playback(recording_id: str) -> str:
    return TimestampSigner(salt=_SIGNER_SALT).sign(str(recording_id))


def unsign_playback(token: str, max_age_seconds: int = 300) -> str | None:
    try:
        return TimestampSigner(salt=_SIGNER_SALT).unsign(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None


def playback_expiry(seconds: int = 300):
    return timezone.now() + timedelta(seconds=seconds)
