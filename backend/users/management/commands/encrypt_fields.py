"""Encrypt old plain-text rows of every encrypted column, or re-encrypt with a new key.

    python manage.py encrypt_fields            # encrypt rows saved before encryption
    python manage.py encrypt_fields --rotate   # after changing FIELD_ENCRYPTION_KEY
    python manage.py encrypt_fields --status   # count plain vs encrypted, change nothing

Safe to stop and run again: it works in small batches and skips rows already done.
"""

from __future__ import annotations

import json

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection

from config.field_crypto import (
    ENC_KEY,
    EncryptedCharField,
    EncryptedDecimalField,
    EncryptedJSONField,
    PREFIX,
    rewrite_rows,
)

ENCRYPTED_FIELD_TYPES = (EncryptedCharField, EncryptedDecimalField, EncryptedJSONField)


def encrypted_columns():
    for model in apps.get_models():
        for field in model._meta.concrete_fields:
            if isinstance(field, ENCRYPTED_FIELD_TYPES):
                yield model, field


class Command(BaseCommand):
    help = "Encrypt plain rows of encrypted columns (or --rotate to re-encrypt with the current key)."

    def add_arguments(self, parser):
        parser.add_argument("--rotate", action="store_true", help="Re-encrypt every value with the current key.")
        parser.add_argument("--status", action="store_true", help="Only report counts.")
        parser.add_argument("--batch", type=int, default=500)

    def handle(self, *args, **opts):
        for model, field in encrypted_columns():
            label = f"{model._meta.label}.{field.name}"
            if opts["status"]:
                self.stdout.write(f"{label}: {self._counts(model, field)}")
                continue
            changed = rewrite_rows(
                connection, model, field.name, encrypt=True, rotate=opts["rotate"], batch=opts["batch"]
            )
            self.stdout.write(f"{label}: {changed} rows {'re-encrypted' if opts['rotate'] else 'encrypted'}")

    def _counts(self, model, field) -> str:
        quote = connection.ops.quote_name
        col, table = quote(field.column), quote(model._meta.db_table)
        with connection.cursor() as cursor:
            if isinstance(field, EncryptedJSONField):
                cursor.execute(
                    f"SELECT count(*) FILTER (WHERE {col} ? %s), count(*) FILTER (WHERE NOT {col} ? %s) "
                    f"FROM {table} WHERE {col} IS NOT NULL",
                    [ENC_KEY, ENC_KEY],
                )
            else:
                cursor.execute(
                    # ::text so it also works before the migration (e.g. salary still numeric).
                    f"SELECT count(*) FILTER (WHERE {col}::text LIKE %s), count(*) FILTER (WHERE {col}::text NOT LIKE %s) "
                    f"FROM {table} WHERE {col} IS NOT NULL AND {col}::text <> ''",
                    [PREFIX + "%", PREFIX + "%"],
                )
            encrypted, plain = cursor.fetchone()
        return json.dumps({"encrypted": encrypted, "plain": plain})
