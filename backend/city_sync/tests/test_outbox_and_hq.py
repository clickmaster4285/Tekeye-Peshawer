"""Phase 2–4 acceptance tests: Outbox atomicity + HQ idempotency."""

from __future__ import annotations

import uuid
from unittest import mock

from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from city_sync.hq_receiver import (
    RESULT_APPLIED,
    RESULT_CONFLICT,
    RESULT_DUPLICATE,
    RESULT_STALE,
    apply_event,
    apply_event_batch,
)
from city_sync.models import HqConflict, HqEventLog, HqReplicaRow, SyncOutbox
from city_sync.outbox import enqueue_outbox, model_to_payload, payload_hash
from users.models import Attendance, Staff


@override_settings(
    SYSTEM_ROLE="city",
    LOCATION_CODE="ABBOTTABAD",
    NODE_ID="abt-test-01",
    SYNC_OUTBOX_ENABLED=True,
    SYNC_FORBID_HARD_DELETE=True,
    SYNC_SKIP_BOOT_CHECK=True,
)
class OutboxCityTests(TestCase):
    def setUp(self):
        self.staff = Staff.objects.create(full_name="Sync Test Staff", employee_id="SYNC-001")

    def test_create_attendance_writes_one_outbox_row(self):
        before = SyncOutbox.objects.count()
        att = Attendance.objects.create(
            staff=self.staff,
            date=timezone.localdate(),
            status=Attendance.STATUS_PRESENT,
            source=Attendance.SOURCE_MANUAL,
        )
        self.assertIsNotNone(att.entity_id)
        self.assertEqual(att.location_code, "ABBOTTABAD")
        self.assertEqual(att.version, 1)
        self.assertEqual(SyncOutbox.objects.count(), before + 1)
        row = SyncOutbox.objects.latest("seq")
        self.assertEqual(row.entity_type, "attendance")
        self.assertEqual(row.entity_id, att.entity_id)
        self.assertEqual(row.operation, SyncOutbox.OP_UPSERT)
        self.assertEqual(row.entity_version, 1)

    def test_update_bumps_version_and_outbox(self):
        att = Attendance.objects.create(
            staff=self.staff,
            date=timezone.localdate(),
            status=Attendance.STATUS_PRESENT,
            source=Attendance.SOURCE_MANUAL,
        )
        att.status = Attendance.STATUS_LATE
        att.save()
        att.refresh_from_db()
        self.assertEqual(att.version, 2)
        versions = list(
            SyncOutbox.objects.filter(entity_id=att.entity_id).order_by("seq").values_list(
                "entity_version", flat=True
            )
        )
        self.assertEqual(versions, [1, 2])

    def test_business_rollback_leaves_no_outbox(self):
        before = SyncOutbox.objects.count()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                Attendance.objects.create(
                    staff=self.staff,
                    date=timezone.localdate(),
                    status=Attendance.STATUS_PRESENT,
                    source=Attendance.SOURCE_MANUAL,
                )
                raise RuntimeError("boom")
        self.assertEqual(SyncOutbox.objects.count(), before)

    def test_hard_delete_forbidden(self):
        att = Attendance.objects.create(
            staff=self.staff,
            date=timezone.localdate(),
            status=Attendance.STATUS_PRESENT,
            source=Attendance.SOURCE_MANUAL,
        )
        with self.assertRaises(RuntimeError):
            att.delete()

    def test_soft_delete_tombstone(self):
        att = Attendance.objects.create(
            staff=self.staff,
            date=timezone.localdate(),
            status=Attendance.STATUS_PRESENT,
            source=Attendance.SOURCE_MANUAL,
        )
        att.is_deleted = True
        att.save()
        row = SyncOutbox.objects.filter(entity_id=att.entity_id).latest("seq")
        self.assertEqual(row.operation, SyncOutbox.OP_TOMBSTONE)


@override_settings(
    SYSTEM_ROLE="hq",
    LOCATION_CODE="PESHAWAR",
    NODE_ID="pew-hq-test",
    SYNC_SCHEMA_VERSION=1,
    SYNC_SKIP_BOOT_CHECK=True,
    SYNC_API_KEYS="ABBOTTABAD=test-key-abt",
)
class HqReceiverTests(TestCase):
    def _event(self, **overrides):
        eid = overrides.pop("entity_id", uuid.uuid4())
        event_id = overrides.pop("event_id", uuid.uuid4())
        payload = overrides.pop(
            "payload",
            {"entity_id": str(eid), "status": "present", "updated_at": timezone.now().isoformat()},
        )
        base = {
            "seq": 1,
            "event_id": str(event_id),
            "location_code": "ABBOTTABAD",
            "entity_type": "attendance",
            "entity_id": str(eid),
            "operation": "upsert",
            "entity_version": 1,
            "schema_version": 1,
            "payload": payload,
            "payload_hash": payload_hash(payload),
        }
        base.update(overrides)
        return base

    def test_apply_insert(self):
        ev = self._event()
        result = apply_event(ev, credential_location="ABBOTTABAD")
        self.assertEqual(result["result"], RESULT_APPLIED)
        self.assertEqual(HqReplicaRow.objects.count(), 1)

    def test_duplicate_event_id(self):
        ev = self._event()
        self.assertEqual(apply_event(ev, credential_location="ABBOTTABAD")["result"], RESULT_APPLIED)
        self.assertEqual(apply_event(ev, credential_location="ABBOTTABAD")["result"], RESULT_DUPLICATE)
        self.assertEqual(HqReplicaRow.objects.count(), 1)
        self.assertEqual(HqEventLog.objects.count(), 1)

    def test_stale_version_does_not_overwrite(self):
        eid = uuid.uuid4()
        apply_event(self._event(entity_id=eid, entity_version=2, seq=2), credential_location="ABBOTTABAD")
        result = apply_event(
            self._event(entity_id=eid, entity_version=1, seq=3, event_id=uuid.uuid4()),
            credential_location="ABBOTTABAD",
        )
        self.assertEqual(result["result"], RESULT_STALE)
        row = HqReplicaRow.objects.get(entity_id=eid)
        self.assertEqual(row.entity_version, 2)
        self.assertTrue(HqConflict.objects.filter(entity_id=eid, reason="stale").exists())

    def test_equal_version_payload_mismatch_is_conflict(self):
        eid = uuid.uuid4()
        p1 = {"entity_id": str(eid), "status": "present", "updated_at": timezone.now().isoformat()}
        apply_event(
            self._event(entity_id=eid, payload=p1, payload_hash=payload_hash(p1)),
            credential_location="ABBOTTABAD",
        )
        p2 = {"entity_id": str(eid), "status": "late", "updated_at": timezone.now().isoformat()}
        result = apply_event(
            self._event(
                entity_id=eid,
                entity_version=1,
                seq=2,
                event_id=uuid.uuid4(),
                payload=p2,
                payload_hash=payload_hash(p2),
            ),
            credential_location="ABBOTTABAD",
        )
        self.assertEqual(result["result"], RESULT_CONFLICT)

    def test_batch_processed_in_seq_order(self):
        eid = uuid.uuid4()
        events = [
            self._event(entity_id=eid, entity_version=2, seq=20, event_id=uuid.uuid4()),
            self._event(entity_id=eid, entity_version=1, seq=10, event_id=uuid.uuid4()),
        ]
        results = apply_event_batch(events, credential_location="ABBOTTABAD")
        self.assertEqual([r["result"] for r in results], [RESULT_APPLIED, RESULT_APPLIED])
        self.assertEqual(HqReplicaRow.objects.get(entity_id=eid).entity_version, 2)

    def test_wrong_location_rejected(self):
        ev = self._event(location_code="DI_KHAN")
        result = apply_event(ev, credential_location="ABBOTTABAD")
        self.assertEqual(result["result"], "rejected")

    def test_schema_unsupported_returns_retry(self):
        ev = self._event(schema_version=99)
        result = apply_event(ev, credential_location="ABBOTTABAD")
        self.assertEqual(result["result"], "retry")
        self.assertTrue(result.get("schema_hold"))

    def test_http_events_endpoint(self):
        client = APIClient()
        ev = self._event()
        resp = client.post(
            "/api/sync/v1/events",
            {"location_code": "ABBOTTABAD", "events": [ev]},
            format="json",
            HTTP_AUTHORIZATION="Bearer test-key-abt",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["results"][0]["result"], RESULT_APPLIED)
