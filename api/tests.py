import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from bible.models import BibleTranslation
from church.models import Event, Member, WorkerAssignment
from church.tests_helpers import make_branch, make_user
from sermons.tests import FakeYouTube
from sermons.youtube import YouTubeService

User = get_user_model()
PASSWORD = "pass12345!Xy"


class ApiBase(APITestCase):
    def setUp(self):
        cache.clear()
        self.sa = make_user("super@example.org", User.Role.SUPER_ADMIN)
        self.ba1 = make_user("ba1@example.org", User.Role.BRANCH_ADMIN)
        self.ba2 = make_user("ba2@example.org", User.Role.BRANCH_ADMIN)
        self.b1 = make_branch("Lagos", self.ba1)
        self.b2 = make_branch("Abuja", self.ba2)
        self.member = make_user("mem@example.org")

    def as_user(self, user):
        self.client.force_authenticate(user)


class AuthApiTests(ApiBase):
    def test_register_login_refresh_me(self):
        r = self.client.post("/api/v1/auth/register/", {
            "first_name": "Ada", "last_name": "Obi", "email": "ada@example.org", "password": "Str0ng-pass-99",
            "branch": self.b1.pk}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["user"]["role"], "member")
        self.assertTrue(Member.objects.filter(user__email="ada@example.org", branch=self.b1).exists())
        r = self.client.post("/api/v1/auth/token/", {"email": "ada@example.org", "password": "Str0ng-pass-99"}, format="json")
        self.assertEqual(r.status_code, 200)
        access, refresh = r.data["access"], r.data["refresh"]
        r = self.client.post("/api/v1/auth/token/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(r.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(self.client.get("/api/v1/me/").data["email"], "ada@example.org")

    def test_register_weak_password_and_duplicate(self):
        base = {"first_name": "A", "last_name": "B", "email": "x@example.org"}
        self.assertEqual(self.client.post("/api/v1/auth/register/", {**base, "password": "123"}, format="json").status_code, 400)
        make_user("x@example.org")
        self.assertEqual(self.client.post("/api/v1/auth/register/", {**base, "password": "Str0ng-pass-99"}, format="json").status_code, 400)

    def test_wrong_password_rejected(self):
        r = self.client.post("/api/v1/auth/token/", {"email": "mem@example.org", "password": "nope"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_me_requires_auth_and_cannot_change_role(self):
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 401)
        self.as_user(self.member)
        r = self.client.patch("/api/v1/me/", {"role": "super_admin", "phone": "555", "first_name": "Zed"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, "member")
        self.assertEqual(self.member.profile.phone, "555")


class PermissionApiTests(ApiBase):
    def test_members_endpoint_staff_only_and_scoped(self):
        Member.objects.create(full_name="L", branch=self.b1)
        Member.objects.create(full_name="A", branch=self.b2)
        self.as_user(self.member)
        self.assertEqual(self.client.get("/api/v1/members/").status_code, 403)
        self.as_user(self.ba1)
        names = [m["full_name"] for m in self.client.get("/api/v1/members/").data["results"]]
        self.assertEqual(names, ["L"])
        self.as_user(self.sa)
        self.assertEqual(self.client.get("/api/v1/members/").data["count"], 2)

    def test_branch_admin_cannot_write_to_other_branch(self):
        self.as_user(self.ba1)
        r = self.client.post("/api/v1/members/", {"full_name": "Sneaky", "branch": self.b2.pk}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/v1/members/", {"full_name": "Ok", "branch": self.b1.pk}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_branch_write_super_only(self):
        self.as_user(self.ba1)
        self.assertEqual(self.client.post("/api/v1/branches/", {"name": "New"}, format="json").status_code, 403)
        self.as_user(self.sa)
        self.assertEqual(self.client.post("/api/v1/branches/", {"name": "New"}, format="json").status_code, 201)

    def test_public_branch_list_hides_inactive_and_admins(self):
        make_branch("Closed", is_active=False)
        r = self.client.get("/api/v1/branches/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual({b["name"] for b in r.data["results"]}, {"Lagos", "Abuja"})
        self.assertNotIn("admins", r.data["results"][0])


class EventApiTests(ApiBase):
    def test_public_sees_confirmed_only_staff_can_write_in_scope(self):
        when = timezone.now() + timezone.timedelta(days=3)
        Event.objects.create(title="Pub", start_at=when, status="confirmed", branch=self.b1)
        Event.objects.create(title="Draft", start_at=when, status="draft", branch=self.b1)
        titles = {e["title"] for e in self.client.get("/api/v1/events/").data["results"]}
        self.assertEqual(titles, {"Pub"})
        self.as_user(self.ba1)
        payload = {"title": "New", "start_at": when.isoformat(), "branch": self.b1.pk, "status": "confirmed", "kind": "service"}
        self.assertEqual(self.client.post("/api/v1/events/", payload, format="json").status_code, 201)
        self.assertEqual(self.client.post("/api/v1/events/", {**payload, "branch": self.b2.pk}, format="json").status_code, 400)
        self.as_user(self.member)
        self.assertEqual(self.client.post("/api/v1/events/", payload, format="json").status_code, 403)

    def test_end_before_start_rejected(self):
        self.as_user(self.sa)
        now = timezone.now()
        r = self.client.post("/api/v1/events/", {"title": "Bad", "start_at": now.isoformat(),
                                                 "end_at": (now - timezone.timedelta(hours=1)).isoformat(), "kind": "other"}, format="json")
        self.assertEqual(r.status_code, 400)


class WorkerApplicationApiTests(ApiBase):
    def test_full_flow(self):
        self.as_user(self.member)
        body = {"branch": self.b1.pk, "experience": "I have served in media for five years."}
        r = self.client.post("/api/v1/worker-applications/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        app_id = r.data["id"]
        self.assertEqual(r.data["status"], "pending")
        self.assertEqual(self.client.post("/api/v1/worker-applications/", body, format="json").status_code, 400)  # duplicate
        self.assertEqual(self.client.get("/api/v1/worker-applications/mine/").data[0]["id"], app_id)
        self.assertEqual(self.client.post(f"/api/v1/worker-applications/{app_id}/approve/").status_code, 403)

        self.as_user(self.ba2)  # other branch's admin cannot even see it
        self.assertEqual(self.client.post(f"/api/v1/worker-applications/{app_id}/approve/").status_code, 404)

        self.as_user(self.ba1)
        r = self.client.post(f"/api/v1/worker-applications/{app_id}/approve/", {"note": "Welcome"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "approved")
        self.assertEqual(WorkerAssignment.objects.filter(user=self.member, branch=self.b1).count(), 1)
        self.assertEqual(self.client.post(f"/api/v1/worker-applications/{app_id}/approve/").status_code, 400)  # already reviewed

    def test_applicant_only_sees_own(self):
        other = make_user("other@example.org")
        from church import services
        services.submit_worker_application(other, self.b1, None, "x" * 25)
        self.as_user(self.member)
        self.assertEqual(self.client.get("/api/v1/worker-applications/").data["count"], 0)


class ContentApiTests(ApiBase):
    def test_notifications_and_read_state(self):
        from church.models import Notification
        Notification.objects.create(title="Hi", message="All", audience="all")
        Notification.objects.create(title="Future", message="Later", audience="all", send_at=timezone.now() + timezone.timedelta(days=1))
        self.as_user(self.member)
        r = self.client.get("/api/v1/notifications/")
        self.assertEqual([n["title"] for n in r.data["results"]], ["Hi"])
        self.assertFalse(r.data["results"][0]["is_read"])
        self.client.post("/api/v1/notifications/read-all/")
        self.assertTrue(self.client.get("/api/v1/notifications/").data["results"][0]["is_read"])
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/v1/notifications/").status_code, 401)

    def test_devotionals_public_published_only(self):
        from church.models import Devotional
        Devotional.objects.create(title="Pub", body="b", is_published=True, date=timezone.localdate())
        Devotional.objects.create(title="Draft", body="b", is_published=False)
        r = self.client.get("/api/v1/devotionals/")
        self.assertEqual([d["title"] for d in r.data["results"]], ["Pub"])
        self.assertEqual(self.client.get("/api/v1/devotionals/today/").data["title"], "Pub")

    def test_announcements_require_auth_and_respect_branch(self):
        from church.models import Announcement
        Announcement.objects.create(title="Global", body="b", is_published=True)
        Announcement.objects.create(title="Abuja only", body="b", is_published=True, branch=self.b2)
        Member.objects.create(user=self.member, full_name="M", branch=self.b1)
        self.assertEqual(self.client.get("/api/v1/announcements/").status_code, 401)
        self.as_user(self.member)
        self.assertEqual([a["title"] for a in self.client.get("/api/v1/announcements/").data["results"]], ["Global"])

    def test_bible_versions_format(self):
        media = tempfile.mkdtemp()
        try:
            with override_settings(MEDIA_ROOT=media):
                t = BibleTranslation(name="kjv")
                t.file.save("x.json", ContentFile(b'{"a": 1}'), save=False)
                t.save()
                r = self.client.get("/api/v1/bible/versions/")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(set(r.data[0]), {"name", "size", "size_in_bytes", "url"})
                self.assertEqual(r.data[0]["name"], "KJV")
                self.assertTrue(r.data[0]["url"].startswith("http"))
        finally:
            shutil.rmtree(media, ignore_errors=True)

    @override_settings(YOUTUBE_API_KEY="k", YOUTUBE_CHANNEL_ID="UC_test")
    def test_sermons_and_live_endpoints(self):
        with mock.patch.object(YouTubeService, "_http_get", FakeYouTube(live_ids=["vid00001"])):
            r = self.client.get("/api/v1/sermons/")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data["next_page_token"], "NEXT")
            self.assertEqual(len(r.data["results"]), 2)
            self.assertEqual(self.client.get("/api/v1/sermons/vid00001/").data["video_id"], "vid00001")
            live = self.client.get("/api/v1/live/").data
            self.assertTrue(live["is_live"])


class MobileAuthExtrasTests(ApiBase):
    def test_register_with_username_and_location(self):
        r = self.client.post("/api/v1/auth/register/", {
            "first_name": "Ngozi", "last_name": "O", "email": "ngozi@example.org", "password": "Str0ng-pass-99",
            "username": "ngozi_o", "location": "Luton", "phone": "123"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["user"]["username"], "ngozi_o")
        # sign in with the username AND with the email
        for who in ("ngozi_o", "ngozi@example.org"):
            r = self.client.post("/api/v1/auth/token/", {"email": who, "password": "Str0ng-pass-99"}, format="json")
            self.assertEqual(r.status_code, 200, who)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        me = self.client.get("/api/v1/me/").data
        self.assertEqual(me["location"], "Luton")
        self.assertTrue(me["member_id"].startswith("KP-"))

    def test_username_rules(self):
        base = {"first_name": "A", "last_name": "B", "email": "u1@example.org", "password": "Str0ng-pass-99"}
        self.assertEqual(self.client.post("/api/v1/auth/register/", {**base, "username": "a@b"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/v1/auth/register/", {**base, "username": "ab"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/v1/auth/register/", {**base, "username": "good_name"}, format="json").status_code, 201)
        self.assertEqual(self.client.post("/api/v1/auth/register/", {**base, "email": "u2@example.org", "username": "GOOD_name"}, format="json").status_code, 400)

    def test_me_patch_keeps_custom_username(self):
        self.as_user(self.member)
        r = self.client.patch("/api/v1/me/", {"username": "new_handle", "location": "Lagos"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.member.refresh_from_db()
        self.assertEqual(self.member.username, "new_handle")
        self.client.patch("/api/v1/me/", {"email": "changed@example.org"}, format="json")
        self.member.refresh_from_db()
        self.assertEqual(self.member.username, "new_handle")

    @override_settings(REQUIRE_EMAIL_VERIFICATION=True)
    def test_email_code_flow_and_enforcement(self):
        from django.core import mail
        body = {"first_name": "A", "last_name": "B", "email": "verify@example.org", "password": "Str0ng-pass-99"}
        self.assertEqual(self.client.post("/api/v1/auth/register/", body, format="json").status_code, 400)  # not verified
        self.assertEqual(self.client.post("/api/v1/auth/email-code/", {"email": "verify@example.org"}, format="json").status_code, 200)
        code = mail.outbox[-1].body.split(": ")[1].split("\n")[0]
        self.assertEqual(self.client.post("/api/v1/auth/email-code/verify/", {"email": "verify@example.org", "code": "000000"}, format="json").status_code, 400)
        r = self.client.post("/api/v1/auth/email-code/verify/", {"email": "verify@example.org", "code": code}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        token = r.data["email_token"]
        self.assertEqual(self.client.post("/api/v1/auth/register/", {**body, "email_token": "bad"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/v1/auth/register/", {**body, "email_token": token}, format="json").status_code, 201)
        # token is bound to the email it was issued for
        other = {**body, "email": "other@example.org", "email_token": token}
        self.assertEqual(self.client.post("/api/v1/auth/register/", other, format="json").status_code, 400)

    def test_code_attempts_limited_and_resend_cooldown(self):
        from django.core import mail
        self.client.post("/api/v1/auth/email-code/", {"email": "limit@example.org"}, format="json")
        self.assertEqual(self.client.post("/api/v1/auth/email-code/", {"email": "limit@example.org"}, format="json").status_code, 429)
        code = mail.outbox[-1].body.split(": ")[1].split("\n")[0]
        for _ in range(5):
            self.client.post("/api/v1/auth/email-code/verify/", {"email": "limit@example.org", "code": "999999" if code != "999999" else "111111"}, format="json")
        self.assertEqual(self.client.post("/api/v1/auth/email-code/verify/", {"email": "limit@example.org", "code": code}, format="json").status_code, 400)

    def test_password_reset_flow(self):
        from django.core import mail
        u = make_user("reset@example.org")
        self.assertEqual(self.client.post("/api/v1/auth/password-reset/", {"email": "nobody@example.org"}, format="json").status_code, 200)
        self.assertEqual(len(mail.outbox), 0)  # unknown address: same answer, no email
        self.client.post("/api/v1/auth/password-reset/", {"email": "reset@example.org"}, format="json")
        code = mail.outbox[-1].body.split(": ")[1].split("\n")[0]
        r = self.client.post("/api/v1/auth/password-reset/verify/", {"email": "reset@example.org", "code": code}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        token = r.data["reset_token"]
        self.assertEqual(self.client.post("/api/v1/auth/password-reset/confirm/", {"reset_token": token, "new_password": "123"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/v1/auth/password-reset/confirm/", {"reset_token": token, "new_password": "Brand-new-pass-77"}, format="json").status_code, 200)
        u.refresh_from_db()
        self.assertTrue(u.check_password("Brand-new-pass-77"))
        # the token cannot be replayed
        self.assertEqual(self.client.post("/api/v1/auth/password-reset/confirm/", {"reset_token": token, "new_password": "Another-pass-88"}, format="json").status_code, 400)

    def test_prayer_requests_private_to_owner(self):
        self.assertEqual(self.client.post("/api/v1/prayer-requests/", {"request": "x"}, format="json").status_code, 401)
        self.as_user(self.member)
        r = self.client.post("/api/v1/prayer-requests/", {"request": "Please pray for my family"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.client.get("/api/v1/prayer-requests/").data["count"], 1)
        self.as_user(self.ba1)
        self.assertEqual(self.client.get("/api/v1/prayer-requests/").data["count"], 0)

    def test_site_info_public(self):
        r = self.client.get("/api/v1/site/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("give_instructions", r.data)


class RecurringEventApiTests(ApiBase):
    def test_upcoming_includes_recurring_with_past_start(self):
        past = timezone.now() - timezone.timedelta(days=200)
        Event.objects.create(title="Sunday Service", start_at=past, status="confirmed", repeat="weekly", kind="service")
        Event.objects.create(title="Old one-off", start_at=past, status="confirmed")
        titles = {e["title"] for e in self.client.get("/api/v1/events/upcoming/").data["results"]}
        self.assertEqual(titles, {"Sunday Service"})
