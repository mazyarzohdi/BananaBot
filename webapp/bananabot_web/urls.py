"""URL configuration for BananaBot Web Panel."""

import os
from django.urls import path, include

# NOTE: panel.urls must be included exactly once. Including the same
# app_name under two different prefixes makes Django's {% url %} reversal
# ambiguous (it silently picks whichever was registered last), which breaks
# every internal link once the site is served under a WEB_PATH prefix.
WEB_PATH = os.environ.get("WEB_PATH", "/panel").strip("/")

urlpatterns = [
    path(f"{WEB_PATH}/", include("panel.urls")),
    path(f"{WEB_PATH}/api/v1/", include("panel.api.urls")),
]
