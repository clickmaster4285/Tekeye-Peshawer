"""Stop password guessing without letting an attacker lock real users out.

Two counters per username, both reset by a successful login:
- per username + client IP: LOGIN_MAX_FAILURES wrong passwords lock that IP out
  of that account, so someone guessing cannot lock the owner out from their own PC;
- per username from all IPs: LOGIN_MAX_FAILURES_TOTAL is a ceiling against
  guessing spread over many machines.

Counts live in the "login_guard" cache (files on disk), which every gunicorn
worker shares; the default in-memory cache is per process.
"""

from __future__ import annotations

import ipaddress

from django.conf import settings
from django.core.cache import caches


def _cache():
    return caches["login_guard"]


def _window_seconds() -> int:
    return max(1, int(getattr(settings, "LOGIN_LOCKOUT_MINUTES", 15))) * 60


def _name(username: str) -> str:
    return (username or "").strip().lower()


def _ip_key(username: str, ip: str) -> str:
    return f"login-fail:{_name(username)}:{ip or '-'}"


def _total_key(username: str) -> str:
    return f"login-fail-all:{_name(username)}"


def _is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def client_ip(request) -> str:
    """The browser's IP. Proxy headers are trusted only from nginx on this machine."""
    remote = (request.META.get("REMOTE_ADDR") or "").strip()
    if _is_loopback(remote):
        real = (request.META.get("HTTP_X_REAL_IP") or "").strip()
        forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[-1].strip()
        for candidate in (real, forwarded):
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                continue
    return remote


def is_locked_out(username: str, ip: str = "") -> bool:
    if not _name(username):
        return False
    per_ip = int(getattr(settings, "LOGIN_MAX_FAILURES", 5))
    total = int(getattr(settings, "LOGIN_MAX_FAILURES_TOTAL", 50))
    cache = _cache()
    if per_ip > 0 and int(cache.get(_ip_key(username, ip)) or 0) >= per_ip:
        return True
    return total > 0 and int(cache.get(_total_key(username)) or 0) >= total


def _bump(key: str) -> None:
    cache = _cache()
    if cache.add(key, 1, _window_seconds()):
        return
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, _window_seconds())


def record_failure(username: str, ip: str = "") -> None:
    if not _name(username):
        return
    _bump(_ip_key(username, ip))
    _bump(_total_key(username))


def clear_failures(username: str, ip: str = "") -> None:
    _cache().delete_many([_ip_key(username, ip), _total_key(username)])
