from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from users.token_auth import issue_token, user_for_token_key

User = get_user_model()


def _make_user(username="officer", password="S3cure-pass-123"):
    user = User(username=username, is_active=True)
    user.set_password(password)
    user.save()
    return user


@override_settings(TOKEN_TTL_HOURS=24, TOKEN_NO_EXPIRY_USERS=["svc_remote"])
class ExpiringTokenTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.client = APIClient()

    def _age(self, token, hours):
        Token.objects.filter(pk=token.pk).update(created=timezone.now() - timedelta(hours=hours))
        token.refresh_from_db()

    def test_fresh_token_works(self):
        token = issue_token(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertEqual(self.client.get("/api/detention-memos/list/").status_code, 200)

    def test_expired_token_is_rejected(self):
        token = issue_token(self.user)
        self._age(token, 25)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertEqual(self.client.get("/api/detention-memos/list/").status_code, 401)
        self.assertIsNone(user_for_token_key(token.key))

    def test_login_replaces_expired_token(self):
        old = issue_token(self.user)
        self._age(old, 25)
        new = issue_token(self.user)
        self.assertNotEqual(old.key, new.key)
        self.assertEqual(user_for_token_key(new.key), self.user)

    def test_service_account_never_expires(self):
        svc = _make_user("svc_remote")
        token = issue_token(svc)
        self._age(token, 24 * 365)
        self.assertEqual(user_for_token_key(token.key), svc)


class DetentionsNeedLoginTests(TestCase):
    def test_anonymous_cannot_list_or_delete(self):
        client = APIClient()
        self.assertEqual(client.get("/api/detention-memos/list/").status_code, 401)
        self.assertEqual(client.get("/api/deposit-accounts/list/").status_code, 401)
        self.assertEqual(
            client.delete("/api/detention-memos/00000000-0000-0000-0000-000000000000/delete/").status_code,
            401,
        )


@override_settings(LOGIN_MAX_FAILURES=3, LOGIN_LOCKOUT_MINUTES=15)
class LoginLockoutTests(TestCase):
    def setUp(self):
        cache.clear()
        _make_user("guard", "Right-pass-987")
        self.client = APIClient()

    def _login(self, password):
        return self.client.post("/api/auth/login/", {"username": "guard", "password": password}, format="json")

    def test_locks_after_repeated_wrong_passwords(self):
        for _ in range(3):
            self.assertEqual(self._login("wrong").status_code, 400)
        # Even the right password is refused while locked.
        self.assertEqual(self._login("Right-pass-987").status_code, 429)

    def test_success_clears_the_count(self):
        self._login("wrong")
        self._login("wrong")
        self.assertEqual(self._login("Right-pass-987").status_code, 200)
        self._login("wrong")
        self._login("wrong")
        self.assertEqual(self._login("Right-pass-987").status_code, 200)


class LogoutCancelsTokenTests(TestCase):
    def setUp(self):
        cache.clear()
        _make_user("leaver", "Right-pass-987")
        self.client = APIClient()

    def test_login_cookie_is_httponly_and_logout_cancels_token(self):
        res = self.client.post("/api/auth/login/", {"username": "leaver", "password": "Right-pass-987"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.cookies["tekeye_auth_token"]["httponly"])
        key = res.data["token"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {key}")
        self.assertEqual(self.client.post("/api/auth/web-logout/").status_code, 200)
        self.assertFalse(Token.objects.filter(key=key).exists())
        # The copied token no longer works.
        self.assertEqual(self.client.get("/api/detention-memos/list/").status_code, 401)


def _user_with_role(username, role, location="PESHAWAR"):
    user = User(username=username, role=role, location=location, is_active=True, phone="0300")
    user.set_password("S3cure-pass-123")
    user.save()
    return user


class RoleEscalationTests(TestCase):
    """HR-level roles must not be able to create or become administrators."""

    def setUp(self):
        self.hr = _user_with_role("hr_officer", "HR")
        self.admin = _user_with_role("boss", "ADMIN", location="")
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _new_user(self, role):
        return self.client.post(
            "/api/users/",
            {"username": f"new_{role.lower()}", "password": "S3cure-pass-123",
             "full_name": "New Person", "role": role, "phone": "0300", "location": "PESHAWAR"},
            format="json",
        )

    def test_hr_cannot_create_super_admin(self):
        self.assertEqual(self._new_user("ADMIN").status_code, 400)
        self.assertFalse(User.objects.filter(username="new_admin").exists())

    def test_hr_cannot_promote_self(self):
        resp = self.client.patch(f"/api/users/{self.hr.pk}/", {"role": "ADMIN"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.hr.refresh_from_db()
        self.assertEqual(self.hr.role, "HR")

    def test_hr_cannot_reset_admin_password(self):
        resp = self.client.patch(f"/api/users/{self.admin.pk}/", {"password": "Hacked-pass-999"}, format="json")
        self.assertIn(resp.status_code, (403, 404))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("S3cure-pass-123"))

    def test_super_admin_can_create_admin(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self._new_user("LOCATION_ADMIN").status_code, 201)


class NvrPasswordNotLeakedTests(TestCase):
    def setUp(self):
        from cameras.models import Camera, Nvr, Site

        site = Site.objects.create(code="PESHAWAR", name="Peshawar")
        nvr = Nvr.objects.create(site=site, name="NVR 1", ip_address="10.0.0.5", password="nvr-secret")
        Camera.objects.create(nvr=nvr, channel=1, name="Gate")
        self.client = APIClient()

    def _rtsp_urls(self, user):
        self.client.force_authenticate(user)
        resp = self.client.get("/api/cameras/streams/?allocated=0")
        self.assertEqual(resp.status_code, 200)
        return [c["rtsp_url"] for c in resp.json()["cameras"]]

    def test_normal_user_gets_no_rtsp_password(self):
        urls = self._rtsp_urls(_user_with_role("guard", "GUARD"))
        self.assertTrue(urls)
        self.assertFalse(any("nvr-secret" in u for u in urls))

    def test_super_admin_still_gets_rtsp(self):
        urls = self._rtsp_urls(_user_with_role("boss", "ADMIN", location=""))
        self.assertTrue(any("nvr-secret" in u for u in urls))

    def test_normal_user_cannot_change_nvr(self):
        from cameras.models import Nvr

        self.client.force_authenticate(_user_with_role("guard", "GUARD"))
        nvr = Nvr.objects.get()
        resp = self.client.patch(f"/api/nvrs/{nvr.pk}/", {"ip_address": "6.6.6.6"}, format="json")
        self.assertEqual(resp.status_code, 403)
