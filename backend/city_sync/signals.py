"""Generic hooks: every SYNCED_ENTITY_TYPES model → Outbox (+ media)."""

from __future__ import annotations

import logging

from django.apps import apps
from django.conf import settings
from django.db.models.signals import post_save, pre_delete, pre_save

from city_sync.identity import location_code
from city_sync.outbox import enqueue_from_instance
from city_sync.syncable import (
    EVIDENCE_ENTITY_TYPES,
    SYNC_MEDIA_FIELDS,
    SYNCED_ENTITY_TYPES,
    entity_type_for_model,
    new_entity_id,
)

logger = logging.getLogger(__name__)

_SYNC_SKIP_ATTR = "_city_sync_skip_outbox"
_CONNECTED = False


def _pre_save(sender, instance, **kwargs):
    entity_type = entity_type_for_model(sender)
    if not entity_type:
        return
    if getattr(instance, _SYNC_SKIP_ATTR, False):
        return

    if not getattr(instance, "location_code", None):
        instance.location_code = location_code()
    if not getattr(instance, "entity_id", None):
        # Reuse UUID primary keys when present
        pk = getattr(instance, "pk", None)
        if pk is not None and hasattr(pk, "hex"):
            instance.entity_id = pk
        else:
            instance.entity_id = new_entity_id()

    if instance.pk:
        try:
            old = sender.objects.filter(pk=instance.pk).values("version").first()
        except Exception:  # noqa: BLE001
            old = None
        if old is not None:
            prev = int(old.get("version") or 0)
            current = int(getattr(instance, "version", 1) or 1)
            if current <= prev:
                instance.version = prev + 1
        elif not getattr(instance, "version", None):
            instance.version = 1
    elif not getattr(instance, "version", None):
        instance.version = 1


def _post_save(sender, instance, created, **kwargs):
    entity_type = entity_type_for_model(sender)
    if not entity_type:
        return
    if getattr(instance, _SYNC_SKIP_ATTR, False):
        return
    if not getattr(settings, "SYNC_OUTBOX_ENABLED", True):
        return

    enqueue_from_instance(instance, entity_type=entity_type, created=created)

    if not getattr(settings, "SYNC_MEDIA_ENABLED", True):
        return
    fields = SYNC_MEDIA_FIELDS.get(entity_type) or []
    if not fields:
        return
    try:
        from city_sync.media_sync import enqueue_media_file
        from city_sync.models import MediaQueue

        priority = (
            MediaQueue.PRIORITY_EVIDENCE
            if entity_type in EVIDENCE_ENTITY_TYPES
            else MediaQueue.PRIORITY_ROUTINE
        )
        for fname in fields:
            f = getattr(instance, fname, None)
            name = getattr(f, "name", "") if f else ""
            if name:
                enqueue_media_file(
                    absolute_or_media_path=name,
                    record_entity_type=entity_type,
                    record_entity_id=instance.entity_id,
                    priority=priority,
                    wait_outbox_done=True,
                )
    except Exception:  # noqa: BLE001
        logger.exception("Media enqueue failed for %s pk=%s", entity_type, instance.pk)


def _forbid_hard_delete(sender, instance, **kwargs):
    entity_type = entity_type_for_model(sender)
    if not entity_type:
        return
    if not getattr(settings, "SYNC_FORBID_HARD_DELETE", True):
        return
    raise RuntimeError(
        f"Hard delete forbidden for synced entity '{entity_type}'. "
        "Set is_deleted=True and save() so a tombstone is synced to HQ."
    )


def connect_signals() -> None:
    global _CONNECTED
    if _CONNECTED:
        return
    for entity_type, label in SYNCED_ENTITY_TYPES.items():
        try:
            model = apps.get_model(label)
        except LookupError:
            logger.warning("Synced model not found: %s (%s)", entity_type, label)
            continue
        pre_save.connect(
            _pre_save,
            sender=model,
            dispatch_uid=f"city_sync.pre_save.{entity_type}",
        )
        post_save.connect(
            _post_save,
            sender=model,
            dispatch_uid=f"city_sync.post_save.{entity_type}",
        )
        pre_delete.connect(
            _forbid_hard_delete,
            sender=model,
            dispatch_uid=f"city_sync.pre_delete.{entity_type}",
        )
    _CONNECTED = True
    logger.info("city_sync signals connected for %s entities", len(SYNCED_ENTITY_TYPES))


try:
    connect_signals()
except Exception:  # noqa: BLE001
    logger.debug("city_sync signals deferred", exc_info=True)
