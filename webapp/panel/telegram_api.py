"""Minimal Telegram Bot API client for the web panel.

The panel (Django/gunicorn) runs as a completely separate process from the
bot (aiogram polling loop), so it can't reuse the bot's in-memory `Bot`
instance to send messages or fetch files. Everything here talks to the
plain HTTPS Bot API directly using only the standard library, so no extra
dependency is needed just for this.

Used for two things:
  1. Notifying a user + editing admin messages when an admin approves or
     rejects a deposit from the web panel instead of from inside the bot.
  2. Proxying a payment's uploaded receipt photo (Telegram file_id) so it
     can be displayed as a normal <img> in the panel.
"""

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid

from django.conf import settings

API_BASE = "https://api.telegram.org"


def _call(method: str, payload: dict, timeout: float = 10) -> dict | None:
    token = settings.BOT_TOKEN
    if not token:
        return None
    url = f"{API_BASE}/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        # Best-effort: a Telegram notification failing should never block
        # the admin's approve/reject action from completing in the DB.
        return None


def send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> dict | None:
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _call("sendMessage", payload)


def send_photo(
    chat_id: int,
    photo_bytes: bytes,
    filename: str,
    caption: str = "",
    reply_markup: dict | None = None,
    timeout: float = 20,
) -> dict | None:
    """Send a photo (e.g. an uploaded deposit receipt) via multipart/form-data.

    Everything else in this module sends plain JSON, but sendPhoto with raw
    bytes needs an actual file upload, so this builds the multipart body by
    hand rather than pulling in an HTTP client dependency just for this.
    """
    token = settings.BOT_TOKEN
    if not token:
        return None
    url = f"{API_BASE}/bot{token}/sendPhoto"
    boundary = uuid.uuid4().hex
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    def field(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    body = bytearray()
    body += field("chat_id", str(chat_id))
    if caption:
        body += field("caption", caption)
    if reply_markup:
        body += field("reply_markup", json.dumps(reply_markup))
    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    body += photo_bytes
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url, data=bytes(body), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def edit_message_caption(chat_id: int, message_id: int, caption: str) -> bool:
    result = _call(
        "editMessageCaption",
        {"chat_id": chat_id, "message_id": message_id, "caption": caption},
    )
    return bool(result and result.get("ok"))


def edit_message_text(chat_id: int, message_id: int, text: str) -> bool:
    result = _call(
        "editMessageText",
        {"chat_id": chat_id, "message_id": message_id, "text": text},
    )
    return bool(result and result.get("ok"))


def get_file_path(file_id: str, timeout: float = 10) -> str | None:
    token = settings.BOT_TOKEN
    if not token:
        return None
    url = f"{API_BASE}/bot{token}/getFile?" + urllib.parse.urlencode({"file_id": file_id})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    if not data.get("ok"):
        return None
    return data["result"].get("file_path")


def download_file(file_path: str, timeout: float = 15) -> bytes | None:
    token = settings.BOT_TOKEN
    if not token:
        return None
    url = f"{API_BASE}/file/bot{token}/{file_path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError):
        return None
