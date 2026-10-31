from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from push_notifications.views import RegisterPushTokenView
from . import views
from . import admin_views as av
from .views import NoteViewSet

router = DefaultRouter()
router.register("branches", views.BranchViewSet, basename="branch")
router.register("members", views.MemberViewSet, basename="member")
router.register("workers", views.WorkerViewSet, basename="worker")
router.register("worker-applications", views.WorkerApplicationViewSet, basename="worker-application")
router.register("events", views.EventViewSet, basename="event")
router.register("rotas", views.RotaViewSet, basename="rota")
router.register("pastors", views.PastorViewSet, basename="pastor")
router.register("announcements", views.AnnouncementViewSet, basename="announcement")
router.register("devotionals", views.DevotionalViewSet, basename="devotional")
router.register("notifications", views.NotificationViewSet, basename="notification")
router.register("prayer-requests", views.PrayerRequestViewSet, basename="prayer-request")
router.register("stories", views.StoryViewSet, basename="story")
router.register("notes", NoteViewSet, basename="note")
router.register("ministries", av.MinistryViewSet, basename="ministry")
router.register("praise-reports", av.PraiseReportViewSet, basename="praise-report")
router.register("admin/prayer-requests", av.PrayerAdminViewSet, basename="admin-prayer-request")
router.register("admin/giving", av.GivingViewSet, basename="admin-giving")

urlpatterns = [
    path("", views.ApiRoot.as_view(), name="api-root"),
    path("branches/", views.PublicBranchListView.as_view(), name="api-public-branches"),
    path("auth/register/", views.RegisterView.as_view(), name="api-register"),
    path("auth/token/", views.LoginView.as_view(), name="api-token"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="api-token-refresh"),
    path("auth/email-code/", views.EmailCodeRequestView.as_view(), name="api-email-code"),
    path("auth/email-code/verify/", views.EmailCodeVerifyView.as_view(), name="api-email-code-verify"),
    path("auth/password-reset/", views.PasswordResetRequestView.as_view(), name="api-reset"),
    path("auth/password-reset/verify/", views.PasswordResetVerifyView.as_view(), name="api-reset-verify"),
    path("auth/password-reset/confirm/", views.PasswordResetConfirmView.as_view(), name="api-reset-confirm"),
    path("site/", views.SiteInfoView.as_view(), name="api-site"),
    path("me/", views.MeView.as_view(), name="api-me"),
    path("me/password/", views.PasswordChangeView.as_view(), name="api-password"),
    path("sermons/", views.SermonListView.as_view(), name="api-sermons"),
    path("sermons/<str:video_id>/", views.SermonDetailView.as_view(), name="api-sermon"),
    path("live/", views.LiveStreamView.as_view(), name="api-live"),
    path("bible/versions/", views.BibleVersionList.as_view(), name="api-bible-versions"),
    path(
        "push-tokens/register/",
        RegisterPushTokenView.as_view(),
        name="api-register-push-token",
    ),
    path("dashboard/", av.DashboardView.as_view(), name="api-dashboard"),
    # --- admin / management
    path("admin/users/", av.AdminUserList.as_view(), name="api-admin-users"),
    path("admin/settings/", av.SiteSettingsAdminView.as_view(), name="api-admin-settings"),
    path("admin/bible/", av.BibleAdminList.as_view(), name="api-admin-bible"),
    path("admin/bible/<int:pk>/", av.BibleAdminDetail.as_view(), name="api-admin-bible-detail"),
    path("admin/bible/<int:pk>/replace/", av.BibleAdminReplace.as_view(), name="api-admin-bible-replace"),
    path("admin/sermons/", av.SermonAdminList.as_view(), name="api-admin-sermons"),
    path("admin/sermons/refresh/", av.SermonAdminRefresh.as_view(), name="api-admin-sermons-refresh"),
    path("admin/sermons/<str:video_id>/", av.SermonAdminDetail.as_view(), name="api-admin-sermon"),
    path("admin/notifications/", av.NotificationAdminList.as_view(), name="api-admin-notifications"),
    path("admin/push/devices/", av.PushDeviceList.as_view(), name="api-admin-push-devices"),
    path("admin/push/recipients/", av.PushRecipientList.as_view(), name="api-admin-push-recipients"),
    path("admin/push/send/", av.PushSend.as_view(), name="api-admin-push-send"),
]
urlpatterns += router.urls
