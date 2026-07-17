"""Standalone auto-payment (bank SMS) webhook server.

Runs as its own systemd service (bananabot-webhook) on its OWN port —
deliberately separate from the web panel's port, so it can be exposed,
firewalled, or reconfigured independently. Uses ONLY the Python standard
library (http.server, sqlite3, urllib) so it has zero third-party
dependencies and doesn't share a process (or a port) with either the bot
or the Django web panel.

The port is read from the shared `settings` DB table (key:
auto_payment_port) once at startup. Changing it from the bot's own admin
settings menu (⚙️ تنظیمات ربات → 🔌 پورت وبهوک پرداخت خودکار) restarts this
service automatically so the new port takes effect right away — see
bot/handlers/admin.py's cfg_save_value.

Enabling/disabling auto-payment itself (auto_payment_enabled) does NOT
require a restart: this process keeps running either way and just replies
"disabled" while it's off, so toggling it is instant.
"""

import hmac
import json
import logging
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] payment_webhook: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("payment_webhook")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("DATABASE_PATH", "data/bot.db")
if not os.path.isabs(DB_PATH):
    DB_PATH = str(BASE_DIR / DB_PATH)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

TELEGRAM_API_BASE = "https://api.telegram.org"

# Persian bank SMS formats vary by bank/direction. Some put the label
# BEFORE the amount:
#   "بانك ملي ايران\nانتقال: 659,775+\nحساب:5556\nمانده:,015,\n1130-14:35"
#                    ^^^^^^^ this is what we want (659,775 Rial, ignoring
#                    the trailing +/- sign some banks add)
# Others put the amount BEFORE the label:
#   "بانک ملی 658,230 :انتقال حساب 9,790,323 :مانده 0306-08:44"
#                ^^^^^^^ same thing, other direction
# Both are tried, label-before-amount first since it's the more commonly
# seen format.
_LABEL_THEN_AMOUNT_RE = re.compile(r"(?:انتقال|واریز)\s*:\s*([\d,]+)")
_AMOUNT_THEN_LABEL_RE = re.compile(r"([\d,]+)\s*:\s*(?:انتقال|واریز)")


def parse_transfer_amount_rial(sms_text: str) -> int | None:
    """Extracts the transferred amount (in Rials, as-is — no conversion)
    from a Persian bank SMS, trying both label/amount orderings. Example:
    'انتقال: 659,775+' -> 659775
    """
    if not sms_text:
        return None
    match = _LABEL_THEN_AMOUNT_RE.search(sms_text) or _AMOUNT_THEN_LABEL_RE.search(sms_text)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def get_payment_by_expected_amount(amount: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT py.*, u.telegram_id FROM payments py JOIN users u ON py.user_id = u.id "
            "WHERE py.expected_amount = ? AND py.status = 'pending' "
            "AND (py.expires_at IS NULL OR py.expires_at > datetime('now')) "
            "ORDER BY py.id DESC LIMIT 1",
            (amount,),
        ).fetchone()
    return dict(row) if row else None


def approve_payment(payment_id: int) -> bool:
    """Only acts if still pending — race-safe against a human admin
    approving/rejecting the same payment at the same instant."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if not row or row["status"] != "pending":
            return False
        conn.execute(
            "UPDATE payments SET status='approved', admin_note='تایید خودکار (پیامک بانکی)' WHERE id=?",
            (payment_id,),
        )
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE id=?",
            (row["amount"], row["user_id"]),
        )
        conn.commit()
        return True


def get_product(product_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return dict(row) if row else None


def get_reseller_plan(plan_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM reseller_plans WHERE id = ?", (plan_id,)).fetchone()
    return dict(row) if row else None


def get_user_balance(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["balance"] if row else 0


def send_telegram_message(chat_id: int, text: str, reply_markup: dict | None = None):
    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN not available to this process — cannot notify user %s.", chat_id)
        return
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    req = urllib.request.Request(
        f"{TELEGRAM_API_BASE}/bot{BOT_TOKEN}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except (urllib.error.URLError, TimeoutError):
        logger.exception("Failed to notify user %s", chat_id)


def notify_payment_approved(payment: dict):
    telegram_id = payment.get("telegram_id")
    if not telegram_id:
        return
    text = f"✅ پرداخت شما تأیید شد.\n💰 موجودی: {get_user_balance(payment['user_id']):,} تومان"
    reply_markup = None
    if payment.get("renew_sub_id"):
        text += f"\n\nحالا می‌توانید تمدید سرویس #{payment['renew_sub_id']} را تکمیل کنید 👇"
        reply_markup = {"inline_keyboard": [[
            {"text": "🔁 تکمیل تمدید سرویس", "callback_data": f"svc_renew_ok:{payment['renew_sub_id']}"},
        ]]}
    elif payment.get("reseller_plan_id"):
        plan = get_reseller_plan(payment["reseller_plan_id"])
        if plan:
            text += f"\n\nحالا می‌توانید خرید/تمدید نمایندگی «{plan['name']}» را تکمیل کنید 👇"
            reply_markup = {"inline_keyboard": [[
                {"text": "🤝 تکمیل خرید/تمدید نمایندگی", "callback_data": f"res_confirm:{payment['reseller_plan_id']}"},
            ]]}
    elif payment.get("product_id"):
        product = get_product(payment["product_id"])
        if product:
            text += f"\n\nحالا می‌توانید خرید «{product['name']}» را تکمیل کنید 👇"
            reply_markup = {"inline_keyboard": [[
                {"text": "🛒 تکمیل خرید", "callback_data": f"confirm_buy:{payment['product_id']}"},
            ]]}
    send_telegram_message(int(telegram_id), text, reply_markup)


class WebhookHandler(BaseHTTPRequestHandler):
    server_version = "BananaBotPaymentWebhook/1.0"

    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _json_response(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # Simple health check — hit this in a browser to confirm the
        # service is up and listening on the right port.
        self._json_response(200, {"ok": True, "service": "bananabot-payment-webhook"})

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length else b""

    def _extract_sms_text(self, raw_body: bytes) -> str | None:
        """Tries a few ways to pull the SMS text out of the request body,
        since not every SMS-forwarding app sends clean
        {"sms_body": "..."} JSON exactly as documented — some send
        form-urlencoded fields, and some just send the raw SMS text with
        no wrapper at all. Logs which shape actually showed up so this can
        be tightened later if needed."""
        text = raw_body.decode("utf-8", errors="replace")

        # 1) Proper JSON: {"sms_body": "..."}
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and "sms_body" in payload:
                return (payload.get("sms_body") or "").strip()
        except ValueError:
            pass

        # 1b) Almost-JSON: some forwarder apps build the JSON by naively
        # substituting the raw SMS text into a template without escaping
        # embedded newlines/quotes — real bank SMS are multi-line, so this
        # is common. That makes it technically invalid JSON (raw control
        # characters aren't allowed inside a JSON string, so json.loads
        # above fails), but the {"sms_body": "...."} shape is still clearly
        # recognizable, so pull the value out directly instead of falling
        # through to the "use the whole raw body" last resort below.
        match = re.search(r'"sms_body"\s*:\s*"(.*)"\s*\}\s*$', text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 2) application/x-www-form-urlencoded: sms_body=...
        content_type = self.headers.get("Content-Type", "")
        if "form-urlencoded" in content_type or "=" in text:
            parsed = urllib.parse.parse_qs(text)
            if "sms_body" in parsed and parsed["sms_body"]:
                return parsed["sms_body"][0].strip()

        # 3) Last resort: some forwarder apps are misconfigured and send
        # the raw SMS text with no wrapper at all — if the body itself
        # looks like it contains a transfer amount, just use it directly.
        if text.strip():
            return text.strip()

        return None

    def do_POST(self):
        client = self.client_address[0]

        if self.path.rstrip("/") != "/webhook/payment":
            logger.warning("Request to unknown path %r from %s — check the forwarder app's URL.", self.path, client)
            self._json_response(404, {"ok": False, "error": "not_found"})
            return

        raw_body = self._read_body()  # always drain the body, even if we reject below
        logger.info("Incoming webhook POST from %s (%d bytes body).", client, len(raw_body))

        configured_secret = get_setting("auto_payment_secret", "")
        if not configured_secret:
            logger.warning("Rejected request from %s: no auto_payment_secret configured yet.", client)
            self._json_response(403, {"ok": False, "error": "not_configured"})
            return

        provided_secret = self.headers.get("X-Webhook-Secret", "")
        if not provided_secret or not hmac.compare_digest(provided_secret, configured_secret):
            logger.warning(
                "Rejected request from %s: missing/incorrect X-Webhook-Secret header (got %r).",
                client, provided_secret,
            )
            self._json_response(401, {"ok": False, "error": "unauthorized"})
            return

        if get_setting("auto_payment_enabled", "0") != "1":
            logger.info("Request from %s ignored: auto-payment is currently disabled in bot settings.", client)
            self._json_response(200, {"ok": False, "error": "auto_payment_disabled"})
            return

        sms_text = self._extract_sms_text(raw_body)
        if not sms_text:
            logger.warning("Request from %s had an empty/unparsable body: %r", client, raw_body[:500])
            self._json_response(400, {"ok": False, "error": "invalid_body"})
            return

        # Always logged (even on success) — this is the single most useful
        # line for figuring out why a real SMS didn't match: you can see
        # exactly what text the forwarder app actually sent.
        logger.info("SMS text received: %r", sms_text)

        amount_rial = parse_transfer_amount_rial(sms_text)
        if amount_rial is None:
            logger.warning(
                "Could not find a transfer amount in the SMS text above — "
                "check it contains 'انتقال' or 'واریز' right after the amount."
            )
            self._json_response(200, {"ok": False, "error": "amount_not_found"})
            return

        payment = get_payment_by_expected_amount(amount_rial)
        if not payment:
            logger.info("Parsed amount %s rial — no pending auto-payment is currently expecting exactly this.", amount_rial)
            self._json_response(200, {"ok": False, "matched": False, "amount_rial": amount_rial})
            return

        if not approve_payment(payment["id"]):
            logger.info("Amount %s rial matched payment #%s, but it was already handled by then.", amount_rial, payment["id"])
            self._json_response(200, {"ok": False, "error": "already_handled", "payment_id": payment["id"]})
            return

        notify_payment_approved(payment)
        logger.info("Auto-approved payment #%s for %s rial.", payment["id"], amount_rial)
        self._json_response(200, {
            "ok": True, "matched": True,
            "payment_id": payment["id"], "amount_rial": amount_rial,
        })


def main():
    port = int(get_setting("auto_payment_port", "8100") or "8100")
    server = ThreadingHTTPServer(("0.0.0.0", port), WebhookHandler)
    logger.info("Payment webhook server listening on 0.0.0.0:%s (DB: %s)", port, DB_PATH)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
