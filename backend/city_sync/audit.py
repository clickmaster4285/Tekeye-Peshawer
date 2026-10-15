"""Append-only audit helpers (Phase 9)."""

from __future__ import annotations

import logging
from typing import Any

from city_sync.identity import location_code
from city_sync.models import SyncAuditLog

logger = logging.getLogger(__name__)


def audit(action: str, *, detail: dict[str, Any] | None = None, actor: str = "system", loc: str | None = None) -> None:
    try:
        SyncAuditLog.objects.create(
            action=action,
            actor=actor,
            location_code=(loc or location_code() or ""),
            detail=detail or {},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write SyncAuditLog action=%s", action)
