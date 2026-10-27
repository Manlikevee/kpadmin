from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts import codes
from accounts.access import branches_for, member_branch_ids, scope_to_branches
from bible.models import BibleTranslation
from church import services
from church.models import (Announcement, Branch, Devotional, Event, Member, Notification, NotificationRead,
                           PrayerRequest, WorkerApplication, WorkerAssignment, Story, Note)
from core.models import SiteSettings
from sermons.views import overlay_notes
from sermons.youtube import get_service

from . import serializers as s
from .filters import AnnouncementFilter, ApplicationFilter, EventFilter, MemberFilter
from .pagination import StandardPagination
from .permissions import IsStaffRole, ReadAnyWriteStaff, ReadAnyWriteSuper
from .serializers import NoteSerializer

User = get_user_model()


class ApiRoot(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        base = request.build_absolute_uri("/api/v1/")
        names = ["auth/register/", "auth/token/", "auth/token/refresh/", "auth/email-code/", "auth/email-code/verify/",
                 "auth/password-reset/", "auth/password-reset/verify/", "auth/password-reset/confirm/", "me/",
                 "me/password/", "branches/", "members/", "workers/", "worker-applications/", "events/",
                 "announcements/", "sermons/", "live/", "devotionals/", "notifications/", "bible/versions/",
                 "prayer-requests/", "site/"]
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


class EmailCodeRequestView(APIView):
    """Step 1 of sign-up: email a 6-digit code to a new address."""

    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        ser = s.EmailSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError({"email": ["An account with this email already exists."]})
        try:
            code = codes.issue_code("signup", email)
        except codes.TooSoon as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        codes.send_code_email(email, code, "signup")
        return Response({"detail": "Code sent."})


class EmailCodeVerifyView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        ser = s.CodeVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email, code = ser.validated_data["email"].lower(), ser.validated_data["code"]
        if not codes.check_code("signup", email, code):
            raise ValidationError({"code": ["That code isn't right or has expired."]})
        return Response({"email_token": codes.make_token("signup", email)})


class PasswordResetRequestView(APIView):
    """Always answers 200 so it can't be used to discover which emails have accounts."""

    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        ser = s.EmailSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].lower()
        if User.objects.filter(email__iexact=email, is_active=True).exists():
            try:
                codes.send_code_email(email, codes.issue_code("reset", email), "reset")
            except codes.TooSoon as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        return Response({"detail": "If that email has an account, a code is on its way."})


class PasswordResetVerifyView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        ser = s.CodeVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email, code = ser.validated_data["email"].lower(), ser.validated_data["code"]
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if not user or not codes.check_code("reset", email, code):
            raise ValidationError({"code": ["That code isn't right or has expired."]})
        return Response({"reset_token": codes.make_token("reset", email, extra=user.password[-12:])})


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        ser = s.PasswordResetConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = codes.read_token("reset", ser.validated_data["reset_token"])
        user = User.objects.filter(email__iexact=data["e"], is_active=True).first() if data else None
        if not user or user.password[-12:] != data["x"]:  # tokens die as soon as the password changes
            raise ValidationError({"reset_token": ["This reset link has expired. Please start again."]})
        try:
            validate_password(ser.validated_data["new_password"], user)
        except DjangoValidationError as exc:
            raise ValidationError({"new_password": list(exc.messages)})
        user.set_password(ser.validated_data["new_password"])
        user.save()
        return Response({"detail": "Password changed."})


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
        # one-off events still ahead, plus recurring ones (their first date may be in the past)
        qs = self.filter_queryset(self.get_queryset()).filter(Q(start_at__gte=timezone.now()) | ~Q(repeat="none"))
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


class DevotionalViewSet(viewsets.ModelViewSet):
    serializer_class = s.DevotionalSerializer
    permission_classes = [permissions.IsAuthenticated, ReadAnyWriteStaff]
    pagination_class = StandardPagination
    filterset_fields = ("date",)
    search_fields = ("title", "scripture_ref")

    def get_queryset(self):
        qs = Devotional.objects.all()
        u = self.request.user

        # Staff can manage devotionals, including future and unpublished ones.
        if u.is_staff_role:
            return qs

        # Other authenticated users can only see published devotionals
        # dated today or earlier.
        return qs.filter(
            is_published=True,
            date__lte=timezone.localdate(),
        )

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=False, methods=["get"])
    def today(self, request):
        obj = (
            self.get_queryset()
            .filter(
                is_published=True,
                date__lte=timezone.localdate(),
            )
            .order_by("-date")
            .first()
        )

        if not obj:
            raise Http404("No devotional available.")

        return Response(self.get_serializer(obj).data)

    @action(detail=False, methods=["post"], url_path="bulk-create")
    def bulk_create(self, request):
        if not isinstance(request.data, list):
            return Response(
                {"detail": "Expected a JSON array of devotionals."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not request.data:
            return Response(
                {"detail": "Provide at least one devotional."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            devotionals = serializer.save()

        return Response(
            {
                "message": "Devotionals created successfully.",
                "count": len(devotionals),
                "results": self.get_serializer(
                    devotionals,
                    many=True,
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )

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


class PrayerRequestViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                           viewsets.GenericViewSet):
    """Members send prayer requests and see the ones they sent."""

    serializer_class = s.PrayerRequestSerializer
    pagination_class = StandardPagination
    filterset_fields = ("status",)

    def get_queryset(self):
        return PrayerRequest.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        text = serializer.validated_data["request"]
        member = getattr(self.request.user, "member_record", None)
        serializer.save(
            user=self.request.user, title=text[:80], email=self.request.user.email,
            name=serializer.validated_data.get("name") or self.request.user.display_name,
            branch=member.branch if member else None)


class SiteInfoView(APIView):
    """Public church details and giving instructions (managed in the web dashboard Settings)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        cfg = SiteSettings.load()
        return Response({"church_name": cfg.church_name, "tagline": cfg.tagline, "contact_email": cfg.contact_email,
                         "contact_phone": cfg.contact_phone, "address": cfg.address,
                         "give_instructions": cfg.give_instructions})


class StoryViewSet(viewsets.ModelViewSet):
    serializer_class = s.StorySerializer
    permission_classes = [ReadAnyWriteStaff]
    pagination_class = StandardPagination
    filterset_fields = ("branch", "is_video")
    search_fields = ("title", "caption")

    def get_queryset(self):
        cutoff = timezone.now() - timedelta(hours=48)
        qs = Story.objects.select_related("branch").filter(
            created_at__gte=cutoff
        )

        user = self.request.user

        # Superadmins can see every story across every branch.
        if user.is_authenticated and getattr(
            user, "is_super_admin", False
        ):
            return qs

        # Other staff can only access stories in their permitted branches.
        if user.is_authenticated and getattr(user, "is_staff_role", False):
            if self.request.method == "GET":
                return scope_to_branches(
                    qs, user, include_global=True
                )
            return scope_to_branches(qs, user)

        # Public users and regular members see published stories only.
        return qs.filter(
            is_published=True
        ).exclude(media="")

    def perform_create(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        instance.delete()


class NoteViewSet(viewsets.ModelViewSet):
    serializer_class = NoteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # A user can only access their own notes.
        return Note.objects.filter(
            user=self.request.user
        ).order_by("-is_pinned", "-updated_at")

    def perform_create(self, serializer):
        # Never accept the owner from the request body.
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"], url_path="toggle-pin")
    def toggle_pin(self, request, pk=None):
        note = self.get_object()
        note.is_pinned = not note.is_pinned
        note.save(update_fields=["is_pinned", "updated_at"])

        return Response({
            "id": note.id,
            "is_pinned": note.is_pinned,
            "message": (
                "Note pinned."
                if note.is_pinned
                else "Note unpinned."
            ),
        })