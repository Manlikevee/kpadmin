from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.access import branches_for, member_branch_ids, scope_to_branches
from bible.models import BibleTranslation
from church import services
from church.models import (Announcement, Branch, Devotional, Event, Member, Notification, NotificationRead,
                           WorkerApplication, WorkerAssignment)
from sermons.views import overlay_notes
from sermons.youtube import get_service

from . import serializers as s
from .filters import AnnouncementFilter, ApplicationFilter, EventFilter, MemberFilter
from .pagination import StandardPagination
from .permissions import IsStaffRole, ReadAnyWriteStaff, ReadAnyWriteSuper

User = get_user_model()


class ApiRoot(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        base = request.build_absolute_uri("/api/v1/")
        names = ["auth/register/", "auth/token/", "auth/token/refresh/", "me/", "me/password/", "branches/",
                 "members/", "workers/", "worker-applications/", "events/", "announcements/", "sermons/",
                 "live/", "devotionals/", "notifications/", "bible/versions/"]
        return Response({n.strip("/").replace("/", "_"): base + n for n in names})


# ------------------------------------------------------------------- auth
class LoginView(TokenObtainPairView):
    serializer_class = s.EmailTokenObtainPairSerializer
    throttle_scope = "auth"


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        ser = s.RegisterSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        user = ser.save()
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        return Response({"user": s.UserSerializer(user, context={"request": request}).data,
                         "refresh": str(refresh), "access": str(refresh.access_token)},
                        status=status.HTTP_201_CREATED)


class MeView(APIView):
    def get(self, request):
        return Response(s.MeSerializer(request.user, context={"request": request}).data)

    def patch(self, request):
        ser = s.MeSerializer(request.user, data=request.data, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)


class PasswordChangeView(APIView):
    def post(self, request):
        ser = s.PasswordChangeSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        request.user.set_password(ser.validated_data["new_password"])
        request.user.save()
        return Response({"detail": "Password changed."})


# --------------------------------------------------------------- viewsets
class BranchViewSet(viewsets.ModelViewSet):
    serializer_class = s.BranchSerializer
    permission_classes = [ReadAnyWriteSuper]
    pagination_class = StandardPagination
    filterset_fields = ("is_active", "city", "country")
    search_fields = ("name", "city", "address")

    def get_queryset(self):
        qs = Branch.objects.all()
        u = self.request.user
        if u.is_authenticated and u.is_super_admin:
            return qs
        return qs.filter(is_active=True)


class MemberViewSet(viewsets.ModelViewSet):
    """Staff only; a branch admin only ever sees/changes their own branches' members."""

    serializer_class = s.MemberSerializer
    permission_classes = [IsStaffRole]
    pagination_class = StandardPagination
    filterset_class = MemberFilter
    search_fields = ("full_name", "email", "phone")

    def get_queryset(self):
        return scope_to_branches(Member.objects.select_related("branch"), self.request.user)


class WorkerViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = s.WorkerAssignmentSerializer
    permission_classes = [IsStaffRole]
    pagination_class = StandardPagination
    filterset_fields = ("branch", "ministry", "is_active")

    def get_queryset(self):
        return scope_to_branches(WorkerAssignment.objects.select_related("user", "branch", "ministry"),
                                 self.request.user)


class WorkerApplicationViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                               viewsets.GenericViewSet):
    """Applicants create and track their own; staff review those for branches they manage."""

    serializer_class = s.WorkerApplicationSerializer
    pagination_class = StandardPagination
    filterset_class = ApplicationFilter

    def get_queryset(self):
        qs = WorkerApplication.objects.select_related("applicant", "branch", "ministry", "reviewed_by")
        u = self.request.user
        if u.is_staff_role:
            return scope_to_branches(qs, u)
        return qs.filter(applicant=u)

    @action(detail=False, methods=["get"], url_path="mine")
    def mine(self, request):
        qs = WorkerApplication.objects.filter(applicant=request.user).select_related("branch", "ministry")
        return Response(s.WorkerApplicationSerializer(qs, many=True, context={"request": request}).data)

    def _decide(self, request, pk, fn):
        if not request.user.is_staff_role:
            raise PermissionDenied("Only branch admins and super admins can review applications.")
        obj = self.get_object()  # scoped queryset: other branches -> 404
        ser = s.ReviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            fn(obj, request.user, ser.validated_data.get("note", ""))
        except services.ApplicationError as exc:
            raise ValidationError({"detail": str(exc)})
        except PermissionError as exc:
            raise PermissionDenied(str(exc))
        obj.refresh_from_db()
        return Response(s.WorkerApplicationSerializer(obj, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, pk, services.approve_application)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, pk, services.reject_application)


class EventViewSet(viewsets.ModelViewSet):
    serializer_class = s.EventSerializer
    permission_classes = [ReadAnyWriteStaff]
    pagination_class = StandardPagination
    filterset_class = EventFilter
    search_fields = ("title", "location")

    def get_queryset(self):
        qs = Event.objects.select_related("branch")
        u = self.request.user
        if u.is_authenticated and u.is_staff_role:
            if self.action in ("list", "retrieve") and self.request.method == "GET":
                # staff browsing: their branches + global events (drafts included)
                return scope_to_branches(qs, u, include_global=True)
            return scope_to_branches(qs, u)
        return qs.filter(status="confirmed")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["get"], permission_classes=[permissions.AllowAny])
    def upcoming(self, request):
        qs = self.filter_queryset(self.get_queryset()).filter(start_at__gte=timezone.now())
        page = self.paginate_queryset(qs)
        ser = self.get_serializer(page if page is not None else qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)


class AnnouncementViewSet(viewsets.ModelViewSet):
    serializer_class = s.AnnouncementSerializer
    permission_classes = [permissions.IsAuthenticated, ReadAnyWriteStaff]
    pagination_class = StandardPagination
    filterset_class = AnnouncementFilter
    search_fields = ("title", "body")

    def get_queryset(self):
        qs = Announcement.objects.select_related("branch")
        u = self.request.user
        if u.is_staff_role:
            if self.request.method == "GET":
                return scope_to_branches(qs, u, include_global=True)
            return scope_to_branches(qs, u)
        now = timezone.now()
        mine = Q(branch__isnull=True) | Q(branch_id__in=member_branch_ids(u))
        return qs.filter(mine, is_published=True).filter(Q(publish_at__isnull=True) | Q(publish_at__lte=now))

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class DevotionalViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = s.DevotionalSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = StandardPagination
    filterset_fields = ("date",)
    search_fields = ("title", "scripture_ref")

    def get_queryset(self):
        return Devotional.objects.filter(is_published=True, date__lte=timezone.localdate())

    @action(detail=False, methods=["get"])
    def today(self, request):
        obj = self.get_queryset().first()
        if not obj:
            raise Http404
        return Response(self.get_serializer(obj).data)


class NotificationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = s.NotificationSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        return services.notifications_for(self.request.user)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["read_ids"] = set(NotificationRead.objects.filter(user=self.request.user).values_list("notification_id", flat=True))
        return ctx

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        obj = self.get_object()
        services.mark_notifications_read(request.user, [obj])
        return Response({"detail": "Marked as read."})

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        services.mark_notifications_read(request.user)
        return Response({"detail": "All notifications marked as read."})

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        return Response({"unread": services.unread_count(request.user)})


# ----------------------------------------------------- sermons / live / bible
class SermonListView(APIView):
    """Cached YouTube sermons. ``?page_token=`` pages through the whole archive."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        try:
            size = int(request.query_params.get("page_size", 12))
        except ValueError:
            size = 12
        page = get_service().get_sermons(page_token=request.query_params.get("page_token", ""), page_size=size)
        return Response({"results": overlay_notes(page["items"]), "next_page_token": page["next_page_token"],
                         "prev_page_token": page["prev_page_token"], "stale": page["stale"], "error": page["error"]})


class SermonDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, video_id):
        video = get_service().get_video(video_id)
        video = overlay_notes([video]) if video else []
        if not video:
            raise Http404
        return Response(video[0])


class LiveStreamView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        st = get_service().get_live_status()
        return Response({"is_live": bool(st["live"]), "live": st["live"], "upcoming": st["upcoming"]})


class BibleVersionList(ListAPIView):
    serializer_class = s.BibleVersionSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None
    queryset = BibleTranslation.objects.all()
