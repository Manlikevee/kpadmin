from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("about/", views.AboutView.as_view(), name="about"),
    path("contact/", views.ContactView.as_view(), name="contact"),
    path("new-here/", views.NewHereView.as_view(), name="new_here"),
    path("ministries/", views.MinistriesView.as_view(), name="ministries"),
    path("gallery/", views.GalleryView.as_view(), name="gallery"),
    path("locations/", views.LocationsView.as_view(), name="locations"),
    path("give/", views.GiveView.as_view(), name="give"),
    path("prayer/", views.PrayerView.as_view(), name="prayer"),
    path("praise/", views.PraiseView.as_view(), name="praise"),
    path("devotionals/", views.DevotionalsView.as_view(), name="devotionals"),
    path("events/", views.EventsView.as_view(), name="events"),
    path("subscribe/", views.subscribe, name="subscribe"),
    path("events/<int:pk>/", views.event_detail, name="event"),
]
