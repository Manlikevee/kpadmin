from django.urls import path

from . import views_admin

urlpatterns = [
    path("", views_admin.SermonAdminList.as_view(), name="list"),
    path("refresh/", views_admin.refresh_cache, name="refresh"),
    path("<str:video_id>/", views_admin.sermon_admin_detail, name="detail"),
    path("<str:video_id>/edit/", views_admin.sermon_admin_edit, name="edit"),
]
