"""Payment notification service for administrators.

Sends immediate Telegram alerts to all ADMIN_IDS upon successful payment:
- User info: Full name, Username, Telegram Chat ID
- Payment info: Amount (Toman & Rial), Payment method, Purpose (Product, Renewal, Reseller, Deposit)
- Gateway details: Direct payment URL (for CardGozar), Tracking code, Reference ID, Payer card
- Action buttons: View gateway link, User admin card, and User payment history
- Race-safe and idempotent: Prevents duplicate notifications using admin_notified atomic flag.
"""

import html
import json
import logging
import os
import sqlite3
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


def _build_notification_text_and_markup(payment: dict, user: dict, product_name: str = "", plan_name: str = "") -> tuple[str, dict]:
    """Constructs HTML text and dict-based inline keyboard for admin notification."""
    amount = payment.get("amount") or 0
    method = payment.get("payment_method") or payment.get("method") or "card"
    ref_id = payment.get("gateway_ref_id") or payment.get("ref_id") or ""
    tracking_code = payment.get("gateway_tracking_code") or payment.get("track_id") or payment.get("tracking_code") or ""
    payer_card = payment.get("gateway_payer_card") or payment.get("payer_card") or ""
    payment_url = payment.get("gateway_payment_url") or payment.get("payment_url") or ""
    order_token = payment.get("gateway_order_token") or payment.get("order_token") or ""
    coupon_code = payment.get("coupon_code") or ""
    discount_amount = payment.get("discount_amount") or 0
    created_at = payment.get("created_at") or ""

    method_titles = {
        "cardgozar": "🚀 درگاه هوشمند کارت‌گذر (تایید آنی)",
        "card": "💳 کارت به کارت (ارسال فیش / دستی)",
        "auto_card": "🤖 کارت به کارت (تایید خودکار پیامک بانکی)",
        "balance": "💰 کسر از کیف پول",
    }
    method_str = method_titles.get(method, f"🔹 {method}")

    # Purpose
    prod_id = payment.get("product_id")
    renew_id = payment.get("renew_sub_id")
    reseller_pid = payment.get("reseller_plan_id")

    if prod_id:
        p_title = product_name or f"محصول #{prod_id}"
        purpose = f"📦 خرید سرویس: <b>{html.escape(p_title)}</b>"
    elif renew_id:
        purpose = f"🔁 تمدید سرویس اشتراک: <b>#{renew_id}</b>"
    elif reseller_pid:
        r_title = plan_name or f"پلن #{reseller_pid}"
        purpose = f"🤝 خرید/تمدید پلن نمایندگی: <b>{html.escape(r_title)}</b>"
    else:
        purpose = "💰 افزایش موجودی کیف پول (شارژ حساب)"

    # User details
    full_name = html.escape(user.get("full_name") or "—")
    uname = user.get("username")
    username_str = f"@{html.escape(uname)}" if uname else "— (ندارد)"
    tid = user.get("telegram_id")
    balance = user.get("balance", 0)

    lines = [
        "🎉 <b>پرداخت موفق جدید ثبت شد!</b>\n",
        f"💳 <b>شناسه پرداخت:</b> <code>#{payment['id']}</code>",
        f"💰 <b>مبلغ پرداختی:</b> <b>{amount:,} تومان</b>",
        f"⚙️ <b>روش پرداخت:</b> {method_str}",
        f"📦 <b>بابت:</b> {purpose}",
    ]

    if coupon_code and discount_amount:
        lines.append(f"🎟 <b>کوپن تخفیف:</b> <code>{html.escape(coupon_code)}</code> (تخفیف: {discount_amount:,} تومان)")

    lines.append("\n👤 <b>مشخصات خریدار:</b>")
    lines.append(f"• <b>نام:</b> {full_name}")
    lines.append(f"• <b>یوزرنیم:</b> {username_str}")
    lines.append(f"• <b>چت‌آیدی تلگرام:</b> <code>{tid}</code>")
    lines.append(f"• <b>موجودی فعلی کاربر:</b> <b>{balance:,} تومان</b>")

    # Gateway specific details (especially CardGozar)
    if method == "cardgozar" or payment_url or ref_id:
        lines.append("\n🚀 <b>اطلاعات درگاه پرداخت کارت‌گذر:</b>")
        if ref_id:
            lines.append(f"• <b>کد پیگیری درگاه (Ref ID):</b> <code>{html.escape(ref_id)}</code>")
        if tracking_code:
            lines.append(f"• <b>شناسه ۴ رقمی واریز:</b> <code>{html.escape(tracking_code)}</code>")
        if payer_card:
            lines.append(f"• <b>کارت پرداخت‌کننده:</b> <code>{html.escape(payer_card)}</code>")
        if order_token:
            lines.append(f"• <b>توکن سفارش:</b> <code>{html.escape(order_token)}</code>")
        if payment_url:
            lines.append(f"• <b>🔗 لینک صفحه پرداخت:</b>\n{payment_url}")

    if created_at:
        lines.append(f"\n⏰ <b>زمان ثبت:</b> <code>{created_at}</code>")

    # Inline Keyboard Buttons
    keyboard_rows = []
    if payment_url and payment_url.startswith("http"):
        keyboard_rows.append([
            {"text": "🔗 مشاهده صفحه پرداخت کارت‌گذر", "url": payment_url}
        ])
    keyboard_rows.append([
        {"text": "👤 مشخصات کاربر", "callback_data": f"ulist_view:{tid}"},
        {"text": "💳 تاریخچه پرداختی‌ها", "callback_data": f"uadm_pays:{tid}"},
    ])

    markup_dict = {"inline_keyboard": keyboard_rows}
    return "\n".join(lines), markup_dict


async def notify_admins_payment_success(bot, db, payment_id: int) -> bool:
    """Async notification for Aiogram Bot context."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from config import get_settings

    # Idempotent lock: claim notification flag
    claimed = await db.claim_admin_payment_notified(payment_id)
    if not claimed:
        logger.debug("Admin notification for payment #%s already sent. Skipping duplicate.", payment_id)
        return False

    payment = await db.get_payment(payment_id)
    if not payment:
        return False

    user = await db._fetchone("SELECT * FROM users WHERE id = ?", (payment["user_id"],))
    if not user:
        return False

    prod_name = ""
    if payment.get("product_id"):
        prod = await db.get_product(payment["product_id"])
        prod_name = prod["name"] if prod else ""

    plan_name = ""
    if payment.get("reseller_plan_id"):
        plan = await db.get_reseller_plan(payment["reseller_plan_id"])
        plan_name = plan["name"] if plan else ""

    text, markup_dict = _build_notification_text_and_markup(payment, user, prod_name, plan_name)

    # Convert markup_dict to aiogram InlineKeyboardMarkup
    aiogram_rows = []
    for row in markup_dict.get("inline_keyboard", []):
        aiogram_buttons = []
        for btn in row:
            if "url" in btn:
                aiogram_buttons.append(InlineKeyboardButton(text=btn["text"], url=btn["url"]))
            else:
                aiogram_buttons.append(InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"]))
        aiogram_rows.append(aiogram_buttons)
    markup = InlineKeyboardMarkup(inline_keyboard=aiogram_rows)

    admin_ids = get_settings().admin_ids
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=markup, parse_mode="HTML")
            logger.info("Sent successful payment alert for #%s to admin %s", payment_id, admin_id)
        except Exception as exc:
            logger.warning("Failed to send payment alert for #%s to admin %s: %s", payment_id, admin_id, exc)

    return True


def notify_admins_payment_success_sync(payment_id: int) -> bool:
    """Synchronous notification for Django Web Panel and Webhook Server."""
    from config import get_settings
    admin_ids = get_settings().admin_ids
    if not admin_ids:
        return False

    payment = None
    user = None
    prod_name = ""
    plan_name = ""

    # Prefer webapp.panel.db if available (supports both PostgreSQL and SQLite)
    try:
        from webapp.panel.db import get_conn, row_to_dict
        with get_conn() as conn:
            cur = conn.execute(
                "UPDATE payments SET admin_notified = 1 WHERE id = ? AND (admin_notified IS NULL OR admin_notified = 0)",
                (payment_id,),
            )
            if getattr(cur, "rowcount", 0) == 0:
                return False

            p_row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
            if not p_row:
                return False
            payment = row_to_dict(p_row)

            u_row = conn.execute("SELECT * FROM users WHERE id = ?", (payment["user_id"],)).fetchone()
            if not u_row:
                return False
            user = row_to_dict(u_row)

            if payment.get("product_id"):
                p_res = conn.execute("SELECT name FROM products WHERE id = ?", (payment["product_id"],)).fetchone()
                if p_res:
                    prod_name = p_res[0] if isinstance(p_res, (list, tuple)) else p_res["name"]

            if payment.get("reseller_plan_id"):
                pl_res = conn.execute("SELECT name FROM reseller_plans WHERE id = ?", (payment["reseller_plan_id"],)).fetchone()
                if pl_res:
                    plan_name = pl_res[0] if isinstance(pl_res, (list, tuple)) else pl_res["name"]
    except Exception:
        # Fallback to direct sqlite3
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bot.db")
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # Idempotent claim
            cur.execute(
                "UPDATE payments SET admin_notified = 1 WHERE id = ? AND (admin_notified IS NULL OR admin_notified = 0)",
                (payment_id,),
            )
            if cur.rowcount == 0:
                conn.close()
                return False
            conn.commit()

            # Fetch payment + user
            cur.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
            p_row = cur.fetchone()
            if not p_row:
                conn.close()
                return False
            payment = dict(p_row)

            cur.execute("SELECT * FROM users WHERE id = ?", (payment["user_id"],))
            u_row = cur.fetchone()
            if not u_row:
                conn.close()
                return False
            user = dict(u_row)

            if payment.get("product_id"):
                cur.execute("SELECT name FROM products WHERE id = ?", (payment["product_id"],))
                p_res = cur.fetchone()
                if p_res:
                    prod_name = p_res[0]

            if payment.get("reseller_plan_id"):
                cur.execute("SELECT name FROM reseller_plans WHERE id = ?", (payment["reseller_plan_id"],))
                pl_res = cur.fetchone()
                if pl_res:
                    plan_name = pl_res[0]

            conn.close()
        except Exception as exc:
            logger.exception("Database error during sync admin payment notification for #%s: %s", payment_id, exc)
            return False

    if not payment or not user:
        return False

    text, markup_dict = _build_notification_text_and_markup(payment, user, prod_name, plan_name)

    # Send via telegram_api
    try:
        from webapp.panel import telegram_api
        for admin_id in admin_ids:
            telegram_api.send_message(admin_id, text, reply_markup=markup_dict, parse_mode="HTML")
            logger.info("Sent sync payment alert for #%s to admin %s", payment_id, admin_id)
        return True
    except Exception:
        # Fallback to direct Bot API call
        bot_token = get_settings().bot_token
        if not bot_token:
            return False
        for admin_id in admin_ids:
            try:
                payload = json.dumps({
                    "chat_id": admin_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": markup_dict,
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as _:
                    pass
            except Exception as exc:
                logger.warning("Failed direct telegram post to admin %s: %s", admin_id, exc)
        return True
