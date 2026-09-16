import os
from django.urls import path, include
from django.views.generic.base import RedirectView
from panel import game_views

WEB_PATH = os.environ.get("WEB_PATH", "/panel").strip("/")

urlpatterns = [
    path("", RedirectView.as_view(url=f"/{WEB_PATH}/", permanent=False)),
    path(f"{WEB_PATH}/", include("panel.urls")),
    path(f"{WEB_PATH}/api/v1/", include("panel.api.urls")),
    # Direct aliases so /api/game/... works regardless of WEB_PATH
    path("api/game/state/", game_views.api_game_state),
    path("api/game/sync/", game_views.api_game_sync),
    path("api/game/upgrade/", game_views.api_game_upgrade),
    path("api/game/leaderboard/", game_views.api_game_leaderboard),
    path("api/game/nickname/", game_views.api_game_nickname),
]
