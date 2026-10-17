"""Encrypt sensitive columns in the database (Fernet: AES-128-CBC + HMAC-SHA256).

The model fields below encrypt on save and decrypt on load, so the rest of the code
keeps working with plain values. A database dump, backup or SQL user sees only
"enc1:..." text.

Key (one per site, never stored in the database):
- FIELD_ENCRYPTION_KEY in .env, or else
- backend/.keys/field_encryption.key, created on first use.
BACK THE KEY UP SEPARATELY FROM THE DATABASE: without it the encrypted values are lost.
To change the key, put the new key in FIELD_ENCRYPTION_KEY, list the old one in
FIELD_ENCRYPTION_OLD_KEYS (comma-separated) and run `manage.py encrypt_fields --rotate`.

Rows saved before encryption (plain text) still read normally. The migrations that
switched each column encrypt the small tables; `manage.py encrypt_fields` encrypts the
rest (e.g. the large sync outbox) in batches.

Encrypted columns cannot be searched, filtered or sorted in SQL (each save gives a
different ciphertext), so only use these fields for values the code never queries.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from decimal import Decimal
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

logger = logging.getLogger(__name__)

PREFIX = "enc1:"
ENC_KEY = "_enc"
_KEY_FILE = "field_encryption.key"
_lock = threading.Lock()
_fernet: MultiFernet | None = None


def _key_file() -> Path:
    folder = Path(getattr(settings, "VIEW_PASS_KEY_DIR", "") or (Path(settings.BASE_DIR) / ".keys"))
    folder.mkdir(parents=True, exist_ok=True)
    return folder / _KEY_FILE


def _primary_key() -> bytes:
    from_env = (getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "").strip()
    if from_env:
        return from_env.encode()
    path = _key_file()
    if not path.exists():
        # O_EXCL: two processes starting together cannot write two different keys.
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as fh:
                fh.write(Fernet.generate_key())
            logger.warning("Created a new field encryption key at %s - BACK IT UP NOW.", path)
    return path.read_bytes().strip()


def fernet() -> MultiFernet:
    global _fernet
    if _fernet is None:
        with _lock:
            if _fernet is None:
                keys = [_primary_key()] + [
                    k.strip().encode()
                    for k in (getattr(settings, "FIELD_ENCRYPTION_OLD_KEYS", "") or "").split(",")
                    if k.strip()
                ]
                try:
                    _fernet = MultiFernet([Fernet(k) for k in keys])
                except ValueError as exc:
                    raise ImproperlyConfigured(f"Bad field encryption key: {exc}") from exc
    return _fernet


def reset_cache() -> None:
    """Forget the loaded key (tests, key rotation)."""
    global _fernet
    _fernet = None


def encrypt_str(value: str) -> str:
    return PREFIX + fernet().encrypt(value.encode()).decode()


def decrypt_str(value: str) -> str:
    """Plain text from the database; values without the prefix are pre-encryption rows."""
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    try:
        return fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise ImproperlyConfigured(
            "Cannot decrypt a database value: FIELD_ENCRYPTION_KEY / .keys/field_encryption.key "
            "is not the key this data was saved with."
        ) from exc


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


class _EncryptedMixin:
    """Stored as text whatever the Python type; plain values in, plain values out."""

    def db_type(self, connection):
        return "text"

    def rel_db_type(self, connection):
        return "text"

    def _to_plain_str(self, value) -> str:
        return str(value)

    def _from_plain_str(self, value: str):
        return self.to_python(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return encrypt_str(self._to_plain_str(value))

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        return self._from_plain_str(decrypt_str(value))

    def get_db_prep_value(self, value, connection, prepared=False):
        # Skip the parent's DB-specific step (e.g. Decimal quantising) - the value is already text.
        if not prepared:
            value = self.get_prep_value(value)
        return value


class EncryptedCharField(_EncryptedMixin, models.CharField):
    """Like CharField (max_length still checks the plain value), stored encrypted."""


class EncryptedDecimalField(_EncryptedMixin, models.DecimalField):
    """Like DecimalField (API still sees a number), stored encrypted."""

    def _to_plain_str(self, value) -> str:
        return str(Decimal(value))


class EncryptedJSONField(models.JSONField):
    """Like JSONField, but the column holds {"_enc": "enc1:..."} instead of the data.

    The column stays jsonb, so switching a big table to this field needs no table
    rewrite; rows saved before the switch are plain JSON and still read normally.
    """

    def get_prep_value(self, value):
        if value is None:
            return None
        return {ENC_KEY: encrypt_str(json.dumps(value, cls=self.encoder or DjangoJSONEncoder))}

    def from_db_value(self, value, expression, connection):
        value = super().from_db_value(value, expression, connection)
        if isinstance(value, dict) and set(value) == {ENC_KEY}:
            return json.loads(decrypt_str(value[ENC_KEY]))
        return value


# ---------------------------------------------------------------------------
# Migration helpers: encrypt / decrypt rows saved before a column was switched.
# ---------------------------------------------------------------------------


def _wrap_json(text: str) -> str:
    return json.dumps({ENC_KEY: encrypt_str(text)})


def _unwrap_json(text: str) -> str:
    data = json.loads(text)
    return decrypt_str(data[ENC_KEY]) if isinstance(data, dict) and set(data) == {ENC_KEY} else text


def _is_plain(stored: str, is_json: bool) -> bool:
    if is_json:
        data = json.loads(stored)
        return not (isinstance(data, dict) and set(data) == {ENC_KEY})
    return stored != "" and not is_encrypted(stored)


def rewrite_rows(connection, model, field_name: str, *, encrypt: bool, rotate: bool = False, batch: int = 500) -> int:
    """Encrypt (or decrypt) one column of every row, in primary-key order, `batch` rows at a time.

    Raw SQL, so it works from migrations and never loads the whole table into memory.
    rotate=True also re-encrypts already encrypted values with the current key.
    """
    field = model._meta.get_field(field_name)
    is_json = field.get_internal_type() == "JSONField"
    quote = connection.ops.quote_name
    table, pk, col = quote(model._meta.db_table), quote(model._meta.pk.column), quote(field.column)
    read_col = f"{col}::text" if is_json else col
    write_value = "%s::jsonb" if is_json else "%s"
    last = None
    changed = 0
    while True:
        with connection.cursor() as cursor:
            where = f"WHERE {col} IS NOT NULL" + (f" AND {pk} > %s" if last is not None else "")
            cursor.execute(
                f"SELECT {pk}, {read_col} FROM {table} {where} ORDER BY {pk} LIMIT {int(batch)}",
                [last] if last is not None else [],
            )
            rows = cursor.fetchall()
            if not rows:
                break
            last = rows[-1][0]
            updates = []
            for row_pk, stored in rows:
                plain = _is_plain(stored, is_json)
                if encrypt and plain:
                    updates.append((_wrap_json(stored) if is_json else encrypt_str(stored), row_pk))
                elif encrypt and rotate:
                    plain_text = _unwrap_json(stored) if is_json else decrypt_str(stored)
                    updates.append((_wrap_json(plain_text) if is_json else encrypt_str(plain_text), row_pk))
                elif not encrypt and not plain:
                    updates.append((_unwrap_json(stored) if is_json else decrypt_str(stored), row_pk))
            if updates:
                cursor.executemany(f"UPDATE {table} SET {col} = {write_value} WHERE {pk} = %s", updates)
                changed += len(updates)
    if changed:
        logger.info("%s %s rows of %s.%s", "Encrypted" if encrypt else "Decrypted", changed, table, field_name)
    return changed


def encrypt_existing(app_label: str, model_name: str, fields: list[str]):
    """RunPython forward: encrypt rows saved before the column was switched."""

    def forward(apps, schema_editor):
        model = apps.get_model(app_label, model_name)
        for name in fields:
            rewrite_rows(schema_editor.connection, model, name, encrypt=True)

    return forward


def decrypt_existing(app_label: str, model_name: str, fields: list[str]):
    """RunPython backward: write plain values back before the column type is restored."""

    def backward(apps, schema_editor):
        model = apps.get_model(app_label, model_name)
        for name in fields:
            rewrite_rows(schema_editor.connection, model, name, encrypt=False)

    return backward
