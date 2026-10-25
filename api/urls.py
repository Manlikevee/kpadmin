from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

router = DefaultRouter()
router.register("branches", views.BranchViewSet, basename="branch")
router.register("members", views.MemberViewSet, basename="member")
router.register("workers", views.WorkerViewSet, basename="worker")
router.register("worker-applications", views.WorkerApplicationViewSet, basename="worker-application")
router.register("events", views.EventViewSet, basename="event")
router.register("announcements", views.AnnouncementViewSet, basename="announcement")
router.register("devotionals", views.DevotionalViewSet, basename="devotional")
router.register("notifications", views.NotificationViewSet, basename="notification")
router.register("prayer-requests", views.PrayerRequestViewSet, basename="prayer-request")

urlpatterns = [
    path("", views.ApiRoot.as_view(), name="api-root"),
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
]
urlpatterns += router.urls
