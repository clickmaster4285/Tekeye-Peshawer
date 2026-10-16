"""Stage 6 - City Control Grid built from synced data, and live camera counts in the heartbeat."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from cameras.models import DetectionEvent
from city_sync.models import CityCamera, HqCityStatus, SyncSite
from city_sync.tests.test_sites import CITY, HQ
from ops_central.synced_board import synced_alerts, synced_city_rows

HQ_CAMS = {"cameras_total": 4, "cameras_online": 3, "cameras_online_source": "ml"}


def city_event(loc: str, cls: str, *, cam: int = 7, minutes_ago: int = 1, alert: bool = False) -> DetectionEvent:
    event = DetectionEvent.objects.create(
        class_name=cls, label=cls, confidence=0.9, location_code=loc, source_camera_id=cam, is_alert=alert
    )
    DetectionEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
    return event


@override_settings(**HQ)
@mock.patch("cameras.live_status.camera_counts", return_value=HQ_CAMS)
class SyncedBoardTests(TestCase):
    def setUp(self):
        SyncSite.objects.create(location_code="HAYATABAD", name="Hayatabad", base_url="http://x")
        SyncSite.objects.create(location_code="DIKHAN", name="DI Khan", base_url="http://y")
        HqCityStatus.objects.create(
            location_code="HAYATABAD",
            last_heartbeat_at=timezone.now(),
            raw={"cameras_total": 12, "cameras_online": 10},
        )
        CityCamera.objects.create(location_code="HAYATABAD", origin_pk=7, name="Gate 1")

    def rows(self):
        return {r["location_code"]: r for r in synced_city_rows()}

    def test_hq_and_every_synced_city_are_listed(self, _cams):
        rows = self.rows()
        self.assertEqual(set(rows), {"PESHAWAR", "HAYATABAD", "DIKHAN"})
        self.assertTrue(rows["PESHAWAR"]["is_hq"])
        self.assertEqual((rows["PESHAWAR"]["cameras_online"], rows["PESHAWAR"]["cameras_total"]), (3, 4))

    def test_city_status_and_cameras_come_from_its_heartbeat(self, _cams):
        rows = self.rows()
        self.assertEqual(rows["HAYATABAD"]["status"], "Online")
        self.assertEqual((rows["HAYATABAD"]["cameras_online"], rows["HAYATABAD"]["cameras_total"]), (10, 12))
        self.assertEqual(rows["DIKHAN"]["status"], "Offline")  # never sent a heartbeat

    def test_offline_city_has_no_live_cameras(self, _cams):
        HqCityStatus.objects.filter(location_code="HAYATABAD").update(
            last_heartbeat_at=timezone.now() - timedelta(hours=2)
        )
        row = self.rows()["HAYATABAD"]
        self.assertEqual((row["status"], row["cameras_online"], row["cameras_total"]), ("Offline", 0, 12))

    def test_old_city_without_counts_uses_recent_detections(self, _cams):
        HqCityStatus.objects.filter(location_code="HAYATABAD").update(raw={})
        city_event("HAYATABAD", "person", cam=7)
        city_event("HAYATABAD", "car", cam=7, minutes_ago=60)
        row = self.rows()["HAYATABAD"]
        self.assertEqual((row["cameras_online"], row["cameras_total"]), (1, 1))  # 1 camera in its directory

    def test_numbers_and_detail_are_per_location(self, _cams):
        city_event("HAYATABAD", "person", minutes_ago=1)
        city_event("HAYATABAD", "heavy-weapon", minutes_ago=2, alert=True)
        city_event("HAYATABAD", "chair", minutes_ago=3)  # not a tracked type: counted, not listed
        city_event("HAYATABAD", "car", minutes_ago=60 * 30)  # older than 24h
        city_event("DIKHAN", "person")
        rows = self.rows()
        self.assertEqual(rows["HAYATABAD"]["ai_detections_24h"], 3)
        self.assertEqual(rows["DIKHAN"]["ai_detections_24h"], 1)
        self.assertEqual(rows["PESHAWAR"]["ai_detections_24h"], 0)
        detail = rows["HAYATABAD"]["detail"]
        self.assertEqual([d["type"] for d in detail["detections"]], ["Person", "Weapon", "Vehicle"])
        self.assertEqual(detail["detections"][0]["camera"], "Gate 1")
        self.assertEqual(len(detail["trend"]), 7)
        self.assertEqual(detail["trend"][-1]["weapons"], 1)

    def test_logs_feed_has_ai_alerts_with_city_and_camera_and_offline_cities(self, _cams):
        city_event("HAYATABAD", "heavy-weapon")
        city_event("HAYATABAD", "person")  # not an alert
        alerts = synced_alerts(synced_city_rows())
        ai = [a for a in alerts if a["id"].startswith("ai-")]
        self.assertEqual(len(ai), 1)
        self.assertEqual((ai[0]["city"], ai[0]["severity"], ai[0]["camera"]), ("Hayatabad", "High", "Gate 1"))
        self.assertIn("image", ai[0])
        self.assertTrue(any(a["id"] == "offline-dikhan" and a["severity"] == "Critical" for a in alerts))


@override_settings(**CITY)
class HeartbeatCameraCountTests(TestCase):
    @mock.patch("cameras.live_status.camera_counts", return_value=HQ_CAMS)
    def test_city_heartbeat_reports_live_cameras(self, _cams):
        from city_sync.control import heartbeat_extras

        extras = heartbeat_extras()
        self.assertEqual((extras["cameras_online"], extras["cameras_total"]), (3, 4))

    def test_counts_fall_back_to_recent_detections_without_ml(self):
        from cameras import live_status
        from cameras.models import Camera, Nvr, Site

        live_status._cache = None
        nvr = Nvr.objects.create(site=Site.objects.create(code="T", name="T"), name="N", ip_address="127.0.0.1")
        cams = [Camera.objects.create(nvr=nvr, name=f"C{i}", code=f"c{i}", channel=i + 1) for i in range(3)]
        DetectionEvent.objects.create(camera=cams[0], class_name="person", confidence=0.9)
        with mock.patch("ml.client.known_ml_base_urls", return_value=[]):
            counts = live_status.camera_counts()
        live_status._cache = None
        self.assertEqual((counts["cameras_online"], counts["cameras_total"], counts["cameras_online_source"]), (1, 3, "detections"))
