from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from users.token_auth import issue_token

from .models import (
    EmployeeCallRecord,
    EmployeeCallRecording,
    MonitoringAudit,
    MonitoringConsent,
    MonitoringPolicy,
)
from .services import mask_number

BASE = "/api/v1/employee-monitor"


def _user(username, role="GUARD", location=""):
    u = User(username=username, is_active=True, role=role, location=location, phone="0300", email=f"{username}@x.pk")
    u.set_password("S3cure-pass-123")
    u.save()
    return u


User = get_user_model()


def _client(user):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {issue_token(user).key}")
    return c


def _policy():
    return MonitoringPolicy.objects.create(
        version="t1", is_active=True, effective_at=timezone.now(),
        categories=[{"key": "loc", "label": "Location", "description": "GPS", "retention_days": 30}],
    )


class MaskNumberTests(TestCase):
    def test_masking_keeps_prefix_and_last_two(self):
        self.assertEqual(mask_number("+923001234567"), "+92********67")
        self.assertEqual(mask_number("12"), "***")
        self.assertEqual(mask_number(""), "")


@override_settings(EMPLOYEE_MONITORING_ENABLED=True, TEKEYE_DEPLOYMENT_ID="ciis-test")
class FeatureFlagTests(TestCase):
    def test_disabled_returns_501(self):
        with override_settings(EMPLOYEE_MONITORING_ENABLED=False):
            r = _client(_user("off")).get(f"{BASE}/me/")
            self.assertEqual(r.status_code, 501)

    def test_requires_auth(self):
        self.assertEqual(APIClient().get(f"{BASE}/me/").status_code, 401)

    def test_me_reports_deployment(self):
        r = _client(_user("me1")).get(f"{BASE}/me/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["deployment_id"], "ciis-test")


@override_settings(EMPLOYEE_MONITORING_ENABLED=True)
class ConsentTests(TestCase):
    def test_acknowledge_then_current(self):
        p = _policy()
        c = _client(_user("c1"))
        r = c.post(f"{BASE}/consents/", {"policy_id": str(p.id), "action": "acknowledge", "disclosed_categories": ["loc"]}, format="json")
        self.assertEqual(r.status_code, 201)
        cur = c.get(f"{BASE}/consents/current/").json()
        self.assertEqual(cur["status"], "acknowledged")
        self.assertTrue(MonitoringAudit.objects.filter(action="consent_acknowledge").exists())

    def test_withdraw_is_latest(self):
        p = _policy()
        u = _user("c2")
        c = _client(u)
        c.post(f"{BASE}/consents/", {"policy_id": str(p.id), "action": "acknowledge"}, format="json")
        c.post(f"{BASE}/consents/", {"policy_id": str(p.id), "action": "withdraw"}, format="json")
        self.assertEqual(c.get(f"{BASE}/consents/current/").json()["status"], "withdrawn")
        self.assertEqual(MonitoringConsent.objects.filter(user=u).count(), 2)


@override_settings(EMPLOYEE_MONITORING_ENABLED=True)
class CallIngestTests(TestCase):
    def _batch(self, client, event_id="e1", username=""):
        return client.post(
            f"{BASE}/calls/metadata/batch/",
            {"source": "pbx", "source_label": "PBX", "events": [{
                "source_event_id": event_id, "direction": "outbound", "number": "+923001234567",
                "username": username, "started_at": "2026-10-22T09:00:00Z", "duration_seconds": 60,
                "recording_status": "not_recorded",
            }]},
            format="json",
        )

    def test_ordinary_user_cannot_ingest(self):
        r = self._batch(_client(_user("g1", role="GUARD")))
        self.assertEqual(r.status_code, 403)

    def test_admin_ingest_masks_and_dedupes(self):
        admin = _user("a1", role="ADMIN")
        c = _client(admin)
        self.assertEqual(self._batch(c, "e1", username="a1").json()["accepted"], ["e1"])
        self.assertEqual(self._batch(c, "e1", username="a1").json()["duplicates"], ["e1"])
        rec = EmployeeCallRecord.objects.get(source_event_id="e1")
        self.assertEqual(rec.masked_number, "+92********67")
        self.assertNotIn("1234567", rec.masked_number)  # full number never in the masked field

    def test_user_sees_only_own_calls(self):
        admin = _user("a2", role="ADMIN")
        owner = _user("o1", role="GUARD")
        self._batch(_client(admin), "mine", username="o1")
        self._batch(_client(admin), "other", username="a2")
        results = _client(owner).get(f"{BASE}/calls/").json()["results"]
        self.assertEqual({r["id"] for r in results}, set(str(x) for x in EmployeeCallRecord.objects.filter(user=owner).values_list("id", flat=True)))


@override_settings(EMPLOYEE_MONITORING_ENABLED=True)
class RecordingTests(TestCase):
    def test_playback_blocked_until_available_and_audited(self):
        admin = _user("a3", role="ADMIN")
        c = _client(admin)
        up = c.post(f"{BASE}/recordings/uploads/", {
            "source": "pbx", "source_recording_id": "r1", "username": "a3", "content_type": "audio/mpeg",
        }, format="json")
        rid = up.json()["upload_id"]
        # pending -> 409
        self.assertEqual(c.get(f"{BASE}/recordings/{rid}/playback/").status_code, 409)
        # mark available, request playback -> signed url + audit
        EmployeeCallRecording.objects.filter(id=rid).update(status=EmployeeCallRecording.AVAILABLE)
        r = c.get(f"{BASE}/recordings/{rid}/playback/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("/recordings/stream/?t=", r.json()["url"])
        self.assertTrue(MonitoringAudit.objects.filter(action="recording_playback_authorized").exists())

    def test_other_user_cannot_get_playback(self):
        admin = _user("a4", role="ADMIN")
        owner = _user("o2", role="GUARD")
        other = _user("o3", role="GUARD")
        up = _client(admin).post(f"{BASE}/recordings/uploads/", {
            "source": "pbx", "source_recording_id": "r2", "username": "o2",
        }, format="json")
        rid = up.json()["upload_id"]
        EmployeeCallRecording.objects.filter(id=rid).update(status=EmployeeCallRecording.AVAILABLE)
        self.assertEqual(_client(other).get(f"{BASE}/recordings/{rid}/playback/").status_code, 403)
        self.assertEqual(_client(owner).get(f"{BASE}/recordings/{rid}/playback/").status_code, 200)
