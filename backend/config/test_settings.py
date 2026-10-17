"""Test settings: build schema from models so stale SeparateDatabaseAndState migrations do not block CIIS tests."""

import tempfile

from config.settings import *  # noqa: F403


class DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = DisableMigrations()

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "login_guard": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "login-guard-tests"},
}

VIEW_PASS_KEY_DIR = tempfile.mkdtemp(prefix="view-pass-keys-")
