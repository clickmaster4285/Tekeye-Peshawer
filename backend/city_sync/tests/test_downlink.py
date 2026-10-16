"""Stage 4 - HQ enrolls, edits and transfers city staff; the city pulls and applies."""

from __future__ import annotations

import uuid
from datetime import date
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from city_sync import downlink
from city_sync.models import CityControlState, HqDownlink, SyncOutbox, SyncSite
from city_sync.sites_api import issue_key
from city_sync.tests.test_materialize import send, staff_payload
from city_sync.tests.test_sites import CITY, HQ, _FakeResponse
from recognition.models import FaceEnrollment
from users.models import Attendance, LeaveRequest, LeaveType, Staff, User


class _Resp(_FakeResponse):
    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


def admin_client() -> APIClient:
    client = APIClient()
    client.force_authenticate(User.objects.create_user(username="sa", password="x", role="ADMIN"))
    return client


@override_settings(**HQ)
class HqQueueTests(TestCase):
    def setUp(self):
        for code in ("ABBOTTABAD", "DIKHAN"):
            SyncSite.objects.create(location_code=code, name=code.title(), base_url="http://x")

    def _enrolled_staff(self, loc="ABBOTTABAD") -> Staff:
        with self.captureOnCommitCallbacks(execute=True):
            staff = Staff.objects.create(
                full_name="Ali", cnic="17301-1111111-1", location_code=loc,
                face_embeddings=[{"embedding": [0.1, 0.2]}], staff_photos=["staff_photos/ali.jpg"],
            )
            FaceEnrollment.objects.create(
                staff=staff, dataset_folder="ali", embedding=[0.1, 0.2], embeddings=[[0.1, 0.2]], is_trained=True
            )
        return staff

    def test_enrollment_for_city_queues_one_upsert_with_face(self):
        staff = self._enrolled_staff()
        rows = list(HqDownlink.objects.filter(location_code="ABBOTTABAD"))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row.entity_type, row.operation, row.entity_id), ("staff", "upsert", staff.entity_id))
        self.assertEqual(row.payload["face_embeddings"], [{"embedding": [0.1, 0.2]}])
        self.assertTrue(row.payload["_face_enrollment"]["is_trained"])
        self.assertIn({"field": "staff_photos", "path": "staff_photos/ali.jpg"}, row.media)
        self.assertNotIn("user", row.payload)

    def test_hq_cameras_do_not_recognize_city_staff(self):
        from recognition.services.gallery import build_gallery

        city = self._enrolled_staff()
        own = Staff.objects.create(full_name="Local")
        FaceEnrollment.objects.create(staff=own, dataset_folder="own", embedding=[0.5], is_trained=True)
        keys = set(build_gallery())
        self.assertIn(FaceEnrollment.objects.get(staff=own).gallery_key, keys)
        self.assertNotIn(FaceEnrollment.objects.get(staff=city).gallery_key, keys)

    def test_editing_city_copy_never_sends_empty_face(self):
        sid = uuid.uuid4()
        send("staff", staff_payload(12), entity_id=sid)  # city copy: face cleared at HQ
        copy = Staff.objects.get(entity_id=sid)
        with self.captureOnCommitCallbacks(execute=True):
            copy.designation = "Inspector"
            copy.save()
        row = HqDownlink.objects.get(entity_id=sid)
        self.assertEqual(row.payload["designation"], "Inspector")
        self.assertNotIn("face_embeddings", row.payload)
        self.assertNotIn("staff_photos", row.payload)

    def test_transfer_retires_old_city_and_sends_new_city(self):
        staff = self._enrolled_staff()
        HqDownlink.objects.all().delete()
        with self.captureOnCommitCallbacks(execute=True):
            staff.location_code = "DIKHAN"
            staff.save()
        old = HqDownlink.objects.get(location_code="ABBOTTABAD")
        new = HqDownlink.objects.get(location_code="DIKHAN")
        self.assertEqual((old.operation, old.payload["transferred_to"]), ("retire", "DIKHAN"))
        self.assertEqual(new.operation, "upsert")
        self.assertIn("_face_enrollment", new.payload)

    def test_attendance_for_city_staff_belongs_to_that_city(self):
        staff = self._enrolled_staff()
        with self.captureOnCommitCallbacks(execute=True):
            att = Attendance.objects.create(staff=staff, date=date(2026, 10, 15), status="present", source="manual")
        self.assertEqual(att.location_code, "ABBOTTABAD")
        row = HqDownlink.objects.get(entity_type="attendance")
        self.assertEqual(row.payload["_staff_entity_id"], str(staff.entity_id))

    def test_hq_staff_are_not_queued(self):
        with self.captureOnCommitCallbacks(execute=True):
            Staff.objects.create(full_name="Peshawar only")
        self.assertFalse(HqDownlink.objects.exists())

    def test_only_super_admin_sets_a_known_location(self):
        staff = Staff.objects.create(full_name="X")
        hr = APIClient()
        hr.force_authenticate(User.objects.create_user(username="hr", password="x", role="HR"))
        res = hr.patch(f"/api/staff/{staff.pk}/", {"location_code": "ABBOTTABAD"}, format="json")
        self.assertEqual(res.status_code, 400, res.content)
        client = admin_client()
        self.assertEqual(client.patch(f"/api/staff/{staff.pk}/", {"location_code": "NOWHERE"}, format="json").status_code, 400)
        res = client.patch(f"/api/staff/{staff.pk}/", {"location_code": "abbottabad"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(Staff.objects.get(pk=staff.pk).location_code, "ABBOTTABAD")

    def test_city_pulls_acks_and_downloads_only_its_files(self):
        self._enrolled_staff()
        key = issue_key(SyncSite.objects.get(location_code="ABBOTTABAD"))
        other = issue_key(SyncSite.objects.get(location_code="DIKHAN"))
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

        hb = client.post("/api/sync/v1/heartbeat/", {"node_id": "abt", "location_code": "ABBOTTABAD"}, format="json")
        seq = hb.json()["control"]["downlink_seq"]
        self.assertGreater(seq, 0)
        items = client.get("/api/sync/v1/downlink", {"after": 0}).json()["items"]
        self.assertEqual([i["seq"] for i in items], [seq])

        with mock.patch("django.core.files.storage.default_storage.exists", return_value=False):
            ok = client.get("/api/sync/v1/downlink/media", {"seq": seq, "path": "staff_photos/ali.jpg"})
        self.assertEqual(ok.status_code, 404)  # listed, but the file is not on disk in the test
        self.assertEqual(ok.json()["detail"], "file missing at HQ")
        denied = client.get("/api/sync/v1/downlink/media", {"seq": seq, "path": "../settings.py"})
        self.assertEqual(denied.json()["detail"], "not found")
        other_client = APIClient()
        other_client.credentials(HTTP_AUTHORIZATION=f"Bearer {other}")
        self.assertEqual(other_client.get("/api/sync/v1/downlink", {"after": 0}).json()["items"], [])

        client.post("/api/sync/v1/downlink/ack", {"results": [{"seq": seq, "status": "applied"}]}, format="json")
        self.assertEqual(HqDownlink.objects.get(seq=seq).status, "applied")
        site = admin_client().get("/api/sync/v1/sites/").json()["sites"][0]
        self.assertEqual(site["downlink_pending"], 0)


@override_settings(**CITY)
class CityApplyTests(TestCase):
    def _item(self, seq, entity_type, operation, entity_id, payload, media=None):
        return {"seq": seq, "entity_type": entity_type, "operation": operation,
                "entity_id": str(entity_id), "payload": payload, "media": media or []}

    def _staff_item(self, eid, **extra):
        payload = {"full_name": "Ali", "cnic": "17301-1111111-1", "designation": "Officer",
                   "face_embeddings": [{"embedding": [0.1, 0.2]}], "face_identity_label": "ali",
                   "staff_photos": ["staff_photos/ali.jpg"],
                   "_face_enrollment": {"is_trained": True, "is_enrolled": True, "embedding": [0.1, 0.2],
                                        "embeddings": [[0.1, 0.2]], "total_images": 3, "model_version": "v1"},
                   **extra}
        return self._item(1, "staff", "upsert", eid, payload, [{"field": "staff_photos", "path": "staff_photos/ali.jpg"}])

    @mock.patch("city_sync.downlink._download")
    def test_staff_created_with_face_and_echoed_to_hq(self, download):
        eid = uuid.uuid4()
        self.assertTrue(downlink.apply_item(self._staff_item(eid)))
        download.assert_called_once_with(1, "staff_photos/ali.jpg")
        staff = Staff.objects.get(entity_id=eid)
        self.assertEqual(staff.location_code, "ABBOTTABAD")
        self.assertEqual(staff.face_identity_label, "ali")
        self.assertTrue(staff.face_enrollment.is_trained)
        self.assertEqual(staff.face_enrollment.dataset_folder, f"hq/{eid}")
        self.assertTrue(SyncOutbox.objects.filter(entity_type="staff", entity_id=eid).exists())

    @mock.patch("city_sync.downlink._download")
    def test_peshawar_wins_over_city_record_with_same_cnic(self, _download):
        local = Staff.objects.create(full_name="Ali (city)", cnic="17301-1111111-1", designation="Clerk")
        downlink.apply_item(self._staff_item(uuid.uuid4()))
        local.refresh_from_db()
        self.assertEqual(local.designation, "Officer")
        self.assertEqual(Staff.objects.count(), 1)

    @mock.patch("city_sync.downlink._download")
    def test_transfer_out_keeps_record_and_drops_face(self, _download):
        eid = uuid.uuid4()
        downlink.apply_item(self._staff_item(eid))
        downlink.apply_item(self._item(2, "staff", "retire", eid, {"transferred_to": "DIKHAN"}))
        staff = Staff.objects.get(entity_id=eid)
        self.assertEqual(staff.transferred_to, "DIKHAN")
        self.assertEqual(staff.face_embeddings, [])
        self.assertFalse(staff.is_deleted)
        self.assertFalse(FaceEnrollment.objects.get(staff=staff).is_trained)

    def test_attendance_correction_updates_todays_row(self):
        staff = Staff.objects.create(full_name="Ali")
        existing = Attendance.objects.create(staff=staff, date=date(2026, 10, 15), status="absent", source="cctv")
        downlink.apply_item(self._item(3, "attendance", "upsert", uuid.uuid4(), {
            "_staff_entity_id": str(staff.entity_id), "date": "2026-10-15", "status": "present", "source": "manual",
        }))
        existing.refresh_from_db()
        self.assertEqual(existing.status, "present")
        self.assertEqual(Attendance.objects.count(), 1)

    def test_leave_request_uses_city_leave_type_by_code(self):
        staff = Staff.objects.create(full_name="Ali")
        sick = LeaveType.objects.create(name="Sick", code="SICK")
        rid = uuid.uuid4()
        downlink.apply_item(self._item(4, "leave_request", "upsert", rid, {
            "_staff_entity_id": str(staff.entity_id), "_ref_leave_type": {"code": "SICK", "name": "Sick"},
            "from_date": "2026-10-20", "to_date": "2026-10-20", "days": 1, "status": "APPROVED",
        }))
        req = LeaveRequest.objects.get(entity_id=rid)
        self.assertEqual((req.leave_type_id, req.staff_id, req.status), (sick.pk, staff.pk, "APPROVED"))

    @mock.patch("city_sync.downlink._refresh_faces")
    @mock.patch("city_sync.downlink._download")
    @mock.patch("city_sync.downlink._hq_post")
    @mock.patch("city_sync.downlink._hq_get")
    def test_pull_applies_in_order_reports_failures_and_moves_on(self, hq_get, hq_post, _download, refresh):
        eid = uuid.uuid4()
        bad = self._item(2, "attendance", "upsert", uuid.uuid4(), {"_staff_entity_id": str(uuid.uuid4()), "date": "2026-10-15"})
        hq_get.side_effect = [_Resp(data={"items": [self._staff_item(eid), bad]}), _Resp(data={"items": []})]
        result = downlink.pull_downlink(2)
        self.assertEqual((result["applied"], result["failed"], result["cursor"]), (1, 1, 2))
        acks = hq_post.call_args[0][1]["results"]
        self.assertEqual([a["status"] for a in acks], ["applied", "failed"])
        self.assertEqual(CityControlState.load().downlink_seq, 2)
        refresh.assert_called_once()

    @mock.patch("city_sync.downlink.pull_downlink")
    def test_heartbeat_starts_pull_only_when_behind(self, pull):
        from city_sync import control

        control.apply_hq_control({"downlink_seq": 0})
        pull.assert_not_called()
        control.apply_hq_control({"downlink_seq": 5})
        pull.assert_called_once_with(5)
