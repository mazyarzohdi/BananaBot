import os
from django.urls import path, include
from django.views.generic.base import RedirectView

from panel import views as panel_views

WEB_PATH = os.environ.get("WEB_PATH", "/panel").strip("/")

handler404 = "panel.views.custom_error_404"
handler500 = "panel.views.custom_error_500"

urlpatterns = [
    path("", RedirectView.as_view(url=f"/{WEB_PATH}/", permanent=False)),
    path(f"{WEB_PATH}/", include("panel.urls")),
    path(f"{WEB_PATH}/api/v1/", include("panel.api.urls")),
    # Direct alias so CardGozar callback works regardless of WEB_PATH
    path("api/payments/cardgozar/callback/", panel_views.cardgozar_callback, name="root_cardgozar_callback"),
]
