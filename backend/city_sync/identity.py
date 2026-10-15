"""Phase 1 — city / HQ identity and boot checks."""

from __future__ import annotations

import logging
import os
from typing import Iterable

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

ROLE_CITY = "city"
ROLE_HQ = "hq"
ALLOWED_ROLES = frozenset({ROLE_CITY, ROLE_HQ})

# Canonical location codes (guide + existing Ops Central keys).
DEFAULT_ALLOWED_LOCATION_CODES = frozenset(
    {
        "PESHAWAR",
        "ABBOTTABAD",
        "DI_KHAN",
        "MARDAN",
        "NOWSHERA",
        "KOHAT",
        "SWH_RATTA_KULACHI",
        "DDK",
        "THAKOT",
        "HAYATABAD",
        "PEW",
        "ABT",
        "DIK",
        "MRD",
        "NOW",
        "KHT",
    }
)


def system_role() -> str:
    return str(getattr(settings, "SYSTEM_ROLE", "") or "").strip().lower()


def location_code() -> str:
    return str(getattr(settings, "LOCATION_CODE", "") or "").strip().upper()


def node_id() -> str:
    return str(getattr(settings, "NODE_ID", "") or "").strip()


def schema_version() -> int:
    return int(getattr(settings, "SYNC_SCHEMA_VERSION", 1))


def app_version() -> str:
    return str(getattr(settings, "APP_VERSION", "0.0.0") or "0.0.0")


def is_city() -> bool:
    return system_role() == ROLE_CITY


def is_hq() -> bool:
    return system_role() == ROLE_HQ


def allowed_location_codes() -> frozenset[str]:
    raw = getattr(settings, "ALLOWED_LOCATION_CODES", None)
    if raw:
        if isinstance(raw, str):
            items = [x.strip().upper() for x in raw.split(",") if x.strip()]
        else:
            items = [str(x).strip().upper() for x in raw if str(x).strip()]
        return frozenset(items) | DEFAULT_ALLOWED_LOCATION_CODES
    return DEFAULT_ALLOWED_LOCATION_CODES


def _check_ntp_drift() -> None:
    """Refuse start if clock is >5s off NTP (optional in DEBUG / when disabled)."""
    if not getattr(settings, "SYNC_REQUIRE_NTP", False):
        return
    max_drift = float(getattr(settings, "SYNC_MAX_CLOCK_DRIFT_SECONDS", 5.0))
    try:
        import ntplib  # optional dependency

        client = ntplib.NTPClient()
        server = os.getenv("NTP_SERVER", "pool.ntp.org")
        resp = client.request(server, version=3, timeout=3)
        drift = abs(float(resp.offset))
    except Exception as exc:  # noqa: BLE001 — boot must not hang on NTP library absence
        if getattr(settings, "DEBUG", False):
            logger.warning("NTP check skipped (%s)", exc)
            return
        raise ImproperlyConfigured(f"NTP check failed: {exc}") from exc
    if drift > max_drift:
        raise ImproperlyConfigured(
            f"Server clock is {drift:.2f}s off NTP (max {max_drift}s). Fix chrony/NTP before starting."
        )


def validate_node_identity() -> None:
    role = system_role()
    code = location_code()
    nid = node_id()

    if role not in ALLOWED_ROLES:
        raise ImproperlyConfigured(
            f"SYSTEM_ROLE must be 'city' or 'hq' (got {role!r}). "
            "Set SYSTEM_ROLE in backend/.env."
        )
    if not code:
        raise ImproperlyConfigured("LOCATION_CODE is required (e.g. ABBOTTABAD, PESHAWAR, DI_KHAN).")
    if code not in allowed_location_codes():
        raise ImproperlyConfigured(
            f"LOCATION_CODE={code!r} is not in ALLOWED_LOCATION_CODES."
        )
    if not nid:
        raise ImproperlyConfigured("NODE_ID is required (unique per server, e.g. abt-app-01).")

    # HQ must not pretend to be a generic city write node for other cities.
    if role == ROLE_HQ and getattr(settings, "SYNC_HQ_ACCEPTS_CITY_WRITES", False):
        raise ImproperlyConfigured(
            "SYSTEM_ROLE=hq cannot enable SYNC_HQ_ACCEPTS_CITY_WRITES. "
            "Run Peshawar-as-branch as a separate city deployment."
        )

    _check_ntp_drift()
    logger.info(
        "CIIS node identity OK role=%s location=%s node=%s schema=%s app=%s",
        role,
        code,
        nid,
        schema_version(),
        app_version(),
    )


def identity_dict() -> dict:
    return {
        "system_role": system_role(),
        "location_code": location_code(),
        "node_id": node_id(),
        "schema_version": schema_version(),
        "app_version": app_version(),
    }
