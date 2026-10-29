import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from accounts.access import branches_for
from accounts import codes
from accounts.models import Profile
from accounts.services import create_member_account
from bible.models import BibleTranslation
from church import services
from church.models import (Announcement, Branch, Devotional, Event, Member, Ministry, Notification,
                           PrayerRequest, WorkerApplication, WorkerAssignment, Story, Note)

User = get_user_model()

USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{3,24}$")


def clean_username(value, exclude_pk=None):
    value = (value or "").strip()
    if not value:
        return ""
    if not USERNAME_RE.match(value):
        raise serializers.ValidationError("Use 3-24 letters, numbers, dots or underscores.")
    qs = User.objects.filter(username__iexact=value)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists() or User.objects.filter(email__iexact=value).exclude(pk=exclude_pk or 0).exists():
        raise serializers.ValidationError("That username is already taken.")
    return value


def member_id(user):
    return f"KP-{user.pk:06d}"


class ManagedBranchField(serializers.PrimaryKeyRelatedField):
    """Only branches the requesting user manages can be written."""

    def get_queryset(self):
        request = self.context.get("request")
        return branches_for(request.user) if request and request.user.is_authenticated else Branch.objects.none()


# ------------------------------------------------------------------- auth
class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Sign in with ``email`` + ``password`` (``username`` also accepted)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"] = serializers.CharField(write_only=True, required=False)
        self.fields["username"].required = False

    def validate(self, attrs):
        identifier = attrs.get("email") or attrs.get("username")
        if not identifier:
            raise serializers.ValidationError({"email": "This field is required."})
        attrs["username"] = identifier
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user, context=self.context).data
        return data


class RegisterSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    phone = serializers.CharField(max_length=24, required=False, allow_blank=True)
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True), required=False,
                                                allow_null=True)
    username = serializers.CharField(required=False, allow_blank=True)
    location = serializers.CharField(max_length=100, required=False, allow_blank=True)
    email_token = serializers.CharField(write_only=True, required=False, allow_blank=True)

    def validate_username(self, value):
        return clean_username(value)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()

    def validate(self, attrs):
        token = attrs.pop("email_token", "")
        if settings.REQUIRE_EMAIL_VERIFICATION:
            data = codes.read_token("signup", token) if token else None
            if not data or data["e"] != attrs["email"]:
                raise serializers.ValidationError({"email_token": "Please verify your email address first."})
        probe = User(email=attrs["email"], first_name=attrs["first_name"], last_name=attrs["last_name"])
        try:
            validate_password(attrs["password"], probe)
        except Exception as exc:
            raise serializers.ValidationError({"password": list(getattr(exc, "messages", [str(exc)]))})
        return attrs

    def create(self, validated):
        return create_member_account(**validated)


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ("phone", "image", "bio", "location")


class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = ("id", "username", "email", "first_name", "last_name", "role", "role_display", "profile")
        read_only_fields = ("id", "username", "role", "role_display")


class MeSerializer(serializers.ModelSerializer):
    """Profile editing: names, email and profile fields. Role is never writable."""

    phone = serializers.CharField(source="profile.phone", required=False, allow_blank=True, max_length=24)
    bio = serializers.CharField(source="profile.bio", required=False, allow_blank=True, max_length=300)
    image = serializers.ImageField(source="profile.image", required=False, allow_null=True)
    location = serializers.CharField(source="profile.location", required=False, allow_blank=True, max_length=100)
    username = serializers.CharField(required=False, allow_blank=True)
    member_id = serializers.SerializerMethodField()
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    managed_branches = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "member_id", "username", "email", "first_name", "last_name", "role", "role_display",
                  "phone", "bio", "image", "location", "date_joined", "managed_branches")
        read_only_fields = ("id", "role", "date_joined")

    def get_member_id(self, obj):
        return member_id(obj)

    def validate_username(self, value):
        return clean_username(value, exclude_pk=self.instance.pk) or self.instance.username

    def get_managed_branches(self, obj):
        return list(branches_for(obj).values_list("pk", flat=True))

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("Another account already uses this email.")
        return value

    def update(self, instance, validated):
        profile_data = validated.pop("profile", {})
        old_email = instance.email
        for k, v in validated.items():
            setattr(instance, k, v)
        if "email" in validated and "username" not in validated and instance.username.lower() == old_email.lower():
            instance.username = instance.email  # username followed the email; keep it that way
        instance.save()
        profile = instance.profile
        for k, v in profile_data.items():
            setattr(profile, k, v)
        profile.save()
        return instance


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context["request"].user)
        return value


# --------------------------------------------------------------- church data
class BranchSerializer(serializers.ModelSerializer):
    service_time_lines = serializers.ListField(read_only=True)
    admins = serializers.PrimaryKeyRelatedField(many=True, queryset=User.objects.filter(is_active=True), required=False)

    class Meta:
        model = Branch
        fields = ("id", "name", "slug", "address", "city", "country", "latitude", "longitude", "phone", "email",
                  "description", "service_times", "service_time_lines", "is_active", "admins", "created_at", "updated_at")
        read_only_fields = ("slug", "created_at", "updated_at")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if not (request and request.user.is_authenticated and request.user.is_staff_role):
            data.pop("admins", None)  # don't expose staff ids to the public
        return data

    @transaction.atomic
    def create(self, validated):
        branch = super().create(validated)
        services.sync_branch_admin_roles(branch)
        return branch

    @transaction.atomic
    def update(self, instance, validated):
        previous = set(instance.admins.values_list("pk", flat=True))
        branch = super().update(instance, validated)
        services.sync_branch_admin_roles(branch, previous)
        return branch


class MinistrySerializer(serializers.ModelSerializer):
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.all(), required=False, allow_null=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)
    leader = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), required=False,
                                                allow_null=True)
    leader_name = serializers.CharField(source="leader.display_name", read_only=True, default=None)
    worker_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Ministry
        fields = ("id", "name", "description", "branch", "branch_name", "leader", "leader_name", "is_active",
                  "worker_count", "created_at")
        read_only_fields = ("created_at",)
        validators = []  # the DB constraints are conditional; checked in validate()

    def validate(self, attrs):
        name = attrs.get("name", getattr(self.instance, "name", None))
        branch = attrs.get("branch", getattr(self.instance, "branch", None))
        if name:
            dupes = Ministry.objects.filter(branch=branch, name__iexact=name.strip())
            if self.instance:
                dupes = dupes.exclude(pk=self.instance.pk)
            if dupes.exists():
                raise serializers.ValidationError({"name": "A ministry with this name already exists here."})
        return attrs


class MemberSerializer(serializers.ModelSerializer):
    branch = ManagedBranchField(queryset=Branch.objects.all(), required=False, allow_null=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)

    class Meta:
        model = Member
        fields = ("id", "user", "full_name", "email", "phone", "branch", "branch_name", "status", "joined_on",
                  "notes", "created_at")
        read_only_fields = ("user", "created_at")

    def validate_branch(self, value):
        if value is None and not self.context["request"].user.is_super_admin:
            raise serializers.ValidationError("A branch is required.")
        return value


class WorkerAssignmentSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True))
    branch = ManagedBranchField(queryset=Branch.objects.all())
    ministry = serializers.PrimaryKeyRelatedField(queryset=Ministry.objects.filter(is_active=True), required=False,
                                                  allow_null=True)
    user_name = serializers.CharField(source="user.display_name", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    ministry_name = serializers.CharField(source="ministry.name", read_only=True, default=None)

    class Meta:
        model = WorkerAssignment
        fields = ("id", "user", "user_name", "user_email", "branch", "branch_name", "ministry", "ministry_name",
                  "title", "is_active", "started_on")
        read_only_fields = ("started_on",)
        validators = []  # uniqueness is handled with update_or_create below

    def validate(self, attrs):
        inst = self.instance
        if inst:
            for field in ("user", "branch"):
                if field in attrs and attrs[field] != getattr(inst, field):
                    raise serializers.ValidationError({field: "Cannot be changed. Create a new assignment instead."})
        branch = attrs.get("branch") or (inst.branch if inst else None)
        ministry = attrs.get("ministry", inst.ministry if inst else None)
        if branch and ministry and ministry.branch_id not in (None, branch.pk):
            raise serializers.ValidationError({"ministry": "That ministry belongs to a different branch."})
        if inst and "ministry" in attrs:
            clash = WorkerAssignment.objects.filter(user=inst.user, branch=inst.branch, ministry=ministry)
            if clash.exclude(pk=inst.pk).exists():
                raise serializers.ValidationError({"ministry": "This person already has that assignment."})
        return attrs

    def create(self, validated):
        # never duplicate an existing assignment (same as the dashboard form)
        assignment, _ = WorkerAssignment.objects.update_or_create(
            user=validated["user"], branch=validated["branch"], ministry=validated.get("ministry"),
            defaults={"title": validated.get("title", ""), "is_active": validated.get("is_active", True)})
        person = validated["user"]
        if person.role == User.Role.MEMBER:
            person.role = User.Role.WORKER
            person.save(update_fields=["role"])
        return assignment


class WorkerApplicationSerializer(serializers.ModelSerializer):
    applicant_name = serializers.CharField(source="applicant.display_name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    ministry_name = serializers.CharField(source="ministry.name", read_only=True, default=None)
    reviewed_by_name = serializers.CharField(source="reviewed_by.display_name", read_only=True, default=None)
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    ministry = serializers.PrimaryKeyRelatedField(queryset=Ministry.objects.filter(is_active=True),
                                                  required=False, allow_null=True)

    class Meta:
        model = WorkerApplication
        fields = ("id", "applicant", "applicant_name", "branch", "branch_name", "ministry", "ministry_name",
                  "experience", "availability", "status", "submitted_at", "reviewed_by", "reviewed_by_name",
                  "reviewed_at", "review_note")
        read_only_fields = ("applicant", "status", "submitted_at", "reviewed_by", "reviewed_at", "review_note")

    def validate_experience(self, value):
        if len(value.strip()) < 20:
            raise serializers.ValidationError("Please write at least 20 characters.")
        return value

    def create(self, validated):
        try:
            return services.submit_worker_application(
                self.context["request"].user, validated["branch"], validated.get("ministry"),
                validated["experience"], validated.get("availability", ""))
        except services.ApplicationError as exc:
            raise serializers.ValidationError({"detail": str(exc)})


class ReviewSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class EventSerializer(serializers.ModelSerializer):
    branch = ManagedBranchField(queryset=Branch.objects.all(), required=False, allow_null=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)

    class Meta:
        model = Event
        fields = ("id", "title", "description", "branch", "branch_name", "kind", "location", "start_at", "end_at",
                  "repeat", "capacity", "status")

    def validate_branch(self, value):
        if value is None and not self.context["request"].user.is_super_admin:
            raise serializers.ValidationError("A branch is required.")
        return value

    def validate(self, attrs):
        start = attrs.get("start_at", getattr(self.instance, "start_at", None))
        end = attrs.get("end_at", getattr(self.instance, "end_at", None))
        if start and end and end < start:
            raise serializers.ValidationError({"end_at": "End must be after the start."})
        return attrs


class AnnouncementSerializer(serializers.ModelSerializer):
    branch = ManagedBranchField(queryset=Branch.objects.all(), required=False, allow_null=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)

    class Meta:
        model = Announcement
        fields = ("id", "title", "body", "branch", "branch_name", "is_published", "publish_at", "is_pinned",
                  "created_at")
        read_only_fields = ("created_at",)

    def validate_branch(self, value):
        if value is None and not self.context["request"].user.is_super_admin:
            raise serializers.ValidationError("A branch is required.")
        return value


class DevotionalSerializer(serializers.ModelSerializer):
    read_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Devotional
        fields = ("id", "title", "scripture_ref", "scripture_text", "body", "date", "is_published", "read_minutes")


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ("id", "title", "message", "audience", "branch", "send_at", "is_read")

    def get_is_read(self, obj):
        return obj.pk in self.context.get("read_ids", set())


class BibleVersionSerializer(serializers.ModelSerializer):
    """Matches the legacy record shape: name, size, size_in_bytes, url."""

    size = serializers.CharField(read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = BibleTranslation
        fields = ("name", "size", "size_in_bytes", "url")

    def get_url(self, obj):
        request = self.context.get("request")
        return request.build_absolute_uri(obj.url) if request and obj.url else obj.url


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class CodeVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.RegexField(r"^\d{6}$", error_messages={"invalid": "Enter the 6-digit code."})


class PasswordResetConfirmSerializer(serializers.Serializer):
    reset_token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)


class PrayerRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrayerRequest
        fields = ("id", "name", "request", "is_public", "status", "created_at")
        read_only_fields = ("id", "status", "created_at")
        extra_kwargs = {"request": {"max_length": 2000}, "name": {"required": False}}

    def validate_request(self, value):
        if not value.strip():
            raise serializers.ValidationError("Please write your prayer request.")
        return value.strip()




class StorySerializer(serializers.ModelSerializer):
    branch = ManagedBranchField(queryset=Branch.objects.all(), required=False, allow_null=True)
    branch_name = serializers.CharField(
        source="branch.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = Story
        fields = [
            "id",
            "title",
            "caption",
            "media",
            "is_video",
            "branch",
            "branch_name",
            "is_published",
            "published_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "published_at",
            "created_at",
        ]

    def validate_branch(self, value):
        if value is None and not self.context["request"].user.is_super_admin:
            raise serializers.ValidationError("A branch is required.")
        return value

    def validate_media(self, value):
        if value and value.size > 100 * 1024 * 1024:
            raise serializers.ValidationError(
                "Story media must be 100 MB or smaller."
            )
        return value

    def validate(self, attrs):
        # same rule as the dashboard: stamp the publish time once, clear it when unpublished
        published = attrs.get("is_published", getattr(self.instance, "is_published", False))
        current = getattr(self.instance, "published_at", None)
        attrs["published_at"] = (current or timezone.now()) if published else None
        return attrs


class NoteSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(
        source="get_category_display",
        read_only=True,
    )

    class Meta:
        model = Note
        fields = [
            "id",
            "title",
            "body",
            "category",
            "category_label",
            "scripture",
            "is_pinned",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "category_label",
            "created_at",
            "updated_at",
        ]

    def validate_category(self, value):
        valid_categories = Note.Category.values

        if value not in valid_categories:
            raise serializers.ValidationError(
                "Select a valid note category."
            )

        return value