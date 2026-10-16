"""Stage 5 - city_sync_check pre-flight command."""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from city_sync.tests.test_sites import CITY, HQ, _FakeResponse


def _resp(status_code=200, data=None):
    resp = _FakeResponse(status_code, data)
    resp.headers = {}
    return resp


HQ_IDENTITY = _resp(data={"system_role": "hq", "location_code": "PESHAWAR", "node_id": "pew-app-01"})


def run_check() -> str:
    out = StringIO()
    call_command("city_sync_check", stdout=out)
    return out.getvalue()


@override_settings(**CITY)
class CitySyncCheckTests(TestCase):
    @mock.patch("city_sync.management.commands.city_sync_check.requests.get")
    def test_ready_when_hq_accepts_the_key(self, get):
        get.side_effect = [HQ_IDENTITY, _resp(data={"items": [], "count": 0})]
        out = run_check()
        self.assertIn("Peshawar accepts this server's key", out)
        self.assertNotIn("FAIL", out)
        self.assertEqual(get.call_args_list[1].kwargs["headers"], {"Authorization": "Bearer k"})

    @mock.patch("city_sync.management.commands.city_sync_check.requests.get")
    def test_rejected_key_is_not_ready(self, get):
        get.side_effect = [HQ_IDENTITY, _resp(401, {"detail": "Invalid API key"})]
        out = run_check()
        self.assertIn("Peshawar rejected the key (Invalid API key)", out)
        self.assertIn("NOT READY", out)

    @mock.patch("city_sync.management.commands.city_sync_check.requests.get")
    def test_pointing_at_another_city_is_caught(self, get):
        get.return_value = _resp(data={"system_role": "city", "location_code": "DI_KHAN"})
        out = run_check()
        self.assertIn("not the head office", out)
        self.assertEqual(get.call_count, 1)

    @override_settings(SYNC_API_KEY="")
    def test_missing_key_stops_early(self):
        out = run_check()
        self.assertIn("SYNC_API_KEY is empty", out)
        self.assertNotIn("Peshawar HQ", out)


@override_settings(**HQ)
class CitySyncCheckOnHqTests(TestCase):
    def test_refuses_on_hq(self):
        self.assertIn("SYSTEM_ROLE is 'hq'", run_check())
