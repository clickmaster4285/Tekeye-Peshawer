"""Stage 3a — city staff / attendance copied into HQ's real tables."""

from __future__ import annotations

import itertools
import uuid
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from city_sync.hq_receiver import apply_event
from city_sync.materialize import attach_media
from city_sync.models import HqConflict, HqEntityMap, HqMediaObject, HqPendingLink, SyncOutbox
from users.models import Attendance, Staff, User

HQ = dict(SYSTEM_ROLE="hq", LOCATION_CODE="PESHAWAR", NODE_ID="pew-test-01", SYNC_SKIP_BOOT_CHECK=True)
CITY = dict(SYSTEM_ROLE="city", LOCATION_CODE="ABBOTTABAD", NODE_ID="abt-test-01", SYNC_SKIP_BOOT_CHECK=True)

_seq = itertools.count(1)


def send(entity_type, payload, *, entity_id, version=1, op="upsert", loc="ABBOTTABAD"):
    """Deliver one city event to HQ the way SyncEventsView does."""
    event = {
        "event_id": str(uuid.uuid4()),
        "location_code": loc,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "operation": op,
        "entity_version": version,
        "schema_version": 1,
        "seq": next(_seq),
        "payload": {**payload, "entity_id": str(entity_id), "version": version},
    }
    return apply_event(event, credential_location=loc)


def staff_payload(pk, **extra):
    return {
        "_pk": pk,
        "_model": "users.Staff",
        "full_name": "Ali Khan",
        "cnic": None,
        "employee_id": None,
        "user": 7,  # city user id: does not exist at HQ
        "profile_image": None,
        "face_embedding": [0.1, 0.2],
        "face_embeddings": [{"embedding": [0.1, 0.2]}],
        "face_identity_label": "ali",
        "staff_photos": ["staff/ali.jpg"],
        "created_at": "2026-09-01T08:00:00+05:00",
        **extra,
    }


def attendance_payload(pk, staff_pk, **extra):
    return {
        "_pk": pk,
        "_model": "users.Attendance",
        "user": None,
        "staff": staff_pk,
        "date": "2026-10-14",
        "check_in": "2026-10-14T09:01:00+05:00",
        "status": "present",
        "source": "cctv",
        "image": None,
        "created_at": "2026-10-14T09:01:00+05:00",
        **extra,
    }


@override_settings(**HQ)
class MaterializeTests(TestCase):
    def test_staff_then_attendance_copied_and_linked(self):
        sid, aid = uuid.uuid4(), uuid.uuid4()
        self.assertEqual(send("staff", staff_payload(12), entity_id=sid)["result"], "applied")
        send("attendance", attendance_payload(500, 12), entity_id=aid)

        staff = Staff.objects.get(entity_id=sid)
        self.assertEqual(staff.location_code, "ABBOTTABAD")
        self.assertIsNone(staff.user_id)
        # City face data never reaches HQ recognition.
        self.assertIsNone(staff.face_embedding)
        self.assertEqual(staff.face_embeddings, [])
        self.assertEqual(staff.staff_photos, [])
        self.assertEqual(staff.created_at.date().isoformat(), "2026-09-01")

        att = Attendance.objects.get(entity_id=aid)
        self.assertEqual(att.staff_id, staff.pk)
        self.assertEqual(att.location_code, "ABBOTTABAD")
        # No outbox at HQ for copied rows.
        self.assertFalse(SyncOutbox.objects.exists())

    def test_attendance_before_staff_is_linked_later(self):
        sid, aid = uuid.uuid4(), uuid.uuid4()
        send("attendance", attendance_payload(500, 12), entity_id=aid)
        att = Attendance.objects.get(entity_id=aid)
        self.assertIsNone(att.staff_id)
        self.assertEqual(HqPendingLink.objects.count(), 1)

        send("staff", staff_payload(12), entity_id=sid)
        att.refresh_from_db()
        self.assertEqual(att.staff_id, Staff.objects.get(entity_id=sid).pk)
        self.assertFalse(HqPendingLink.objects.exists())

    def test_newer_version_updates_same_row_and_tombstone_hides_it(self):
        sid = uuid.uuid4()
        send("staff", staff_payload(12), entity_id=sid)
        pk = Staff.objects.get(entity_id=sid).pk
        send("staff", staff_payload(12, full_name="Ali Khan Jadoon"), entity_id=sid, version=2)
        self.assertEqual(Staff.objects.get(pk=pk).full_name, "Ali Khan Jadoon")
        self.assertEqual(Staff.objects.filter(entity_id=sid).count(), 1)

        send("staff", staff_payload(12, is_deleted=True), entity_id=sid, version=3, op="tombstone")
        self.assertTrue(Staff.objects.get(pk=pk).is_deleted)

        admin = User.objects.create_user(username="sa", password="x", role="ADMIN")
        client = APIClient()
        client.force_authenticate(admin)
        rows = client.get("/api/staff/").json()
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        self.assertNotIn(pk, [r["id"] for r in rows])

    def test_peshawar_wins_on_same_cnic(self):
        own = Staff.objects.create(full_name="Ali (HQ record)", cnic="17301-1234567-1")
        sid, aid = uuid.uuid4(), uuid.uuid4()
        result = send("staff", staff_payload(12, full_name="Ali (city)", cnic="17301-1234567-1"), entity_id=sid)
        self.assertEqual(result["result"], "applied")
        own.refresh_from_db()
        self.assertEqual(own.full_name, "Ali (HQ record)")
        self.assertEqual(Staff.objects.count(), 1)
        self.assertTrue(HqEntityMap.objects.get(entity_type="staff").hq_owned)

        # Later city edits do not overwrite the HQ row, but attendance links to it.
        send("staff", staff_payload(12, full_name="Changed at city", cnic="17301-1234567-1"), entity_id=sid, version=2)
        own.refresh_from_db()
        self.assertEqual(own.full_name, "Ali (HQ record)")
        send("attendance", attendance_payload(500, 12), entity_id=aid)
        self.assertEqual(Attendance.objects.get(entity_id=aid).staff_id, own.pk)

    def test_employee_id_clash_is_cleared_and_reported(self):
        Staff.objects.create(full_name="HQ person", employee_id="EMP-001")
        sid = uuid.uuid4()
        send("staff", staff_payload(12, employee_id="EMP-001"), entity_id=sid)
        copy = Staff.objects.get(entity_id=sid)
        self.assertIsNone(copy.employee_id)
        self.assertTrue(HqConflict.objects.filter(reason__startswith="cleared_on_clash").exists())

    def test_media_attached_when_verified(self):
        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            aid = uuid.uuid4()
            send("staff", staff_payload(12), entity_id=uuid.uuid4())
            send("attendance", attendance_payload(500, 12, image="attendance/abc.jpg"), entity_id=aid)
            self.assertFalse(Attendance.objects.get(entity_id=aid).image)

            stored = Path(media_root) / "hq_sync_media" / "ABBOTTABAD" / "2026" / "10" / "m1.jpg"
            stored.parent.mkdir(parents=True)
            stored.write_bytes(b"jpg")
            media = HqMediaObject.objects.create(
                media_id=uuid.uuid4(),
                location_code="ABBOTTABAD",
                record_entity_type="attendance",
                record_entity_id=aid,
                source_path="attendance/abc.jpg",
                sha256="x",
                storage_path=str(stored),
                status=HqMediaObject.STATUS_VERIFIED,
                verified_at=timezone.now(),
            )
            self.assertTrue(attach_media(media))
            self.assertEqual(
                Attendance.objects.get(entity_id=aid).image.name, "hq_sync_media/ABBOTTABAD/2026/10/m1.jpg"
            )

    def test_ml_face_sync_ignores_city_copies(self):
        from ml.face_sync import collect_db_face_embeddings

        Staff.objects.create(full_name="Local", face_identity_label="local", face_embedding=[0.5])
        Staff.objects.create(
            full_name="City", face_identity_label="city", face_embedding=[0.9], location_code="ABBOTTABAD"
        )
        self.assertEqual([r["identity"] for r in collect_db_face_embeddings()], ["local"])

    def test_claim_local_rows_skips_city_copies(self):
        Staff.objects.create(full_name="Old local", location_code="ABBOTTABAD")
        sid = uuid.uuid4()
        send("staff", staff_payload(12), entity_id=sid)
        call_command("hq_claim_local_rows", stdout=StringIO())
        self.assertEqual(Staff.objects.get(full_name="Old local").location_code, "PESHAWAR")
        self.assertEqual(Staff.objects.get(entity_id=sid).location_code, "ABBOTTABAD")

    def test_source_location_filter_for_super_admin_only(self):
        Staff.objects.create(full_name="Local", location_code="")
        send("staff", staff_payload(12), entity_id=uuid.uuid4())
        admin = User.objects.create_user(username="sa", password="x", role="ADMIN")
        client = APIClient()
        client.force_authenticate(admin)

        def names(qs):
            data = client.get(f"/api/staff/{qs}").json()
            return sorted(r["full_name"] for r in (data.get("results", data) if isinstance(data, dict) else data))

        self.assertEqual(names(""), ["Ali Khan", "Local"])
        self.assertEqual(names("?source_location=ABBOTTABAD"), ["Ali Khan"])
        self.assertEqual(names("?source_location=PESHAWAR"), ["Local"])


@override_settings(**HQ)
class MaterializeStage3bTests(TestCase):
    def test_detection_copied_without_camera_and_filtered_by_location(self):
        from cameras.models import ClipStatus, DetectionEvent

        eid = uuid.uuid4()
        payload = {
            "_pk": 1,
            "_model": "cameras.DetectionEvent",
            "camera": 1,
            "class_name": "car",
            "label": "car",
            "confidence": 0.9,
            "clip": "",
            "clip_status": "recording",
            "person_identity_id": 77,
            "created_at": "2026-10-15T10:40:51+00:00",
        }
        send("detection_event", payload, entity_id=eid)
        event = DetectionEvent.objects.get(entity_id=eid)
        self.assertIsNone(event.camera_id)
        self.assertIsNone(event.person_identity_id)
        # HQ's snapshot worker must never pick up a city event.
        self.assertEqual(event.clip_status, ClipStatus.SKIPPED)
        self.assertEqual(event.location_code, "ABBOTTABAD")

        admin = User.objects.create_user(username="sa", password="x", role="ADMIN")
        client = APIClient()
        client.force_authenticate(admin)

        def ids(qs=""):
            data = client.get(f"/api/cameras/detection-events/{qs}").json()
            rows = data.get("results", data) if isinstance(data, dict) else data
            return [r["id"] for r in rows]

        self.assertIn(event.pk, ids())
        self.assertIn(event.pk, ids("?source_location=ABBOTTABAD"))
        self.assertNotIn(event.pk, ids("?source_location=PESHAWAR"))

    def test_vehicle_waits_for_its_visitor(self):
        from visitors.models import Vehicle, Visitor

        vid, cid = uuid.uuid4(), uuid.uuid4()
        vehicle = {"_pk": 3, "_model": "visitors.Vehicle", "visitor": 9, "plate_number": "ABC-123"}
        self.assertEqual(send("vehicle", vehicle, entity_id=cid)["result"], "applied")
        self.assertFalse(Vehicle.objects.filter(entity_id=cid).exists())

        send("visitor", {"_pk": 9, "_model": "visitors.Visitor", "full_name": "Guest", "registered_by_user_id": 4}, entity_id=vid)
        visitor = Visitor.objects.get(entity_id=vid)
        self.assertIsNone(visitor.registered_by_user_id)
        copied = Vehicle.objects.get(entity_id=cid)
        self.assertEqual(copied.visitor_id, visitor.pk)
        self.assertEqual(copied.location_code, "ABBOTTABAD")
        self.assertFalse(HqPendingLink.objects.exists())

    def test_detention_memo_keeps_uuid_and_children_link(self):
        from detentions.models import DepositAccountEntry, DetentionMemo

        memo_pk, entry_pk = uuid.uuid4(), uuid.uuid4()
        send("detention_memo", {"_pk": str(memo_pk), "_model": "detentions.DetentionMemo", "case_no": "C-1"}, entity_id=memo_pk)
        send(
            "deposit_account_entry",
            {"_pk": str(entry_pk), "_model": "detentions.DepositAccountEntry", "detention_memo": str(memo_pk)},
            entity_id=entry_pk,
        )
        memo = DetentionMemo.objects.get(entity_id=memo_pk)
        self.assertEqual(memo.pk, memo_pk)
        self.assertEqual(DepositAccountEntry.objects.get(entity_id=entry_pk).detention_memo_id, memo_pk)

    def test_vms_list_record_id_clash_is_prefixed(self):
        from visitors.models import VmsListRecord

        VmsListRecord.objects.create(module="vms_blacklist_management_rows", record_id="row-1", data={})
        rid = uuid.uuid4()
        send(
            "vms_list_record",
            {"_pk": 5, "_model": "visitors.VmsListRecord", "module": "vms_blacklist_management_rows", "record_id": "row-1", "data": {"name": "X"}},
            entity_id=rid,
        )
        self.assertEqual(VmsListRecord.objects.get(entity_id=rid).record_id, "ABBOTTABAD:row-1")
        self.assertTrue(HqConflict.objects.filter(reason__startswith="prefixed_on_clash").exists())

        # The whole-list editor only shows (and rewrites) this server's own rows.
        admin = User.objects.create_user(username="sa", password="x", role="ADMIN")
        client = APIClient()
        client.force_authenticate(admin)
        rows = client.get("/api/vms/lists/?module=vms_blacklist_management_rows").json()
        self.assertEqual([r["id"] for r in rows], ["row-1"])

    def test_destruction_alert_drops_city_user_ids(self):
        from warehouse.models import DestructionAlert

        aid = uuid.uuid4()
        send(
            "destruction_alert",
            {"_pk": str(aid), "_model": "warehouse.DestructionAlert", "detention_memo_id": str(uuid.uuid4()),
             "notified_user_ids": [1, 2], "camera": 4},
            entity_id=aid,
        )
        alert = DestructionAlert.objects.get(entity_id=aid)
        self.assertEqual(alert.notified_user_ids, [])
        self.assertIsNone(alert.camera_id)


@override_settings(**CITY)
class CityDeleteTests(TestCase):
    def test_normal_delete_works_and_sends_tombstone(self):
        staff = Staff.objects.create(full_name="Gone", employee_id="DEL-1")
        entity_id = staff.entity_id
        staff.delete()
        self.assertFalse(Staff.objects.filter(pk=staff.pk).exists())
        tomb = SyncOutbox.objects.filter(entity_id=entity_id, operation=SyncOutbox.OP_TOMBSTONE).get()
        self.assertEqual(tomb.entity_version, 2)
        self.assertTrue(tomb.payload["is_deleted"])
