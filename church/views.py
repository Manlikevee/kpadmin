from collections import OrderedDict
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST

from accounts.access import branches_for, can_manage_branch, member_branch_ids, scope_to_branches
from accounts.mixins import (RoleRequiredMixin, StaffRequiredMixin, SuperAdminRequiredMixin,
                             WorkerRequiredMixin)
from core.models import SiteSettings
from core.forms import SiteSettingsForm
from sermons.youtube import get_service

from . import forms, services
from .crud import ManagedDeleteView, ManagedDetailView, ManagedFormView, ManagedListView
from .models import (Announcement, Branch, Devotional, Event, GivingRecord, Member, Ministry,
                     Notification, PraiseReport, PrayerRequest, Story, WorkerApplication,
                     WorkerAssignment)

User = get_user_model()


# --------------------------------------------------------------------- home
@login_required
def home(request):
    """Send each signed-in user to the dashboard for their role."""
    u = request.user
    if u.is_super_admin:
        return redirect("church:dashboard")
    if u.is_branch_admin:
        return redirect("church:branch_dashboard")
    if u.is_worker:
        return redirect("church:worker_dashboard")
    return redirect("church:member_dashboard")


def _growth_chart(qs, date_field="joined_on", months=7):
    """Return SVG path strings + labels for the 'Member growth' chart."""
    today = timezone.localdate()
    y, m = today.year, today.month
    keys = []
    for i in range(months - 1, -1, -1):
        mm, yy = m - i, y
        while mm <= 0:
            mm += 12
            yy -= 1
        keys.append((yy, mm))
    counts = {k: 0 for k in keys}
    for d in qs.values_list(date_field, flat=True):
        if d and (d.year, d.month) in counts:
            counts[(d.year, d.month)] += 1
    vals = [counts[k] for k in keys]
    top = max(vals) or 1
    xs = [30 + i * (470 / max(months - 1, 1)) for i in range(months)]
    ys = [170 - (v / top) * 140 for v in vals]
    pts = list(zip(xs, ys))
    line = "M" + " L".join(f"{x:.0f} {y_:.0f}" for x, y_ in pts)
    area = line + f" L{xs[-1]:.0f} 170 L{xs[0]:.0f} 170z"
    import calendar
    labels = [{"x": f"{x:.0f}", "t": calendar.month_abbr[k[1]]} for x, k in zip(xs, keys)]
    return {"line": line, "area": area, "labels": labels, "last": {"x": f"{pts[-1][0]:.0f}", "y": f"{pts[-1][1]:.0f}"},
            "total": sum(vals)}


class SuperDashboard(SuperAdminRequiredMixin, View):
    def get(self, request):
        now = timezone.now()
        month_start = timezone.localdate().replace(day=1)
        giving = GivingRecord.objects.filter(given_on__gte=month_start).aggregate(t=Sum("amount"))["t"] or 0
        ctx = {
            "page_id": "dashboard",
            "member_count": Member.objects.count(),
            "new_members": Member.objects.filter(joined_on__gte=month_start).count(),
            "pending_prayers": PrayerRequest.objects.filter(status="pending").count(),
            "unassigned_prayers": PrayerRequest.objects.filter(status="pending", assigned_to__isnull=True).count(),
            "branch_count": Branch.objects.filter(is_active=True).count(),
            "giving_month": giving,
            "upcoming_events": Event.objects.filter(start_at__gte=now).select_related("branch")[:3],
            "pending_praise": PraiseReport.objects.filter(status="pending").select_related("user")[:3],
            "pending_prayer_items": PrayerRequest.objects.filter(status="pending")[:3],
            "pending_members": Member.objects.filter(status="pending")[:2],
            "pending_applications": WorkerApplication.objects.filter(status="pending").count(),
            "chart": _growth_chart(Member.objects.all()),
        }
        ctx["review_count"] = (ctx["pending_praise"].count() + len(ctx["pending_prayer_items"])
                               + len(ctx["pending_members"]))
        return render(request, "dashboard/dashboard.html", ctx)


class BranchDashboardView(StaffRequiredMixin, View):
    """Branch dashboard. Branch admins see their branch(es); super admins can open any."""

    def get(self, request, pk=None):
        managed = branches_for(request.user)
        if pk is None and request.GET.get("branch"):
            pk = request.GET.get("branch")
        branch = get_object_or_404(managed, pk=pk) if pk else managed.first()
        if branch is None:
            return render(request, "dashboard/branch-dashboard.html", {"branch": None, "page_id": "branch-dashboard",
                                                                       "managed": managed})
        now = timezone.now()
        pending = WorkerApplication.objects.filter(branch=branch, status="pending").select_related("applicant", "ministry")
        month_start = timezone.localdate().replace(day=1)
        events = Event.objects.filter(Q(branch=branch) | Q(branch__isnull=True), start_at__gte=now)
        return render(request, "dashboard/branch-dashboard.html", {
            "branch": branch, "managed": managed, "page_id": "branch-dashboard",
            "member_count": branch.members.count(),
            "new_members": branch.members.filter(joined_on__gte=month_start).count(),
            "worker_count": branch.worker_assignments.filter(is_active=True).count(),
            "ministry_count": branch.worker_assignments.filter(is_active=True, ministry__isnull=False)
                                    .values("ministry").distinct().count(),
            "pending": pending, "pending_count": pending.count(),
            "events": events.select_related("branch")[:3], "event_count": events.count(),
            "announcements": Announcement.objects.filter(Q(branch=branch) | Q(branch__isnull=True), is_published=True)[:3],
            "review_form": forms.ApplicationReviewForm(),
        })


class WorkerDashboard(WorkerRequiredMixin, View):
    def get(self, request):
        return render(request, "dashboard/worker-dashboard.html", portal_context(request, "worker-dashboard"))


class MemberDashboard(RoleRequiredMixin, View):
    allowed_roles = ("member", "worker", "branch_admin")

    def get(self, request):
        ctx = portal_context(request, "member-dashboard")
        ctx["applications"] = request.user.worker_applications.select_related("branch", "ministry")[:5]
        ctx["branches"] = Branch.objects.filter(is_active=True)
        return render(request, "dashboard/member-dashboard.html", ctx)


def portal_context(request, page_id):
    """Shared data for the worker and member dashboards (one source of truth)."""
    user = request.user
    now = timezone.now()
    branch_ids = member_branch_ids(user)
    in_scope = Q(branch__isnull=True) | Q(branch_id__in=branch_ids)
    notes = services.notifications_for(user)
    sermons = get_service().get_sermons(page_size=3)
    today = timezone.localdate()
    return {
        "page_id": page_id,
        "announcements": Announcement.objects.filter(in_scope, is_published=True).filter(
            Q(publish_at__isnull=True) | Q(publish_at__lte=now))[:4],
        "events": Event.objects.filter(in_scope, status="confirmed", start_at__gte=now).select_related("branch")[:5],
        "devotional": Devotional.objects.filter(is_published=True, date__lte=today).first(),
        "recent_devotionals": Devotional.objects.filter(is_published=True, date__lte=today)[:4],
        "sermons": sermons["items"], "sermons_error": sermons["error"],
        "notifications": notes[:5], "unread": services.unread_count(user),
        "assignments": user.worker_assignments.filter(is_active=True).select_related("branch", "ministry"),
        "member": getattr(user, "member_record", None),
    }


# ------------------------------------------------------------ notifications
class MyNotifications(View):
    def get(self, request):
        if not request.user.is_authenticated:
            return redirect("accounts:login")
        notes = list(services.notifications_for(request.user)[:50])
        from .models import NotificationRead
        read = set(NotificationRead.objects.filter(user=request.user, notification__in=notes)
                   .values_list("notification_id", flat=True))
        for n in notes:
            n.unread = n.pk not in read
        services.mark_notifications_read(request.user, notes)
        return render(request, "dashboard/my-notifications.html", {"notes": notes, "page_id": "my-notifications"})


class NotificationsAdmin(StaffRequiredMixin, View):
    def _history(self, user):
        qs = Notification.objects.select_related("branch", "recipient")
        if not user.is_super_admin:
            qs = qs.filter(Q(branch__in=branches_for(user)) | Q(created_by=user))
        return qs.exclude(audience="user")[:15]

    def get(self, request):
        form = forms.NotificationForm(user=request.user)
        return render(request, "dashboard/notifications.html",
                      {"form": form, "history": self._history(request.user), "page_id": "notifications"})

    def post(self, request):
        form = forms.NotificationForm(request.POST, user=request.user)
        if form.is_valid():
            note = form.save(commit=False)
            note.created_by = request.user
            note.save()
            messages.success(request, "Notification scheduled." if not note.is_sent else "Notification sent.")
            return redirect("church:notifications")
        return render(request, "dashboard/notifications.html",
                      {"form": form, "history": self._history(request.user), "page_id": "notifications"})


# ---------------------------------------------------------------- branches
class BranchList(SuperAdminRequiredMixin, View):
    def get(self, request):
        branches = Branch.objects.annotate(member_total=Count("members", distinct=True),
                                           worker_total=Count("worker_assignments", filter=Q(worker_assignments__is_active=True), distinct=True)
                                           ).prefetch_related("admins")
        return render(request, "dashboard/branches.html", {
            "branches": branches, "form": forms.BranchForm(), "page_id": "branches",
            "total": branches.count(), "active": sum(1 for b in branches if b.is_active),
            "total_members": sum(b.member_total for b in branches),
        })


class BranchSave(SuperAdminRequiredMixin, View):
    def post(self, request, pk=None):
        branch = get_object_or_404(Branch, pk=pk) if pk else None
        form = forms.BranchForm(request.POST, instance=branch)
        if form.is_valid():
            form.save()  # also saves the admins (many-to-many)
            messages.success(request, "Branch saved.")
        else:
            for field, errs in form.errors.items():
                for e in errs:
                    messages.error(request, f"{form.fields[field].label or field}: {e}" if field != "__all__" else e)
        return redirect("church:branches")


# ----------------------------------------------------------------- members
class MemberMixin:
    model = Member
    page_id = "members"
    branch_field = "branch"
    include_global = False

    def base_queryset(self):
        return Member.objects.select_related("branch", "user")


class MemberList(MemberMixin, ManagedListView):
    template_name = "dashboard/members.html"
    context_object_name = "members"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        qs = self.get_scoped_queryset()
        ctx["counts"] = {"all": qs.count(), **{s: qs.filter(status=s).count() for s in ("active", "pending", "inactive")}}
        return ctx


class MemberDetail(MemberMixin, ManagedDetailView):
    template_name = "dashboard/member-detail.html"
    context_object_name = "member"


class MemberForm(MemberMixin, ManagedFormView):
    delete_url_name = "church:member_delete"
    form_class = forms.MemberForm
    template_name = "dashboard/member-form.html"
    list_url = "church:members"
    detail_url = "church:member_detail"
    success_message = "Member saved."


class MemberDelete(MemberMixin, ManagedDeleteView):
    list_url = "church:members"
    success_message = "Member removed."


# ----------------------------------------------------------------- workers
class WorkersView(StaffRequiredMixin, View):
    tab = "all"

    def get(self, request):
        user = request.user
        branches = branches_for(user)
        tab = "apps" if (self.tab == "apps" or request.GET.get("tab") == "applications") else "all"
        assignments = scope_to_branches(WorkerAssignment.objects.select_related("user", "branch", "ministry"), user)
        apps = scope_to_branches(WorkerApplication.objects.select_related("applicant", "branch", "ministry", "reviewed_by"), user)
        branch_filter = request.GET.get("branch")
        if branch_filter and branches.filter(pk=branch_filter).exists():
            assignments = assignments.filter(branch_id=branch_filter)
            apps = apps.filter(branch_id=branch_filter)
        status = request.GET.get("status")
        if tab == "all" and status in ("active", "inactive"):
            assignments = assignments.filter(is_active=(status == "active"))
        if tab == "apps" and status in ("pending", "approved", "rejected"):
            apps = apps.filter(status=status)
        return render(request, "dashboard/workers.html", {
            "tab": tab, "assignments": assignments, "applications": apps, "branches": branches,
            "branch_filter": branch_filter or "", "status_filter": status or "",
            "pending_count": apps.filter(status="pending").count() if tab == "apps" else
            scope_to_branches(WorkerApplication.objects.filter(status="pending"), user).count(),
            "worker_total": scope_to_branches(WorkerAssignment.objects.filter(is_active=True), user).count(),
            "form": forms.WorkerAssignmentForm(acting_user=user),
            "review_form": forms.ApplicationReviewForm(),
            "page_id": "applications" if tab == "apps" and user.is_branch_admin else "workers",
        })


class WorkerAdd(StaffRequiredMixin, View):
    def post(self, request):
        form = forms.WorkerAssignmentForm(request.POST, acting_user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Worker assignment saved.")
        else:
            for errs in form.errors.values():
                for e in errs:
                    messages.error(request, e)
        return redirect("church:workers")


class WorkerToggle(StaffRequiredMixin, View):
    def post(self, request, pk):
        qs = scope_to_branches(WorkerAssignment.objects.all(), request.user)
        a = get_object_or_404(qs, pk=pk)
        a.is_active = not a.is_active
        a.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f"{a.user.display_name} is now {'active' if a.is_active else 'inactive'}.")
        return redirect("church:workers")


class ApplicationDecision(StaffRequiredMixin, View):
    action = "approve"

    def post(self, request, pk):
        qs = scope_to_branches(WorkerApplication.objects.all(), request.user)
        app = get_object_or_404(qs, pk=pk)  # branch admins get 404 for other branches
        note = forms.ApplicationReviewForm(request.POST)
        note = note.cleaned_data["note"] if note.is_valid() else ""
        try:
            if self.action == "approve":
                services.approve_application(app, request.user, note)
                messages.success(request, f"{app.applicant.display_name} approved as a worker.")
            else:
                services.reject_application(app, request.user, note)
                messages.success(request, "Application rejected.")
        except services.ApplicationError as exc:
            messages.error(request, str(exc))
        except PermissionError:
            raise PermissionDenied
        return redirect(request.POST.get("next") if request.POST.get("next", "").startswith("/portal/") else "church:applications")


@login_required
def apply_worker(request):
    """Any signed-in non-staff user can apply and track their application status."""
    user = request.user
    form = forms.WorkerApplicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            services.submit_worker_application(user, d["branch"], d.get("ministry"), d["experience"], d.get("availability", ""))
            messages.success(request, "Application submitted. We'll notify you when it's reviewed.")
            return redirect("church:apply")
        except services.ApplicationError as exc:
            form.add_error(None, str(exc))
    return render(request, "dashboard/apply-worker.html", {
        "form": form, "page_id": "apply-worker",
        "applications": user.worker_applications.select_related("branch", "ministry", "reviewed_by"),
    })


# -------------------------------------------------------------- ministries
class MinistryMixin:
    model = Ministry
    page_id = "ministries"
    super_only = True

    def base_queryset(self):
        return Ministry.objects.select_related("branch", "leader").annotate(
            worker_total=Count("workers", filter=Q(workers__is_active=True)))


class MinistryList(MinistryMixin, ManagedListView):
    template_name = "dashboard/ministries.html"
    context_object_name = "ministries"


class MinistryDetail(MinistryMixin, ManagedDetailView):
    template_name = "dashboard/ministry-detail.html"
    context_object_name = "ministry"


class MinistryForm(MinistryMixin, ManagedFormView):
    delete_url_name = "church:ministry_delete"
    form_class = forms.MinistryForm
    template_name = "dashboard/ministry-form.html"
    list_url = "church:ministries"
    detail_url = "church:ministry_detail"


class MinistryDelete(MinistryMixin, ManagedDeleteView):
    list_url = "church:ministries"


# ------------------------------------------------------------------ events
class EventMixin:
    model = Event
    page_id = "events"
    include_global = True

    def base_queryset(self):
        return Event.objects.select_related("branch")


class EventList(EventMixin, ManagedListView):
    template_name = "dashboard/events.html"
    context_object_name = "events"

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.GET.get("past"):
            return qs.filter(start_at__lt=timezone.now()).order_by("-start_at")
        return qs.filter(start_at__gte=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0))

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["weekly"] = self.get_scoped_queryset().filter(repeat="weekly", status="confirmed")[:6]
        ctx["showing_past"] = bool(self.request.GET.get("past"))
        return ctx


class EventDetail(EventMixin, ManagedDetailView):
    template_name = "dashboard/event-detail.html"
    context_object_name = "event"


class EventForm(EventMixin, ManagedFormView):
    delete_url_name = "church:event_delete"
    form_class = forms.EventForm
    template_name = "dashboard/event-form.html"
    list_url = "church:events"
    detail_url = "church:event_detail"
    owner_field = "created_by"
    success_message = "Event saved."


class EventDelete(EventMixin, ManagedDeleteView):
    list_url = "church:events"


@login_required
@require_POST
def event_cancel(request, pk):
    if not request.user.is_staff_role:
        raise PermissionDenied
    qs = scope_to_branches(Event.objects.all(), request.user)
    event = get_object_or_404(qs, pk=pk)
    event.status = Event.Status.CANCELLED
    event.save(update_fields=["status", "updated_at"])
    messages.success(request, "Event cancelled.")
    return redirect("church:event_detail", pk=pk)


# ----------------------------------------------------------- announcements
class AnnouncementMixin:
    model = Announcement
    page_id = "announcements"
    include_global = True

    def base_queryset(self):
        return Announcement.objects.select_related("branch", "author")


class AnnouncementList(AnnouncementMixin, ManagedListView):
    template_name = "dashboard/announcements.html"
    context_object_name = "announcements"


class AnnouncementDetail(AnnouncementMixin, ManagedDetailView):
    template_name = "dashboard/announcement-detail.html"
    context_object_name = "announcement"


class AnnouncementForm(AnnouncementMixin, ManagedFormView):
    delete_url_name = "church:announcement_delete"
    form_class = forms.AnnouncementForm
    template_name = "dashboard/announcement-form.html"
    list_url = "church:announcements"
    detail_url = "church:announcement_detail"
    owner_field = "author"


class AnnouncementDelete(AnnouncementMixin, ManagedDeleteView):
    list_url = "church:announcements"


# -------------------------------------------------------------- devotionals
class DevotionalMixin:
    model = Devotional
    page_id = "bible-devotionals"
    super_only = True
    branch_field = None


class DevotionalList(DevotionalMixin, ManagedListView):
    template_name = "dashboard/bible-devotionals.html"
    context_object_name = "devotionals"


class DevotionalDetail(DevotionalMixin, ManagedDetailView):
    template_name = "dashboard/devotional-detail.html"
    context_object_name = "devotional"


class DevotionalForm(DevotionalMixin, ManagedFormView):
    delete_url_name = "church:devotional_delete"
    form_class = forms.DevotionalForm
    template_name = "dashboard/devotional-form.html"
    list_url = "church:devotionals"
    detail_url = "church:devotional_detail"
    owner_field = "author"

    def get_form(self, data=None, files=None, instance=None):
        return self.form_class(data, files, instance=instance)


class DevotionalDelete(DevotionalMixin, ManagedDeleteView):
    list_url = "church:devotionals"


# ------------------------------------------------------------------ prayer
class PrayerMixin:
    model = PrayerRequest
    page_id = "prayer-requests"
    super_only = True

    def base_queryset(self):
        return PrayerRequest.objects.select_related("user", "branch", "assigned_to")


class PrayerBoard(PrayerMixin, ManagedListView):
    template_name = "dashboard/prayer-requests.html"
    context_object_name = "requests"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        qs = self.get_scoped_queryset()
        ctx["columns"] = [
            ("Pending", "", "pending", qs.filter(status="pending")),
            ("In progress", "ip", "in_progress", qs.filter(status="in_progress")),
            ("Answered", "an", "answered", qs.filter(status="answered")),
        ]
        ctx["columns"] = [(t, c, s, q.count(), q[:8]) for t, c, s, q in ctx["columns"]]
        return ctx


class PrayerDetail(PrayerMixin, ManagedDetailView):
    template_name = "dashboard/prayer-detail.html"
    context_object_name = "prayer"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["team"] = User.objects.filter(is_active=True).exclude(role="member").order_by("first_name")
        return ctx


class PrayerUpdate(SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        prayer = get_object_or_404(PrayerRequest, pk=pk)
        status = request.POST.get("status")
        if status in PrayerRequest.Status.values:
            prayer.status = status
        assignee = request.POST.get("assigned_to")
        if assignee == "":
            prayer.assigned_to = None
        elif assignee:
            prayer.assigned_to = get_object_or_404(User, pk=assignee, is_active=True)
            if prayer.status == "pending":
                prayer.status = "in_progress"
        prayer.save()
        messages.success(request, "Prayer request updated.")
        return redirect("church:prayer_detail", pk=pk)


# ------------------------------------------------------------------ praise
class PraiseMixin:
    model = PraiseReport
    page_id = "praise-reports"
    super_only = True

    def base_queryset(self):
        return PraiseReport.objects.select_related("user", "branch")


class PraiseList(PraiseMixin, ManagedListView):
    template_name = "dashboard/praise-reports.html"
    context_object_name = "reports"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        qs = self.get_scoped_queryset()
        ctx["counts"] = {"all": qs.count(), "pending": qs.filter(status="pending").count(),
                         "published": qs.filter(status="published").count()}
        return ctx


class PraiseDetail(PraiseMixin, ManagedDetailView):
    template_name = "dashboard/praise-detail.html"
    context_object_name = "report"


class PraiseForm(PraiseMixin, ManagedFormView):
    delete_url_name = "church:praise_delete"
    form_class = forms.PraiseForm
    template_name = "dashboard/praise-form.html"
    list_url = "church:praise_reports"
    detail_url = "church:praise_detail"


class PraiseDelete(PraiseMixin, ManagedDeleteView):
    list_url = "church:praise_reports"


class PraiseDecision(SuperAdminRequiredMixin, View):
    status = "published"

    def post(self, request, pk):
        report = get_object_or_404(PraiseReport, pk=pk)
        report.status = self.status
        report.save(update_fields=["status", "updated_at"])
        messages.success(request, "Praise report " + ("approved." if self.status == "published" else "declined."))
        return redirect(request.POST.get("next") if request.POST.get("next", "").startswith("/portal/") else "church:praise_reports")


# ------------------------------------------------------------------ giving
class GivingMixin:
    model = GivingRecord
    page_id = "giving"
    super_only = True

    def base_queryset(self):
        return GivingRecord.objects.select_related("user", "branch")


class GivingList(GivingMixin, ManagedListView):
    template_name = "dashboard/giving.html"
    context_object_name = "records"

    def get_queryset(self):
        return super().get_queryset()[:15]

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        month_start = timezone.localdate().replace(day=1)
        month = GivingRecord.objects.filter(given_on__gte=month_start)
        total = month.aggregate(t=Sum("amount"))["t"] or 0
        by_fund = []
        labels = dict(GivingRecord.Fund.choices)
        for row in month.values("fund").annotate(t=Sum("amount")).order_by("-t"):
            pct = round(float(row["t"]) / float(total) * 100) if total else 0
            by_fund.append({"label": labels.get(row["fund"], row["fund"]), "total": row["t"], "pct": pct})
        ctx.update(month_total=total, month_count=month.count(), by_fund=by_fund)
        return ctx


class GivingForm(GivingMixin, ManagedFormView):
    delete_url_name = "church:giving_delete"
    form_class = forms.GivingForm
    template_name = "dashboard/giving-form.html"
    list_url = "church:giving"


class GivingDelete(GivingMixin, ManagedDeleteView):
    list_url = "church:giving"


# ----------------------------------------------------------------- stories
class StoryMixin:
    model = Story
    page_id = "stories"
    super_only = True

    def base_queryset(self):
        return Story.objects.select_related("branch")


class StoryList(StoryMixin, ManagedListView):
    template_name = "dashboard/stories.html"
    context_object_name = "stories"


class StoryForm(StoryMixin, ManagedFormView):
    delete_url_name = "church:story_delete"
    form_class = forms.StoryForm
    template_name = "dashboard/story-form.html"
    list_url = "church:stories"

    def before_save(self, obj, created):
        if obj.is_published and not obj.published_at:
            obj.published_at = timezone.now()
        if not obj.is_published:
            obj.published_at = None


class StoryDelete(StoryMixin, ManagedDeleteView):
    list_url = "church:stories"


# ---------------------------------------------------------------- settings
class SettingsView(SuperAdminRequiredMixin, View):
    def get(self, request):
        return render(request, "dashboard/settings.html",
                      {"form": SiteSettingsForm(instance=SiteSettings.load()), "page_id": "settings"})

    def post(self, request):
        form = SiteSettingsForm(request.POST, instance=SiteSettings.load())
        if form.is_valid():
            form.save()
            messages.success(request, "Settings saved.")
            return redirect("church:settings")
        return render(request, "dashboard/settings.html", {"form": form, "page_id": "settings"})
