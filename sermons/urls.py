from django.urls import path

from . import views

app_name = "sermons"

urlpatterns = [
    path("", views.sermon_list, name="list"),
    path("live-status/", views.live_status, name="live_status"),
    path("<str:video_id>/", views.sermon_detail, name="detail"),
]
