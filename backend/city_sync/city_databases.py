"""
HQ per-city Postgres databases (dual-store with HqReplicaRow).

When SYNC_HQ_CITY_DB_ENABLED=True on HQ:
  - Creates TEKEYE_HQ_{LOCATION} (or configured template) for each connected city
  - Migrates schema to match the app
  - Projects applied sync events into real tables on that DB
  - Media remains under HQ paths (hq_sync_media + optional city_dbs mirror)

City Outbox → HqReplicaRow path is unchanged; this is an additional sink.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_ready_locations: set[str] = set()
_migrate_attempted: set[str] = set()


def hq_city_db_enabled() -> bool:
    role = str(getattr(settings, "SYSTEM_ROLE", "") or "").strip().lower()
    return role == "hq" and bool(getattr(settings, "SYNC_HQ_CITY_DB_ENABLED", False))


def known_city_locations() -> list[str]:
    """Locations from SYNC_API_KEYS + ALLOWED_LOCATION_CODES (excluding HQ self)."""
    locs: set[str] = set()
    raw = getattr(settings, "SYNC_API_KEYS", "") or ""
    for part in str(raw).split(","):
        part = part.strip()
        if "=" in part:
            locs.add(part.split("=", 1)[0].strip().upper())
    hq = str(getattr(settings, "LOCATION_CODE", "PESHAWAR") or "PESHAWAR").upper()
    for code in getattr(settings, "ALLOWED_LOCATION_CODES", []) or []:
        c = str(code).strip().upper()
        if c and c != hq and len(c) > 3:  # skip short aliases like ABT
            locs.add(c)
    locs.discard(hq)
    locs.discard("")
    return sorted(locs)


def city_db_alias(location_code: str) -> str:
    return f"city_{str(location_code).strip().upper()}"


def city_db_name(location_code: str) -> str:
    loc = str(location_code).strip().upper()
    template = getattr(settings, "SYNC_HQ_CITY_DB_NAME_TEMPLATE", "TEKEYE_HQ_{LOCATION}") or "TEKEYE_HQ_{LOCATION}"
    return template.format(LOCATION=loc)


def city_media_root(location_code: str) -> Path:
    loc = str(location_code).strip().upper()
    custom = (getattr(settings, "SYNC_HQ_CITY_MEDIA_ROOT", "") or "").strip()
    if custom:
        base = Path(custom.format(LOCATION=loc) if "{LOCATION}" in custom else custom) / loc
    else:
        base = Path(settings.MEDIA_ROOT) / "city_dbs" / loc / "media"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _default_db_settings() -> dict:
    return dict(settings.DATABASES["default"])


def register_city_database(location_code: str) -> str:
    """Register Django DATABASES alias for the city (does not create Postgres DB)."""
    loc = str(location_code).strip().upper()
    alias = city_db_alias(loc)
    cfg = _default_db_settings()
    cfg["NAME"] = city_db_name(loc)
    cfg["CONN_MAX_AGE"] = 0
    settings.DATABASES[alias] = cfg
    connections.databases[alias] = cfg
    return alias


def _postgres_exists(db_name: str) -> bool:
    # Connect via default credentials to maintenance DB
    cfg = _default_db_settings()
    maint = dict(cfg)
    maint["NAME"] = "postgres"
    maint["CONN_MAX_AGE"] = 0
    alias = "_city_db_maint"
    settings.DATABASES[alias] = maint
    connections.databases[alias] = maint
    try:
        with connections[alias].cursor() as c:
            c.execute("SELECT 1 FROM pg_database WHERE datname = %s", [db_name])
            return c.fetchone() is not None
    finally:
        connections[alias].close()


def create_postgres_database(location_code: str) -> str:
    """CREATE DATABASE if missing. Returns database name."""
    loc = str(location_code).strip().upper()
    db_name = city_db_name(loc)
    if not getattr(settings, "SYNC_HQ_CITY_DB_AUTO_CREATE", True):
        return db_name
    if _postgres_exists(db_name):
        return db_name

    cfg = _default_db_settings()
    maint = dict(cfg)
    maint["NAME"] = "postgres"
    maint["CONN_MAX_AGE"] = 0
    alias = "_city_db_maint"
    settings.DATABASES[alias] = maint
    connections.databases[alias] = maint
    try:
        # CREATE DATABASE cannot run inside a transaction
        conn = connections[alias]
        old = conn.get_autocommit()
        conn.set_autocommit(True)
        try:
            with conn.cursor() as c:
                c.execute(f'CREATE DATABASE "{db_name}"')
            logger.info("Created HQ city database %s for %s", db_name, loc)
        finally:
            conn.set_autocommit(old)
    except Exception as exc:  # noqa: BLE001
        # Race: another process created it
        if "already exists" not in str(exc).lower():
            raise
    finally:
        connections[alias].close()
    return db_name


def migrate_city_database(location_code: str, *, force: bool = False) -> None:
    loc = str(location_code).strip().upper()
    if not getattr(settings, "SYNC_HQ_CITY_DB_AUTO_MIGRATE", True) and not force:
        return
    alias = city_db_alias(loc)
    with _lock:
        if loc in _migrate_attempted and not force:
            return
        _migrate_attempted.add(loc)
    try:
        call_command(
            "migrate",
            database=alias,
            interactive=False,
            verbosity=0,
            run_syncdb=False,
        )
        logger.info("Migrated HQ city database alias=%s", alias)
    except Exception:  # noqa: BLE001
        logger.exception("migrate failed for city DB %s", loc)
        with _lock:
            _migrate_attempted.discard(loc)
        raise


def ensure_city_database(location_code: str, *, migrate: bool = True) -> str | None:
    """
    Ensure Postgres DB exists, Django alias registered, schema migrated.
    Returns alias or None if feature disabled.
    """
    if not hq_city_db_enabled():
        return None
    loc = str(location_code).strip().upper()
    if not loc:
        return None
    with _lock:
        alias = register_city_database(loc)
        if loc in _ready_locations:
            return alias
        create_postgres_database(loc)
        # Probe connection
        connections[alias].ensure_connection()
        if migrate:
            migrate_city_database(loc)
        city_media_root(loc)
        _ready_locations.add(loc)
        return alias


def ensure_all_known_city_databases() -> dict[str, str]:
    out: dict[str, str] = {}
    if not hq_city_db_enabled():
        return out
    for loc in known_city_locations():
        try:
            alias = ensure_city_database(loc)
            if alias:
                out[loc] = alias
        except Exception:  # noqa: BLE001
            logger.exception("ensure_city_database failed for %s", loc)
    return out


def _coerce_value(model, field_name: str, value: Any) -> Any:
    if value is None:
        return None
    try:
        field = model._meta.get_field(field_name)
    except Exception:  # noqa: BLE001
        return value
    internal = field.get_internal_type()
    if internal in {"UUIDField"} and not isinstance(value, UUID):
        try:
            return UUID(str(value))
        except Exception:  # noqa: BLE001
            return value
    if internal in {"DateTimeField", "DateField"} and isinstance(value, str):
        dt = parse_datetime(value)
        return dt or value
    if internal in {"BooleanField"} and isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    if internal in {"FileField", "ImageField"}:
        return value  # store path string
    return value


def project_event_to_city_db(
    *,
    location_code: str,
    entity_type: str,
    entity_id: UUID | str,
    operation: str,
    payload: dict,
) -> dict:
    """Upsert one applied event into the city's HQ Postgres DB."""
    if not hq_city_db_enabled():
        return {"skipped": True, "reason": "disabled"}

    from city_sync.syncable import SYNCED_ENTITY_TYPES, resolve_model

    loc = str(location_code).strip().upper()
    try:
        alias = ensure_city_database(loc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("city DB ensure failed loc=%s", loc)
        return {"ok": False, "error": str(exc)}

    if not alias:
        return {"skipped": True, "reason": "no_alias"}

    label = SYNCED_ENTITY_TYPES.get(entity_type)
    if not label:
        return {"skipped": True, "reason": "unknown_entity_type"}

    try:
        model = resolve_model(label)
    except LookupError:
        return {"skipped": True, "reason": "model_missing"}

    eid = entity_id if isinstance(entity_id, UUID) else UUID(str(entity_id))
    data = {k: v for k, v in (payload or {}).items() if not str(k).startswith("_")}
    pk = payload.get("_pk") if isinstance(payload, dict) else None

    # Only concrete local fields
    field_names = {f.name for f in model._meta.local_fields}
    attnames = {f.attname for f in model._meta.local_fields}
    cleaned: dict[str, Any] = {}
    for k, v in data.items():
        if k in field_names or k in attnames:
            cleaned[k] = _coerce_value(model, k, v)

    if "entity_id" in field_names and "entity_id" not in cleaned:
        cleaned["entity_id"] = eid
    if "location_code" in field_names and not cleaned.get("location_code"):
        cleaned["location_code"] = loc
    if operation == "tombstone" and "is_deleted" in field_names:
        cleaned["is_deleted"] = True

    qs = model.objects.using(alias)
    obj = None
    if "entity_id" in field_names:
        obj = qs.filter(entity_id=eid).first()
    if obj is None and pk is not None:
        obj = qs.filter(pk=pk).first()

    try:
        if obj is None:
            create_kwargs = dict(cleaned)
            if pk is not None and model._meta.pk.attname not in create_kwargs:
                create_kwargs[model._meta.pk.attname] = pk
            obj = model(**{k: v for k, v in create_kwargs.items() if k in field_names or k in attnames})
            setattr(obj, "_city_sync_skip_outbox", True)
            obj.save(using=alias, force_insert=True)
            return {"ok": True, "action": "insert", "alias": alias}
        for k, v in cleaned.items():
            setattr(obj, k, v)
        setattr(obj, "_city_sync_skip_outbox", True)
        obj.save(using=alias)
        return {"ok": True, "action": "update", "alias": alias}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "project_event_to_city_db failed loc=%s type=%s id=%s: %s",
            loc,
            entity_type,
            eid,
            exc,
        )
        return {"ok": False, "error": str(exc)}


def mirror_media_to_city_folder(*, location_code: str, source_path: str | Path, media_id: str) -> str | None:
    """Copy verified HQ media into city_dbs/{LOC}/media/ for a full Peshawar copy."""
    if not hq_city_db_enabled():
        return None
    if not getattr(settings, "SYNC_HQ_CITY_MEDIA_MIRROR", True):
        return None
    src = Path(source_path)
    if not src.is_file():
        return None
    dest_dir = city_media_root(location_code)
    dest = dest_dir / f"{media_id}{src.suffix if src.suffix != '.partial' else ''}"
    if src.suffix == "":
        dest = dest_dir / str(media_id)
    try:
        if not dest.exists() or dest.stat().st_size != src.stat().st_size:
            dest.write_bytes(src.read_bytes())
        return str(dest)
    except Exception:  # noqa: BLE001
        logger.exception("media mirror failed loc=%s media_id=%s", location_code, media_id)
        return None


def project_all_replicas(location_code: str, *, limit: int = 0) -> dict:
    """Backfill city HQ DB from existing HqReplicaRow rows."""
    from city_sync.models import HqReplicaRow

    loc = str(location_code).strip().upper()
    ensure_city_database(loc)
    qs = HqReplicaRow.objects.filter(location_code=loc).order_by("entity_type", "entity_id")
    if limit:
        qs = qs[:limit]
    ok = fail = skip = 0
    for row in qs.iterator(chunk_size=200):
        op = "tombstone" if row.is_deleted else "upsert"
        result = project_event_to_city_db(
            location_code=loc,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            operation=op,
            payload=row.payload if isinstance(row.payload, dict) else {},
        )
        if result.get("skipped"):
            skip += 1
        elif result.get("ok"):
            ok += 1
        else:
            fail += 1
    return {"location": loc, "ok": ok, "fail": fail, "skip": skip}
