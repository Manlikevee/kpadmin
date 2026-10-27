
from django.urls import path

from .views import RegisterPushTokenView

urlpatterns = [
    path(
        "push-tokens/register/",
        RegisterPushTokenView.as_view(),
        name="register-push-token",
    ),
]
