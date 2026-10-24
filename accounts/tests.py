from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from church.models import Branch, Member
from church.tests_helpers import make_user

User = get_user_model()


class ProfileSignalTests(TestCase):
    def test_profile_created_once(self):
        u = make_user("a@example.org")
        self.assertEqual(Profile.objects.filter(user=u).count(), 1)
        u.first_name = "Changed"
        u.save()
        self.assertEqual(Profile.objects.filter(user=u).count(), 1)

    def test_superuser_gets_super_admin_role(self):
        u = User.objects.create_superuser(username="root", email="root@example.org", password="x12345678!A")
        self.assertTrue(u.is_super_admin)
        self.assertEqual(u.role, User.Role.SUPER_ADMIN)


class AuthTests(TestCase):
    def test_login_with_email_case_insensitive(self):
        make_user("Grace@Example.org")
        self.assertTrue(self.client.login(username="grace@example.ORG", password="pass12345!Xy"))

    def test_registration_creates_member_profile_and_member_record(self):
        branch = Branch.objects.create(name="Lagos")
        resp = self.client.post(reverse("accounts:register"), {
            "first_name": "Ada", "last_name": "Obi", "email": "ada@example.org", "phone": "+2348000000",
            "branch": branch.pk, "password1": "Str0ng-pass-99", "password2": "Str0ng-pass-99"})
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(email="ada@example.org")
        self.assertEqual(user.role, User.Role.MEMBER)
        self.assertEqual(user.profile.phone, "+2348000000")
        self.assertEqual(Member.objects.get(user=user).branch, branch)

    def test_registration_cannot_choose_role(self):
        self.client.post(reverse("accounts:register"), {
            "first_name": "Eve", "last_name": "X", "email": "eve@example.org", "role": "super_admin",
            "password1": "Str0ng-pass-99", "password2": "Str0ng-pass-99"})
        self.assertEqual(User.objects.get(email="eve@example.org").role, User.Role.MEMBER)

    def test_duplicate_email_rejected(self):
        make_user("dup@example.org")
        resp = self.client.post(reverse("accounts:register"), {
            "first_name": "D", "last_name": "U", "email": "DUP@example.org",
            "password1": "Str0ng-pass-99", "password2": "Str0ng-pass-99"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(User.objects.filter(email__iexact="dup@example.org").count(), 1)

    def test_profile_page_cannot_change_role(self):
        u = make_user("m@example.org")
        self.client.force_login(u)
        self.client.post(reverse("accounts:profile"), {
            "u-first_name": "New", "u-last_name": "Name", "u-email": "m@example.org", "u-role": "super_admin",
            "p-phone": "123", "p-bio": ""})
        u.refresh_from_db()
        self.assertEqual(u.role, User.Role.MEMBER)
        self.assertEqual(u.first_name, "New")
