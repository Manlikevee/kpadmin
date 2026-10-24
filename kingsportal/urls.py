from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/v1/", include("api.urls")),
    path("accounts/", include("accounts.urls")),
    path("portal/", include("church.urls")),
    path("portal/bible/", include("bible.urls")),
    path("portal/sermons/", include(("sermons.urls_admin", "sermons_admin"))),
    path("sermons/", include("sermons.urls")),
    path("", include("core.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
