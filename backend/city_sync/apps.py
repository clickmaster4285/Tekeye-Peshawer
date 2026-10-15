from django.apps import AppConfig


class CitySyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "city_sync"
    verbose_name = "City ↔ HQ Sync"

    def ready(self) -> None:
        # Identity boot check (Phase 1). Soft-fail in tests via SYNC_SKIP_BOOT_CHECK.
        import sys

        from django.conf import settings

        # Always register signals for all SYNCED_ENTITY_TYPES.
        from city_sync import signals

        try:
            signals.connect_signals()
        except Exception:  # noqa: BLE001
            pass

        if getattr(settings, "SYNC_SKIP_BOOT_CHECK", False):
            return
        # Avoid blocking migrate/makemigrations/shell collectstatic on partial env.
        skip_cmds = {"migrate", "makemigrations", "showmigrations", "collectstatic", "test"}
        if any(cmd in sys.argv for cmd in skip_cmds):
            return
        from city_sync.identity import validate_node_identity

        validate_node_identity()
