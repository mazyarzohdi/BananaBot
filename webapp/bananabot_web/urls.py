import os
from django.urls import path, include
from django.views.generic.base import RedirectView

WEB_PATH = os.environ.get("WEB_PATH", "/panel").strip("/")

urlpatterns = [
    path("", RedirectView.as_view(url=f"/{WEB_PATH}/", permanent=False)),
    path(f"{WEB_PATH}/", include("panel.urls")),
    path(f"{WEB_PATH}/api/v1/", include("panel.api.urls")),
]
