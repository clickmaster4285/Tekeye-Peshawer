import os
import threading

from .models import UserActivityLog

try:
    import requests
except ImportError:
    requests = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# Off by default: the lookup is an outbound HTTP call on the request path, so a slow
# or rate-limited provider stalls every API response. Set true only behind a cache.
GEO_LOOKUP_ENABLED = _env_bool("ACTIVITY_LOG_GEO_LOOKUP", False)
GEO_TIMEOUT_SEC = 2.0
_GEO_CACHE: dict[str, tuple[str | None, str | None]] = {}
_GEO_CACHE_MAX = 2048
_GEO_LOCK = threading.Lock()

try:
    from user_agents import parse as parse_user_agent
except ImportError:
    parse_user_agent = None


# Paths we don't log (e.g. report endpoint to avoid duplicate entries, or health checks)
SKIP_LOG_PATHS = (
    "/api/activity-logs/report/",
    "/api/activity-logs/report",
    "/api/mobile-sessions/",
    "/api/mobile/heartbeat/",
    "/api/mobile/heartbeat",
    "/api/mobile/gps/",
    "/api/gps/ping/",
    "/api/gps/heartbeat/",
    "/favicon.ico",
    "/media/",
)

# Polled or streamed endpoints. These fire many times per minute per open tab, so an
# audit row per call is pure write amplification — they accounted for ~250k rows.
SKIP_LOG_PATH_PARTS = (
    "/ml-live/detections",
    "/ml-live/mjpeg",
    "/detection-events",
    "/person-journey/ingest",
    "/ops/servers/",
    "/ops/all-cities-streams",
    "/ops/all-cities-selection",
    "/ops/ephemeral-mjpeg",
    "/cameras/preview/mjpeg",
    "/cameras/streams",
    "/ml/status",
    "/ml-status",
)


def _valid_ip(raw) -> str | None:
    import ipaddress

    value = (raw or "").strip()
    if not value:
        return None
    if value.startswith("::ffff:"):
        value = value[7:]
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


def get_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return _valid_ip(x_forwarded_for.split(",")[0])
    return _valid_ip(request.META.get("REMOTE_ADDR"))


def get_device_info(request):
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    if parse_user_agent is None:
        return "PC", "", (user_agent or "")[:50]
    parsed = parse_user_agent(user_agent)
    device = "Mobile" if parsed.is_mobile else "PC"
    os_str = parsed.os.family or ""
    browser = parsed.browser.family or ""
    return device, os_str, browser


def _is_local_ip(ip: str) -> bool:
    """Loopback / LAN / link-local. A public geo provider can never resolve these."""
    import ipaddress

    if ip in ("127.0.0.1", "127.0.1", "localhost"):
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved


def get_geo(ip):
    if not ip or _is_local_ip(ip):
        return "Pakistan", "Local"
    if not GEO_LOOKUP_ENABLED or requests is None:
        return None, None
    with _GEO_LOCK:
        cached = _GEO_CACHE.get(ip)
    if cached is not None:
        return cached
    result: tuple[str | None, str | None] = (None, None)
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}", timeout=GEO_TIMEOUT_SEC)
        if r.ok:
            j = r.json()
            result = (j.get("country"), j.get("city"))
    except Exception:
        pass
    with _GEO_LOCK:
        if len(_GEO_CACHE) >= _GEO_CACHE_MAX:
            _GEO_CACHE.clear()
        _GEO_CACHE[ip] = result
    return result


def create_activity_log(user, request, action, source="web"):
    ip = get_ip(request)
    device, os_str, browser = get_device_info(request)
    country, city = get_geo(ip)
    UserActivityLog.objects.create(
        user=user,
        ip_address=ip,
        country=country,
        city=city,
        device=(device or "")[:50],
        os=(os_str or "")[:50],
        browser=(browser or "")[:50],
        action=action[:255],
        source=(source or "web")[:20],
    )


class ActivityLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.user.is_authenticated:
            path = request.path.rstrip("/") or "/"
            if any(path.startswith(p.rstrip("/")) for p in SKIP_LOG_PATHS):
                return response
            if any(part in path for part in SKIP_LOG_PATH_PARTS):
                return response
            action = f"{request.method} {path}"
            try:
                create_activity_log(request.user, request, action)
            except Exception:
                # Auditing must never fail the request it is auditing.
                pass

        return response
