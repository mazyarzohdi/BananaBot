"""Telegram authentication helpers.

BananaBot's panel supports two separate Telegram auth flows, which use two
different signing algorithms per Telegram's own docs — mixing them up is a
common cause of "auth always fails":

- Login Widget (browser access, telegram-widget.js): secret_key = SHA256(bot_token)
- Mini App / WebApp (opened from inside the bot via a web_app button):
  secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
"""

import hashlib
import hmac
import json
import time
import urllib.parse
from functools import wraps
from django.conf import settings
from django.shortcuts import redirect
from django.http import HttpRequest


def verify_telegram_auth(data: dict) -> bool:
    """Verify data received from Telegram Login Widget (browser login)."""
    token = settings.BOT_TOKEN
    if not token:
        return False

    check_hash = data.pop("hash", "")
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items())
    )
    secret_key = hashlib.sha256(token.encode()).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, check_hash):
        return False

    # Auth must not be older than 24 hours
    auth_date = int(data.get("auth_date", 0))
    if time.time() - auth_date > 86400:
        return False

    return True


def verify_webapp_init_data(init_data: str, max_age_seconds: int = 86400) -> dict | None:
    """Verify the `initData` string a Telegram Mini App sends to its backend.

    Returns the parsed Telegram user dict on success, or None if the data is
    missing, malformed, unsigned by our bot, or expired.
    """
    token = settings.BOT_TOKEN
    if not token or not init_data:
        return None

    try:
        pairs = urllib.parse.parse_qsl(init_data, strict_parsing=True)
    except ValueError:
        return None

    data = dict(pairs)
    check_hash = data.pop("hash", None)
    if not check_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))

    # Per Telegram docs: secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, check_hash):
        return None

    auth_date = int(data.get("auth_date", 0))
    if time.time() - auth_date > max_age_seconds:
        return None

    try:
        user = json.loads(data.get("user", "{}"))
    except (json.JSONDecodeError, TypeError):
        return None

    if not user or "id" not in user:
        return None

    return user


def login_required(view_func):
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        if not request.session.get("tg_user"):
            return redirect("panel:login")
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        tg_user = request.session.get("tg_user")
        if not tg_user:
            return redirect("panel:login")
        if int(tg_user["id"]) not in settings.ADMIN_TELEGRAM_IDS:
            return redirect("panel:dashboard")
        return view_func(request, *args, **kwargs)
    return wrapper


def get_current_user(request: HttpRequest) -> dict | None:
    return request.session.get("tg_user")


def is_admin(request: HttpRequest) -> bool:
    user = get_current_user(request)
    if not user:
        return False
    return int(user["id"]) in settings.ADMIN_TELEGRAM_IDS
