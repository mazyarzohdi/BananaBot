"""JSON endpoints for the reseller (نماینده) API.

All responses are JSON. All mutating endpoints (POST/PATCH/DELETE)
require `X-Timestamp` + `X-Nonce` headers in addition to the API key —
see `panel.api.auth.authenticate`. Every request is authenticated,
gated (expiry/quota/status), and logged by the `@api_view` decorator —
views below only implement the actual business action.
"""

import json

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .. import db as bot_db
from .. import reseller_core
from . import constants
from .auth import enforce_endpoint_rate_limit
from .decorators import api_view

# Maps reseller_core error codes to HTTP status codes.
_ERROR_STATUS = {
    "INVALID_INPUT": 400,
    "QUOTA_EXCEEDED": 403,
    "DURATION_EXCEEDS_RESELLER_EXPIRY": 403,
    "NO_INBOUNDS": 409,
    "PANEL_ERROR": 502,
    "PANEL_DELETE_FAILED": 502,
}


def _error_response(result: dict, default_status: int = 400) -> JsonResponse:
    status = _ERROR_STATUS.get(result["error_code"], default_status)
    return JsonResponse({"ok": False, "error_code": result["error_code"], "message": result["error"]}, status=status)


def _serialize_config(config: dict) -> dict:
    try:
        links = json.loads(config.get("config_links") or "[]")
    except (TypeError, ValueError):
        links = []
    return {
        "id": config["id"],
        "label": config.get("label") or "",
        "email": config["email"],
        "sub_id": config.get("sub_id") or "",
        "volume_gb": config["volume_gb"],
        "consumed_gb": config.get("consumed_gb") or 0,
        "expiry_time_ms": config.get("expiry_time") or 0,
        "expiry_display": reseller_core.format_expiry_ms(config.get("expiry_time") or 0),
        "config_link": config.get("config_link") or "",
        "config_links": links,
        "sub_link": config.get("sub_link") or "",
        "status": config["status"],
        "source": config.get("source") or "panel",
        "created_at": config.get("created_at"),
    }


def _get_owned_config(reseller: dict, config_id: int) -> dict | None:
    config = bot_db.get_reseller_config(config_id)
    if not config or config["reseller_id"] != reseller["id"]:
        return None
    return config


# ── Account ───────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
@api_view("get_account", require_nonce=False)
def account(request, reseller, api_key_row):
    used_gb = bot_db.get_reseller_used_gb(reseller["id"])
    remaining_gb = max(0.0, reseller["quota_gb"] - used_gb)
    return JsonResponse({
        "ok": True,
        "reseller": {
            "id": reseller["id"],
            "status": reseller["status"],
            "quota_gb": reseller["quota_gb"],
            "used_gb": round(used_gb, 3),
            "remaining_gb": round(remaining_gb, 3),
            "expires_at": reseller["expires_at"],
            "expires_at_display": reseller_core.format_ts(reseller["expires_at"]),
        },
    })


# ── Configs: list / get / create ─────────────────────────────────────────────

@require_http_methods(["GET"])
@api_view("list_configs", require_nonce=False)
def configs_list(request, reseller, api_key_row):
    include_deleted = request.GET.get("include_deleted") == "1"
    configs = bot_db.get_reseller_configs(reseller["id"], include_deleted=include_deleted)
    return JsonResponse({"ok": True, "configs": [_serialize_config(c) for c in configs]})


@require_http_methods(["GET"])
@api_view("get_config", require_nonce=False)
def config_detail(request, reseller, api_key_row, config_id: int):
    config = _get_owned_config(reseller, config_id)
    if not config:
        return JsonResponse({"ok": False, "error_code": "CONFIG_NOT_FOUND", "message": "کانفیگ پیدا نشد."}, status=404)
    return JsonResponse({"ok": True, "config": _serialize_config(config)})


@require_http_methods(["POST"])
@api_view("create_config")
def configs_create(request, reseller, api_key_row):
    limited = enforce_endpoint_rate_limit(api_key_row["id"], "create_config", constants.RATE_LIMIT_CREATE_CONFIG)
    if limited:
        return JsonResponse({"ok": False, "error_code": limited.error_code, "message": limited.message}, status=limited.http_status)

    body = request.json
    label = str(body.get("label") or "").strip()[:100]
    try:
        volume_gb = float(body.get("volume_gb"))
        duration_days = int(body.get("duration_days"))
    except (TypeError, ValueError):
        return JsonResponse(
            {"ok": False, "error_code": "INVALID_INPUT", "message": "volume_gb و duration_days الزامی و باید عددی باشند."},
            status=400,
        )

    result = reseller_core.create_config(
        reseller, reseller["telegram_id"], label, volume_gb, duration_days,
        source="api", api_key_id=api_key_row["id"],
    )
    if not result["ok"]:
        return _error_response(result)
    return JsonResponse({"ok": True, "config": _serialize_config(result["config"])}, status=201)


# ── Configs: update / rename / toggle / delete ───────────────────────────────

@require_http_methods(["PATCH"])
@api_view("update_config")
def config_update(request, reseller, api_key_row, config_id: int):
    limited = enforce_endpoint_rate_limit(api_key_row["id"], "mutate_config", constants.RATE_LIMIT_MUTATIONS)
    if limited:
        return JsonResponse({"ok": False, "error_code": limited.error_code, "message": limited.message}, status=limited.http_status)

    config = _get_owned_config(reseller, config_id)
    if not config:
        return JsonResponse({"ok": False, "error_code": "CONFIG_NOT_FOUND", "message": "کانفیگ پیدا نشد."}, status=404)

    body = request.json
    if "label" in body and "volume_gb" not in body and "duration_days" not in body:
        result = reseller_core.rename_config(config, str(body.get("label") or "").strip()[:100])
        return JsonResponse({"ok": True, "config": _serialize_config(result["config"])})

    try:
        volume_gb = float(body.get("volume_gb"))
        duration_days = int(body.get("duration_days"))
    except (TypeError, ValueError):
        return JsonResponse(
            {"ok": False, "error_code": "INVALID_INPUT", "message": "برای تمدید/ویرایش، volume_gb و duration_days الزامی هستند."},
            status=400,
        )

    result = reseller_core.update_config(reseller, config, volume_gb, duration_days)
    if not result["ok"]:
        return _error_response(result)
    return JsonResponse({"ok": True, "config": _serialize_config(result["config"])})


@require_http_methods(["POST"])
@api_view("toggle_config")
def config_toggle(request, reseller, api_key_row, config_id: int):
    limited = enforce_endpoint_rate_limit(api_key_row["id"], "mutate_config", constants.RATE_LIMIT_MUTATIONS)
    if limited:
        return JsonResponse({"ok": False, "error_code": limited.error_code, "message": limited.message}, status=limited.http_status)

    config = _get_owned_config(reseller, config_id)
    if not config:
        return JsonResponse({"ok": False, "error_code": "CONFIG_NOT_FOUND", "message": "کانفیگ پیدا نشد."}, status=404)

    body = request.json
    enable = body.get("enable")
    if enable is not None and not isinstance(enable, bool):
        return JsonResponse({"ok": False, "error_code": "INVALID_INPUT", "message": "enable باید true یا false باشد."}, status=400)

    result = reseller_core.toggle_config(reseller, config, enable=enable)
    if not result["ok"]:
        return _error_response(result)
    return JsonResponse({"ok": True, "config": _serialize_config(result["config"])})


@require_http_methods(["DELETE"])
@api_view("delete_config")
def config_delete(request, reseller, api_key_row, config_id: int):
    limited = enforce_endpoint_rate_limit(api_key_row["id"], "mutate_config", constants.RATE_LIMIT_MUTATIONS)
    if limited:
        return JsonResponse({"ok": False, "error_code": limited.error_code, "message": limited.message}, status=limited.http_status)

    config = _get_owned_config(reseller, config_id)
    if not config:
        return JsonResponse({"ok": False, "error_code": "CONFIG_NOT_FOUND", "message": "کانفیگ پیدا نشد."}, status=404)

    result = reseller_core.delete_config(reseller, config)
    if not result["ok"]:
        return _error_response(result)
    c = result["config"]
    return JsonResponse({
        "ok": True,
        "config": _serialize_config(c),
        "freed_gb": c.get("_freed_gb", 0),
        "window_used_gb": c.get("_window_used_gb", 0),
    })
