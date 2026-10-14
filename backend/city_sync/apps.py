from django.apps import AppConfig


class CitySyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "city_sync"
    verbose_name = "City ↔ HQ Sync"

    def ready(self) -> None:
        import sys

        from django.conf import settings

        skip_cmds = {
            "migrate",
            "makemigrations",
            "showmigrations",
            "collectstatic",
            "test",
            "prepare_full_table_sync",
        }
        is_prepare = "prepare_full_table_sync" in sys.argv

        try:
            from city_sync.full_registry import ensure_all_orm_sync_fields
            from city_sync.syncable import refresh_synced_registry

            # ORM fields so signals/outbox see entity_id on every business model.
            ensure_all_orm_sync_fields()
            refresh_synced_registry()
        except Exception:  # noqa: BLE001
            pass

        from city_sync import signals

        try:
            signals.connect_signals()
        except Exception:  # noqa: BLE001
            pass

        if getattr(settings, "SYNC_SKIP_BOOT_CHECK", False):
            return
        if any(cmd in sys.argv for cmd in skip_cmds) and not is_prepare:
            return
        if is_prepare:
            return
        from city_sync.identity import validate_node_identity

        validate_node_identity()
