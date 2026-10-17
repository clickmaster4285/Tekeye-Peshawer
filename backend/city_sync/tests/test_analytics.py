"""Analytics Dashboard - numbers from real detections, per location, with a searchable log."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from cameras.models import DetectionEvent
from city_sync.models import HqCityStatus, SyncSite
from city_sync.tests.test_sites import HQ
from ops_central.analytics import build_dashboard, event_log
from users.models import User

CAMS = {"cameras_total": 4, "cameras_online": 3, "cameras_online_source": "ml"}


def event(loc: str, cls: str, *, alert=False, days_ago=0, conf=0.8):
    e = DetectionEvent.objects.create(class_name=cls, label=cls, confidence=conf, location_code=loc, is_alert=alert)
    DetectionEvent.objects.filter(pk=e.pk).update(created_at=timezone.now() - timedelta(days=days_ago, minutes=1))
    return e


@override_settings(**HQ)
@mock.patch("cameras.live_status.camera_counts", return_value=CAMS)
class AnalyticsTests(TestCase):
    def setUp(self):
        SyncSite.objects.create(location_code="HAYATABAD", name="Hayatabad", base_url="http://x")
        HqCityStatus.objects.create(
            location_code="HAYATABAD", last_heartbeat_at=timezone.now(), raw={"cameras_total": 12, "cameras_online": 10}
        )
        event("PESHAWAR", "person")
        event("", "car")  # untagged = HQ's own
        event("HAYATABAD", "heavy-weapon", alert=True)
        event("HAYATABAD", "License_Plate")
        event("HAYATABAD", "truck", days_ago=20)  # outside the default 7 days

    def test_all_locations_totals(self, _c):
        d = build_dashboard(scope="ALL", raw_from=None, raw_to=None)
        s = d["stats"]
        self.assertEqual((s["people"], s["vehicles"], s["weapons"], s["plates"], s["total"]), (1, 1, 1, 1, 4))
        o = d["overview"]
        self.assertEqual((o["cameras_online"], o["cameras_total"]), (13, 16))
        self.assertEqual(o["alerts_by_severity"]["critical"], 1)
        self.assertEqual(o["alerts_by_severity"]["medium"], 1)
        self.assertEqual(o["incidents_today"], 1)
        self.assertEqual(len(d["over_time"]), 7)
        self.assertEqual(sum(r["weapons"] for r in d["over_time"]), 1)
        self.assertEqual(d["top_alert_cameras"][0]["location"], "Hayatabad")
        self.assertEqual([a["severity"] for a in d["alerts"]], ["Critical"])

    def test_one_city_and_hq_scopes(self, _c):
        city = build_dashboard(scope="hayatabad", raw_from=None, raw_to=None)
        self.assertEqual((city["scope"], city["stats"]["total"], city["overview"]["cameras_total"]), ("HAYATABAD", 2, 12))
        hq = build_dashboard(scope="PESHAWAR", raw_from=None, raw_to=None)
        self.assertEqual(hq["stats"]["total"], 2)  # includes the untagged row

    def test_date_range_and_hourly_buckets(self, _c):
        today = timezone.localdate().isoformat()
        d = build_dashboard(scope="ALL", raw_from=today, raw_to=today)
        self.assertEqual((d["range"]["bucket"], len(d["over_time"])), ("hour", 24))
        month = build_dashboard(scope="ALL", raw_from=(timezone.localdate() - timedelta(days=29)).isoformat(), raw_to=today)
        self.assertEqual(month["stats"]["total"], 5)

    def test_unknown_location_falls_back_to_all(self, _c):
        self.assertEqual(build_dashboard(scope="NOWHERE", raw_from=None, raw_to=None)["scope"], "ALL")

    def test_event_log_filters_and_search(self, _c):
        self.assertEqual(event_log(scope="ALL", raw_from=None, raw_to=None)["count"], 4)
        crit = event_log(scope="ALL", raw_from=None, raw_to=None, severities=["Critical"])
        self.assertEqual([r["object"] for r in crit["results"]], ["heavy-weapon"])
        self.assertEqual(crit["results"][0]["location"], "Hayatabad")
        vehicles = event_log(scope="ALL", raw_from=None, raw_to=None, types=["Vehicle"])
        self.assertEqual(vehicles["count"], 1)
        self.assertEqual(event_log(scope="ALL", raw_from=None, raw_to=None, q="plate")["count"], 1)

    def test_api_needs_login_and_returns_data(self, _c):
        self.assertIn(APIClient().get("/api/ops/analytics/").status_code, (401, 403))
        client = APIClient()
        client.force_authenticate(User.objects.create_user(username="sa", password="x", role="ADMIN"))
        res = client.get("/api/ops/analytics/", {"location": "ALL"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["stats"]["total"], 4)
        res = client.get("/api/ops/analytics/events/", {"severity": "Critical,High", "page": 1})
        self.assertEqual(res.json()["count"], 1)
