"""Serializers for the admin / management part of the mobile API."""
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from accounts.access import branches_for
from bible.models import BibleTranslation
from church.models import Branch, GivingRecord, Notification, PraiseReport, PrayerRequest
from core.models import SiteSettings
from push_notifications.models import DevicePushToken
from sermons.models import SermonNote

from .serializers import BibleVersionSerializer, ManagedBranchField

User = get_user_model()


# ------------------------------------------------------------------- users
class AdminUserSerializer(serializers.ModelSerializer):
    """Light user record for pickers (assign a worker, a prayer, a branch admin)."""

    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = ("id", "display_name", "email", "role", "role_display", "is_active")
        read_only_fields = fields


# ------------------------------------------------------------------ prayer
class PrayerRequestAdminSerializer(serializers.ModelSerializer):
    """Everything about a prayer request; only ``status`` and ``assigned_to`` can be changed."""

    author_name = serializers.CharField(read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)
    assigned_to = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), required=False,
                                                     allow_null=True)
    assigned_to_name = serializers.CharField(source="assigned_to.display_name", read_only=True, default=None)

    class Meta:
        model = PrayerRequest
        fields = ("id", "title", "request", "author_name", "name", "email", "user", "branch", "branch_name",
                  "is_public", "status", "assigned_to", "assigned_to_name", "created_at", "updated_at")
        read_only_fields = ("id", "title", "request", "name", "email", "user", "branch", "is_public",
                            "created_at", "updated_at")

    def update(self, instance, validated):
        if "status" in validated:
            instance.status = validated["status"]
        if "assigned_to" in validated:
            instance.assigned_to = validated["assigned_to"]
            # same rule as the dashboard: picking someone moves a pending request along
            if validated["assigned_to"] and instance.status == PrayerRequest.Status.PENDING:
                instance.status = PrayerRequest.Status.IN_PROGRESS
        instance.save()
        return instance


# ------------------------------------------------------------------ praise
class PraiseReportSerializer(serializers.ModelSerializer):
    """What members and the public see. ``status`` can't be set from here."""

    author_name = serializers.CharField(read_only=True)
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True), required=False,
                                                allow_null=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)

    class Meta:
        model = PraiseReport
        fields = ("id", "author_name", "name", "category", "story", "branch", "branch_name", "status",
                  "created_at")
        read_only_fields = ("id", "status", "created_at")
        extra_kwargs = {"name": {"required": False}, "story": {"max_length": 5000}}

    def validate_story(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Please share your praise report.")
        return value


class PraiseReportAdminSerializer(PraiseReportSerializer):
    """Super admins: any branch, writable ``status``, and the submitting user."""

    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.all(), required=False, allow_null=True)

    class Meta(PraiseReportSerializer.Meta):
        fields = PraiseReportSerializer.Meta.fields + ("user",)
        read_only_fields = ("id", "user", "created_at")


# ------------------------------------------------------------------ giving
class GivingRecordSerializer(serializers.ModelSerializer):
    branch = ManagedBranchField(queryset=Branch.objects.all(), required=False, allow_null=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)
    giver = serializers.CharField(read_only=True)
    fund_display = serializers.CharField(source="get_fund_display", read_only=True)

    class Meta:
        model = GivingRecord
        fields = ("id", "donor_name", "giver", "user", "amount", "currency", "fund", "fund_display", "method",
                  "reference", "given_on", "branch", "branch_name", "created_at")
        read_only_fields = ("id", "user", "created_at")

    def validate_currency(self, value):
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError("Use a 3-letter currency code, e.g. NGN.")
        return value


# --------------------------------------------------------------- settings
class SiteSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteSettings
        fields = ("church_name", "tagline", "contact_email", "contact_phone", "address", "give_instructions",
                  "updated_at")
        read_only_fields = ("updated_at",)


# ------------------------------------------------------------------- bible
class BibleTranslationAdminSerializer(BibleVersionSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.display_name", read_only=True, default=None)

    class Meta:
        model = BibleTranslation
        fields = ("id", "name", "size", "size_in_bytes", "url", "file_name", "uploaded_by", "uploaded_by_name",
                  "created_at", "updated_at")
        read_only_fields = fields


# ----------------------------------------------------------------- sermons
class SermonNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = SermonNote
        fields = ("speaker", "series", "notes", "is_featured", "is_hidden", "updated_at")
        read_only_fields = ("updated_at",)


# ------------------------------------------------------------ notifications
class NotificationAdminSerializer(serializers.ModelSerializer):
    """In-app notifications (scheduled or sent immediately). Same rules as the dashboard form."""

    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.all(), required=False, allow_null=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)
    audience_display = serializers.CharField(source="get_audience_display", read_only=True)
    created_by_name = serializers.CharField(source="created_by.display_name", read_only=True, default=None)
    is_sent = serializers.BooleanField(read_only=True)
    send_at = serializers.DateTimeField(required=False)

    class Meta:
        model = Notification
        fields = ("id", "title", "message", "audience", "audience_display", "branch", "branch_name", "send_at",
                  "is_sent", "created_by_name", "created_at")
        read_only_fields = ("id", "created_at")
        # required, so the per-user checks in validate_audience can't be skipped by omitting it
        extra_kwargs = {"audience": {"required": True}}

    def validate_audience(self, value):
        user = self.context["request"].user
        if value == Notification.Audience.USER:
            raise serializers.ValidationError("Choose all, branch or workers.")
        if value == Notification.Audience.ALL and not user.is_super_admin:
            raise serializers.ValidationError("Only super admins can notify everyone.")
        return value

    def validate_branch(self, value):
        if value is not None and not branches_for(self.context["request"].user).filter(pk=value.pk).exists():
            raise serializers.ValidationError("You don't manage that branch.")
        return value

    def validate(self, attrs):
        user = self.context["request"].user
        branch = attrs.get("branch")
        if attrs.get("audience") == Notification.Audience.BRANCH and not branch:
            raise serializers.ValidationError({"branch": "Choose which branch should receive this."})
        if not user.is_super_admin and not branch:
            raise serializers.ValidationError({"branch": "Choose one of your branches."})
        attrs.setdefault("send_at", timezone.now())
        return attrs


# -------------------------------------------------------------------- push
class PushDeviceSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.display_name", read_only=True)
    token_preview = serializers.SerializerMethodField()

    class Meta:
        model = DevicePushToken
        fields = ("id", "user", "user_name", "platform", "token_preview", "created_at", "updated_at")
        read_only_fields = fields

    def get_token_preview(self, obj):
        return "…" + obj.token.rstrip("]")[-6:]  # never hand full device tokens to a client


class PushRecipientSerializer(serializers.ModelSerializer):
    device_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = ("id", "display_name", "email", "device_count")
        read_only_fields = fields


class PushSendSerializer(serializers.Serializer):
    TARGETS = (("all", "All registered users"), ("selected", "Selected users"))

    title = serializers.CharField(max_length=100)
    message = serializers.CharField(max_length=500)
    target = serializers.ChoiceField(choices=TARGETS, default="selected")
    users = serializers.PrimaryKeyRelatedField(
        many=True, required=False,
        queryset=User.objects.filter(pk__in=DevicePushToken.objects.values("user_id")))

    def validate(self, attrs):
        if attrs["target"] == "selected" and not attrs.get("users"):
            raise serializers.ValidationError(
                {"users": "Select at least one registered user, or use target \"all\"."})
        return attrs
