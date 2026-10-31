from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from church.storage import StoryMediaCloudinaryStorage

User = settings.AUTH_USER_MODEL


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Branch(TimeStamped):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True, help_text="Unique identifier used in URLs.")
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    description = models.TextField(blank=True)
    service_times = models.TextField(blank=True, help_text="One per line, e.g. 'Sunday 9:00 AM'.")
    is_active = models.BooleanField(default=True)
    admins = models.ManyToManyField(
        User, blank=True, related_name="managed_branches", help_text="Branch admins / heads of this branch."
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "branches"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:130] or "branch"
            slug, n = base, 2
            while Branch.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def service_time_lines(self):
        return [line.strip() for line in self.service_times.splitlines() if line.strip()]

    def __str__(self):
        return self.name


class Ministry(TimeStamped):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE, related_name="ministries",
                               help_text="Leave empty for a church-wide ministry.")
    leader = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="led_ministries")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "ministries"
        constraints = [
            models.UniqueConstraint(fields=["branch", "name"], name="uniq_ministry_name_per_branch"),
            models.UniqueConstraint(fields=["name"], condition=Q(branch__isnull=True), name="uniq_global_ministry_name"),
        ]

    def __str__(self):
        return self.name


class Pastor(TimeStamped):
    name = models.CharField(max_length=160)
    title = models.CharField(max_length=120, default="Pastor")
    bio = models.TextField(blank=True)
    # Kept as a fallback for portraits entered before image uploads were added.
    photo_url = models.URLField(blank=True)
    photo = models.ImageField(upload_to="pastors/", storage=StoryMediaCloudinaryStorage(), blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return f"{self.name} — {self.title}"


class Member(TimeStamped):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PENDING = "pending", "Pending"
        INACTIVE = "inactive", "Inactive"

    user = models.OneToOneField(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="member_record")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="members")
    full_name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    joined_on = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["full_name"]

    @property
    def role_label(self):
        if self.user_id:
            return self.user.get_role_display()
        return "Member"

    @property
    def initials(self):
        parts = [p for p in self.full_name.split() if p[:1].isalnum()]
        return "".join(p[0].upper() for p in parts[:2]) or "?"

    def __str__(self):
        return self.full_name


class WorkerAssignment(TimeStamped):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="worker_assignments")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="worker_assignments")
    ministry = models.ForeignKey(Ministry, null=True, blank=True, on_delete=models.SET_NULL, related_name="workers")
    title = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    started_on = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["branch__name", "user__first_name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "branch", "ministry"], condition=Q(ministry__isnull=False),
                                    name="uniq_worker_assignment_with_ministry"),
            models.UniqueConstraint(fields=["user", "branch"], condition=Q(ministry__isnull=True),
                                    name="uniq_worker_assignment_no_ministry"),
        ]

    def __str__(self):
        return f"{self.user} @ {self.branch}"


class WorkerApplication(TimeStamped):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    applicant = models.ForeignKey(User, on_delete=models.CASCADE, related_name="worker_applications")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="worker_applications")
    ministry = models.ForeignKey(Ministry, null=True, blank=True, on_delete=models.SET_NULL, related_name="applications")
    experience = models.TextField(help_text="Relevant experience or information.")
    availability = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    submitted_at = models.DateTimeField(default=timezone.now)
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_applications")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            # a person can only have one open application per branch
            models.UniqueConstraint(fields=["applicant", "branch"], condition=Q(status="pending"),
                                    name="uniq_pending_application_per_branch"),
        ]

    def __str__(self):
        return f"{self.applicant} → {self.branch} ({self.status})"


class Event(TimeStamped):
    class Kind(models.TextChoices):
        SERVICE = "service", "Service"
        STUDY = "study", "Bible study"
        PRAYER = "prayer", "Prayer"
        FELLOWSHIP = "fellowship", "Fellowship"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    class Repeat(models.TextChoices):
        NONE = "none", "Does not repeat"
        WEEKLY = "weekly", "Every week"
        MONTHLY = "monthly", "Every month"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE, related_name="events",
                               help_text="Leave empty for an event shown to every branch.")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.OTHER)
    location = models.CharField(max_length=200, blank=True)
    start_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField(null=True, blank=True)
    repeat = models.CharField(max_length=8, choices=Repeat.choices, default=Repeat.NONE)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["start_at"]
        constraints = [
            models.CheckConstraint(condition=Q(end_at__isnull=True) | Q(end_at__gte=models.F("start_at")),
                                   name="event_end_after_start"),
        ]

    def __str__(self):
        return self.title


class Rota(TimeStamped):
    """A service rota belongs to one scheduled service event."""
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name="rota")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="rotas")
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_rotas")

    class Meta:
        ordering = ["event__start_at"]

    def __str__(self):
        return f"{self.event.title} — {self.branch}"


class RotaPosition(TimeStamped):
    """One service function (for example Prayer or Projection) and its workers."""
    rota = models.ForeignKey(Rota, on_delete=models.CASCADE, related_name="positions")
    category = models.CharField(max_length=80, default="Service team")
    name = models.CharField(max_length=120)
    workers = models.ManyToManyField(WorkerAssignment, blank=True, related_name="rota_positions")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "category", "name"]

    def __str__(self):
        return f"{self.category}: {self.name}"


class Announcement(TimeStamped):
    title = models.CharField(max_length=200)
    body = models.TextField()
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE, related_name="announcements",
                               help_text="Leave empty to announce to everyone.")
    is_published = models.BooleanField(default=False)
    publish_at = models.DateTimeField(null=True, blank=True)
    is_pinned = models.BooleanField(default=False)
    author = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-is_pinned", "-publish_at", "-created_at"]

    @property
    def is_live(self):
        return self.is_published and (self.publish_at is None or self.publish_at <= timezone.now())

    @property
    def state(self):
        if not self.is_published:
            return "draft"
        return "published" if self.is_live else "scheduled"

    def __str__(self):
        return self.title


class Devotional(TimeStamped):
    title = models.CharField(max_length=200)
    scripture_ref = models.CharField(max_length=120, blank=True, help_text="e.g. Hebrews 11:1")
    scripture_text = models.TextField(blank=True)
    body = models.TextField()
    date = models.DateField(default=timezone.localdate, db_index=True)
    author = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_published = models.BooleanField(default=False)

    class Meta:
        ordering = ["-date"]

    @property
    def read_minutes(self):
        return max(1, round(len((self.body or "").split()) / 200))

    @property
    def state(self):
        if not self.is_published:
            return "draft"
        return "scheduled" if self.date > timezone.localdate() else "published"

    def __str__(self):
        return self.title


class Notification(TimeStamped):
    class Audience(models.TextChoices):
        ALL = "all", "All members"
        BRANCH = "branch", "A branch"
        WORKERS = "workers", "Workers"
        USER = "user", "One person"

    title = models.CharField(max_length=80)
    message = models.CharField(max_length=140)
    audience = models.CharField(max_length=8, choices=Audience.choices, default=Audience.ALL)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    recipient = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="direct_notifications")
    send_at = models.DateTimeField(default=timezone.now, help_text="Future dates are scheduled.")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-send_at"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(audience="branch") | Q(branch__isnull=False), name="notification_branch_required"),
            models.CheckConstraint(
                condition=~Q(audience="user") | Q(recipient__isnull=False), name="notification_recipient_required"),
        ]

    @property
    def is_sent(self):
        return self.send_at <= timezone.now()

    def __str__(self):
        return self.title


class NotificationRead(models.Model):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["notification", "user"], name="uniq_notification_read")]


class PrayerRequest(TimeStamped):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In progress"
        ANSWERED = "answered", "Answered"

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="prayer_requests")
    name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    title = models.CharField(max_length=200)
    request = models.TextField()
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="prayer_requests")
    is_public = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    assigned_to = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_prayers")

    class Meta:
        ordering = ["-created_at"]

    @property
    def author_name(self):
        return self.name or (self.user.display_name if self.user_id else "Anonymous")

    def __str__(self):
        return self.title


class PraiseReport(TimeStamped):
    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting review"
        PUBLISHED = "published", "Published"
        DECLINED = "declined", "Declined"

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="praise_reports")
    name = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=60, blank=True, help_text="e.g. Healing, Provision")
    story = models.TextField()
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="praise_reports")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def author_name(self):
        return self.name or (self.user.display_name if self.user_id else "Anonymous")

    def __str__(self):
        return f"{self.category or 'Praise'} · {self.author_name}"


class GivingRecord(TimeStamped):
    class Fund(models.TextChoices):
        TITHE = "tithe", "Tithes"
        OFFERING = "offering", "Offering"
        BUILDING = "building", "Building fund"
        MISSIONS = "missions", "Missions"
        OTHER = "other", "Other"

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="giving_records")
    donor_name = models.CharField(max_length=120, blank=True)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="giving_records")
    fund = models.CharField(max_length=10, choices=Fund.choices, default=Fund.OFFERING)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency = models.CharField(max_length=3, default="NGN")
    method = models.CharField(max_length=40, blank=True)
    reference = models.CharField(max_length=80, blank=True)
    given_on = models.DateField(default=timezone.localdate, db_index=True)

    class Meta:
        ordering = ["-given_on", "-created_at"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="giving_amount_positive")]

    @property
    def giver(self):
        return self.donor_name or (self.user.display_name if self.user_id else "Anonymous")

    def __str__(self):
        return f"{self.giver}: {self.amount} {self.currency}"


class Story(TimeStamped):
    title = models.CharField(max_length=120)
    caption = models.CharField(max_length=240, blank=True)
    media = models.FileField(
        upload_to="stories/",
        storage=StoryMediaCloudinaryStorage(),
        blank=True,
    )
    is_video = models.BooleanField(default=False)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE, related_name="stories")
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        verbose_name_plural = "stories"

    @property
    def expires_at(self):
        return self.published_at + timezone.timedelta(hours=24) if self.published_at else None

    @property
    def is_live(self):
        return bool(self.is_published and self.expires_at and self.expires_at > timezone.now())

    def __str__(self):
        return self.title


class ContactMessage(TimeStamped):
    class Kind(models.TextChoices):
        CONTACT = "contact", "Contact"
        VISIT = "visit", "Plan a visit"
        SUBSCRIBE = "subscribe", "Newsletter"

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CONTACT)
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages")
    subject = models.CharField(max_length=160, blank=True)
    message = models.TextField(blank=True)
    handled = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} from {self.name}"



class Note(TimeStamped):
    class Category(models.TextChoices):
        SERMON = "sermon", "Sermon"
        DEVOTION = "devotion", "Devotion"
        PRAYER = "prayer", "Prayer"
        PERSONAL = "personal", "Personal"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="personal_notes",
    )

    title = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )

    body = models.TextField(blank=True, default="")

    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.SERMON,
        db_index=True,
    )

    scripture = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )

    is_pinned = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-is_pinned", "-updated_at"]
        verbose_name = "Note"
        verbose_name_plural = "Notes"
        indexes = [
            models.Index(
                fields=["user", "-updated_at"],
                name="note_user_updated_idx",
            ),
            models.Index(
                fields=["user", "category"],
                name="note_user_category_idx",
            ),
        ]

    def __str__(self):
        return self.title or "Untitled note"
