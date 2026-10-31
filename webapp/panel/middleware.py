"""Middleware needed for the panel to work as a Telegram Mini App.

Django's default XFrameOptionsMiddleware sends `X-Frame-Options: DENY`,
which blocks the page from being embedded in *any* frame. Telegram Desktop
(and some other Telegram clients) render Mini Apps inside an embedded
webview that behaves like an iframe, so DENY silently breaks the Mini App
there (blank/white screen, page "refuses to connect"). Mobile clients are
less strict, which is why this can look like it "mostly works" until
someone opens it on desktop.

We replace the blanket DENY with a Content-Security-Policy that only
allows framing from Telegram's own domains, which keeps the page safe from
being embedded on arbitrary third-party sites while still letting Telegram
itself display it.
"""




from django.conf import settings

TELEGRAM_ALLOWED_FRAME_ANCESTORS = (
    "'self' https://web.telegram.org https://webk.telegram.org "
    "https://webz.telegram.org https://*.telegram.org https://*.web.telegram.org"
)


class TelegramEmbedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path.rstrip("/")
        admin_prefix = f"{settings.WEB_PATH}/admin"

        # Admin routes must never be framed under any circumstances (prevent Clickjacking)
        if path.startswith(admin_prefix) or path == admin_prefix:
            response["X-Frame-Options"] = "DENY"
            response["Content-Security-Policy"] = "frame-ancestors 'none'"
            return response

        # User and Mini App routes: only allow framing from official Telegram domains
        if "X-Frame-Options" in response:
            del response["X-Frame-Options"]
        response["Content-Security-Policy"] = f"frame-ancestors {TELEGRAM_ALLOWED_FRAME_ANCESTORS}"
        return response


import json
import logging
import secrets
import traceback
from . import db as bot_db
from .auth import get_current_user

error_logger = logging.getLogger("panel.errors")


class ExceptionLoggingMiddleware:
    """Catches unhandled exceptions in Django request processing and logs
    them to user_error_logs table and log files with a generated tracking code."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        tracking_code = f"ERR-{secrets.token_hex(3).upper()}"
        request._error_tracking_code = tracking_code

        tg_user = get_current_user(request)
        telegram_id = int(tg_user["id"]) if (tg_user and "id" in tg_user) else None
        user_id = None
        if telegram_id:
            try:
                with bot_db.get_conn() as conn:
                    row = conn.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
                    if row:
                        user_id = row["id"]
            except Exception:
                pass

        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
        client_info = {
            "ip": ip,
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255],
            "method": request.method,
            "path": request.path,
        }

        tb_str = traceback.format_exc()
        error_type = type(exception).__name__
        error_msg = str(exception) or error_type

        error_logger.error(
            "Unhandled Web Error [%s] at %s %s: %s\n%s",
            tracking_code,
            request.method,
            request.path,
            error_msg,
            tb_str,
        )

        try:
            bot_db.insert_user_error_log(
                tracking_code=tracking_code,
                source="web_backend",
                error_type=error_type,
                error_message=error_msg[:1000],
                stack_trace=tb_str,
                user_id=user_id,
                telegram_id=telegram_id,
                severity="critical",
                request_url=request.build_absolute_uri(),
                client_info=json.dumps(client_info, ensure_ascii=False),
            )
        except Exception as db_exc:
            error_logger.warning("Failed to save exception to database: %s", db_exc)

        return None  # Let standard Django exception / 500 handling continue
