"""Stop password guessing: lock a username out after too many wrong passwords.

Counted per username (not per IP) because behind nginx every request comes
from 127.0.0.1. Counts live in the Django cache.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache


def _key(username: str) -> str:
    return f"login-fail:{(username or '').strip().lower()}"


def _window_seconds() -> int:
    return max(1, int(getattr(settings, "LOGIN_LOCKOUT_MINUTES", 15))) * 60


def is_locked_out(username: str) -> bool:
    limit = int(getattr(settings, "LOGIN_MAX_FAILURES", 5))
    if limit <= 0 or not (username or "").strip():
        return False
    return int(cache.get(_key(username)) or 0) >= limit


def record_failure(username: str) -> None:
    if not (username or "").strip():
        return
    key = _key(username)
    if cache.add(key, 1, _window_seconds()):
        return
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, _window_seconds())


def clear_failures(username: str) -> None:
    cache.delete(_key(username))
