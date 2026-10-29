"""Tests for the admin / management endpoints of the mobile API (``/api/v1/...``)."""
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from api.tests import ApiBase
from bible.models import BibleTranslation
from church.models import (Event, GivingRecord, Member, Ministry, Notification, PraiseReport, PrayerRequest,
                           WorkerAssignment)
from core.models import SiteSettings
from push_notifications.models import DevicePushToken
from sermons.tests import FakeYouTube
from sermons.youtube import YouTubeService

User = get_user_model()
API = "/api/v1"


# --------------------------------------------------------------- dashboard
class DashboardApiTests(ApiBase):
    def test_requires_login(self):
        self.assertEqual(self.client.get(f"{API}/dashboard/").status_code, 401)

    def test_super_admin_summary(self):
        Member.objects.create(full_name="A", branch=self.b1)
        GivingRecord.objects.create(amount="100.00", currency="NGN")
        GivingRecord.objects.create(amount="5.00", currency="USD")
        PrayerRequest.objects.create(title="t", request="r")
        self.as_user(self.sa)
        r = self.client.get(f"{API}/dashboard/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["role"], "super_admin")
        self.assertEqual(r.data["stats"]["members"], 1)
        self.assertEqual(r.data["stats"]["pending_prayers"], 1)
        # one total per currency, never summed together
        self.assertEqual({g["currency"] for g in r.data["stats"]["giving_this_month"]}, {"NGN", "USD"})
        self.assertEqual(len(r.data["member_growth"]), 7)
        self.assertEqual(r.data["member_growth"][-1]["count"], 1)

    def test_branch_admin_is_scoped_to_their_branch(self):
        Member.objects.create(full_name="L", branch=self.b1)
        Member.objects.create(full_name="A", branch=self.b2)
        self.as_user(self.ba1)
        r = self.client.get(f"{API}/dashboard/")
        self.assertEqual(r.data["role"], "branch_admin")
        self.assertEqual(r.data["branch"]["id"], self.b1.pk)
        self.assertEqual(r.data["stats"]["members"], 1)
        self.assertEqual(self.client.get(f"{API}/dashboard/?branch={self.b2.pk}").status_code, 404)
        self.assertEqual(self.client.get(f"{API}/dashboard/?branch=abc").status_code, 404)

    def test_member_gets_portal_payload(self):
        self.as_user(self.member)
        r = self.client.get(f"{API}/dashboard/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["role"], "member")
        for key in ("announcements", "upcoming_events", "notifications", "unread_notifications", "my_applications"):
            self.assertIn(key, r.data)
        self.assertNotIn("stats", r.data)


# ------------------------------------------------------------------ users
class AdminUserApiTests(ApiBase):
    def test_staff_only_and_searchable(self):
        self.as_user(self.member)
        self.assertEqual(self.client.get(f"{API}/admin/users/").status_code, 403)
        self.as_user(self.ba1)
        r = self.client.get(f"{API}/admin/users/?search=mem@example")
        self.assertEqual([u["email"] for u in r.data["results"]], ["mem@example.org"])
        emails = {u["email"] for u in self.client.get(f"{API}/admin/users/?assignable=true").data["results"]}
        self.assertNotIn("mem@example.org", emails)
        self.assertIn("ba2@example.org", emails)


# -------------------------------------------------------------- ministries
class MinistryApiTests(ApiBase):
    def test_public_read_active_only_and_branch_filter(self):
        Ministry.objects.create(name="Choir", branch=self.b1)
        Ministry.objects.create(name="Ushers", branch=self.b2)
        Ministry.objects.create(name="Media")  # church-wide
        Ministry.objects.create(name="Hidden", branch=self.b1, is_active=False)
        r = self.client.get(f"{API}/ministries/?for_branch={self.b1.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual({m["name"] for m in r.data["results"]}, {"Choir", "Media"})

    def test_only_super_admin_writes_and_names_are_unique(self):
        body = {"name": "Prayer Team", "branch": self.b1.pk}
        self.as_user(self.member)
        self.assertEqual(self.client.post(f"{API}/ministries/", body, format="json").status_code, 403)
        self.as_user(self.ba1)
        self.assertEqual(self.client.post(f"{API}/ministries/", body, format="json").status_code, 403)
        self.as_user(self.sa)
        r = self.client.post(f"{API}/ministries/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        dup = self.client.post(f"{API}/ministries/", {"name": "prayer team", "branch": self.b1.pk}, format="json")
        self.assertEqual(dup.status_code, 400)
        # same name in another branch is fine
        self.assertEqual(self.client.post(f"{API}/ministries/", {"name": "Prayer Team", "branch": self.b2.pk},
                                          format="json").status_code, 201)
        self.assertEqual(self.client.patch(f"{API}/ministries/{r.data['id']}/", {"is_active": False},
                                           format="json").status_code, 200)


# ----------------------------------------------------------------- workers
class WorkerApiTests(ApiBase):
    def test_branch_admin_adds_updates_and_toggles(self):
        self.as_user(self.ba1)
        body = {"user": self.member.pk, "branch": self.b1.pk, "title": "Usher"}
        r = self.client.post(f"{API}/workers/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, "worker")
        # adding the same person again updates, it doesn't duplicate
        self.client.post(f"{API}/workers/", {**body, "title": "Head usher"}, format="json")
        self.assertEqual(WorkerAssignment.objects.filter(user=self.member).count(), 1)
        wid = r.data["id"]
        self.assertEqual(self.client.patch(f"{API}/workers/{wid}/", {"title": "Greeter"}, format="json").data["title"],
                         "Greeter")
        self.assertFalse(self.client.post(f"{API}/workers/{wid}/toggle/").data["is_active"])
        self.assertTrue(self.client.post(f"{API}/workers/{wid}/toggle/").data["is_active"])

    def test_cannot_use_another_branch(self):
        self.as_user(self.ba1)
        r = self.client.post(f"{API}/workers/", {"user": self.member.pk, "branch": self.b2.pk}, format="json")
        self.assertEqual(r.status_code, 400)
        other = WorkerAssignment.objects.create(user=self.member, branch=self.b2)
        self.assertEqual(self.client.get(f"{API}/workers/{other.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"{API}/workers/{other.pk}/toggle/").status_code, 404)

    def test_ministry_must_belong_to_branch_and_user_branch_are_fixed(self):
        abuja = Ministry.objects.create(name="Abuja only", branch=self.b2)
        self.as_user(self.sa)
        bad = self.client.post(f"{API}/workers/", {"user": self.member.pk, "branch": self.b1.pk,
                                                   "ministry": abuja.pk}, format="json")
        self.assertEqual(bad.status_code, 400)
        w = WorkerAssignment.objects.create(user=self.member, branch=self.b1)
        moved = self.client.patch(f"{API}/workers/{w.pk}/", {"branch": self.b2.pk}, format="json")
        self.assertEqual(moved.status_code, 400)

    def test_members_cannot_use_workers_endpoint(self):
        self.as_user(self.member)
        self.assertEqual(self.client.get(f"{API}/workers/").status_code, 403)
        self.assertEqual(self.client.post(f"{API}/workers/", {}, format="json").status_code, 403)


# ------------------------------------------------------- branches + events
class BranchAdminRoleTests(ApiBase):
    def test_assigning_branch_admin_promotes_and_removing_demotes(self):
        self.as_user(self.sa)
        r = self.client.post(f"{API}/branches/", {"name": "Ibadan", "admins": [self.member.pk]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, "branch_admin")
        r = self.client.patch(f"{API}/branches/{r.data['id']}/", {"admins": []}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, "member")


class EventCancelTests(ApiBase):
    def test_cancel_is_scoped(self):
        mine = Event.objects.create(title="Lagos", start_at=timezone.now(), status="confirmed", branch=self.b1)
        theirs = Event.objects.create(title="Abuja", start_at=timezone.now(), status="confirmed", branch=self.b2)
        self.as_user(self.member)
        self.assertEqual(self.client.post(f"{API}/events/{mine.pk}/cancel/").status_code, 403)
        self.as_user(self.ba1)
        self.assertEqual(self.client.post(f"{API}/events/{theirs.pk}/cancel/").status_code, 404)
        r = self.client.post(f"{API}/events/{mine.pk}/cancel/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], "cancelled")


# ------------------------------------------------------------------ praise
class PraiseApiTests(ApiBase):
    def test_submit_review_publish_flow(self):
        Member.objects.create(user=self.member, full_name="M", branch=self.b1)
        self.assertEqual(self.client.post(f"{API}/praise-reports/", {"story": "x"}, format="json").status_code, 401)

        self.as_user(self.member)
        r = self.client.post(f"{API}/praise-reports/", {"story": "God healed me", "category": "Healing",
                                                        "status": "published"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["status"], "pending")  # members can't self-publish
        self.assertEqual(PraiseReport.objects.get().branch_id, self.b1.pk)
        pid = r.data["id"]
        self.assertEqual(self.client.get(f"{API}/praise-reports/mine/").data["count"], 1)
        self.assertEqual(self.client.post(f"{API}/praise-reports/{pid}/approve/").status_code, 403)

        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(f"{API}/praise-reports/").data["count"], 0)  # still pending
        self.assertEqual(self.client.get(f"{API}/praise-reports/{pid}/").status_code, 404)

        self.as_user(self.sa)
        self.assertEqual(self.client.get(f"{API}/praise-reports/?status=pending").data["count"], 1)
        self.assertEqual(self.client.post(f"{API}/praise-reports/{pid}/approve/").data["status"], "published")
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(f"{API}/praise-reports/").data["count"], 1)

        self.as_user(self.sa)
        self.assertEqual(self.client.post(f"{API}/praise-reports/{pid}/decline/").data["status"], "declined")

    def test_blank_story_rejected(self):
        self.as_user(self.member)
        self.assertEqual(self.client.post(f"{API}/praise-reports/", {"story": "   "}, format="json").status_code, 400)

    def test_members_cannot_edit_or_delete(self):
        report = PraiseReport.objects.create(story="s", status="published", user=self.member)
        self.as_user(self.member)
        self.assertEqual(self.client.patch(f"{API}/praise-reports/{report.pk}/", {"story": "z"},
                                           format="json").status_code, 403)
        self.assertEqual(self.client.delete(f"{API}/praise-reports/{report.pk}/").status_code, 403)


# ------------------------------------------------------------------ prayer
class PrayerAdminApiTests(ApiBase):
    def setUp(self):
        super().setUp()
        self.p1 = PrayerRequest.objects.create(title="One", request="Pray 1", user=self.member)
        PrayerRequest.objects.create(title="Two", request="Pray 2", status="answered")

    def test_super_admin_only(self):
        for user in (self.member, self.ba1):
            self.as_user(user)
            self.assertEqual(self.client.get(f"{API}/admin/prayer-requests/").status_code, 403)
        self.as_user(self.sa)
        self.assertEqual(self.client.get(f"{API}/admin/prayer-requests/").data["count"], 2)
        self.assertEqual(self.client.get(f"{API}/admin/prayer-requests/?status=answered").data["count"], 1)

    def test_board_and_assigning_moves_to_in_progress(self):
        self.as_user(self.sa)
        board = self.client.get(f"{API}/admin/prayer-requests/board/").data
        counts = {c["status"]: c["count"] for c in board["columns"]}
        self.assertEqual(counts, {"pending": 1, "in_progress": 0, "answered": 1})
        self.assertEqual(board["unassigned_pending"], 1)
        r = self.client.patch(f"{API}/admin/prayer-requests/{self.p1.pk}/", {"assigned_to": self.ba1.pk},
                              format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], "in_progress")
        self.assertEqual(r.data["assigned_to_name"], self.ba1.display_name)
        # only status / assigned_to are editable
        r = self.client.patch(f"{API}/admin/prayer-requests/{self.p1.pk}/", {"request": "changed", "status": "answered"},
                              format="json")
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.request, "Pray 1")
        self.assertEqual(self.p1.status, "answered")
        self.assertEqual(self.client.put(f"{API}/admin/prayer-requests/{self.p1.pk}/", {}, format="json").status_code, 405)

    def test_assignees_exclude_plain_members(self):
        self.as_user(self.sa)
        emails = {u["email"] for u in self.client.get(f"{API}/admin/prayer-requests/assignees/").data}
        self.assertIn("ba1@example.org", emails)
        self.assertNotIn("mem@example.org", emails)


# ------------------------------------------------------------------ giving
class GivingApiTests(ApiBase):
    def test_crud_permissions_and_validation(self):
        body = {"donor_name": "Ada", "amount": "2500.50", "currency": "ngn", "fund": "tithe"}
        self.as_user(self.ba1)
        self.assertEqual(self.client.get(f"{API}/admin/giving/").status_code, 403)
        self.as_user(self.sa)
        r = self.client.post(f"{API}/admin/giving/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["currency"], "NGN")
        self.assertEqual(r.data["fund_display"], "Tithes")
        self.assertEqual(self.client.post(f"{API}/admin/giving/", {**body, "amount": "-5"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"{API}/admin/giving/", {**body, "currency": "NAIRA"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(f"{API}/admin/giving/{r.data['id']}/", {"method": "Transfer"},
                                           format="json").data["method"], "Transfer")
        self.assertEqual(self.client.delete(f"{API}/admin/giving/{r.data['id']}/").status_code, 204)

    def test_monthly_summary_per_currency(self):
        GivingRecord.objects.create(amount="300", currency="NGN", fund="tithe")
        GivingRecord.objects.create(amount="100", currency="NGN", fund="offering")
        GivingRecord.objects.create(amount="7", currency="USD", fund="offering")
        old = timezone.localdate().replace(day=1) - timedelta(days=40)
        GivingRecord.objects.create(amount="999", currency="NGN", given_on=old)
        self.as_user(self.sa)
        r = self.client.get(f"{API}/admin/giving/summary/")
        self.assertEqual(r.status_code, 200, r.content)
        totals = {t["currency"]: t["total"] for t in r.data["totals"]}
        self.assertEqual(totals, {"NGN": "400.00", "USD": "7.00"})
        tithe = [f for f in r.data["by_fund"] if f["currency"] == "NGN" and f["fund"] == "tithe"][0]
        self.assertEqual(tithe["percent"], 75)
        self.assertEqual(self.client.get(f"{API}/admin/giving/summary/?month=nope").status_code, 400)
        self.assertEqual(self.client.get(f"{API}/admin/giving/summary/?branch=x").status_code, 400)


# ---------------------------------------------------------------- settings
class SiteSettingsApiTests(ApiBase):
    def test_super_admin_edits_and_public_endpoint_reflects_it(self):
        self.as_user(self.ba1)
        self.assertEqual(self.client.get(f"{API}/admin/settings/").status_code, 403)
        self.as_user(self.sa)
        r = self.client.patch(f"{API}/admin/settings/", {"tagline": "Welcome home", "contact_phone": "0800"},
                              format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(SiteSettings.load().tagline, "Welcome home")
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(f"{API}/site/").data["tagline"], "Welcome home")
        self.as_user(self.sa)
        self.assertEqual(self.client.patch(f"{API}/admin/settings/", {"contact_email": "nope"},
                                           format="json").status_code, 400)


# ------------------------------------------------------------------- bible
class BibleAdminApiTests(ApiBase):
    def setUp(self):
        super().setUp()
        # the model's storage is Cloudinary; swap in a temp folder so nothing leaves the machine
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        field = BibleTranslation._meta.get_field("file")
        original = field.storage
        field.storage = FileSystemStorage(location=tmp, base_url="/media/")
        self.addCleanup(setattr, field, "storage", original)
        patcher = mock.patch("bible.services.destroy_remote_file")
        self.destroy = patcher.start()
        self.addCleanup(patcher.stop)

    def upload(self, name="kjv", content=b'{"Genesis": {"1": {"1": "In the beginning"}}}', filename="kjv.json"):
        return self.client.post(f"{API}/admin/bible/", {
            "name": name, "file": SimpleUploadedFile(filename, content, content_type="application/json")},
            format="multipart")

    def test_only_super_admin(self):
        for user in (self.member, self.ba1):
            self.as_user(user)
            self.assertEqual(self.client.get(f"{API}/admin/bible/").status_code, 403)
            self.assertEqual(self.upload().status_code, 403)

    def test_upload_list_duplicate_and_validation(self):
        self.as_user(self.sa)
        r = self.upload()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["name"], "KJV")
        self.assertGreater(r.data["size_in_bytes"], 0)
        listing = self.client.get(f"{API}/admin/bible/").data
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["results"][0]["name"], "KJV")
        self.assertEqual(self.upload(name="KJV").status_code, 400)            # duplicate
        self.assertEqual(self.upload(name="NIV", content=b"{not json").status_code, 400)
        self.assertEqual(self.upload(name="NIV", filename="x.txt").status_code, 400)
        self.assertEqual(self.upload(name="bad name!").status_code, 400)
        self.assertEqual(BibleTranslation.objects.count(), 1)

    def test_replace_updates_file_and_size_and_removes_old_asset(self):
        self.as_user(self.sa)
        created = self.upload().data
        new = b'{"Genesis": {"1": {"1": "In the beginning God created the heaven and the earth"}}}'
        r = self.client.post(f"{API}/admin/bible/{created['id']}/replace/", {
            "file": SimpleUploadedFile("new.json", new, content_type="application/json")}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["name"], "KJV")  # name is kept when omitted
        self.assertEqual(r.data["size_in_bytes"], len(new))
        self.destroy.assert_called_once()

    def test_delete_removes_remote_file_then_row(self):
        self.as_user(self.sa)
        created = self.upload().data
        self.assertEqual(self.client.delete(f"{API}/admin/bible/{created['id']}/").status_code, 204)
        self.assertFalse(BibleTranslation.objects.exists())
        self.destroy.assert_called_once()

    def test_failed_remote_delete_keeps_the_row(self):
        self.as_user(self.sa)
        created = self.upload().data
        self.destroy.side_effect = RuntimeError("cloudinary down")
        self.assertEqual(self.client.delete(f"{API}/admin/bible/{created['id']}/").status_code, 502)
        self.assertTrue(BibleTranslation.objects.filter(pk=created["id"]).exists())


# ----------------------------------------------------------------- sermons
@override_settings(YOUTUBE_API_KEY="k", YOUTUBE_CHANNEL_ID="UC_test")
class SermonAdminApiTests(ApiBase):
    def run_api(self, fn, **fake_kwargs):
        with mock.patch.object(YouTubeService, "_http_get", FakeYouTube(**fake_kwargs)):
            return fn()

    def test_staff_only(self):
        self.as_user(self.member)
        self.assertEqual(self.client.get(f"{API}/admin/sermons/").status_code, 403)
        self.assertEqual(self.client.post(f"{API}/admin/sermons/refresh/").status_code, 403)

    def test_edit_metadata_and_hide(self):
        self.as_user(self.ba1)
        r = self.run_api(lambda: self.client.get(f"{API}/admin/sermons/"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([v["video_id"] for v in r.data["results"]], ["vid00001", "vid00002"])
        self.assertTrue(all(v["note"] is None for v in r.data["results"]))

        r = self.run_api(lambda: self.client.patch(f"{API}/admin/sermons/vid00001/",
                                                   {"speaker": "Pastor A", "is_hidden": True}, format="json"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["note"]["speaker"], "Pastor A")

        # hidden from the public API, still visible to admins
        public = self.run_api(lambda: self.client.get(f"{API}/sermons/"))
        self.assertEqual([v["video_id"] for v in public.data["results"]], ["vid00002"])
        admin = self.run_api(lambda: self.client.get(f"{API}/admin/sermons/"))
        self.assertEqual(len(admin.data["results"]), 2)

    def test_unknown_video_404_and_refresh(self):
        self.as_user(self.sa)
        r = self.run_api(lambda: self.client.patch(f"{API}/admin/sermons/vid00009/", {"speaker": "x"}, format="json"),
                         missing=["vid00009"])
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.client.post(f"{API}/admin/sermons/refresh/").status_code, 200)


# ------------------------------------------------------------ notifications
class NotificationAdminApiTests(ApiBase):
    def send(self, **body):
        return self.client.post(f"{API}/admin/notifications/", body, format="json")

    def test_member_cannot(self):
        self.as_user(self.member)
        self.assertEqual(self.client.get(f"{API}/admin/notifications/").status_code, 403)
        self.assertEqual(self.send(title="t", message="m", audience="all").status_code, 403)

    def test_branch_admin_rules(self):
        self.as_user(self.ba1)
        ok = self.send(title="Sunday", message="Service at 9", audience="branch", branch=self.b1.pk)
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertTrue(ok.data["is_sent"])
        self.assertEqual(self.send(title="t", message="m", audience="all", branch=self.b1.pk).status_code, 400)
        self.assertEqual(self.send(title="t", message="m", audience="branch", branch=self.b2.pk).status_code, 400)
        self.assertEqual(self.send(title="t", message="m", audience="workers").status_code, 400)  # branch required
        self.assertEqual(self.send(title="t", message="m", branch=self.b1.pk).status_code, 400)  # audience required
        self.assertEqual(self.send(title="t", message="m", audience="user", branch=self.b1.pk).status_code, 400)
        # the audience can't be dodged by leaving it out
        self.assertEqual(Notification.objects.count(), 1)

    def test_super_admin_all_and_scheduling(self):
        self.as_user(self.sa)
        later = (timezone.now() + timedelta(days=2)).isoformat()
        r = self.send(title="Big news", message="Everyone", audience="all", send_at=later)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertFalse(r.data["is_sent"])
        self.assertEqual(self.send(title="x", message="y", audience="branch").status_code, 400)
        self.assertEqual(self.send(title="x" * 81, message="y", audience="all").status_code, 400)

    def test_history_is_scoped(self):
        Notification.objects.create(title="L", message="m", audience="branch", branch=self.b1, created_by=self.ba1)
        Notification.objects.create(title="A", message="m", audience="branch", branch=self.b2, created_by=self.ba2)
        self.as_user(self.ba1)
        self.assertEqual([n["title"] for n in self.client.get(f"{API}/admin/notifications/").data["results"]], ["L"])
        self.as_user(self.sa)
        self.assertEqual(self.client.get(f"{API}/admin/notifications/").data["count"], 2)


# -------------------------------------------------------------------- push
class PushAdminApiTests(ApiBase):
    def setUp(self):
        super().setUp()
        self.device = DevicePushToken.objects.create(user=self.member, token="ExponentPushToken[abcdef123456]",
                                                     platform="android")

    @staticmethod
    def expo(statuses):
        resp = mock.Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"data": [{"status": s} for s in statuses]}
        return resp

    def test_super_admin_only(self):
        for user in (self.member, self.ba1):
            self.as_user(user)
            self.assertEqual(self.client.get(f"{API}/admin/push/devices/").status_code, 403)
            self.assertEqual(self.client.post(f"{API}/admin/push/send/", {"title": "t", "message": "m",
                                                                         "target": "all"}, format="json").status_code, 403)

    def test_devices_are_masked_and_recipients_listed(self):
        self.as_user(self.sa)
        row = self.client.get(f"{API}/admin/push/devices/").data["results"][0]
        self.assertEqual(row["token_preview"], "…123456")
        self.assertNotIn("token", row)
        rec = self.client.get(f"{API}/admin/push/recipients/").data["results"]
        self.assertEqual([(r["email"], r["device_count"]) for r in rec], [("mem@example.org", 1)])

    def test_send_to_all_and_selected(self):
        self.as_user(self.sa)
        with mock.patch("push_notifications.services.requests.post", return_value=self.expo(["ok"])) as post:
            r = self.client.post(f"{API}/admin/push/send/", {"title": "Hi", "message": "Service today",
                                                              "target": "all"}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual((r.data["recipients"], r.data["devices"], r.data["accepted"]), (1, 1, 1))
            sent = post.call_args.kwargs["json"]
            self.assertEqual(sent[0]["to"], "ExponentPushToken[abcdef123456]")
            r = self.client.post(f"{API}/admin/push/send/", {"title": "Hi", "message": "m", "target": "selected",
                                                              "users": [self.member.pk]}, format="json")
            self.assertEqual(r.status_code, 200, r.content)

    def test_validation_and_failures(self):
        self.as_user(self.sa)
        url = f"{API}/admin/push/send/"
        self.assertEqual(self.client.post(url, {"title": "t", "message": "m", "target": "selected"},
                                          format="json").status_code, 400)
        # a user with no registered device can't be selected
        self.assertEqual(self.client.post(url, {"title": "t", "message": "m", "target": "selected",
                                                "users": [self.ba1.pk]}, format="json").status_code, 400)
        with mock.patch("push_notifications.services.requests.post", return_value=self.expo(["error"])):
            r = self.client.post(url, {"title": "t", "message": "m", "target": "all"}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.data["failed"], 1)
        DevicePushToken.objects.all().delete()
        self.assertEqual(self.client.post(url, {"title": "t", "message": "m", "target": "all"},
                                          format="json").status_code, 400)


# ----------------------------------------- fixes to pre-existing endpoints
class ExistingEndpointFixTests(ApiBase):
    def test_devotionals_are_super_admin_write_and_can_be_published(self):
        body = {"title": "Faith", "body": "Text", "is_published": True, "date": str(timezone.localdate())}
        self.as_user(self.ba1)
        self.assertEqual(self.client.post(f"{API}/devotionals/", body, format="json").status_code, 403)
        self.as_user(self.sa)
        r = self.client.post(f"{API}/devotionals/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.data["is_published"])
        self.as_user(self.member)
        self.assertEqual(self.client.get(f"{API}/devotionals/today/").data["title"], "Faith")

    def test_unauthenticated_publish_everything_helper_is_gone(self):
        self.assertEqual(self.client.get(f"{API}/updatedev").status_code, 404)

    def test_story_branch_scoping_and_publish_time(self):
        self.as_user(self.ba1)
        other = self.client.post(f"{API}/stories/", {"title": "x", "branch": self.b2.pk}, format="json")
        self.assertEqual(other.status_code, 400)
        r = self.client.post(f"{API}/stories/", {"title": "Mine", "branch": self.b1.pk, "is_published": True},
                             format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIsNotNone(r.data["published_at"])
        r = self.client.patch(f"{API}/stories/{r.data['id']}/", {"is_published": False}, format="json")
        self.assertIsNone(r.data["published_at"])
