"""Minimal synchronous 3x-ui (MHSanaei) panel API client, for the Django
web panel process.

The bot already has a full async client (services/xui_client.py, built on
aiohttp) — but that process is a separate aiogram polling loop, and the
panel's venv doesn't include aiohttp. Since the panel only ever needs to
delete a client (when an admin removes a user's active service from the
web UI), this only implements that one endpoint, using the same request
shape as the bot's client so both stay compatible with the same 3x-ui
panel installs.
"""

import json
import random
import string
import time
import urllib.error
import urllib.request
from typing import Any


class XUIError(Exception):
    pass


def _request(base_url: str, api_token: str, method: str, path: str, data: Any = None, timeout: float = 15) -> dict:
    url = base_url.rstrip("/") + path
    body = json.dumps(data if data is not None else {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as e:
        raise XUIError(str(e)) from e
    try:
        result = json.loads(text) if text else {}
    except ValueError as e:
        raise XUIError(f"پاسخ نامعتبر از پنل: {e}") from e
    if not isinstance(result, dict):
        # برخی endpoint ها گاهی یک لیست/رشته خام یا null برمی‌گردانند؛
        # نرمالایز می‌کنیم تا فراخوانی‌های بعدی .get(...) کرش نکنند.
        result = {"obj": result}
    if result.get("success") is False:
        raise XUIError(result.get("msg", "خطای پنل"))
    return result


def add_client(
    base_url: str, api_token: str, inbound_ids: list[int], email: str,
    total_gb: float, expiry_time_ms: int, sub_id: str = "", tg_id: int = 0,
    comment: str = "", on_hold: bool = False, timeout: float = 15,
) -> None:
    total_bytes = int(total_gb * (1024 ** 3)) if total_gb > 0 else 0
    client_data: dict[str, Any] = {
        "email": email, "totalGB": total_bytes, "expiryTime": expiry_time_ms,
        "tgId": tg_id, "comment": comment, "enable": True,
    }
    if sub_id:
        client_data["subId"] = sub_id
    _request(base_url, api_token, "POST", "/panel/api/clients/add", {
        "inboundIds": inbound_ids, "client": client_data,
    }, timeout=timeout)


def get_client(base_url: str, api_token: str, email: str, timeout: float = 15) -> dict | None:
    result = _request(base_url, api_token, "GET", f"/panel/api/clients/get/{email}", timeout=timeout)
    return result.get("obj")


def update_client(base_url: str, api_token: str, email: str, client_data: dict, timeout: float = 15) -> None:
    _request(base_url, api_token, "POST", f"/panel/api/clients/update/{email}", client_data, timeout=timeout)


def reset_client_traffic(base_url: str, api_token: str, email: str, timeout: float = 15) -> None:
    _request(base_url, api_token, "POST", f"/panel/api/clients/resetTraffic/{email}", {}, timeout=timeout)


def get_client_links(base_url: str, api_token: str, email: str, timeout: float = 15) -> list[str]:
    result = _request(base_url, api_token, "GET", f"/panel/api/clients/links/{email}", timeout=timeout)
    obj = result.get("obj", [])
    if isinstance(obj, list):
        return obj
    if isinstance(obj, str):
        return [obj] if obj else []
    return []


def get_client_traffic(base_url: str, api_token: str, email: str, timeout: float = 15) -> dict:
    result = _request(base_url, api_token, "GET", f"/panel/api/clients/traffic/{email}", timeout=timeout)
    return result.get("obj") or {}


def compute_expiry_ms(duration_days: int, on_hold: bool = False) -> int:
    if duration_days <= 0:
        return 0
    if on_hold:
        return -duration_days * 86400000
    return (int(time.time()) + duration_days * 86400) * 1000


def generate_client_email(telegram_id: int, suffix: str = "") -> str:
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    base = f"rs{telegram_id}_{rand}"
    return f"{base}{suffix}" if suffix else base


def generate_sub_id() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=16))


def delete_client(base_url: str, api_token: str, email: str, keep_traffic: bool = False, timeout: float = 15) -> bool:
    """Delete a client from a 3x-ui panel. Returns True on confirmed
    success, False otherwise (network error, auth error, or the panel
    reporting failure) — the caller decides whether that's fatal."""
    if not base_url or not api_token or not email:
        return False

    path = f"/panel/api/clients/del/{email}"
    if keep_traffic:
        path += "?keepTraffic=1"
    url = base_url.rstrip("/") + path

    req = urllib.request.Request(
        url, data=b"{}", method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False

    if isinstance(body, dict) and body.get("success") is False:
        return False
    return True
