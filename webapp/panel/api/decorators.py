import functools
import json
import logging
import time

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .. import db as bot_db
from . import auth as api_auth

logger = logging.getLogger(__name__)


def _client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def api_view(endpoint: str, require_nonce: bool = True):
    """Wraps a reseller-API view with: Bearer-key auth, expiry/quota/
    status gating, replay + rate-limit protection, a full audit-log line
    for every request (success or failure), and safe JSON error handling.

    The wrapped view receives `(request, reseller, api_key_row, **kwargs)`
    and must return a `JsonResponse`. `request.body` is parsed as JSON
    ahead of time into `request.json` (empty dict if not valid JSON /
    empty body) so views don't each need to repeat that boilerplate.
    """
    def decorator(view_func):
        @csrf_exempt
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            start = time.monotonic()
            ip = _client_ip(request)
            ua = request.META.get("HTTP_USER_AGENT", "")

            try:
                request.json = json.loads(request.body.decode("utf-8")) if request.body else {}
                if not isinstance(request.json, dict):
                    request.json = {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                request.json = {}
                bad_json = True
            else:
                bad_json = False

            result = api_auth.authenticate(request, require_nonce=require_nonce)

            if bad_json and result.ok:
                result = api_auth.AuthResult(False, 400, "INVALID_JSON", "بدنه‌ی درخواست JSON معتبر نیست.",
                                              reseller=result.reseller, api_key_row=result.api_key_row)

            if not result.ok:
                response = JsonResponse(
                    {"ok": False, "error_code": result.error_code, "message": result.message},
                    status=result.http_status,
                )
                _log(request, endpoint, ip, ua, start, result.http_status, result.error_code,
                     result.api_key_row, result.reseller)
                return response

            try:
                response = view_func(request, result.reseller, result.api_key_row, *args, **kwargs)
            except Exception:
                logger.exception("api %s: unhandled error", endpoint)
                response = JsonResponse(
                    {"ok": False, "error_code": "INTERNAL_ERROR", "message": "خطای داخلی سرور."},
                    status=500,
                )
                _log(request, endpoint, ip, ua, start, 500, "INTERNAL_ERROR", result.api_key_row, result.reseller)
                return response

            error_code = ""
            if response.status_code >= 400:
                try:
                    error_code = json.loads(response.content.decode("utf-8")).get("error_code", "")
                except Exception:
                    error_code = ""
            _log(request, endpoint, ip, ua, start, response.status_code, error_code,
                 result.api_key_row, result.reseller)
            return response

        return wrapper
    return decorator


def _log(request, endpoint, ip, ua, start, status_code, error_code, api_key_row, reseller):
    try:
        bot_db.log_api_request(
            api_key_id=(api_key_row["id"] if api_key_row else None),
            reseller_id=(reseller["id"] if reseller else None),
            endpoint=endpoint, method=request.method, path=request.path,
            status_code=status_code, error_code=error_code or "", ip=ip, user_agent=ua,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception:
        logger.exception("api %s: failed to write request log", endpoint)
