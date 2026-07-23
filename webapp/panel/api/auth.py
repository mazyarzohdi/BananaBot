"""Authentication & request-security pipeline for the reseller JSON API.

Every request must pass, in order:

1. `Authorization: Bearer <api_key>` — key must parse, exist, and its
   secret must match the stored hash.
2. The API key itself must not be revoked/inactive.
3. The reseller account it belongs to must be `active` (not disabled by
   admin) — otherwise 403 RESELLER_DISABLED.
4. The reseller's plan must not be expired — otherwise 403 RESELLER_EXPIRED.
   This is enforced here, server-side, on every single request — a still
   valid API key cannot be used to bypass panel/plan expiry.
5. The underlying x-ui panel record must still be active.
6. `X-Timestamp` + `X-Nonce` headers must be present, the timestamp must
   be within the allowed clock-skew window, and the nonce must not have
   been seen before for this key (replay protection).
7. Rate limiting (per key, sliding window via the request log).

Everything is logged to `api_request_log` regardless of outcome — see
`panel.api.decorators.api_view`, which wraps this and writes the log line
after the view returns.
"""

import time
from dataclasses import dataclass

from django.conf import settings

from .. import apikeys
from .. import db as bot_db
from .. import reseller_core
from . import constants


@dataclass
class AuthResult:
    ok: bool
    http_status: int = 200
    error_code: str | None = None
    message: str | None = None
    reseller: dict | None = None
    api_key_row: dict | None = None


def _client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def authenticate(request, require_nonce: bool = True) -> AuthResult:
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return AuthResult(False, 401, "MISSING_API_KEY", "هدر Authorization: Bearer <api_key> الزامی است.")

    raw_key = auth_header[len("Bearer "):].strip()
    parsed = apikeys.parse_api_key(raw_key)
    if not parsed:
        return AuthResult(False, 401, "INVALID_API_KEY", "کلید API نامعتبر است.")
    key_id, secret = parsed

    row = bot_db.get_api_key_by_key_id(key_id)
    if not row or not apikeys.verify_secret(secret, row["key_hash"]):
        return AuthResult(False, 401, "INVALID_API_KEY", "کلید API نامعتبر است.")

    if not row.get("is_active"):
        return AuthResult(False, 401, "API_KEY_REVOKED", "این کلید API باطل شده است.")

    reseller = reseller_core.reseller_from_api_key_row(row)

    locked = reseller_core.lock_reason(reseller)
    if locked:
        error_code, message = locked
        return AuthResult(False, 403, error_code, message, reseller=reseller, api_key_row=row)

    if not reseller.get("panel_is_active"):
        return AuthResult(False, 403, "PANEL_DISABLED", "پنل مرتبط با این نمایندگی غیرفعال است.", reseller=reseller, api_key_row=row)

    # ── Rate limiting (global, per key) ──
    limit, window = constants.RATE_LIMIT_GLOBAL
    if bot_db.count_recent_requests(row["id"], window) >= limit:
        return AuthResult(False, 429, "RATE_LIMITED", "تعداد درخواست‌های شما بیش از حد مجاز است. کمی صبر کنید.", reseller=reseller, api_key_row=row)

    # ── Replay protection ──
    if require_nonce:
        timestamp_header = request.META.get("HTTP_X_TIMESTAMP", "")
        nonce = request.META.get("HTTP_X_NONCE", "")
        if not timestamp_header or not nonce:
            return AuthResult(
                False, 400, "MISSING_NONCE",
                "هدرهای X-Timestamp و X-Nonce برای هر درخواست الزامی هستند.",
                reseller=reseller, api_key_row=row,
            )
        try:
            ts = int(timestamp_header)
        except ValueError:
            return AuthResult(False, 400, "INVALID_TIMESTAMP", "X-Timestamp باید یک عدد Unix timestamp باشد.", reseller=reseller, api_key_row=row)

        if abs(int(time.time()) - ts) > constants.TIMESTAMP_WINDOW_SECONDS:
            return AuthResult(
                False, 400, "STALE_TIMESTAMP",
                f"X-Timestamp خارج از بازه‌ی مجاز است (حداکثر {constants.TIMESTAMP_WINDOW_SECONDS} ثانیه اختلاف).",
                reseller=reseller, api_key_row=row,
            )

        if len(nonce) < 8 or len(nonce) > 128:
            return AuthResult(False, 400, "INVALID_NONCE", "X-Nonce نامعتبر است.", reseller=reseller, api_key_row=row)

        if not bot_db.check_and_consume_nonce(row["id"], nonce):
            return AuthResult(
                False, 409, "REPLAY_DETECTED",
                "این درخواست قبلاً پردازش شده است (nonce تکراری).",
                reseller=reseller, api_key_row=row,
            )

    bot_db.touch_api_key_usage(row["id"], _client_ip(request))
    return AuthResult(True, 200, reseller=reseller, api_key_row=row)


def enforce_endpoint_rate_limit(api_key_id: int, endpoint: str, limit_window: tuple[int, int]) -> AuthResult | None:
    limit, window = limit_window
    if bot_db.count_recent_requests(api_key_id, window, endpoint=endpoint) >= limit:
        return AuthResult(
            False, 429, "RATE_LIMITED",
            f"تعداد درخواست‌ها به «{endpoint}» بیش از حد مجاز است. کمی صبر کنید.",
        )
    return None
