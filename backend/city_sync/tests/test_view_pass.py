"""Watching a city's cameras from HQ: HQ signs a pass, the city serves the video itself."""

from __future__ import annotations

import time
from unittest import mock

from django.http import HttpResponse
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from city_sync.models import CityCamera, SyncCredential, SyncSite
from city_sync.tests.test_sites import CITY, HQ
from city_sync.view_pass import check_pass, issue_pass
from users.models import User

KEY = "k"  # CITY settings use SYNC_API_KEY="k"


def hq_pass(loc="ABBOTTABAD", ttl=300) -> str:
    with override_settings(**HQ):
        SyncCredential.objects.update_or_create(
            location_code=loc, defaults={"key_hash": SyncCredential.hash_key(KEY), "is_active": True}
        )
        return issue_pass(loc, user="sa", ttl=ttl)[0]


@override_settings(**CITY)
class ViewPassTests(TestCase):
    def test_city_accepts_its_own_pass(self):
        self.assertEqual(check_pass(hq_pass())["sub"], "sa")

    def test_pass_for_another_city_is_refused(self):
        self.assertIsNone(check_pass(hq_pass("DIKHAN")))

    def test_expired_or_tampered_pass_is_refused(self):
        self.assertIsNone(check_pass(hq_pass(ttl=-1)))
        token = hq_pass()
        body, sig = token.rsplit(".", 1)
        self.assertIsNone(check_pass(f"{body}x.{sig}"))
        self.assertIsNone(check_pass(""))

    @override_settings(SYNC_API_KEY="other-key")
    def test_pass_signed_for_a_different_key_is_refused(self):
        self.assertIsNone(check_pass(hq_pass()))


@override_settings(**CITY)
class CityStreamEndpointTests(TestCase):
    def setUp(self):
        from cameras.models import Camera, Nvr, Site
        from ops_central.models import RemoteServer

        nvr = Nvr.objects.create(site=Site.objects.create(code="T", name="T"), name="N", ip_address="127.0.0.1")
        self.ml = RemoteServer.objects.create(name="ML", base_url="http://127.0.0.1:8001", is_active=True)
        self.cam = Camera.objects.create(nvr=nvr, name="Gate", code="g", channel=1, ml_server=self.ml)
        self.unassigned = Camera.objects.create(nvr=nvr, name="Back", code="b", channel=2)

    def url(self, cam, token, kind="live"):
        return f"/api/sync/v1/view/{cam.pk}/?pass={token}&kind={kind}"

    def test_no_pass_no_video(self):
        self.assertEqual(APIClient().get(self.url(self.cam, "")).status_code, 403)

    @mock.patch("ops_central.views.proxy_ml_stream", return_value=HttpResponse(b"jpg", content_type="image/jpeg"))
    def test_valid_pass_streams_from_the_city_ml_server(self, proxy):
        res = APIClient().get(self.url(self.cam, hq_pass(), kind="jpeg"))
        self.assertEqual(res.status_code, 200)
        proxy.assert_called_once_with(self.ml, self.cam.stream_key, "jpeg")

    def test_camera_without_ml_server_says_so(self):
        res = APIClient().get(self.url(self.unassigned, hq_pass()))
        self.assertEqual(res.status_code, 409)


@override_settings(**HQ)
class HqCameraListTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user(username="sa", password="x", role="ADMIN"))
        SyncSite.objects.create(location_code="HAYATABAD", name="Hayatabad", base_url="http://192.168.88.73:8000/")
        CityCamera.objects.create(location_code="HAYATABAD", origin_pk=3, name="Gate 1")

    def test_returns_cameras_city_address_and_pass(self):
        SyncCredential.objects.create(location_code="HAYATABAD", key_hash=SyncCredential.hash_key(KEY))
        data = self.client.get("/api/ops/city-cameras/hayatabad/").json()
        self.assertEqual(data["base_url"], "http://192.168.88.73:8000")
        self.assertEqual(data["cameras"], [mock.ANY])
        self.assertEqual((data["cameras"][0]["id"], data["cameras"][0]["name"]), (3, "Gate 1"))
        self.assertGreater(data["expires_at"], time.time())
        self.assertIn(".", data["pass"])

    def test_city_without_key_cannot_be_watched(self):
        self.assertEqual(self.client.get("/api/ops/city-cameras/HAYATABAD/").status_code, 409)
