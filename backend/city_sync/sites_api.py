"""HQ Locations admin API (Stage 2) — add / connect / pause / full-history for city servers.

Super Admin only, and only on the HQ node. City servers push to HQ on their own;
these endpoints manage which cities HQ accepts and what HQ asks them to do.
"""

from __future__ import annotations

import re
import secrets
import uuid
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from city_sync.audit import audit
from city_sync.identity import location_code as hq_location_code
from city_sync.models import HqCityStatus, HqDownlink, HqMediaObject, HqReplicaRow, SyncCredential, SyncSite
from city_sync.views import IsHqRole, city_health_state
from users.models import User
from users.permissions import IsGlobalAdmin

LOCATION_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
LOCATION_LABELS = dict(User.LOCATION_CHOICES)
TEST_TIMEOUT_SECONDS = 5


_MAP_PATTERNS = (
    # Exact place pin in a Google Maps link: ...!3d34.0080!4d71.5789
    re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)"),
    # ?q=34.008,71.5789  /  ?ll=  /  query=
    re.compile(r"[?&](?:q|ll|query|destination)=(-?\d+(?:\.\d+)?)\s*(?:,|%2C)\s*(-?\d+(?:\.\d+)?)", re.I),
    # Map view centre: /@34.008,71.5789,17z
    re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)"),
    # Plain "34.008, 71.5789"
    re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$"),
)


def parse_map_location(raw: str) -> tuple[float, float] | None:
    """(lat, lng) from "34.008, 71.5789" or a Google Maps link; None when empty. ValueError if unreadable."""
    text = (raw or "").strip()
    if not text:
        return None
    for pattern in _MAP_PATTERNS:
        m = pattern.search(text)
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return round(lat, 6), round(lng, 6)
    raise ValueError(
        "Could not read a map position. Paste the Google Maps link of the office, or 'latitude, longitude' "
        "(e.g. 34.008, 71.5789)."
    )


def normalize_base_url(raw: str) -> str:
    """Accept '192.168.120.13', '192.168.120.13:8000' or a full URL; return 'http://host:port'."""
    value = (raw or "").strip().rstrip("/")
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    parts = urlsplit(value)
    if not parts.hostname:
        return ""
    netloc = parts.netloc
    if parts.port is None and parts.scheme == "http":
        netloc = f"{netloc}:8000"  # Django default on every site
    return f"{parts.scheme}://{netloc}"


def hq_public_url(request) -> str:
    configured = (getattr(settings, "HQ_PUBLIC_URL", "") or "").strip().rstrip("/")
    if configured:
        return configured
    return request.build_absolute_uri("/").rstrip("/")


def city_env_snippet(request, site: SyncSite, api_key: str) -> str:
    return "\n".join(
        [
            "SYSTEM_ROLE=city",
            f"LOCATION_CODE={site.location_code}",
            f"NODE_ID={site.location_code.lower().replace('_', '-')}-app-01",
            f"HQ_SYNC_URL={hq_public_url(request)}/api/sync/v1",
            f"SYNC_API_KEY={api_key}",
        ]
    )


def issue_key(site: SyncSite) -> str:
    """Create or replace the site's API key. Only the hash is stored; the raw key is shown once."""
    raw = secrets.token_urlsafe(32)
    SyncCredential.objects.update_or_create(
        location_code=site.location_code,
        defaults={
            "key_hash": SyncCredential.hash_key(raw),
            "label": site.name,
            "is_active": True,
            "revoked_at": None,
        },
    )
    return raw


def serialize_site(site: SyncSite, *, status_row, record_count: int, media_count: int, now) -> dict:
    state, age = ("UNKNOWN", None) if status_row is None else city_health_state(status_row, now)
    if site.is_paused:
        state = "PAUSED"
    full_history = "NONE"
    if site.full_history_request_id:
        full_history = "DONE" if site.full_history_done_at else "REQUESTED"
    return {
        "location_code": site.location_code,
        "name": site.name,
        "base_url": site.base_url,
        "is_paused": site.is_paused,
        "state": state,
        "heartbeat_age_sec": age,
        "last_heartbeat_at": status_row.last_heartbeat_at if status_row else None,
        "app_version": status_row.app_version if status_row else "",
        "pending_outbox": status_row.pending_outbox if status_row else 0,
        "dead_outbox": status_row.dead_outbox if status_row else 0,
        "pending_media": status_row.pending_media if status_row else 0,
        "failed_media": status_row.failed_media if status_row else 0,
        "disk_percent": status_row.disk_percent if status_row else None,
        "records_received": record_count,
        "media_received": media_count,
        "full_history": full_history,
        "full_history_requested_at": site.full_history_requested_at,
        "full_history_done_at": site.full_history_done_at,
        "last_test_at": site.last_test_at,
        "last_test_ok": site.last_test_ok,
        "last_test_detail": site.last_test_detail,
        "latitude": site.latitude,
        "longitude": site.longitude,
        **_downlink_counts(site.location_code),
        "created_at": site.created_at,
    }


def _downlink_counts(loc: str) -> dict:
    """HQ -> city HR changes (Stage 4): waiting for the city, and failed there."""
    rows = HqDownlink.objects.filter(location_code=loc)
    failed = rows.filter(status=HqDownlink.STATUS_FAILED).order_by("-seq").first()
    return {
        "downlink_pending": rows.filter(status=HqDownlink.STATUS_PENDING).count(),
        "downlink_failed": rows.filter(status=HqDownlink.STATUS_FAILED).count(),
        "downlink_last_error": failed.error[:300] if failed else "",
    }


def _serialize_one(site: SyncSite) -> dict:
    return serialize_site(
        site,
        status_row=HqCityStatus.objects.filter(location_code=site.location_code).first(),
        record_count=HqReplicaRow.objects.filter(location_code=site.location_code).count(),
        media_count=HqMediaObject.objects.filter(
            location_code=site.location_code, status=HqMediaObject.STATUS_VERIFIED
        ).count(),
        now=timezone.now(),
    )


def _get_site(code: str) -> SyncSite | None:
    return SyncSite.objects.filter(location_code=(code or "").strip().upper()).first()


class _SitesAdminView(APIView):
    permission_classes = [IsAuthenticated, IsGlobalAdmin, IsHqRole]


class SyncSitesView(_SitesAdminView):
    def get(self, request):
        now = timezone.now()
        statuses = {s.location_code: s for s in HqCityStatus.objects.all()}
        records = dict(
            HqReplicaRow.objects.values_list("location_code").annotate(n=Count("id")).values_list(
                "location_code", "n"
            )
        )
        media = dict(
            HqMediaObject.objects.filter(status=HqMediaObject.STATUS_VERIFIED)
            .values_list("location_code")
            .annotate(n=Count("id"))
            .values_list("location_code", "n")
        )
        sites = [
            serialize_site(
                site,
                status_row=statuses.get(site.location_code),
                record_count=records.get(site.location_code, 0),
                media_count=media.get(site.location_code, 0),
                now=now,
            )
            for site in SyncSite.objects.all()
        ]
        registered = {s["location_code"] for s in sites}
        return Response(
            {
                "hq": {"location_code": hq_location_code(), "public_url": hq_public_url(request)},
                "sites": sites,
                # Cities still sending with an old .env key but not added on this page.
                "unregistered": sorted(code for code in statuses if code not in registered),
                "location_options": [
                    {"code": code, "label": label}
                    for code, label in User.LOCATION_CHOICES
                    if code != hq_location_code()
                ],
            }
        )

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        code = str(body.get("location_code") or "").strip().upper()
        name = str(body.get("name") or "").strip() or LOCATION_LABELS.get(code, code.title())
        base_url = normalize_base_url(str(body.get("base_url") or ""))

        if not LOCATION_CODE_RE.match(code):
            return Response(
                {"detail": "Location code must be capital letters, digits or _ (e.g. MARDAN, DI_KHAN)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if code == hq_location_code():
            return Response(
                {"detail": f"{code} is this head-office server."}, status=status.HTTP_400_BAD_REQUEST
            )
        if not base_url:
            return Response(
                {"detail": "Enter the city server address, e.g. 192.168.120.13 or http://192.168.120.13:8000."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if SyncSite.objects.filter(location_code=code).exists():
            return Response(
                {"detail": f"{code} is already added."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            pin = parse_map_location(str(body.get("map_location") or ""))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            site = SyncSite.objects.create(
                location_code=code,
                name=name[:128],
                base_url=base_url,
                latitude=pin[0] if pin else None,
                longitude=pin[1] if pin else None,
            )
            api_key = issue_key(site)
        audit("site_added", actor=request.user.username, loc=code, detail={"base_url": base_url})
        return Response(
            {
                "site": _serialize_one(site),
                "api_key": api_key,
                "env_snippet": city_env_snippet(request, site, api_key),
            },
            status=status.HTTP_201_CREATED,
        )


class SyncSiteDetailView(_SitesAdminView):
    def patch(self, request, code: str):
        site = _get_site(code)
        if site is None:
            return Response({"detail": "Location not found."}, status=status.HTTP_404_NOT_FOUND)
        body = request.data if isinstance(request.data, dict) else {}
        changed = {}
        if "name" in body:
            name = str(body.get("name") or "").strip()
            if not name:
                return Response({"detail": "Name cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
            site.name = changed["name"] = name[:128]
        if "base_url" in body:
            base_url = normalize_base_url(str(body.get("base_url") or ""))
            if not base_url:
                return Response({"detail": "Enter a valid server address."}, status=status.HTTP_400_BAD_REQUEST)
            site.base_url = changed["base_url"] = base_url
        if "is_paused" in body:
            site.is_paused = changed["is_paused"] = bool(body.get("is_paused"))
        if "map_location" in body:
            try:
                pin = parse_map_location(str(body.get("map_location") or ""))
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            site.latitude, site.longitude = pin if pin else (None, None)
            changed["map_location"] = list(pin) if pin else None
        site.save()
        audit("site_updated", actor=request.user.username, loc=site.location_code, detail={**changed})
        return Response({"site": _serialize_one(site)})

    def delete(self, request, code: str):
        site = _get_site(code)
        if site is None:
            return Response({"detail": "Location not found."}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            SyncCredential.objects.filter(location_code=site.location_code).update(
                is_active=False, revoked_at=timezone.now()
            )
            site.delete()
        # Records and media already received stay at HQ.
        audit("site_removed", actor=request.user.username, loc=code.upper())
        return Response(status=status.HTTP_204_NO_CONTENT)


class SyncSiteRotateKeyView(_SitesAdminView):
    def post(self, request, code: str):
        site = _get_site(code)
        if site is None:
            return Response({"detail": "Location not found."}, status=status.HTTP_404_NOT_FOUND)
        api_key = issue_key(site)
        audit("site_key_rotated", actor=request.user.username, loc=site.location_code)
        return Response({"api_key": api_key, "env_snippet": city_env_snippet(request, site, api_key)})


class SyncSiteTestView(_SitesAdminView):
    """HQ → city reachability: GET {base_url}/api/sync/v1/identity/ and check who answers."""

    def post(self, request, code: str):
        site = _get_site(code)
        if site is None:
            return Response({"detail": "Location not found."}, status=status.HTTP_404_NOT_FOUND)
        url = f"{site.base_url}/api/sync/v1/identity/"
        ok = False
        identity = None
        try:
            resp = requests.get(url, timeout=TEST_TIMEOUT_SECONDS)
            if resp.status_code == 404:
                detail = "Server reached, but it has no sync module. Deploy the new code on this city."
            elif not resp.ok:
                detail = f"Server reached, but it answered HTTP {resp.status_code}."
            else:
                identity = resp.json()
                role = str(identity.get("system_role") or "")
                remote_code = str(identity.get("location_code") or "").upper()
                if role != "city":
                    detail = f"Server reached, but its .env has SYSTEM_ROLE={role or '(empty)'}; it must be city."
                elif remote_code != site.location_code:
                    detail = (
                        f"Server reached, but its .env has LOCATION_CODE={remote_code or '(empty)'}; "
                        f"it must be {site.location_code}."
                    )
                else:
                    ok = True
                    detail = f"Connected to {remote_code} (node {identity.get('node_id') or '-'})."
        except requests.Timeout:
            detail = f"No answer from {site.base_url} within {TEST_TIMEOUT_SECONDS}s. Check the IP, port and firewall."
        except requests.RequestException:
            detail = f"Cannot reach {site.base_url}. Check the IP, port and that the city backend is running."
        except ValueError:
            detail = "Server reached, but the answer was not valid JSON. Is this the CIIS backend port?"

        site.last_test_at = timezone.now()
        site.last_test_ok = ok
        site.last_test_detail = detail[:500]
        site.save(update_fields=["last_test_at", "last_test_ok", "last_test_detail", "updated_at"])
        return Response({"ok": ok, "detail": detail, "identity": identity, "site": _serialize_one(site)})


class SyncSiteFullHistoryView(_SitesAdminView):
    """Ask the city (on its next heartbeat) to send all existing records and media."""

    def post(self, request, code: str):
        site = _get_site(code)
        if site is None:
            return Response({"detail": "Location not found."}, status=status.HTTP_404_NOT_FOUND)
        site.full_history_request_id = uuid.uuid4().hex
        site.full_history_requested_at = timezone.now()
        site.full_history_done_at = None
        site.save(
            update_fields=[
                "full_history_request_id",
                "full_history_requested_at",
                "full_history_done_at",
                "updated_at",
            ]
        )
        audit("site_full_history_requested", actor=request.user.username, loc=site.location_code)
        return Response({"site": _serialize_one(site)})
