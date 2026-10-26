from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.access import branches_for

from .models import (Announcement, Branch, Devotional, Event, GivingRecord, Member, Ministry,
                     Notification, PraiseReport, Story, WorkerApplication, WorkerAssignment, Note)

User = get_user_model()

DT_FORMAT = "%Y-%m-%dT%H:%M"
DT_ATTRS = {"type": "datetime-local"}


def dt_field(required=False, label=None):
    return forms.DateTimeField(
        required=required, label=label,
        widget=forms.DateTimeInput(attrs=DT_ATTRS, format=DT_FORMAT),
        input_formats=[DT_FORMAT, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"],
    )


def date_field(required=True, label=None):
    return forms.DateField(required=required, label=label,
                           widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))


class ScopedForm(forms.ModelForm):
    """Limits the ``branch`` choices to what the signed-in user may manage.

    Because the queryset is restricted, a tampered POST naming another branch
    fails normal ModelChoiceField validation.
    """

    side_fields = ()  # rendered in the sidebar card of the form template

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if "branch" in self.fields and user is not None:
            field = self.fields["branch"]
            field.queryset = branches_for(user)
            if user.is_super_admin:
                field.empty_label = "All branches"
                field.required = False
            else:
                field.empty_label = None
                field.required = True

    @property
    def main_fields(self):
        return [self[n] for n in self.fields if n not in self.side_fields]

    @property
    def side_bound_fields(self):
        return [self[n] for n in self.side_fields if n in self.fields]


class BranchForm(forms.ModelForm):
    admins = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(), required=False, label="Branch administrator(s)",
        widget=forms.SelectMultiple(attrs={"size": 4}),
        help_text="Hold Ctrl/Cmd to select more than one.")

    class Meta:
        model = Branch
        fields = ("name", "address", "city", "country", "phone", "email", "description",
                  "service_times", "admins", "is_active")
        widgets = {"description": forms.Textarea(attrs={"rows": 3}), "service_times": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["admins"].queryset = User.objects.filter(is_active=True).order_by("first_name", "email")
        self.fields["admins"].label_from_instance = lambda u: f"{u.display_name} ({u.email})"

    def save(self, commit=True):
        previous = set(self.instance.admins.values_list("pk", flat=True)) if self.instance.pk else set()
        branch = super().save(commit=commit)
        if commit:
            current = set(branch.admins.values_list("pk", flat=True))
            for user in User.objects.filter(pk__in=current, role__in=[User.Role.MEMBER, User.Role.WORKER]):
                user.role = User.Role.BRANCH_ADMIN
                user.save(update_fields=["role"])
            for user in User.objects.filter(pk__in=previous - current, role=User.Role.BRANCH_ADMIN):
                if not user.managed_branches.exists():  # no longer manages anything
                    user.role = User.Role.WORKER if user.worker_assignments.filter(is_active=True).exists() else User.Role.MEMBER
                    user.save(update_fields=["role"])
        return branch


class MemberForm(ScopedForm):
    side_fields = ("status",)

    class Meta:
        model = Member
        fields = ("full_name", "email", "phone", "branch", "joined_on", "notes", "status")
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    joined_on = date_field(label="Joined on")


class MinistryForm(ScopedForm):
    side_fields = ("is_active",)

    class Meta:
        model = Ministry
        fields = ("name", "description", "branch", "leader", "is_active")
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["leader"].queryset = User.objects.filter(is_active=True).order_by("first_name", "email")
        self.fields["leader"].label_from_instance = lambda u: u.display_name


class EventForm(ScopedForm):
    side_fields = ("status", "kind", "repeat")
    start_at = dt_field(required=True, label="Starts")
    end_at = dt_field(label="Ends (optional)")

    class Meta:
        model = Event
        fields = ("title", "start_at", "end_at", "location", "branch", "description", "capacity",
                  "status", "kind", "repeat")
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class AnnouncementForm(ScopedForm):
    side_fields = ("is_published", "is_pinned", "publish_at")
    publish_at = dt_field(label="Publish at (optional)")

    class Meta:
        model = Announcement
        fields = ("title", "body", "branch", "is_published", "is_pinned", "publish_at")
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}


class DevotionalForm(forms.ModelForm):
    side_fields = ("date", "is_published")
    date = date_field(label="Date")

    class Meta:
        model = Devotional
        fields = ("title", "scripture_ref", "scripture_text", "body", "date", "is_published")
        widgets = {"scripture_text": forms.Textarea(attrs={"rows": 2}), "body": forms.Textarea(attrs={"rows": 8})}

    @property
    def main_fields(self):
        return [self[n] for n in self.fields if n not in self.side_fields]

    @property
    def side_bound_fields(self):
        return [self[n] for n in self.side_fields]


class PraiseForm(ScopedForm):
    side_fields = ("status",)

    class Meta:
        model = PraiseReport
        fields = ("name", "category", "story", "branch", "status")
        widgets = {"story": forms.Textarea(attrs={"rows": 6})}


class StoryForm(ScopedForm):
    side_fields = ("is_video", "is_published")

    class Meta:
        model = Story
        fields = ("title", "caption", "media", "branch", "is_video", "is_published")


class GivingForm(ScopedForm):
    side_fields = ("fund", "currency")
    given_on = date_field(label="Date given")

    class Meta:
        model = GivingRecord
        fields = ("donor_name", "amount", "given_on", "branch", "method", "reference", "fund", "currency")


class WorkerAssignmentForm(forms.ModelForm):
    """Super admins / branch admins add a worker directly (no application)."""

    user = forms.ModelChoiceField(queryset=User.objects.none(), label="Person")

    class Meta:
        model = WorkerAssignment
        fields = ("user", "branch", "ministry", "title", "is_active")

    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        self.fields["user"].queryset = User.objects.filter(is_active=True).order_by("first_name", "email")
        self.fields["user"].label_from_instance = lambda u: f"{u.display_name} ({u.email})"
        self.fields["branch"].queryset = branches_for(acting_user)
        self.fields["ministry"].queryset = Ministry.objects.filter(is_active=True)
        self.fields["ministry"].required = False
        self.fields["title"].label = "Responsibility"

    def clean(self):
        data = super().clean()
        branch, ministry = data.get("branch"), data.get("ministry")
        if branch and ministry and ministry.branch_id not in (None, branch.pk):
            self.add_error("ministry", "That ministry belongs to a different branch.")
        return data

    def save(self, commit=True):
        # update_or_create semantics: never duplicate an existing assignment
        d = self.cleaned_data
        assignment, _ = WorkerAssignment.objects.update_or_create(
            user=d["user"], branch=d["branch"], ministry=d.get("ministry"),
            defaults={"title": d.get("title", ""), "is_active": d.get("is_active", True)})
        person = d["user"]
        if person.role == User.Role.MEMBER:
            person.role = User.Role.WORKER
            person.save(update_fields=["role"])
        return assignment


class WorkerApplicationForm(forms.ModelForm):
    class Meta:
        model = WorkerApplication
        fields = ("branch", "ministry", "experience", "availability")
        widgets = {"experience": forms.Textarea(attrs={"rows": 4})}
        labels = {"branch": "Preferred branch", "ministry": "Ministry or department",
                  "experience": "Skills, experience and why you'd like to serve"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True)
        self.fields["ministry"].queryset = Ministry.objects.filter(is_active=True)
        self.fields["ministry"].required = False
        self.fields["ministry"].empty_label = "No preference"
        self.fields["experience"].min_length = 20


class ApplicationReviewForm(forms.Form):
    note = forms.CharField(required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 2}))


class NotificationForm(forms.ModelForm):
    send_at = dt_field(label="Send at")

    class Meta:
        model = Notification
        fields = ("title", "message", "audience", "branch", "send_at")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["branch"].queryset = branches_for(user)
        self.fields["branch"].required = False
        self.fields["send_at"].required = False
        choices = [(v, l) for v, l in Notification.Audience.choices if v != "user"]
        if not user.is_super_admin:
            choices = [(v, l) for v, l in choices if v != "all"]
        self.fields["audience"].choices = choices

    def clean(self):
        data = super().clean()
        audience, branch = data.get("audience"), data.get("branch")
        if audience == "branch" and not branch:
            self.add_error("branch", "Choose which branch should receive this.")
        if not self.user.is_super_admin and not branch:
            self.add_error("branch", "Choose one of your branches.")
        if not data.get("send_at"):
            data["send_at"] = timezone.now()
        return data


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ["title", "body", "category", "scripture", "is_pinned"]
        widgets = {
            "title": forms.TextInput(attrs={
                "placeholder": "Give your note a title",
            }),
            "body": forms.Textarea(attrs={
                "rows": 10,
                "placeholder": "Write your notes here...",
            }),
            "scripture": forms.TextInput(attrs={
                "placeholder": "e.g. Hebrews 11:1",
            }),
            "category": forms.Select(),
            "is_pinned": forms.CheckboxInput(),
        }


