"""Django Views for the Mors VPN Clicker Game REST API."""

import json
from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_http_methods
from .auth import login_required, get_current_user
from . import game_service
from . import db as bot_db


def _parse_json(request: HttpRequest) -> dict:
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return {}


@login_required
@require_http_methods(["GET"])
def api_game_state(request: HttpRequest) -> JsonResponse:
    tg_user = get_current_user(request)
    telegram_id = int(tg_user["id"])
    try:
        state = game_service.get_user_game_state(telegram_id, tg_user=tg_user)
        return JsonResponse({"success": True, **state})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def api_game_sync(request: HttpRequest) -> JsonResponse:
    tg_user = get_current_user(request)
    telegram_id = int(tg_user["id"])
    payload = _parse_json(request)

    taps = payload.get("taps", 0)
    combo_boost = bool(payload.get("comboBoost", False))

    try:
        state = game_service.process_tap_batch(telegram_id, taps, combo_boost=combo_boost)
        return JsonResponse({"success": True, **state})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@require_http_methods(["POST"])
def api_game_upgrade(request: HttpRequest) -> JsonResponse:
    tg_user = get_current_user(request)
    telegram_id = int(tg_user["id"])
    payload = _parse_json(request)
    upgrade_id = payload.get("upgradeId")

    if not upgrade_id:
        return JsonResponse({"success": False, "error": "شناسه ارتقا مشخص نشده است."}, status=400)

    try:
        state = game_service.purchase_upgrade(telegram_id, upgrade_id)
        return JsonResponse({"success": True, **state})
    except ValueError as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def api_game_leaderboard(request: HttpRequest) -> JsonResponse:
    try:
        data = game_service.get_leaderboard_data()
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def api_game_nickname(request: HttpRequest) -> JsonResponse:
    tg_user = get_current_user(request)
    telegram_id = int(tg_user["id"])
    payload = _parse_json(request)
    new_nick = (payload.get("nickname") or "").strip()

    if len(new_nick) < 2 or len(new_nick) > 24:
        return JsonResponse({"success": False, "error": "نام مستعار باید بین ۲ تا ۲۴ کاراکتر باشد."}, status=400)

    try:
        bot_db.update_game_profile(telegram_id, nickname=new_nick)
        state = game_service.get_user_game_state(telegram_id, tg_user=tg_user)
        return JsonResponse({"success": True, **state})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)
