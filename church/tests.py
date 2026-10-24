import json
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bible.models import BibleTranslation
from church import services
from church.models import (Announcement, Branch, Event, Member, WorkerApplication, WorkerAssignment)
from church.tests_helpers import make_branch, make_user

User = get_user_model()


class BaseCase(TestCase):
    def setUp(self):
        self.sa = make_user("super@example.org", User.Role.SUPER_ADMIN)
        self.ba1 = make_user("ba1@example.org", User.Role.BRANCH_ADMIN)
        self.ba2 = make_user("ba2@example.org", User.Role.BRANCH_ADMIN)
        self.b1 = make_branch("Lagos", self.ba1)
        self.b2 = make_branch("Abuja", self.ba2)
        self.member = make_user("mem@example.org")


class BranchRelationshipTests(BaseCase):
    def test_slug_unique_and_generated(self):
        dup = Branch.objects.create(name="Lagos 2", slug="")
        self.assertTrue(dup.slug)
        self.assertNotEqual(dup.slug, self.b1.slug)

    def test_admin_assignment(self):
        self.assertIn(self.b1, self.ba1.managed_branches.all())
        self.assertNotIn(self.b2, self.ba1.managed_branches.all())


class PermissionTests(BaseCase):
    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse("church:members"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])

    def test_member_forbidden_from_staff_pages(self):
        self.client.force_login(self.member)
        for name in ("church:members", "church:events", "church:dashboard", "church:branches", "bible:list"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_branch_admin_forbidden_from_super_only_pages(self):
        self.client.force_login(self.ba1)
        for name in ("church:branches", "church:giving", "bible:list", "church:settings", "church:ministries"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_role_redirect(self):
        for user, target in ((self.sa, "church:dashboard"), (self.ba1, "church:branch_dashboard"),
                             (self.member, "church:member_dashboard")):
            self.client.force_login(user)
            self.assertRedirects(self.client.get(reverse("church:home")), reverse(target))

    def test_branch_admin_only_sees_own_members(self):
        Member.objects.create(full_name="Lagos Person", branch=self.b1)
        Member.objects.create(full_name="Abuja Person", branch=self.b2)
        self.client.force_login(self.ba1)
        html = self.client.get(reverse("church:members")).content.decode()
        self.assertIn("Lagos Person", html)
        self.assertNotIn("Abuja Person", html)

    def test_branch_admin_cannot_open_or_edit_other_branch_member(self):
        other = Member.objects.create(full_name="Abuja Person", branch=self.b2)
        self.client.force_login(self.ba1)
        self.assertEqual(self.client.get(reverse("church:member_detail", args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("church:member_edit", args=[other.pk]), {"full_name": "x"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("church:member_delete", args=[other.pk])).status_code, 404)

    def test_branch_admin_cannot_create_event_in_other_branch(self):
        self.client.force_login(self.ba1)
        resp = self.client.post(reverse("church:event_create"), {
            "title": "X", "start_at": "2030-01-01T10:00", "branch": self.b2.pk, "status": "confirmed",
            "kind": "service", "repeat": "none"})
        self.assertEqual(resp.status_code, 200)  # form re-rendered with an error
        self.assertFalse(Event.objects.filter(title="X").exists())

    def test_branch_admin_creates_event_in_own_branch(self):
        self.client.force_login(self.ba1)
        resp = self.client.post(reverse("church:event_create"), {
            "title": "Mine", "start_at": "2030-01-01T10:00", "branch": self.b1.pk, "status": "confirmed",
            "kind": "service", "repeat": "none"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Event.objects.get(title="Mine").branch, self.b1)

    def test_branch_admin_cannot_edit_global_announcement(self):
        a = Announcement.objects.create(title="Global", body="b", branch=None, is_published=True)
        self.client.force_login(self.ba1)
        self.assertEqual(self.client.get(reverse("church:announcement_edit", args=[a.pk])).status_code, 403)

    def test_super_admin_manages_branch_and_promotes_admin(self):
        self.client.force_login(self.sa)
        resp = self.client.post(reverse("church:branch_create"), {
            "name": "Accra", "is_active": "on", "admins": [self.member.pk]})
        self.assertEqual(resp.status_code, 302)
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, User.Role.BRANCH_ADMIN)
        self.assertEqual(Branch.objects.get(name="Accra").admins.count(), 1)


class WorkerApplicationTests(BaseCase):
    def apply(self, branch=None):
        return services.submit_worker_application(self.member, branch or self.b1, None, "I can serve well here.", "Sundays")

    def test_duplicate_pending_rejected(self):
        self.apply()
        with self.assertRaises(services.ApplicationError):
            self.apply()

    def test_approval_creates_single_assignment_and_promotes(self):
        app = self.apply()
        services.approve_application(app, self.ba1, "Welcome")
        app.refresh_from_db()
        self.member.refresh_from_db()
        self.assertEqual(app.status, "approved")
        self.assertEqual(app.reviewed_by, self.ba1)
        self.assertEqual(self.member.role, User.Role.WORKER)
        self.assertEqual(WorkerAssignment.objects.filter(user=self.member, branch=self.b1).count(), 1)

    def test_cannot_approve_twice(self):
        app = self.apply()
        services.approve_application(app, self.ba1)
        with self.assertRaises(services.ApplicationError):
            services.approve_application(app, self.ba1)
        self.assertEqual(WorkerAssignment.objects.filter(user=self.member).count(), 1)

    def test_reapply_after_approval_reuses_assignment(self):
        services.approve_application(self.apply(), self.ba1)
        WorkerAssignment.objects.filter(user=self.member).update(is_active=False)
        # not an active worker any more, so a new application is allowed and approval reactivates
        app2 = services.submit_worker_application(self.member, self.b1, None, "Applying again, thanks!")
        services.approve_application(app2, self.ba1)
        self.assertEqual(WorkerAssignment.objects.filter(user=self.member, branch=self.b1).count(), 1)
        self.assertTrue(WorkerAssignment.objects.get(user=self.member, branch=self.b1).is_active)

    def test_other_branch_admin_cannot_review(self):
        app = self.apply()
        with self.assertRaises(PermissionError):
            services.approve_application(app, self.ba2)

    def test_reject_notifies_applicant(self):
        app = self.apply()
        services.reject_application(app, self.ba1, "Not now")
        app.refresh_from_db()
        self.assertEqual(app.status, "rejected")
        self.assertEqual(services.notifications_for(self.member).filter(recipient=self.member).count(), 1)

    def test_views_enforce_branch_scope(self):
        app = self.apply(self.b1)
        self.client.force_login(self.ba2)
        self.assertEqual(self.client.post(reverse("church:application_approve", args=[app.pk])).status_code, 404)
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(reverse("church:application_approve", args=[app.pk])).status_code, 403)
        self.client.force_login(self.ba1)
        self.assertEqual(self.client.post(reverse("church:application_approve", args=[app.pk])).status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, "approved")

    def test_apply_page_creates_application_and_shows_status(self):
        self.client.force_login(self.member)
        resp = self.client.post(reverse("church:apply"), {
            "branch": self.b1.pk, "experience": "I have led choirs for many years.", "availability": ""})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("Pending", self.client.get(reverse("church:apply")).content.decode())

    def test_member_dashboard_has_apply_link(self):
        self.client.force_login(self.member)
        html = self.client.get(reverse("church:member_dashboard")).content.decode()
        self.assertIn("Apply to Become a Worker", html)


class PublicSiteTests(BaseCase):
    def test_public_pages_render(self):
        for name in ("core:home", "core:about", "core:contact", "core:new_here", "core:ministries", "core:gallery",
                     "core:locations", "core:give", "core:prayer", "core:praise", "core:devotionals", "core:events"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_only_confirmed_events_public(self):
        now = timezone.now() + timezone.timedelta(days=2)
        Event.objects.create(title="Visible", start_at=now, status="confirmed")
        Event.objects.create(title="Hidden draft", start_at=now, status="draft")
        html = self.client.get(reverse("core:events")).content.decode()
        self.assertIn("Visible", html)
        self.assertNotIn("Hidden draft", html)

    def test_prayer_form_saves(self):
        resp = self.client.post(reverse("core:prayer"), {"name": "Sam", "title": "Healing", "request": "Please pray"})
        self.assertEqual(resp.status_code, 302)
        from church.models import PrayerRequest
        self.assertTrue(PrayerRequest.objects.filter(title="Healing", status="pending").exists())

    def test_subscribe_no_duplicates(self):
        for _ in range(2):
            self.client.post(reverse("core:subscribe"), {"email": "Fan@Example.org"})
        from church.models import ContactMessage
        self.assertEqual(ContactMessage.objects.filter(kind="subscribe").count(), 1)


class BibleTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def upload(self, name="KJV", content=b'{"Genesis": {"1": {"1": "In the beginning"}}}', filename="k.json"):
        return self.client.post(reverse("bible:upload"), {"name": name, "file": SimpleUploadedFile(filename, content)})

    def test_only_super_admin_can_manage(self):
        for user in (self.member, self.ba1):
            self.client.force_login(user)
            self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(BibleTranslation.objects.count(), 0)

    def test_upload_valid_json_then_replace_then_delete(self):
        self.client.force_login(self.sa)
        self.upload()
        t = BibleTranslation.objects.get(name="KJV")
        self.assertGreater(t.size_in_bytes, 0)
        old_path = t.file.path
        self.client.post(reverse("bible:replace", args=[t.pk]), {
            "name": "KJV", "file": SimpleUploadedFile("n.json", b'{"a": 1}')})
        t.refresh_from_db()
        self.assertEqual(t.size_in_bytes, len(b'{"a": 1}'))
        self.client.post(reverse("bible:delete", args=[t.pk]))
        self.assertEqual(BibleTranslation.objects.count(), 0)

    def test_invalid_json_and_bad_names_rejected(self):
        self.client.force_login(self.sa)
        self.upload(content=b"{not json")
        self.upload(name="../evil", content=b"{}")
        self.upload(name="OK", content=b"{}", filename="x.txt")
        self.upload(name="EMPTY", content=b"{}")  # empty object is rejected
        self.assertEqual(BibleTranslation.objects.count(), 0)

    def test_duplicate_name_rejected_case_insensitive(self):
        self.client.force_login(self.sa)
        self.upload()
        self.upload(name="kjv")
        self.assertEqual(BibleTranslation.objects.count(), 1)

    @override_settings(BIBLE_MAX_UPLOAD_MB=0)
    def test_size_limit(self):
        self.client.force_login(self.sa)
        self.upload()
        self.assertEqual(BibleTranslation.objects.count(), 0)
