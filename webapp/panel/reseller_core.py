"""Shared reseller (نماینده) business logic.

This is the SINGLE source of truth for every security-relevant rule around
reseller configs: expiry, active/disabled status, and remaining quota.
Both the Mini App web UI (`views.reseller_panel`) and the JSON API
(`api.views`) call into these functions instead of re-implementing the
checks — so a reseller can never get a looser set of rules by going
through one surface instead of the other.

Every mutating function returns a small result dict:
    {"ok": bool, "error_code": str | None, "error": str | None, "config": dict | None}

`error_code` is a stable machine-readable string (e.g. "RESELLER_EXPIRED",
"QUOTA_EXCEEDED") meant for the API's JSON responses. `error` is a
human-readable Persian message meant for the web UI's flash messages. The
API also sends `error` back as `message` so API consumers get a readable
string too, without having to hardcode every code's wording themselves.
"""

import json
import logging
import time
from datetime import datetime

from . import db as bot_db
from . import xui_client

logger = logging.getLogger(__name__)


def reseller_from_api_key_row(row: dict) -> dict:
    """Normalizes the wide join row returned by `db.get_api_key_by_key_id`
    into the same reseller dict shape produced by `db.get_reseller_by_user_id`
    / `db.get_reseller`, so reseller_core's functions work identically
    regardless of which surface (Mini App session or API key) is calling."""
    return {
        "id": row["reseller_id"],
        "user_id": row["reseller_user_id"],
        "telegram_id": row["telegram_id"],
        "panel_id": row["panel_id"],
        "quota_gb": row["quota_gb"],
        "expires_at": row["reseller_expires_at"],
        "status": row["reseller_status"],
        "panel_url": row["panel_url"],
        "api_token": row["api_token"],
        "inbound_ids": row["inbound_ids"],
        "sub_link_template": row["sub_link_template"],
        "on_hold": row["on_hold"],
        "panel_is_active": row["panel_is_active"],
    }


def reseller_locked(reseller: dict) -> bool:
    """True if the reseller's panel/token must not be usable at all right
    now: account disabled by admin, OR the reseller plan itself expired."""
    if not reseller:
        return True
    if reseller.get("status") != "active":
        return True
    expires_at = reseller.get("expires_at") or 0
    return bool(expires_at) and expires_at < int(time.time())


def lock_reason(reseller: dict) -> tuple[str, str] | None:
    """Returns (error_code, persian_message) if the reseller is locked,
    else None. Distinguishes disabled-by-admin from expired-plan since the
    API contract calls for a dedicated RESELLER_EXPIRED code."""
    if not reseller:
        return "RESELLER_NOT_FOUND", "حساب نمایندگی یافت نشد."
    if reseller.get("status") != "active":
        return "RESELLER_DISABLED", "حساب نمایندگی شما توسط ادمین غیرفعال شده است."
    expires_at = reseller.get("expires_at") or 0
    if expires_at and expires_at < int(time.time()):
        return "RESELLER_EXPIRED", "مهلت پلن نمایندگی شما به پایان رسیده است."
    return None


def quota_available(reseller: dict, exclude_config_id: int | None = None) -> float:
    used = bot_db.get_reseller_used_gb(reseller["id"])
    if exclude_config_id:
        cfg = bot_db.get_reseller_config(exclude_config_id)
        if cfg and cfg["status"] != "deleted":
            used -= cfg["volume_gb"]
    return max(0.0, reseller["quota_gb"] - used)


def build_sub_link(reseller: dict, sub_id: str) -> str:
    template = reseller.get("sub_link_template") or ""
    if not template or not sub_id:
        return ""
    try:
        return template.format(sub_id=sub_id)
    except (KeyError, IndexError):
        return ""


def format_ts(ts: int) -> str:
    if not ts:
        return "نامحدود"
    if ts < int(time.time()):
        return "منقضی‌شده"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def format_expiry_ms(ms: int) -> str:
    if not ms:
        return "نامحدود"
    if ms < 0:
        return f"{abs(ms) // 86400000} روز پس از اولین اتصال"
    secs = ms / 1000
    if secs < time.time():
        return "منقضی‌شده"
    return datetime.fromtimestamp(secs).strftime("%Y-%m-%d %H:%M")


def annotate_config_usage(reseller: dict, configs: list[dict]) -> None:
    panel_url = reseller.get("panel_url")
    api_token = reseller.get("api_token")
    for c in configs:
        c["expiry_display"] = format_expiry_ms(c.get("expiry_time") or 0)
        if c["status"] == "deleted":
            continue
        try:
            traffic = xui_client.get_client_traffic(panel_url, api_token, c["email"])
            up = traffic.get("up") or 0
            down = traffic.get("down") or 0
            c["usage_used_gb"] = (up + down) / (1024 ** 3)
        except Exception:
            logger.warning("reseller usage annotate: could not fetch traffic for %s", c.get("email"))
            c["usage_used_gb"] = None

        if c["usage_used_gb"] is None:
            c["usage_remaining_gb"] = None
            c["usage_percent"] = None
        elif c["volume_gb"] > 0:
            c["usage_remaining_gb"] = max(0.0, c["volume_gb"] - c["usage_used_gb"])
            c["usage_percent"] = min(100, round((c["usage_used_gb"] / c["volume_gb"]) * 100))
        else:
            c["usage_remaining_gb"] = None
            c["usage_percent"] = 0


def _result(ok: bool, error_code: str | None = None, error: str | None = None, config: dict | None = None) -> dict:
    return {"ok": ok, "error_code": error_code, "error": error, "config": config}


def _panel_ids(reseller: dict) -> tuple[str, str, list[int], bool]:
    try:
        inbound_ids = json.loads(reseller.get("inbound_ids") or "[]")
    except (TypeError, ValueError):
        inbound_ids = []
    on_hold = bool(reseller.get("on_hold"))
    return reseller.get("panel_url"), reseller.get("api_token"), inbound_ids, on_hold


def create_config(
    reseller: dict, tg_id: int, label: str, volume_gb: float, duration_days: int,
    source: str = "panel", api_key_id: int | None = None,
) -> dict:
    """Creates a new client on the x-ui panel + a reseller_configs row.
    Enforces: reseller not locked (checked by caller beforehand — kept out
    of here so callers can produce the right error_code/status), positive
    volume/duration, remaining quota, and duration not exceeding the
    reseller plan's own expiry."""
    if volume_gb <= 0 or duration_days <= 0:
        return _result(False, "INVALID_INPUT", "حجم و زمان باید بزرگتر از صفر باشند.")

    available = quota_available(reseller)
    if volume_gb > available:
        return _result(
            False, "QUOTA_EXCEEDED",
            f"حجم درخواستی بیشتر از حجم باقیمانده شماست ({available:.2f} GB).",
        )

    panel_url, api_token, inbound_ids, on_hold = _panel_ids(reseller)
    expiry_ms = xui_client.compute_expiry_ms(duration_days, on_hold=on_hold)
    if not on_hold and reseller.get("expires_at") and expiry_ms > reseller["expires_at"] * 1000:
        return _result(
            False, "DURATION_EXCEEDS_RESELLER_EXPIRY",
            "مدت درخواستی از تاریخ انقضای پلن نمایندگی شما بیشتر است.",
        )

    if not inbound_ids:
        return _result(False, "NO_INBOUNDS", "برای این پنل Inbound تنظیم نشده. با ادمین تماس بگیرید.")

    email = xui_client.generate_client_email(int(tg_id))
    sub_id = xui_client.generate_sub_id()
    try:
        xui_client.add_client(
            panel_url, api_token, inbound_ids, email,
            volume_gb, expiry_ms, sub_id=sub_id, tg_id=int(tg_id),
            comment=f"reseller_{reseller['id']}", on_hold=on_hold,
        )
    except xui_client.XUIError as e:
        return _result(False, "PANEL_ERROR", f"خطا در ساخت کانفیگ روی پنل: {e}")

    # کلاینت روی پنل ساخته شد؛ از اینجا به بعد هرچه پیش بیاید باید رکورد را
    # در دیتابیس ذخیره کنیم چون کانفیگ واقعاً وجود دارد. گرفتن لینک‌ها صرفاً
    # یک قابلیت جانبی است، نباید کل عملیات را با یک خطای غیرمنتظره متوقف کند.
    try:
        links = xui_client.get_client_links(panel_url, api_token, email)
    except Exception:
        logger.exception("create_config: get_client_links failed for %s", email)
        links = []

    try:
        sub_link = build_sub_link(reseller, sub_id)
    except Exception:
        sub_link = ""

    config_id = bot_db.add_reseller_config(
        reseller_id=reseller["id"], label=label, email=email, sub_id=sub_id,
        volume_gb=volume_gb, expiry_time=expiry_ms,
        config_link=(links[0] if links else ""), config_links=json.dumps(links),
        sub_link=sub_link, status="active", source=source, api_key_id=api_key_id,
    )
    config = bot_db.get_reseller_config(config_id)
    return _result(True, config=config)


def update_config(reseller: dict, config: dict, volume_gb: float, duration_days: int) -> dict:
    if volume_gb <= 0 or duration_days <= 0:
        return _result(False, "INVALID_INPUT", "حجم و زمان باید بزرگتر از صفر باشند.")

    available = quota_available(reseller, exclude_config_id=config["id"])
    if volume_gb > available:
        return _result(
            False, "QUOTA_EXCEEDED",
            f"حجم درخواستی بیشتر از حجم باقیمانده شماست ({available:.2f} GB).",
        )

    panel_url, api_token, _inbound_ids, on_hold = _panel_ids(reseller)
    expiry_ms = xui_client.compute_expiry_ms(duration_days, on_hold=on_hold)
    if not on_hold and reseller.get("expires_at") and expiry_ms > reseller["expires_at"] * 1000:
        return _result(
            False, "DURATION_EXCEEDS_RESELLER_EXPIRY",
            "مدت درخواستی از تاریخ انقضای پلن نمایندگی شما بیشتر است.",
        )

    try:
        client_data = xui_client.get_client(panel_url, api_token, config["email"]) or {}
        client_data.update({
            "email": config["email"],
            "totalGB": int(volume_gb * (1024 ** 3)),
            "expiryTime": expiry_ms,
            "enable": True,
        })
        xui_client.update_client(panel_url, api_token, config["email"], client_data)
    except xui_client.XUIError as e:
        return _result(False, "PANEL_ERROR", f"خطا در بروزرسانی کانفیگ روی پنل: {e}")
    except Exception:
        logger.exception("update_config: unexpected error for config #%s", config["id"])
        return _result(False, "PANEL_ERROR", "خطای غیرمنتظره در ارتباط با پنل. دوباره تلاش کنید.")

    # مهم: قبل از ریست ترافیک، حجمِ واقعیِ مصرف‌شده‌ی همین پنجره را می‌گیریم
    # و برای همیشه به consumed_gb اضافه می‌کنیم، تا نماینده نتواند با
    # «تمدید و حذف» مکرر یک کانفیگِ پرمصرف، مصرف واقعی را دور بزند.
    try:
        traffic = xui_client.get_client_traffic(panel_url, api_token, config["email"])
        up = traffic.get("up") or 0
        down = traffic.get("down") or 0
        window_used_gb = (up + down) / (1024 ** 3)
    except Exception:
        logger.exception("update_config: get_client_traffic failed for config #%s", config["id"])
        window_used_gb = config["volume_gb"]
    window_used_gb = max(0.0, min(window_used_gb, config["volume_gb"]))
    new_consumed_gb = (config.get("consumed_gb") or 0) + window_used_gb

    try:
        xui_client.reset_client_traffic(panel_url, api_token, config["email"])
    except Exception:
        logger.exception("update_config: reset_client_traffic failed for config #%s", config["id"])

    bot_db.update_reseller_config(
        config["id"], volume_gb=volume_gb, expiry_time=expiry_ms, status="active",
        consumed_gb=round(new_consumed_gb, 3),
    )
    updated = bot_db.get_reseller_config(config["id"])
    return _result(True, config=updated)


def toggle_config(reseller: dict, config: dict, enable: bool | None = None) -> dict:
    new_status = "active" if (enable if enable is not None else config["status"] != "active") else "disabled"
    panel_url, api_token, _inbound_ids, _on_hold = _panel_ids(reseller)
    try:
        client_data = xui_client.get_client(panel_url, api_token, config["email"]) or {}
    except Exception:
        logger.warning("toggle_config: get_client failed for config #%s, using local record only", config["id"])
        client_data = {}
    # امنیتی: حجم/انقضا/subId را همیشه از رکورد محلی (منبع معتبر) صراحتاً ست
    # می‌کنیم، نه از پاسخ پنل — تا مقادیر غایب در پاسخ پنل کانفیگ را ناخواسته
    # "نامحدود" نکند.
    client_data.update({
        "email": config["email"],
        "totalGB": int(config["volume_gb"] * (1024 ** 3)),
        "expiryTime": config["expiry_time"],
        "enable": (new_status == "active"),
    })
    if config.get("sub_id"):
        client_data["subId"] = config["sub_id"]
    try:
        xui_client.update_client(panel_url, api_token, config["email"], client_data)
    except xui_client.XUIError as e:
        return _result(False, "PANEL_ERROR", f"خطا در تغییر وضعیت روی پنل: {e}")
    except Exception:
        logger.exception("toggle_config: unexpected error for config #%s", config["id"])
        return _result(False, "PANEL_ERROR", "خطای غیرمنتظره در ارتباط با پنل. دوباره تلاش کنید.")

    bot_db.update_reseller_config(config["id"], status=new_status)
    updated = bot_db.get_reseller_config(config["id"])
    return _result(True, config=updated)


def rename_config(config: dict, label: str) -> dict:
    bot_db.update_reseller_config(config["id"], label=label)
    updated = bot_db.get_reseller_config(config["id"])
    return _result(True, config=updated)


def delete_config(reseller: dict, config: dict) -> dict:
    panel_url, api_token, _inbound_ids, _on_hold = _panel_ids(reseller)

    # قبل از حذف، حجم واقعیِ مصرف‌شده‌ی همین پنجره را از پنل می‌گیریم و روی
    # consumed_gb قبلی جمع می‌کنیم؛ فقط حجمِ استفاده‌نشده‌ی همین پنجره به سقف
    # نماینده برمی‌گردد. وگرنه نماینده می‌توانست با ساخت/حذف مکرر، حجم
    # مصرف‌شده‌ی واقعی را دور بزند.
    try:
        traffic = xui_client.get_client_traffic(panel_url, api_token, config["email"])
        up = traffic.get("up") or 0
        down = traffic.get("down") or 0
        window_used_gb = (up + down) / (1024 ** 3)
    except Exception:
        logger.exception("delete_config: get_client_traffic failed for config #%s", config["id"])
        window_used_gb = config["volume_gb"]

    window_used_gb = max(0.0, min(window_used_gb, config["volume_gb"]))
    freed_gb = config["volume_gb"] - window_used_gb
    total_consumed_gb = (config.get("consumed_gb") or 0) + window_used_gb

    # حذفِ واقعی از پنل باید تأیید شود؛ اگر ناموفق باشد و کلاینت همچنان روی
    # پنل زنده باشد، هرگز کانفیگ را «حذف‌شده» علامت نمی‌زنیم و حجمی هم آزاد
    # نمی‌شود — وگرنه کانفیگ روی پنل زنده و قابل‌استفاده می‌ماند در حالی که
    # از دید سیستم ما حذف‌شده و حجمش هم آزاد شده (سوءاستفاده).
    try:
        deleted_ok = xui_client.delete_client(panel_url, api_token, config["email"])
    except Exception:
        logger.exception("delete_config: delete_client raised for config #%s", config["id"])
        deleted_ok = False

    if not deleted_ok:
        still_exists = True
        try:
            existing = xui_client.get_client(panel_url, api_token, config["email"])
            still_exists = bool(existing)
        except Exception:
            still_exists = True
        if still_exists:
            return _result(
                False, "PANEL_DELETE_FAILED",
                "حذف کانفیگ از روی پنل ناموفق بود. برای جلوگیری از هرگونه مغایرت، کانفیگ در سیستم حذف نشد.",
            )

    bot_db.update_reseller_config(config["id"], status="deleted", consumed_gb=round(total_consumed_gb, 3))
    updated = bot_db.get_reseller_config(config["id"])
    updated["_freed_gb"] = round(freed_gb, 3)
    updated["_window_used_gb"] = round(window_used_gb, 3)
    return _result(True, config=updated)
