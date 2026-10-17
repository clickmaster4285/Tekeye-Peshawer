"""Stage 2 — HQ Locations admin API and HQ → city control over the heartbeat."""

from __future__ import annotations

import uuid
from unittest import mock

import requests
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from city_sync import control
from city_sync.models import CityControlState, SyncCredential, SyncOutbox, SyncSite
from city_sync.sites_api import normalize_base_url
from city_sync.worker import push_once
from users.models import Attendance, Staff, User

HQ = dict(
    SYSTEM_ROLE="hq",
    LOCATION_CODE="PESHAWAR",
    NODE_ID="pew-test-01",
    SYNC_SKIP_BOOT_CHECK=True,
    HQ_PUBLIC_URL="http://192.168.190.137:8000",
)
CITY = dict(
    SYSTEM_ROLE="city",
    LOCATION_CODE="ABBOTTABAD",
    NODE_ID="abt-test-01",
    SYNC_SKIP_BOOT_CHECK=True,
    HQ_SYNC_URL="http://hq.test/api/sync/v1",
    SYNC_API_KEY="k",
)


class _FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}
        self.ok = 200 <= status_code < 300
        self.content = b"{}"

    def json(self):
        return self._data


class NormalizeBaseUrlTests(TestCase):
    def test_ip_only_gets_scheme_and_django_port(self):
        self.assertEqual(normalize_base_url("192.168.120.13"), "http://192.168.120.13:8000")

    def test_explicit_port_and_trailing_slash(self):
        self.assertEqual(normalize_base_url("http://192.168.120.13:9000/"), "http://192.168.120.13:9000")

    def test_https_keeps_default_port(self):
        self.assertEqual(normalize_base_url("https://abt.example"), "https://abt.example")

    def test_empty(self):
        self.assertEqual(normalize_base_url("  "), "")


@override_settings(**HQ)
class SitesAdminApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="sa", password="x", role="ADMIN")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _add(self, code="ABBOTTABAD", base_url="192.168.120.13"):
        return self.client.post(
            "/api/sync/v1/sites/", {"location_code": code, "base_url": base_url}, format="json"
        )

    def test_add_site_returns_key_once_and_env_snippet(self):
        resp = self._add()
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        self.assertEqual(data["site"]["name"], "Abbottabad")
        self.assertEqual(data["site"]["base_url"], "http://192.168.120.13:8000")
        self.assertIn("LOCATION_CODE=ABBOTTABAD", data["env_snippet"])
        self.assertIn("HQ_SYNC_URL=http://192.168.190.137:8000/api/sync/v1", data["env_snippet"])
        self.assertIn(f"SYNC_API_KEY={data['api_key']}", data["env_snippet"])
        cred = SyncCredential.objects.get(location_code="ABBOTTABAD")
        self.assertEqual(cred.key_hash, SyncCredential.hash_key(data["api_key"]))
        # The list never exposes the key again.
        listed = self.client.get("/api/sync/v1/sites/").json()
        self.assertNotIn(data["api_key"], str(listed))
        self.assertEqual(listed["sites"][0]["state"], "UNKNOWN")

    def test_new_future_code_is_accepted(self):
        resp = self._add(code="BANNU", base_url="10.0.0.5")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["site"]["name"], "Bannu")

    def test_rejects_bad_code_duplicate_and_hq_itself(self):
        self.assertEqual(self._add(code="abt city").status_code, 400)
        self.assertEqual(self._add(code="PESHAWAR").status_code, 400)
        self.assertEqual(self._add().status_code, 201)
        self.assertEqual(self._add().status_code, 400)

    def test_non_admin_forbidden(self):
        hr = User.objects.create_user(username="hr", password="x", role="HR")
        client = APIClient()
        client.force_authenticate(hr)
        self.assertEqual(client.get("/api/sync/v1/sites/").status_code, 403)

    @override_settings(SYSTEM_ROLE="city", LOCATION_CODE="ABBOTTABAD")
    def test_city_server_has_no_locations_page(self):
        self.assertEqual(self.client.get("/api/sync/v1/sites/").status_code, 403)

    def test_key_authenticates_heartbeat_and_rotate_invalidates_old_key(self):
        key = self._add().json()["api_key"]
        hb = APIClient().post("/api/sync/v1/heartbeat", {}, format="json", HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertEqual(hb.status_code, 200, hb.content)
        control = hb.json()["control"]
        self.assertTrue(control.pop("view_pass_public_key"))
        self.assertEqual(
            control, {"paused": False, "full_history_request_id": "", "camera_directory_hash": "", "downlink_seq": 0}
        )

        new_key = self.client.post("/api/sync/v1/sites/ABBOTTABAD/rotate-key/").json()["api_key"]
        old = APIClient().post("/api/sync/v1/heartbeat", {}, format="json", HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertIn(old.status_code, (401, 403))  # rejected key
        new = APIClient().post("/api/sync/v1/heartbeat", {}, format="json", HTTP_AUTHORIZATION=f"Bearer {new_key}")
        self.assertEqual(new.status_code, 200)

    def test_remove_revokes_key_but_keeps_nothing_else_listed(self):
        key = self._add().json()["api_key"]
        self.assertEqual(self.client.delete("/api/sync/v1/sites/ABBOTTABAD/").status_code, 204)
        self.assertFalse(SyncSite.objects.exists())
        hb = APIClient().post("/api/sync/v1/heartbeat", {}, format="json", HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertIn(hb.status_code, (401, 403))  # rejected key

    def test_pause_holds_events_as_retry(self):
        key = self._add().json()["api_key"]
        self.client.patch("/api/sync/v1/sites/ABBOTTABAD/", {"is_paused": True}, format="json")
        hb = APIClient().post("/api/sync/v1/heartbeat", {}, format="json", HTTP_AUTHORIZATION=f"Bearer {key}")
        self.assertTrue(hb.json()["control"]["paused"])
        ev_id = str(uuid.uuid4())
        resp = APIClient().post(
            "/api/sync/v1/events",
            {"location_code": "ABBOTTABAD", "events": [{"event_id": ev_id}]},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )
        self.assertEqual(resp.json()["results"], [{"event_id": ev_id, "result": "retry", "detail": "paused_by_hq"}])
        self.assertEqual(self.client.get("/api/sync/v1/sites/").json()["sites"][0]["state"], "PAUSED")

    def test_full_history_request_and_ack(self):
        key = self._add().json()["api_key"]
        site = self.client.post("/api/sync/v1/sites/ABBOTTABAD/full-history/").json()["site"]
        self.assertEqual(site["full_history"], "REQUESTED")
        hb = APIClient().post("/api/sync/v1/heartbeat", {}, format="json", HTTP_AUTHORIZATION=f"Bearer {key}")
        request_id = hb.json()["control"]["full_history_request_id"]
        self.assertTrue(request_id)
        # A stale id from an older request must not mark the new one done.
        APIClient().post(
            "/api/sync/v1/heartbeat", {"full_history_done_id": "old"}, format="json", HTTP_AUTHORIZATION=f"Bearer {key}"
        )
        self.assertIsNone(SyncSite.objects.get().full_history_done_at)
        APIClient().post(
            "/api/sync/v1/heartbeat",
            {"full_history_done_id": request_id},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )
        self.assertIsNotNone(SyncSite.objects.get().full_history_done_at)

    def test_test_connection_messages(self):
        self._add()
        url = "/api/sync/v1/sites/ABBOTTABAD/test/"
        ok_identity = {"system_role": "city", "location_code": "ABBOTTABAD", "node_id": "abt-app-01"}
        with mock.patch("city_sync.sites_api.requests.get", return_value=_FakeResponse(200, ok_identity)):
            data = self.client.post(url).json()
        self.assertTrue(data["ok"])
        self.assertTrue(SyncSite.objects.get().last_test_ok)

        wrong = {**ok_identity, "location_code": "DI_KHAN"}
        with mock.patch("city_sync.sites_api.requests.get", return_value=_FakeResponse(200, wrong)):
            data = self.client.post(url).json()
        self.assertFalse(data["ok"])
        self.assertIn("LOCATION_CODE=DI_KHAN", data["detail"])

        with mock.patch("city_sync.sites_api.requests.get", return_value=_FakeResponse(404)):
            self.assertIn("no sync module", self.client.post(url).json()["detail"])

        with mock.patch("city_sync.sites_api.requests.get", side_effect=requests.ConnectionError()):
            self.assertIn("Cannot reach", self.client.post(url).json()["detail"])


def _run_thread_inline(target=None, **kwargs):
    """Run the full-history thread synchronously so it shares the test transaction."""
    thread = mock.Mock()
    thread.start.side_effect = target
    return thread


@override_settings(**CITY)
class CityControlTests(TestCase):
    def test_pause_stops_outbox_push(self):
        control.apply_hq_control({"paused": True, "full_history_request_id": ""})
        self.assertTrue(control.city_is_paused())
        with mock.patch("city_sync.worker.requests.post") as post:
            self.assertEqual(push_once(), {"skipped": True, "reason": "paused_by_hq"})
            post.assert_not_called()
        control.apply_hq_control({"paused": False, "full_history_request_id": ""})
        self.assertFalse(control.city_is_paused())

    def test_full_history_runs_once_and_reports_done(self):
        staff = Staff.objects.create(full_name="Old Staff", employee_id="OLD-1")
        Attendance.objects.create(
            staff=staff,
            date=timezone.localdate(),
            status=Attendance.STATUS_PRESENT,
            source=Attendance.SOURCE_MANUAL,
        )
        SyncOutbox.objects.all().delete()  # pretend these rows existed before sync was enabled

        # Inline run shares the test connection, so the thread's connection cleanup is skipped.
        with mock.patch("city_sync.control.threading.Thread", side_effect=_run_thread_inline), mock.patch(
            "city_sync.control.close_old_connections"
        ):
            control.apply_hq_control({"paused": False, "full_history_request_id": "req-1"})
            queued = SyncOutbox.objects.count()
            self.assertGreaterEqual(SyncOutbox.objects.filter(entity_type="staff").count(), 1)
            self.assertGreaterEqual(SyncOutbox.objects.filter(entity_type="attendance").count(), 1)
            # Same request again: nothing re-queued.
            control.apply_hq_control({"paused": False, "full_history_request_id": "req-1"})
            self.assertEqual(SyncOutbox.objects.count(), queued)

        state = CityControlState.load()
        self.assertEqual(state.full_history_done_id, "req-1")
        self.assertFalse(state.full_history_running)
        self.assertEqual(control.heartbeat_extras()["full_history_done_id"], "req-1")

    def test_heartbeat_saves_control_from_hq(self):
        reply = _FakeResponse(200, {"ok": True, "control": {"paused": True, "full_history_request_id": ""}})
        with mock.patch("city_sync.worker.requests.post", return_value=reply):
            from city_sync.worker import send_heartbeat

            result = send_heartbeat()
        self.assertEqual(result["status_code"], 200)
        self.assertTrue(CityControlState.load().is_paused)


@override_settings(**HQ)
class MapLocationTests(TestCase):
    """Office pin for the City Status Map: Google Maps link or "lat, lng"."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user(username="sa", password="x", role="ADMIN"))
        SyncSite.objects.create(location_code="HAYATABAD", name="Hayatabad", base_url="http://x")

    def test_parse_formats(self):
        from city_sync.sites_api import parse_map_location as parse

        self.assertEqual(parse("34.008, 71.5789"), (34.008, 71.5789))
        link = "https://www.google.com/maps/place/Customs/@34.0001,71.5002,17z/data=!3m1!4b1!3d34.00812!4d71.57895"
        self.assertEqual(parse(link), (34.00812, 71.57895))  # the place pin, not the view centre
        self.assertEqual(parse("https://maps.google.com/?q=33.9946,71.4365"), (33.9946, 71.4365))
        self.assertIsNone(parse(""))
        for bad in ("hello", "200, 71"):
            with self.assertRaises(ValueError):
                parse(bad)

    def test_set_and_clear_pin(self):
        url = "/api/sync/v1/sites/HAYATABAD/"
        res = self.client.patch(url, {"map_location": "33.9946, 71.4365"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["site"]["latitude"], res.json()["site"]["longitude"]), (33.9946, 71.4365))
        self.assertEqual(self.client.patch(url, {"map_location": "nonsense"}, format="json").status_code, 400)
        res = self.client.patch(url, {"map_location": ""}, format="json")
        self.assertIsNone(res.json()["site"]["latitude"])
