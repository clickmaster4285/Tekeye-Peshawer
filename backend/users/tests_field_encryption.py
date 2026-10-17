"""Sensitive columns are stored encrypted and read back as plain values."""

from __future__ import annotations

import io
import uuid
from decimal import Decimal

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings

from config import field_crypto
from users.models import Staff

KEY = Fernet.generate_key().decode()
OTHER_KEY = Fernet.generate_key().decode()


def _raw(table: str, column: str, pk_col: str, pk) -> str:
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT "{column}"::text FROM "{table}" WHERE "{pk_col}" = %s', [pk])
        return cursor.fetchone()[0]


def _staff(**kwargs):
    defaults = {"full_name": "Ahmed Khan", "cnic": "17301-1234567-1", "emergency_contact": "03001234567"}
    defaults.update(kwargs)
    return Staff.objects.create(**defaults)


@override_settings(FIELD_ENCRYPTION_KEY=KEY, FIELD_ENCRYPTION_OLD_KEYS="")
class FieldEncryptionTests(TestCase):
    def setUp(self):
        field_crypto.reset_cache()
        self.addCleanup(field_crypto.reset_cache)

    def test_staff_money_fields_are_encrypted_in_the_database(self):
        staff = _staff(salary=Decimal("85000.50"), bank_account="0123456789", iban="PK36SCBL0000001123456702")
        for column in ("salary", "bank_account", "iban"):
            stored = _raw("users_staff", column, "id", staff.pk)
            self.assertTrue(stored.startswith("enc1:"), column)
            self.assertNotIn("85000", stored)
            self.assertNotIn("0123456789", stored)
        fresh = Staff.objects.get(pk=staff.pk)
        self.assertEqual(fresh.salary, Decimal("85000.50"))
        self.assertEqual(fresh.iban, "PK36SCBL0000001123456702")
        self.assertIsNone(_staff(cnic="17301-0000000-2").salary)

    def test_rows_saved_before_encryption_still_read_and_get_encrypted(self):
        staff = _staff()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE users_staff SET iban = %s, salary = %s WHERE id = %s", ["PK00PLAIN", "1200.00", staff.pk])
        fresh = Staff.objects.get(pk=staff.pk)
        self.assertEqual((fresh.iban, fresh.salary), ("PK00PLAIN", Decimal("1200.00")))

        call_command("encrypt_fields", stdout=io.StringIO())
        self.assertTrue(_raw("users_staff", "iban", "id", staff.pk).startswith("enc1:"))
        self.assertEqual(Staff.objects.get(pk=staff.pk).iban, "PK00PLAIN")

    def test_nvr_password_is_encrypted_but_rtsp_still_works(self):
        from cameras.models import Nvr, Site
        from cameras.rtsp_utils import build_rtsp_url_from_nvr

        nvr = Nvr.objects.create(
            site=Site.objects.create(code="T", name="T"), name="N", ip_address="10.0.0.5", password="nvr-secret"
        )
        self.assertNotIn("nvr-secret", _raw(Nvr._meta.db_table, "password", "id", nvr.pk))
        self.assertIn(":nvr-secret@", build_rtsp_url_from_nvr(Nvr.objects.get(pk=nvr.pk), 1))

    def test_sync_payload_is_encrypted_inside_jsonb(self):
        from city_sync.models import SyncOutbox

        row = SyncOutbox.objects.create(
            location_code="PESHAWAR", entity_type="staff", entity_id=uuid.uuid4(),
            operation="UPSERT", entity_version=1, payload={"iban": "PK99SECRET", "salary": "500"},
        )
        stored = _raw("city_sync_syncoutbox", "payload", "seq", row.pk)
        self.assertIn('"_enc"', stored)
        self.assertNotIn("PK99SECRET", stored)
        self.assertEqual(SyncOutbox.objects.get(pk=row.pk).payload["iban"], "PK99SECRET")
        self.assertEqual(SyncOutbox.objects.values_list("payload", flat=True).get(pk=row.pk)["salary"], "500")

    def test_wrong_key_fails_loudly_and_rotation_works(self):
        staff = _staff(iban="PK11ROTATE")
        field_crypto.reset_cache()
        with override_settings(FIELD_ENCRYPTION_KEY=OTHER_KEY):
            with self.assertRaises(ImproperlyConfigured):
                Staff.objects.get(pk=staff.pk)
            field_crypto.reset_cache()
            # New key first, old key kept for reading: rotate re-encrypts with the new key.
            with override_settings(FIELD_ENCRYPTION_OLD_KEYS=KEY):
                call_command("encrypt_fields", "--rotate", stdout=io.StringIO())
            field_crypto.reset_cache()
            self.assertEqual(Staff.objects.get(pk=staff.pk).iban, "PK11ROTATE")

    def test_payroll_skips_zero_salary(self):
        _staff(full_name="Paid", salary=Decimal("100"))
        _staff(full_name="Zero", cnic="17301-0000000-3", salary=Decimal("0"))
        paid = [s.full_name for s in Staff.objects.exclude(salary__isnull=True) if s.salary]
        self.assertEqual(paid, ["Paid"])
