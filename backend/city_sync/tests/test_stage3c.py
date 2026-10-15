"""Stage 3c — leave, journeys, city camera names, payroll by location."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from city_sync.control import control_for_location, heartbeat_extras, record_heartbeat_ack
from city_sync.materialize import attach_media
from city_sync.models import CityCamera, HqMediaObject, SyncSite
from city_sync.tests.test_materialize import CITY, HQ, send, staff_payload
from users.models import LeaveRequest, LeaveType, Staff, User


def admin_client() -> APIClient:
    client = APIClient()
    client.force_authenticate(User.objects.create_user(username="sa", password="x", role="ADMIN"))
    return client


@override_settings(**HQ)
class LeaveRequestTests(TestCase):
    def _leave(self, ref: dict):
        send("staff", staff_payload(12), entity_id=uuid.uuid4())
        rid = uuid.uuid4()
        send(
            "leave_request",
            {
                "_pk": 4,
                "_model": "users.LeaveRequest",
                "staff": 12,
                "leave_type": 99,  # city pk: means nothing at HQ
                "_ref_leave_type": ref,
                "from_date": "2026-10-20",
                "to_date": "2026-10-21",
                "days": 2,
                "approved_by": 3,
            },
            entity_id=rid,
        )
        return LeaveRequest.objects.get(entity_id=rid)

    def test_leave_type_matched_by_code(self):
        sick = LeaveType.objects.create(name="Sick Leave", code="SICK")
        req = self._leave({"code": "sick", "name": "Sick"})
        self.assertEqual(req.leave_type_id, sick.pk)
        self.assertIsNone(req.approved_by_id)
        self.assertEqual(req.staff.location_code, "ABBOTTABAD")

    def test_unknown_leave_type_created_inactive(self):
        req = self._leave({"code": "", "name": "Hajj Leave"})
        self.assertEqual(req.leave_type.code, "HAJJ_LEAVE")
        self.assertFalse(req.leave_type.is_active)


@override_settings(**HQ)
class JourneyTests(TestCase):
    def setUp(self):
        SyncSite.objects.create(location_code="ABBOTTABAD", name="Abbottabad", base_url="http://x")
        record_heartbeat_ack(
            "ABBOTTABAD",
            {"camera_directory": [{"id": 2, "code": "C02", "name": "Main Gate", "site_name": "ABT"}], "camera_directory_hash": "h1"},
        )

    def _person(self, **extra):
        pid = uuid.uuid4()
        send(
            "journey_person",
            {
                "_pk": 7,
                "_model": "person_journey.JourneyPerson",
                "uuid": str(uuid.uuid4()),
                "code": "PJ-00001",
                "person_type": "unknown",
                "status": "active",
                "face_embedding": [0.1, 0.2],
                "reid_embedding": [0.3],
                "latest_camera": 2,
                "metadata": {},
                **extra,
            },
            entity_id=pid,
        )
        from person_journey.models import JourneyPerson

        return JourneyPerson.all_objects.get(entity_id=pid)

    def test_person_copied_without_embeddings_and_with_city_code(self):
        person = self._person()
        self.assertEqual(person.face_embedding, [])
        self.assertEqual(person.reid_embedding, [])
        self.assertEqual(person.code, "ABBOTTABAD:PJ-00001")
        self.assertEqual(person.metadata["source_camera_id"], 2)

        rows = admin_client().get("/api/person-journey/persons/?source_location=ABBOTTABAD").json()["results"]
        self.assertEqual([r["code"] for r in rows], ["ABBOTTABAD:PJ-00001"])
        self.assertEqual(rows[0]["latest_camera_name"], "Main Gate")

    def test_hq_numbering_and_matching_ignore_city_people(self):
        from person_journey.services import _max_code_seq, register_staff_journey_person

        hq_staff = Staff.objects.create(full_name="HQ person", cnic="17301-0000000-1")
        # The city's staff with the same CNIC links to Peshawar's staff (Peshawar wins).
        send("staff", staff_payload(12, cnic="17301-0000000-1"), entity_id=uuid.uuid4())
        city_person = self._person(staff=12, person_type="staff")
        self.assertEqual(city_person.staff_id, hq_staff.pk)

        self.assertEqual(_max_code_seq(), 0)
        own = register_staff_journey_person(hq_staff)
        self.assertNotEqual(own.pk, city_person.pk)
        self.assertEqual(own.location_code, "PESHAWAR")

    def test_event_links_detection_and_gets_snapshot(self):
        from person_journey.models import JourneyEvent

        self._person()
        send("detection_event", {"_pk": 30, "_model": "cameras.DetectionEvent", "camera": 2, "class_name": "person", "label": "person", "confidence": 0.9}, entity_id=uuid.uuid4())
        eid = uuid.uuid4()
        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root, MEDIA_URL="/media/"):
            send(
                "journey_event",
                {
                    "_pk": 50,
                    "_model": "person_journey.JourneyEvent",
                    "journey_person": 7,
                    "event_type": "camera_seen",
                    "camera": 2,
                    "track": 900,
                    "detection_event_id": 30,
                    "snapshot_path": "/media/journey_snapshots/2026/10/15/je_50_full.jpg",
                    "metadata": {},
                },
                entity_id=eid,
            )
            event = JourneyEvent.objects.get(entity_id=eid)
            from cameras.models import DetectionEvent

            self.assertEqual(event.detection_event_id, DetectionEvent.objects.get(source_camera_id=2).pk)
            self.assertIsNone(event.camera_id)
            self.assertIsNone(event.track_id)
            self.assertEqual(event.snapshot_path, "")

            stored = Path(media_root) / "hq_sync_media" / "ABBOTTABAD" / "2026" / "10" / "s1.jpg"
            stored.parent.mkdir(parents=True)
            stored.write_bytes(b"jpg")
            media = HqMediaObject.objects.create(
                media_id=uuid.uuid4(),
                location_code="ABBOTTABAD",
                record_entity_type="journey_event",
                record_entity_id=eid,
                source_path="journey_snapshots/2026/10/15/je_50_full.jpg",
                sha256="x",
                storage_path=str(stored),
                status=HqMediaObject.STATUS_VERIFIED,
                verified_at=timezone.now(),
            )
            self.assertTrue(attach_media(media))
            event.refresh_from_db()
            self.assertEqual(event.snapshot_path, "/media/hq_sync_media/ABBOTTABAD/2026/10/s1.jpg")

    def test_detection_shows_city_camera_name(self):
        send("detection_event", {"_pk": 31, "_model": "cameras.DetectionEvent", "camera": 2, "class_name": "car", "label": "car", "confidence": 0.9}, entity_id=uuid.uuid4())
        data = admin_client().get("/api/cameras/detection-events/?source_location=ABBOTTABAD").json()
        rows = data.get("results", data) if isinstance(data, dict) else data
        self.assertEqual(rows[0]["name"], "Main Gate")
        self.assertEqual(rows[0]["camera_code"], "C02")


@override_settings(**HQ)
class CameraDirectoryHqTests(TestCase):
    def test_directory_replaced_and_hash_returned(self):
        SyncSite.objects.create(location_code="ABBOTTABAD", name="Abbottabad", base_url="http://x")
        record_heartbeat_ack("ABBOTTABAD", {"camera_directory": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}], "camera_directory_hash": "h1"})
        record_heartbeat_ack("ABBOTTABAD", {"camera_directory": [{"id": 2, "name": "B2"}], "camera_directory_hash": "h2"})
        self.assertEqual(list(CityCamera.objects.values_list("origin_pk", "name")), [(2, "B2")])
        self.assertEqual(control_for_location("ABBOTTABAD")["camera_directory_hash"], "h2")


@override_settings(**CITY)
class CameraDirectoryCityTests(TestCase):
    def test_list_sent_only_when_hq_hash_differs(self):
        from city_sync import control

        control._hq_camera_hash = None
        extras = heartbeat_extras()
        self.assertIn("camera_directory", extras)
        self.assertNotIn("password", str(extras))
        control.apply_hq_control({"camera_directory_hash": extras["camera_directory_hash"]})
        self.assertNotIn("camera_directory", heartbeat_extras())
        control._hq_camera_hash = None

    def test_leave_request_payload_carries_leave_type_code(self):
        from city_sync.outbox import model_to_payload

        staff = Staff.objects.create(full_name="City staff")
        leave_type = LeaveType.objects.create(name="Casual", code="CASUAL")
        req = LeaveRequest.objects.create(
            staff=staff, leave_type=leave_type, from_date=date(2026, 10, 1), to_date=date(2026, 10, 1), days=1
        )
        self.assertEqual(model_to_payload(req)["_ref_leave_type"], {"code": "CASUAL", "name": "Casual"})


@override_settings(**HQ)
class PayrollTests(TestCase):
    def test_entries_carry_location_and_skip_deleted_staff(self):
        Staff.objects.create(full_name="HQ", salary=Decimal("100"))
        send("staff", staff_payload(12, salary="200"), entity_id=uuid.uuid4())
        Staff.objects.create(full_name="Gone", salary=Decimal("50"), is_deleted=True)
        client = admin_client()
        from users.models import PayrollRun

        client.post(
            "/api/payroll-runs/", {"period_label": "Oct", "period_start": "2026-10-01", "period_end": "2026-10-31"}
        )
        run_id = PayrollRun.objects.get(period_label="Oct").pk
        client.post(f"/api/payroll-runs/{run_id}/process/")
        entries = client.get(f"/api/payroll-runs/{run_id}/").json()["entries"]
        self.assertEqual(sorted((e["staff_name"], e["location_code"]) for e in entries), [("Ali Khan", "ABBOTTABAD"), ("HQ", "PESHAWAR")])
