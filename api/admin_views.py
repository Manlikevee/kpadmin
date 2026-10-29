"""Admin / management endpoints for the mobile app.

Everything here reuses the same models, scoping helpers and business rules as the
web dashboard, so the two can never disagree about who may do what.
"""
import calendar
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, ListCreateAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.access import branches_for, member_branch_ids
from bible import services as bible_services
from bible.forms import BibleUploadForm
from bible.models import BibleTranslation, human_size
from church import services
from church.models import (Announcement, Branch, Devotional, Event, GivingRecord, Member, Ministry, Notification,
                           NotificationRead, PraiseReport, PrayerRequest, WorkerApplication)
from core.models import SiteSettings
from push_notifications.models import DevicePushToken
from push_notifications.services import send_push_bulk
from sermons.models import SermonNote
from sermons.youtube import get_service

from . import admin_serializers as a
from . import serializers as s
from .filters import GivingFilter, MinistryFilter, PraiseFilter, PrayerAdminFilter
from .pagination import StandardPagination
from .permissions import IsStaffRole, IsSuperAdmin, ReadAnyWriteSuper

User = get_user_model()
logger = logging.getLogger(__name__)


def money(value):
    """Two-decimal string, identical on SQLite and PostgreSQL (``Sum`` can come back unquantized)."""
    return str(Decimal(value).quantize(Decimal("0.01")))


def _int_param(request, name, default, low, high):
    try:
        value = int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


# =============================================================== dashboard
def monthly_counts(qs, field, months=7):
    """New rows per month for the last ``months`` months (oldest first), as plain data for charts."""
    today = timezone.localdate()
    keys = []
    for i in range(months - 1, -1, -1):
        month, year = today.month - i, today.year
        while month <= 0:
            month += 12
            year -= 1
        keys.append((year, month))
    counts = dict.fromkeys(keys, 0)
    first = date(keys[0][0], keys[0][1], 1)
    for d in qs.filter(**{f"{field}__gte": first}).values_list(field, flat=True):
        if d and (d.year, d.month) in counts:
            counts[(d.year, d.month)] += 1
    return [{"month": f"{y}-{m:02d}", "label": calendar.month_abbr[m], "count": counts[(y, m)]} for y, m in keys]


class DashboardView(APIView):
    """One call after login: the summary the web dashboard shows for the caller's role.

    ``role`` tells the app which layout to render:
    ``super_admin`` | ``branch_admin`` | ``worker`` / ``member`` (the portal payload).
    """

    def get(self, request):
        user = request.user
        if user.is_super_admin:
            role, data = "super_admin", self.super_admin(request)
        elif user.is_branch_admin:
            role, data = "branch_admin", self.branch_admin(request)
        else:
            role, data = user.role, self.portal(request)
        return Response({"role": role, **data})

    # -- super admin
    def super_admin(self, request):
        ctx = {"request": request}
        now = timezone.now()
        month_start = timezone.localdate().replace(day=1)
        giving = (GivingRecord.objects.filter(given_on__gte=month_start).values("currency")
                  .annotate(total=Sum("amount")).order_by("currency"))
        prayers = PrayerRequest.objects.filter(status="pending")
        return {
            "stats": {
                "members": Member.objects.count(),
                "new_members_this_month": Member.objects.filter(joined_on__gte=month_start).count(),
                "active_branches": Branch.objects.filter(is_active=True).count(),
                "pending_prayers": prayers.count(),
                "unassigned_prayers": prayers.filter(assigned_to__isnull=True).count(),
                "pending_praise_reports": PraiseReport.objects.filter(status="pending").count(),
                "pending_applications": WorkerApplication.objects.filter(status="pending").count(),
                "pending_members": Member.objects.filter(status="pending").count(),
                # one total per currency: never add naira to dollars
                "giving_this_month": [{"currency": r["currency"], "total": money(r["total"])} for r in giving],
            },
            "member_growth": monthly_counts(Member.objects.all(), "joined_on"),
            "upcoming_events": s.EventSerializer(
                Event.objects.filter(start_at__gte=now).select_related("branch")[:3], many=True, context=ctx).data,
            "pending_praise_reports": a.PraiseReportAdminSerializer(
                PraiseReport.objects.filter(status="pending").select_related("branch")[:3], many=True,
                context=ctx).data,
            "pending_prayer_requests": a.PrayerRequestAdminSerializer(
                prayers.select_related("branch", "assigned_to")[:3], many=True, context=ctx).data,
            "pending_member_records": s.MemberSerializer(
                Member.objects.filter(status="pending").select_related("branch")[:2], many=True, context=ctx).data,
        }

    # -- branch admin
    def branch_admin(self, request):
        ctx = {"request": request}
        managed = branches_for(request.user)
        branch_id = request.query_params.get("branch")
        try:
            branch = get_object_or_404(managed, pk=int(branch_id)) if branch_id else managed.first()
        except ValueError:
            raise Http404
        base = {"managed_branches": [{"id": b.pk, "name": b.name} for b in managed]}
        if branch is None:
            return {**base, "branch": None}
        now = timezone.now()
        month_start = timezone.localdate().replace(day=1)
        pending = WorkerApplication.objects.filter(branch=branch, status="pending").select_related(
            "applicant", "branch", "ministry", "reviewed_by")
        events = Event.objects.filter(Q(branch=branch) | Q(branch__isnull=True), start_at__gte=now)
        announcements = Announcement.objects.filter(Q(branch=branch) | Q(branch__isnull=True), is_published=True)
        return {
            **base,
            "branch": s.BranchSerializer(branch, context=ctx).data,
            "stats": {
                "members": branch.members.count(),
                "new_members_this_month": branch.members.filter(joined_on__gte=month_start).count(),
                "workers": branch.worker_assignments.filter(is_active=True).count(),
                "ministries_served": branch.worker_assignments.filter(is_active=True, ministry__isnull=False)
                                           .values("ministry").distinct().count(),
                "pending_applications": pending.count(),
                "upcoming_events": events.count(),
            },
            "pending_applications": s.WorkerApplicationSerializer(pending, many=True, context=ctx).data,
            "upcoming_events": s.EventSerializer(events.select_related("branch")[:3], many=True, context=ctx).data,
            "announcements": s.AnnouncementSerializer(announcements.select_related("branch")[:3], many=True,
                                                      context=ctx).data,
        }

    # -- worker + member (the portal)
    def portal(self, request):
        user = request.user
        ctx = {"request": request}
        now = timezone.now()
        today = timezone.localdate()
        in_scope = Q(branch__isnull=True) | Q(branch_id__in=member_branch_ids(user))
        devotionals = Devotional.objects.filter(is_published=True, date__lte=today)
        notes = services.notifications_for(user)
        read_ids = set(NotificationRead.objects.filter(user=user).values_list("notification_id", flat=True))
        member = getattr(user, "member_record", None)
        return {
            "member": s.MemberSerializer(member, context=ctx).data if member else None,
            "assignments": s.WorkerAssignmentSerializer(
                user.worker_assignments.filter(is_active=True).select_related("user", "branch", "ministry"),
                many=True, context=ctx).data,
            "announcements": s.AnnouncementSerializer(
                Announcement.objects.filter(in_scope, is_published=True)
                .filter(Q(publish_at__isnull=True) | Q(publish_at__lte=now)).select_related("branch")[:4],
                many=True, context=ctx).data,
            "upcoming_events": s.EventSerializer(
                Event.objects.filter(in_scope, status="confirmed", start_at__gte=now).select_related("branch")[:5],
                many=True, context=ctx).data,
            "devotional": s.DevotionalSerializer(devotionals.first(), context=ctx).data if devotionals.exists()
            else None,
            "recent_devotionals": s.DevotionalSerializer(devotionals[:4], many=True, context=ctx).data,
            "notifications": s.NotificationSerializer(notes[:5], many=True, context={**ctx, "read_ids": read_ids}).data,
            "unread_notifications": services.unread_count(user),
            "my_applications": s.WorkerApplicationSerializer(
                user.worker_applications.select_related("applicant", "branch", "ministry", "reviewed_by")[:5],
                many=True, context=ctx).data,
        }


# ================================================================ users
class AdminUserList(ListAPIView):
    """Active users for pickers. ``?search=`` (name/email), ``?role=``, ``?assignable=true`` (not plain members)."""

    serializer_class = a.AdminUserSerializer
    permission_classes = [IsStaffRole]
    pagination_class = StandardPagination
    filterset_fields = ("role",)
    search_fields = ("first_name", "last_name", "email", "username")

    def get_queryset(self):
        qs = User.objects.filter(is_active=True).order_by("first_name", "email")
        if self.request.query_params.get("assignable", "").lower() in ("1", "true", "yes"):
            qs = qs.exclude(role=User.Role.MEMBER)
        return qs


# ============================================================= ministries
class MinistryViewSet(viewsets.ModelViewSet):
    """Everyone can read active ministries (the "apply to serve" form needs them);
    only super admins create, edit or delete. ``?for_branch=<id>`` = that branch's + church-wide ones."""

    serializer_class = s.MinistrySerializer
    permission_classes = [ReadAnyWriteSuper]
    pagination_class = StandardPagination
    filterset_class = MinistryFilter
    search_fields = ("name", "description")

    def get_queryset(self):
        qs = Ministry.objects.select_related("branch", "leader").annotate(
            worker_count=Count("workers", filter=Q(workers__is_active=True), distinct=True))
        u = self.request.user
        if u.is_authenticated and u.is_super_admin:
            return qs
        return qs.filter(is_active=True)


# =============================================================== prayer
class PrayerAdminViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                         viewsets.GenericViewSet):
    """Prayer requests from every member (super admin). Update only ``status`` / ``assigned_to`` via PATCH."""

    serializer_class = a.PrayerRequestAdminSerializer
    permission_classes = [IsSuperAdmin]
    pagination_class = StandardPagination
    filterset_class = PrayerAdminFilter
    search_fields = ("title", "request", "name", "email")
    http_method_names = ["get", "patch", "head", "options"]
    queryset = PrayerRequest.objects.select_related("user", "branch", "assigned_to")

    @action(detail=False, methods=["get"])
    def board(self, request):
        """Kanban columns: counts plus the newest ``?limit=`` (default 8) requests per status."""
        limit = _int_param(request, "limit", 8, 1, 50)
        base = self.get_queryset()
        columns = []
        for value, label in PrayerRequest.Status.choices:
            col = base.filter(status=value)
            columns.append({"status": value, "label": label, "count": col.count(),
                            "items": self.get_serializer(col[:limit], many=True).data})
        return Response({"columns": columns,
                         "unassigned_pending": base.filter(status="pending", assigned_to__isnull=True).count()})

    @action(detail=False, methods=["get"])
    def assignees(self, request):
        """Team members a request can be assigned to (everyone except plain members)."""
        team = User.objects.filter(is_active=True).exclude(role=User.Role.MEMBER).order_by("first_name", "email")
        return Response(a.AdminUserSerializer(team, many=True).data)


# =============================================================== praise
class PraiseReportViewSet(viewsets.ModelViewSet):
    """
    * anyone: list/read **published** reports
    * signed-in members: ``POST`` (goes to review as *pending*) and ``GET mine/``
    * super admin: everything, plus ``POST {id}/approve/`` and ``POST {id}/decline/``
    """

    pagination_class = StandardPagination
    filterset_class = PraiseFilter
    search_fields = ("story", "category", "name")

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.AllowAny()]
        if self.action in ("create", "mine"):
            return [permissions.IsAuthenticated()]
        return [IsSuperAdmin()]

    def _is_super(self):
        u = self.request.user
        return bool(u and u.is_authenticated and u.is_super_admin)

    def get_serializer_class(self):
        return a.PraiseReportAdminSerializer if self._is_super() else a.PraiseReportSerializer

    def get_queryset(self):
        qs = PraiseReport.objects.select_related("user", "branch")
        return qs if self._is_super() else qs.filter(status=PraiseReport.Status.PUBLISHED)

    def perform_create(self, serializer):
        user = self.request.user
        if user.is_super_admin:
            serializer.save()
            return
        member = getattr(user, "member_record", None)
        serializer.save(
            user=user, status=PraiseReport.Status.PENDING,
            name=serializer.validated_data.get("name") or user.display_name,
            branch=serializer.validated_data.get("branch") or (member.branch if member else None))

    @action(detail=False, methods=["get"])
    def mine(self, request):
        qs = PraiseReport.objects.filter(user=request.user).select_related("branch")
        page = self.paginate_queryset(qs)
        ser = a.PraiseReportSerializer(page if page is not None else qs, many=True, context={"request": request})
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    def _decide(self, new_status):
        report = self.get_object()
        report.status = new_status
        report.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(report).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(PraiseReport.Status.PUBLISHED)

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._decide(PraiseReport.Status.DECLINED)


# =============================================================== giving
class GivingViewSet(viewsets.ModelViewSet):
    """Manually recorded gifts (super admin). Amounts are returned as strings; parse them with a decimal library."""

    serializer_class = a.GivingRecordSerializer
    permission_classes = [IsSuperAdmin]
    pagination_class = StandardPagination
    filterset_class = GivingFilter
    search_fields = ("donor_name", "reference", "method")
    queryset = GivingRecord.objects.select_related("user", "branch")

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Totals for one month (``?month=YYYY-MM``, default this month), per currency and per fund."""
        raw = request.query_params.get("month")
        try:
            start = date.fromisoformat(f"{raw}-01") if raw else timezone.localdate().replace(day=1)
        except ValueError:
            raise ValidationError({"month": "Use the format YYYY-MM."})
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        qs = GivingRecord.objects.filter(given_on__gte=start, given_on__lt=end)
        if request.query_params.get("branch"):
            try:
                qs = qs.filter(branch_id=int(request.query_params["branch"]))
            except ValueError:
                raise ValidationError({"branch": "Use a branch id."})

        totals = list(qs.values("currency").annotate(total=Sum("amount"), count=Count("id")).order_by("currency"))
        grand = {t["currency"]: t["total"] for t in totals}
        labels = dict(GivingRecord.Fund.choices)
        by_fund = []
        for row in qs.values("currency", "fund").annotate(total=Sum("amount")).order_by("currency", "-total"):
            whole = grand[row["currency"]]
            by_fund.append({"currency": row["currency"], "fund": row["fund"],
                            "label": labels.get(row["fund"], row["fund"]), "total": money(row["total"]),
                            "percent": round(float(row["total"]) / float(whole) * 100) if whole else 0})
        return Response({
            "month": start.strftime("%Y-%m"), "records": qs.count(),
            "totals": [{"currency": t["currency"], "total": money(t["total"]), "count": t["count"]} for t in totals],
            "by_fund": by_fund})


# ============================================================== settings
class SiteSettingsAdminView(APIView):
    """Church name, contact details and giving instructions (super admin). Public read stays at ``/site/``."""

    permission_classes = [IsSuperAdmin]

    def get(self, request):
        return Response(a.SiteSettingsSerializer(SiteSettings.load()).data)

    def patch(self, request):
        ser = a.SiteSettingsSerializer(SiteSettings.load(), data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    put = patch


# ================================================================ bible
def _bible_errors(form):
    return {field: [str(e) for e in errs] for field, errs in form.errors.items()}


class BibleAdminList(APIView):
    """List (GET) and upload (POST multipart: ``name`` + ``file``) Bible JSON translations. Super admin."""

    permission_classes = [IsSuperAdmin]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        items = list(BibleTranslation.objects.select_related("uploaded_by"))
        total = sum(i.size_in_bytes for i in items)
        largest = max(items, key=lambda i: i.size_in_bytes, default=None)
        return Response({
            "count": len(items), "total_size": human_size(total), "total_size_in_bytes": total,
            "largest": largest.name if largest else None,
            "results": a.BibleTranslationAdminSerializer(items, many=True, context={"request": request}).data})

    def post(self, request):
        form = BibleUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return Response(_bible_errors(form), status=status.HTTP_400_BAD_REQUEST)
        upload = form.cleaned_data["file"]
        try:
            obj = BibleTranslation(name=form.cleaned_data["name"], file=upload, uploaded_by=request.user,
                                   size_in_bytes=upload.size)
            obj.save()
        except Exception:
            logger.exception("Bible translation upload failed")
            return Response({"detail": "Upload failed. Please check the server logs."},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response(a.BibleTranslationAdminSerializer(obj, context={"request": request}).data,
                        status=status.HTTP_201_CREATED)


class BibleAdminDetail(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, pk):
        obj = get_object_or_404(BibleTranslation, pk=pk)
        return Response(a.BibleTranslationAdminSerializer(obj, context={"request": request}).data)

    def delete(self, request, pk):
        obj = get_object_or_404(BibleTranslation, pk=pk)
        try:
            bible_services.delete_translation(obj)
        except Exception:
            logger.exception("Bible translation delete failed")
            return Response({"detail": "Deletion failed. Check Cloudinary and try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BibleAdminReplace(APIView):
    """POST multipart ``file`` (and optionally a new ``name``) to replace an existing version's JSON."""

    permission_classes = [IsSuperAdmin]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        obj = get_object_or_404(BibleTranslation, pk=pk)
        data = request.POST.copy()
        data.setdefault("name", obj.name)
        form = BibleUploadForm(data, request.FILES, instance=obj)
        if not form.is_valid():
            return Response(_bible_errors(form), status=status.HTTP_400_BAD_REQUEST)
        try:
            bible_services.replace_translation(obj, name=form.cleaned_data["name"],
                                               upload=form.cleaned_data["file"], user=request.user)
        except Exception:
            logger.exception("Bible translation replace failed")
            return Response({"detail": "Replacement failed. Check Cloudinary and try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response(a.BibleTranslationAdminSerializer(obj, context={"request": request}).data)


# =============================================================== sermons
class SermonAdminList(APIView):
    """YouTube sermons with the local metadata (speaker, series, hidden/featured) attached. Staff."""

    permission_classes = [IsStaffRole]

    def get(self, request):
        size = _int_param(request, "page_size", 12, 1, 50)
        page = get_service().get_sermons(page_token=request.query_params.get("page_token", ""), page_size=size)
        notes = {n.video_id: n for n in SermonNote.objects.filter(
            video_id__in=[v["video_id"] for v in page["items"]])}
        items = [dict(v, note=a.SermonNoteSerializer(notes[v["video_id"]]).data if v["video_id"] in notes else None)
                 for v in page["items"]]
        return Response({"results": items, "next_page_token": page["next_page_token"],
                         "prev_page_token": page["prev_page_token"], "stale": page["stale"],
                         "error": page["error"]})


class SermonAdminDetail(APIView):
    """GET one sermon with its metadata; PATCH/PUT to save speaker, series, notes, is_featured, is_hidden."""

    permission_classes = [IsStaffRole]

    def _video(self, video_id):
        video = get_service().get_video(video_id)
        if not video:
            raise Http404
        return video

    def get(self, request, video_id):
        video = self._video(video_id)
        note = SermonNote.objects.filter(video_id=video_id).first()
        return Response(dict(video, note=a.SermonNoteSerializer(note).data if note else None))

    def patch(self, request, video_id):
        video = self._video(video_id)
        note, _ = SermonNote.objects.get_or_create(video_id=video_id)
        ser = a.SermonNoteSerializer(note, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(dict(video, note=ser.data))

    put = patch


class SermonAdminRefresh(APIView):
    permission_classes = [IsStaffRole]

    def post(self, request):
        get_service().clear_cache()
        return Response({"detail": "Refreshed from YouTube."})


# ========================================================== notifications
class NotificationAdminList(ListCreateAPIView):
    """In-app notifications: history (GET) and send / schedule (POST). Staff.

    Super admins can target ``all``, a ``branch`` or ``workers``; branch admins only their own branches.
    Leave ``send_at`` out to send now; a future time schedules it.
    """

    serializer_class = a.NotificationAdminSerializer
    permission_classes = [IsStaffRole]
    pagination_class = StandardPagination
    filterset_fields = ("audience", "branch")
    search_fields = ("title", "message")

    def get_queryset(self):
        u = self.request.user
        qs = Notification.objects.select_related("branch", "created_by").exclude(audience="user")
        if not u.is_super_admin:
            qs = qs.filter(Q(branch__in=branches_for(u)) | Q(created_by=u))
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


# ================================================================== push
class PushDeviceList(ListAPIView):
    """Registered phones (super admin). Tokens are masked."""

    serializer_class = a.PushDeviceSerializer
    permission_classes = [IsSuperAdmin]
    pagination_class = StandardPagination
    filterset_fields = ("platform", "user")
    queryset = DevicePushToken.objects.select_related("user").order_by("-updated_at")


class PushRecipientList(ListAPIView):
    """People who can receive a push (they have at least one registered device). Super admin."""

    serializer_class = a.PushRecipientSerializer
    permission_classes = [IsSuperAdmin]
    pagination_class = StandardPagination
    search_fields = ("first_name", "last_name", "email", "username")

    def get_queryset(self):
        return (User.objects.filter(push_tokens__isnull=False).annotate(device_count=Count("push_tokens"))
                .order_by("first_name", "email"))


class PushSend(APIView):
    """Send a push to ``target: "all"`` or ``target: "selected"`` + ``users: [ids]`` (super admin)."""

    permission_classes = [IsSuperAdmin]
    throttle_scope = "push"

    def post(self, request):
        ser = a.PushSendSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        devices = DevicePushToken.objects.all() if d["target"] == "all" else \
            DevicePushToken.objects.filter(user__in=d["users"])
        rows = list(devices.values_list("token", "user_id"))
        if not rows:
            raise ValidationError({"detail": "No registered devices for those recipients."})
        result = send_push_bulk([t for t, _ in rows], d["title"], d["message"], data={"route": "/notifications"})
        body = {"recipients": len({u for _, u in rows}), "devices": len(rows), **result}
        return Response(body, status=status.HTTP_200_OK if result["accepted"] else status.HTTP_502_BAD_GATEWAY)
