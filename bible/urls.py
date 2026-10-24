from django.urls import path

from . import views

app_name = "bible"

urlpatterns = [
    path("", views.BibleListView.as_view(), name="list"),
    path("upload/", views.BibleUploadView.as_view(), name="upload"),
    path("<int:pk>/replace/", views.BibleReplaceView.as_view(), name="replace"),
    path("<int:pk>/delete/", views.BibleDeleteView.as_view(), name="delete"),
]
