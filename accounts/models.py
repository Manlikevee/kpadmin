from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user. Email is unique and may be used to sign in."""

    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        BRANCH_ADMIN = "branch_admin", "Branch Admin"
        WORKER = "worker", "Worker"
        MEMBER = "member", "Member"

    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER, db_index=True)

    class Meta:
        ordering = ["first_name", "last_name", "email"]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        if self.is_superuser:
            self.role = self.Role.SUPER_ADMIN
        super().save(*args, **kwargs)

    # --- role helpers -----------------------------------------------------
    @property
    def is_super_admin(self):
        return self.is_superuser or self.role == self.Role.SUPER_ADMIN

    @property
    def is_branch_admin(self):
        return self.role == self.Role.BRANCH_ADMIN

    @property
    def is_worker(self):
        return self.role == self.Role.WORKER

    @property
    def is_staff_role(self):
        """Super admins and branch admins manage content in the dashboard."""
        return self.is_super_admin or self.is_branch_admin

    def has_role(self, *roles):
        """True if the user holds one of ``roles``. Super admins pass every check."""
        if self.is_super_admin:
            return True
        return self.role in roles

    @property
    def display_name(self):
        return self.get_full_name().strip() or self.username

    @property
    def initials(self):
        parts = [p for p in self.display_name.replace("@", " ").split() if p[:1].isalnum()]
        return "".join(p[0].upper() for p in parts[:2]) or "?"

    def __str__(self):
        return self.display_name


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=24, blank=True)
    image = models.ImageField(upload_to="profiles/", blank=True)
    bio = models.CharField(max_length=300, blank=True , null=True)
    location = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user}"
