"""Discover + prepare ALL business tables for city → HQ outbox sync."""

from __future__ import annotations

import logging
import re
from typing import Iterable

from django.apps import apps
from django.db import connection, models

logger = logging.getLogger(__name__)

# Django / infra / HQ-local — never city-outbox these.
SYNC_EXCLUDE_APPS: frozenset[str] = frozenset(
    {
        "admin",
        "auth",
        "contenttypes",
        "sessions",
        "messages",
        "staticfiles",
        "corsheaders",
        "rest_framework",
        "authtoken",
        "django_filters",
        "city_sync",  # sync meta tables stay local
        "ops_central",  # HQ registry only
        "realtime",
    }
)

SYNC_EXCLUDE_MODELS: frozenset[str] = frozenset(
    {
        # Keep passwords/tokens from being bulk-synced unless explicitly needed later
        # (User is included — remove from exclude to sync accounts)
    }
)

def _snake(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def iter_candidate_models() -> Iterable[type[models.Model]]:
    for model in apps.get_models():
        if model._meta.proxy or model._meta.abstract:
            continue
        app = model._meta.app_label
        if app in SYNC_EXCLUDE_APPS or app.startswith("django"):
            continue
        label = f"{app}.{model._meta.object_name}"
        if label in SYNC_EXCLUDE_MODELS:
            continue
        yield model


def model_label(model) -> str:
    return f"{model._meta.app_label}.{model._meta.object_name}"


def entity_type_for_label(label: str) -> str:
    """users.LeaveType → leave_type (unique across apps: app_model if clash)."""
    app, name = label.split(".", 1)
    base = _snake(name)
    return base


def ensure_orm_sync_fields(model: type[models.Model]) -> list[str]:
    """Attach sync fields on the model class at runtime (ORM awareness)."""
    added: list[str] = []
    existing = {f.name for f in model._meta.local_fields}
    specs: list[tuple[str, models.Field]] = [
        ("entity_id", models.UUIDField(null=True, blank=True, unique=True, db_index=True, editable=False)),
        ("location_code", models.CharField(max_length=64, blank=True, default="", db_index=True)),
        ("version", models.PositiveIntegerField(default=1)),
        ("is_deleted", models.BooleanField(default=False, db_index=True)),
    ]
    for name, field in specs:
        if name in existing:
            continue
        try:
            field.contribute_to_class(model, name)
            added.append(name)
            existing.add(name)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to contribute %s on %s", name, model_label(model))
    return added


def ensure_all_orm_sync_fields() -> int:
    n = 0
    for model in iter_candidate_models():
        added = ensure_orm_sync_fields(model)
        if added:
            n += 1
            logger.info("ORM sync fields on %s: %s", model_label(model), added)
    return n


def _table_columns(table: str) -> set[str]:
    with connection.cursor() as c:
        c.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = %s
            """,
            [table],
        )
        return {r[0] for r in c.fetchall()}


def ensure_db_sync_columns(model: type[models.Model]) -> list[str]:
    """ADD COLUMN IF NOT EXISTS for sync fields on the physical table."""
    table = model._meta.db_table
    cols = _table_columns(table)
    if not cols:
        return []
    added: list[str] = []
    stmts: list[tuple[str, str]] = [
        (
            "entity_id",
            f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS entity_id uuid NULL',
        ),
        (
            "location_code",
            f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS location_code varchar(64) NOT NULL DEFAULT \'\'',
        ),
        (
            "version",
            f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1',
        ),
        (
            "is_deleted",
            f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false',
        ),
    ]
    with connection.cursor() as c:
        for col, sql in stmts:
            if col in cols:
                continue
            # location_code may already exist with different nullability
            if col == "location_code" and "location_code" in cols:
                continue
            c.execute(sql)
            added.append(col)
        # Unique index for entity_id (NULLs ok in Postgres)
        if "entity_id" in added or "entity_id" in cols:
            idx = f"{table}_entity_id_uniq"
            c.execute(
                f'CREATE UNIQUE INDEX IF NOT EXISTS "{idx}" ON "{table}" (entity_id)'
            )
        if "is_deleted" in added or "is_deleted" in cols:
            c.execute(
                f'CREATE INDEX IF NOT EXISTS "{table}_is_deleted_idx" ON "{table}" (is_deleted)'
            )
        if "location_code" in added or "location_code" in cols:
            c.execute(
                f'CREATE INDEX IF NOT EXISTS "{table}_location_code_idx" ON "{table}" (location_code)'
            )
    return added


def ensure_all_db_sync_columns() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for model in iter_candidate_models():
        added = ensure_db_sync_columns(model)
        if added:
            out[model_label(model)] = added
    return out


def build_synced_entity_types() -> dict[str, str]:
    """
    Map entity_type → app.Model for every candidate model.
    Prefer short snake names; disambiguate clashes with app prefix.
    """
    used: dict[str, str] = {}
    result: dict[str, str] = {}
    for model in sorted(iter_candidate_models(), key=lambda m: model_label(m)):
        label = model_label(model)
        et = entity_type_for_label(label)
        if et in used and used[et] != label:
            et = f"{model._meta.app_label}_{et}"
        used[et] = label
        result[et] = label
    return result


def build_sync_media_fields(entity_types: dict[str, str]) -> dict[str, list[str]]:
    media: dict[str, list[str]] = {}
    for et, label in entity_types.items():
        try:
            model = apps.get_model(label)
        except LookupError:
            continue
        names: list[str] = []
        for f in model._meta.get_fields():
            if isinstance(f, (models.FileField, models.ImageField)):
                names.append(f.name)
        if names:
            media[et] = names
    return media
