"""Views for BananaBot Web Panel."""

import json
import logging
import time
from datetime import datetime
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpRequest, HttpResponse, Http404
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib import messages

from .auth import (
    login_required,
    admin_required,
    verify_telegram_auth,
    verify_webapp_init_data,
    get_current_user,
    is_admin,
)
from . import db as bot_db
from . import telegram_api
from . import xui_client
from . import reseller_core
from . import apikeys

logger = logging.getLogger(__name__)


# ── Auth ──────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def webapp_login(request: HttpRequest):
    """Auto-login endpoint used by the Telegram Mini App front-end.

    The page's JS reads `Telegram.WebApp.initData` and POSTs it here as JSON.
    initData is already signed by Telegram, so this is exempt from Django's
    CSRF check the same way an API token endpoint would be — the security
    guarantee comes from the HMAC signature, not from the CSRF cookie.
    """
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "بدنه درخواست نامعتبر است."}, status=400)

    init_data = payload.get("initData", "")
    user = verify_webapp_init_data(init_data)
    if not user:
        return JsonResponse({"ok": False, "error": "اعتبارسنجی Telegram Mini App ناموفق بود."}, status=403)

    request.session["tg_user"] = {
        "id": str(user["id"]),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "username": user.get("username", ""),
        "photo_url": user.get("photo_url", ""),
    }
    return JsonResponse({"ok": True, "redirect": reverse("panel:dashboard")})


def login_view(request: HttpRequest):
    if request.session.get("tg_user"):
        return redirect("panel:dashboard")

    if request.method == "GET" and "id" in request.GET:
        data = dict(request.GET)
        data = {k: v[0] if isinstance(v, list) else v for k, v in data.items()}
        if verify_telegram_auth(data):
            request.session["tg_user"] = data
            return redirect("panel:dashboard")
        else:
            messages.error(request, "اعتبارسنجی تلگرام ناموفق بود.")

    bot_username = bot_db.get_setting("bot_username", "")
    return render(request, "shared/login.html", {
        "bot_username": bot_username,
        "bot_token_set": bool(settings.BOT_TOKEN),
    })


def logout_view(request: HttpRequest):
    request.session.flush()
    return redirect("panel:login")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@login_required
def dashboard(request: HttpRequest):
    tg_user = get_current_user(request)
    _is_admin = is_admin(request)

    db_user = bot_db.get_user_by_telegram_id(int(tg_user["id"]))

    if _is_admin:
        stats = {
            "users": bot_db.get_users_stats(),
            "revenue": bot_db.get_revenue_stats(),
            "active_subs": bot_db.get_active_subscriptions_count(),
            "products": len(bot_db.get_products(active_only=False)),
            "panels": len(bot_db.get_panels()),
            "pending_payments": len(bot_db.get_pending_payments()),
        }
        return render(request, "admin/dashboard.html", {
            "tg_user": tg_user,
            "db_user": db_user,
            "stats": stats,
            "is_admin": True,
        })
    else:
        subscriptions = bot_db.get_user_subscriptions(db_user["id"]) if db_user else []
        products = bot_db.get_products(active_only=True)
        return render(request, "user/dashboard.html", {
            "tg_user": tg_user,
            "db_user": db_user,
            "subscriptions": subscriptions,
            "products": products,
            "is_admin": False,
        })


# ── Admin: Users ──────────────────────────────────────────────────────────────

def _notify_balance_change(user: dict, delta: int, new_balance: int):
    """Same message text the bot itself sends from /addbalance and the
    admin-panel-in-Telegram balance adjust flow (uadm_balance_apply), so a
    user gets identical wording no matter which surface the admin used.
    """
    telegram_id = user.get("telegram_id")
    if not telegram_id:
        return
    telegram_api.send_message(
        int(telegram_id),
        f"💰 موجودی شما {delta:+,} تومان تغییر کرد.\nموجودی جدید: {new_balance:,} تومان",
    )


@admin_required
def admin_users(request: HttpRequest):
    page = int(request.GET.get("page", 1))
    search = request.GET.get("q", "")
    users, total = bot_db.get_users_page(page, per_page=20, search=search)
    total_pages = max(1, -(-total // 20))
    return render(request, "admin/users.html", {
        "users": users, "total": total,
        "page": page, "total_pages": total_pages,
        "search": search, "is_admin": True,
    })


@admin_required
def admin_user_detail(request: HttpRequest, telegram_id: int):
    user = bot_db.get_user_by_telegram_id(telegram_id)
    if not user:
        messages.error(request, "کاربر پیدا نشد.")
        return redirect("panel:admin_users")

    subscriptions = bot_db.get_user_subscriptions(user["id"])

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_balance":
            amount = int(request.POST.get("amount", 0))
            new_balance = bot_db.update_user_balance(user["id"], amount)
            _notify_balance_change(user, amount, new_balance)
            messages.success(request, f"{amount:,} تومان به موجودی اضافه شد. به کاربر اطلاع داده شد.")
        elif action == "sub_balance":
            amount = int(request.POST.get("amount", 0))
            new_balance = bot_db.update_user_balance(user["id"], -amount)
            _notify_balance_change(user, -amount, new_balance)
            messages.success(request, f"{amount:,} تومان از موجودی کم شد. به کاربر اطلاع داده شد.")
        elif action == "ban":
            bot_db.set_user_banned(user["id"], True)
            messages.warning(request, "کاربر بن شد.")
        elif action == "unban":
            bot_db.set_user_banned(user["id"], False)
            messages.success(request, "کاربر آن‌بن شد.")
        return redirect("panel:admin_user_detail", telegram_id=telegram_id)

    user = bot_db.get_user_by_telegram_id(telegram_id)
    return render(request, "admin/user_detail.html", {
        "u": user, "subscriptions": subscriptions, "is_admin": True,
    })


@admin_required
@require_POST
def admin_subscription_delete(request: HttpRequest, sub_id: int):
    sub = bot_db.get_subscription(sub_id)
    if not sub:
        messages.error(request, "سرویس پیدا نشد.")
        return redirect("panel:admin_users")

    if sub["status"] == "deleted":
        messages.warning(request, "این سرویس قبلاً حذف شده بود.")
        return redirect("panel:admin_user_detail", telegram_id=sub["telegram_id"])

    panel_ok = xui_client.delete_client(sub["panel_url"], sub["api_token"], sub["email"])
    # Same behavior as the bot's own delete_subscription: always mark it
    # deleted in our DB even if the panel call failed (e.g. panel offline,
    # client already gone there) — an admin who chose to delete a service
    # doesn't want it stuck "active" in the panel forever because of a
    # transient network error.
    bot_db.delete_subscription_record(sub_id)

    if sub.get("telegram_id"):
        telegram_api.send_message(
            int(sub["telegram_id"]),
            f"❌ سرویس شما ({sub['email']}) توسط ادمین حذف شد.",
        )

    if panel_ok:
        messages.success(request, "سرویس از پنل و دیتابیس حذف شد. به کاربر اطلاع داده شد.")
    else:
        messages.warning(
            request,
            "سرویس در دیتابیس حذف شد، اما حذف آن از پنل x-ui ناموفق بود "
            "(ممکن است پنل در دسترس نباشد یا کلاینت از قبل حذف شده باشد).",
        )
    return redirect("panel:admin_user_detail", telegram_id=sub["telegram_id"])


# ── Admin: Products ───────────────────────────────────────────────────────────

@admin_required
def admin_products(request: HttpRequest):
    products = bot_db.get_products(active_only=False)
    panels = bot_db.get_panels()
    return render(request, "admin/products.html", {
        "products": products, "panels": panels, "is_admin": True,
    })


@admin_required
def admin_product_edit(request: HttpRequest, product_id: int = 0):
    panels = bot_db.get_panels()
    product = bot_db.get_product(product_id) if product_id else None

    if request.method == "POST":
        data = {
            "name": request.POST["name"],
            "panel_id": int(request.POST["panel_id"]),
            "volume_gb": float(request.POST["volume_gb"]),
            "duration_days": int(request.POST["duration_days"]),
            "price": int(request.POST["price"]),
            "description": request.POST.get("description", ""),
            "is_active": 1 if request.POST.get("is_active") else 0,
        }
        if product_id:
            bot_db.update_product(product_id, **data)
            messages.success(request, "محصول ویرایش شد.")
        else:
            bot_db.add_product(**{k: v for k, v in data.items() if k != "is_active"})
            messages.success(request, "محصول اضافه شد.")
        return redirect("panel:admin_products")

    return render(request, "admin/product_edit.html", {
        "product": product, "panels": panels, "is_admin": True,
    })


@admin_required
@require_POST
def admin_product_delete(request: HttpRequest, product_id: int):
    bot_db.delete_product(product_id)
    messages.success(request, "محصول حذف شد.")
    return redirect("panel:admin_products")


# ── Admin: Panels ─────────────────────────────────────────────────────────────

@admin_required
def admin_panels(request: HttpRequest):
    panels = bot_db.get_panels(active_only=False)
    return render(request, "admin/panels.html", {
        "panels": panels, "is_admin": True,
    })


@admin_required
def admin_panel_edit(request: HttpRequest, panel_id: int):
    panel = bot_db.get_panel(panel_id)
    if not panel:
        messages.error(request, "پنل پیدا نشد.")
        return redirect("panel:admin_panels")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_inbounds":
            raw = request.POST.get("inbound_ids", "").strip().strip("[]")
            try:
                ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
                bot_db.update_panel(panel_id, inbound_ids=json.dumps(ids))
                messages.success(request, f"Inbounds بروز شد: {ids}")
            except ValueError:
                messages.error(request, "فرمت نامعتبر. مثال: 54,81,83")
        elif action == "toggle_active":
            new_val = 0 if panel["is_active"] else 1
            bot_db.update_panel(panel_id, is_active=new_val)
            messages.success(request, "وضعیت پنل تغییر کرد.")
        elif action == "toggle_onhold":
            new_val = 0 if panel.get("on_hold") else 1
            bot_db.update_panel(panel_id, on_hold=new_val)
            messages.success(request, "وضعیت On-Hold تغییر کرد.")
        elif action == "delete":
            bot_db.delete_panel(panel_id)
            messages.success(request, "پنل حذف شد.")
            return redirect("panel:admin_panels")
        return redirect("panel:admin_panel_edit", panel_id=panel_id)

    panel = bot_db.get_panel(panel_id)
    try:
        inbound_ids = json.loads(panel["inbound_ids"])
    except Exception:
        inbound_ids = []
    return render(request, "admin/panel_edit.html", {
        "panel": panel, "inbound_ids": inbound_ids, "is_admin": True,
    })


# ── Admin: Payments ───────────────────────────────────────────────────────────

def _notify_payment_status(payment: dict, status: str, note: str = ""):
    """Mirror what the bot itself does in pay_confirm/pay_reject when an
    admin acts from inside Telegram. Approving/rejecting from the web panel
    used to only touch the database — the user never found out their
    balance changed, and (for approvals) never got the button to continue
    their purchase/renewal. This sends the same notification + button the
    bot would have sent, and cleans up the ✅/❌ buttons on the admin
    notification message(s) so a second admin can't act on them from
    inside Telegram anymore.
    """
    telegram_id = payment.get("telegram_id")
    if telegram_id:
        if status == "approved":
            db_user = bot_db.get_user_by_telegram_id(int(telegram_id))
            text = "✅ پرداخت تأیید شد."
            if db_user:
                text += f"\n💰 موجودی: {db_user['balance']:,} تومان"
            reply_markup = None
            if payment.get("renew_sub_id"):
                text += f"\n\nحالا می‌توانید تمدید سرویس #{payment['renew_sub_id']} را تکمیل کنید 👇"
                reply_markup = {"inline_keyboard": [[
                    {"text": "🔁 تکمیل تمدید سرویس", "callback_data": f"svc_renew_ok:{payment['renew_sub_id']}"},
                ]]}
            elif payment.get("reseller_plan_id"):
                plan = bot_db.get_reseller_plan(payment["reseller_plan_id"])
                if plan:
                    text += f"\n\nحالا می‌توانید خرید/تمدید نمایندگی «{plan['name']}» را تکمیل کنید 👇"
                    reply_markup = {"inline_keyboard": [[
                        {"text": "🤝 تکمیل خرید/تمدید نمایندگی", "callback_data": f"res_confirm:{payment['reseller_plan_id']}"},
                    ]]}
            elif payment.get("product_id"):
                product = bot_db.get_product(payment["product_id"])
                if product:
                    text += f"\n\nحالا می‌توانید خرید «{product['name']}» را تکمیل کنید 👇"
                    reply_markup = {"inline_keyboard": [[
                        {"text": "🛒 تکمیل خرید", "callback_data": f"confirm_buy:{payment['product_id']}"},
                    ]]}
            if note:
                text += f"\n📝 یادداشت: {note}"
            telegram_api.send_message(int(telegram_id), text, reply_markup)
        else:
            text = "❌ پرداخت رد شد."
            if note:
                text += f"\n📝 یادداشت: {note}"
            telegram_api.send_message(int(telegram_id), text)

    status_text = (
        f"✅ این پرداخت تأیید شد. (پنل وب)\n💰 مبلغ: {payment['amount']:,} تومان"
        if status == "approved" else "❌ این پرداخت رد شد. (پنل وب)"
    )
    try:
        chats = json.loads(payment.get("notif_chats") or "[]")
    except (TypeError, ValueError):
        chats = []
    for item in chats:
        chat_id, message_id = item.get("chat_id"), item.get("message_id")
        if not chat_id or not message_id:
            continue
        if not telegram_api.edit_message_caption(chat_id, message_id, status_text):
            telegram_api.edit_message_text(chat_id, message_id, status_text)


@admin_required
def admin_payments(request: HttpRequest):
    page = int(request.GET.get("page", 1))
    status = request.GET.get("status", "")
    payments, total = bot_db.get_payments_page(page, per_page=20, status=status)
    total_pages = max(1, -(-total // 20))
    return render(request, "admin/payments.html", {
        "payments": payments, "total": total,
        "page": page, "total_pages": total_pages,
        "status_filter": status, "is_admin": True,
    })


@admin_required
def admin_payment_detail(request: HttpRequest, payment_id: int):
    payment = bot_db.get_payment(payment_id)
    if not payment:
        messages.error(request, "پرداخت پیدا نشد.")
        return redirect("panel:admin_payments")

    if request.method == "POST":
        action = request.POST.get("action")
        note = request.POST.get("note", "")
        admin_tid = (request.session.get("tg_user") or {}).get("id")
        if action == "approve":
            if bot_db.approve_payment(payment_id, note, handled_by=admin_tid):
                _notify_payment_status(payment, "approved", note)
                messages.success(request, "پرداخت تأیید و موجودی شارژ شد. به کاربر اطلاع داده شد.")
            else:
                messages.warning(request, "این پرداخت قبلاً بررسی شده بود.")
        elif action == "reject":
            if bot_db.reject_payment(payment_id, note, handled_by=admin_tid):
                _notify_payment_status(payment, "rejected", note)
                messages.warning(request, "پرداخت رد شد. به کاربر اطلاع داده شد.")
            else:
                messages.warning(request, "این پرداخت قبلاً بررسی شده بود.")
        return redirect("panel:admin_payments")

    return render(request, "admin/payment_detail.html", {
        "payment": payment, "is_admin": True,
    })


@admin_required
def admin_payment_receipt(request: HttpRequest, payment_id: int):
    """Proxy a payment's uploaded receipt photo from Telegram.

    receipt_file_id is a Telegram file_id, not a normal URL — it can only
    be resolved into actual bytes by calling the Bot API with the bot
    token, so we fetch it server-side here and stream it back instead of
    exposing the raw Telegram file URL (which itself contains the bot
    token) to the browser.
    """
    payment = bot_db.get_payment(payment_id)
    if not payment or not payment.get("receipt_file_id"):
        raise Http404("رسیدی برای این پرداخت ثبت نشده است.")

    file_path = telegram_api.get_file_path(payment["receipt_file_id"])
    if not file_path:
        raise Http404("دریافت رسید از تلگرام ناموفق بود.")

    content = telegram_api.download_file(file_path)
    if content is None:
        raise Http404("دریافت رسید از تلگرام ناموفق بود.")

    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    content_type = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "webp": "image/webp", "gif": "image/gif",
    }.get(ext, "application/octet-stream")

    response = HttpResponse(content, content_type=content_type)
    response["Cache-Control"] = "private, max-age=3600"
    return response


# ── Admin: Settings ───────────────────────────────────────────────────────────

SETTINGS_META = {
    "welcome_text":        {"label": "👋 متن خوش‌آمد",             "type": "textarea"},
    "support_text":        {"label": "🆘 متن پشتیبانی",            "type": "textarea"},
    "support_username":    {"label": "📱 یوزرنیم پشتیبان",         "type": "text"},
    "trial_enabled":       {"label": "🎁 اکانت تست (1=فعال/0=غیر)", "type": "text"},
    "trial_product_id":    {"label": "📦 ID محصول تست",             "type": "text"},
    "trial_panel_id":      {"label": "🖥 ID پنل تست",               "type": "text"},
    "trial_volume_gb":     {"label": "📊 حجم تست (GB)",             "type": "text"},
    "trial_duration_days": {"label": "⏱ مدت تست (روز)",            "type": "text"},
    "channel_required":    {"label": "🔒 کانال اجباری (ID)",        "type": "text"},
    "channel_invite_link": {"label": "🔗 لینک دعوت کانال",          "type": "text"},
    "min_deposit":         {"label": "💰 حداقل شارژ (تومان)",       "type": "text"},
}


@admin_required
def admin_settings(request: HttpRequest):
    current = bot_db.get_all_settings()
    revenue = bot_db.get_revenue_stats()

    if request.method == "POST":
        if request.POST.get("action") == "set_revenue":
            try:
                desired_total = int(request.POST.get("revenue_total", ""))
            except ValueError:
                messages.error(request, "مقدار وارد شده برای کل درآمد نامعتبر است.")
                return redirect("panel:admin_settings")
            # Store the DIFFERENCE from what's actually computed from approved
            # payments, not the raw number — so "کل درآمد" keeps growing
            # correctly as new payments get approved afterward, instead of
            # freezing at whatever the admin typed.
            new_adjustment = desired_total - revenue["computed_total"]
            bot_db.set_setting("revenue_adjustment", str(new_adjustment))
            messages.success(request, "مقدار کل درآمد به‌روزرسانی شد.")
            return redirect("panel:admin_settings")

        for key in SETTINGS_META:
            if key in request.POST:
                bot_db.set_setting(key, request.POST[key])
        messages.success(request, "تنظیمات ذخیره شد.")
        return redirect("panel:admin_settings")

    fields = [
        {"key": k, **meta, "value": current.get(k, "")}
        for k, meta in SETTINGS_META.items()
    ]
    auto_payment = {
        "enabled": current.get("auto_payment_enabled", "0") == "1",
        "secret_set": bool(current.get("auto_payment_secret", "")),
        "port": current.get("auto_payment_port", "8100"),
        "host": request.get_host().split(":")[0],
    }
    return render(request, "admin/settings.html", {
        "fields": fields, "is_admin": True, "revenue": revenue, "auto_payment": auto_payment,
    })


# ── User: Services ────────────────────────────────────────────────────────────

@login_required
def user_services(request: HttpRequest):
    tg_user = get_current_user(request)
    db_user = bot_db.get_user_by_telegram_id(int(tg_user["id"]))
    if not db_user:
        messages.error(request, "حساب کاربری شما در ربات ثبت نشده. ابتدا ربات را استارت کنید.")
        return redirect("panel:dashboard")
    subscriptions = bot_db.get_user_subscriptions(db_user["id"])
    return render(request, "user/services.html", {
        "subscriptions": subscriptions, "db_user": db_user,
        "tg_user": tg_user, "is_admin": is_admin(request),
    })


@login_required
def user_buy(request: HttpRequest):
    tg_user = get_current_user(request)
    db_user = bot_db.get_user_by_telegram_id(int(tg_user["id"]))
    products = bot_db.get_products(active_only=True)
    bot_username = bot_db.get_setting("bot_username", "")
    return render(request, "user/buy.html", {
        "products": products, "db_user": db_user,
        "tg_user": tg_user, "is_admin": is_admin(request),
        "bot_username": bot_username,
    })


def _payment_actions_markup(payment_id: int) -> dict:
    """Same callback_data scheme as bot.keyboards.payment_actions_inline.
    Whichever process (bot or panel) sends the message, Telegram routes the
    button tap back to the same bot's update stream, so the bot's existing
    pay_ok/pay_no handlers can approve/reject it without any duplicated
    approval logic here."""
    return {"inline_keyboard": [[
        {"text": "✅ تأیید", "callback_data": f"pay_ok:{payment_id}"},
        {"text": "❌ رد", "callback_data": f"pay_no:{payment_id}"},
    ]]}


@login_required
def user_wallet(request: HttpRequest):
    tg_user = get_current_user(request)
    db_user = bot_db.get_user_by_telegram_id(int(tg_user["id"]))
    card_number = bot_db.get_setting("card_number", "")
    card_holder = bot_db.get_setting("card_holder", "")
    min_deposit = int(bot_db.get_setting("min_deposit", "10000"))
    bot_username = bot_db.get_setting("bot_username", "")

    if request.method == "POST" and db_user:
        action = request.POST.get("action")

        if action == "create_deposit":
            if not card_number:
                messages.error(request, "شماره کارت هنوز توسط ادمین تنظیم نشده. لطفاً بعداً تلاش کنید.")
            else:
                try:
                    amount = int(request.POST.get("amount", 0))
                except ValueError:
                    amount = 0
                if amount < min_deposit:
                    messages.error(request, f"حداقل مبلغ واریز {min_deposit:,} تومان است.")
                else:
                    bot_db.create_payment(db_user["id"], amount, "card")
                    messages.success(request, "درخواست واریز ثبت شد. حالا تصویر رسید پرداخت را آپلود کنید.")
            return redirect("panel:user_wallet")

        elif action == "upload_receipt":
            payment_id = int(request.POST.get("payment_id", 0) or 0)
            payment = bot_db.get_payment(payment_id)
            photo = request.FILES.get("receipt")
            valid = (
                payment and payment["user_id"] == db_user["id"]
                and payment["status"] == "pending" and not payment.get("receipt_file_id")
            )
            if not valid:
                messages.error(request, "درخواست واریز معتبری پیدا نشد. لطفاً دوباره درخواست واریز ثبت کنید.")
            elif not photo:
                messages.error(request, "لطفاً تصویر رسید را انتخاب کنید.")
            elif not photo.content_type or not photo.content_type.startswith("image/"):
                messages.error(request, "فقط فایل تصویری قابل قبول است.")
            else:
                photo_bytes = photo.read()
                caption = (
                    f"💳 درخواست افزایش موجودی\n"
                    f"👤 کاربر: {tg_user['id']}\n"
                    f"💰 مبلغ پرداختی: {payment['amount']:,} تومان\n"
                    f"🌐 ثبت‌شده از پنل وب"
                )
                markup = _payment_actions_markup(payment_id)
                sent_refs, file_id = [], None
                for admin_id in settings.ADMIN_TELEGRAM_IDS:
                    result = telegram_api.send_photo(
                        admin_id, photo_bytes, photo.name or "receipt.jpg",
                        caption=caption, reply_markup=markup,
                    )
                    if result and result.get("ok"):
                        msg = result["result"]
                        sent_refs.append({"chat_id": msg["chat"]["id"], "message_id": msg["message_id"]})
                        if not file_id:
                            sizes = msg.get("photo") or []
                            if sizes:
                                file_id = sizes[-1]["file_id"]
                if sent_refs:
                    if file_id:
                        bot_db.set_payment_receipt(payment_id, file_id)
                    bot_db.set_payment_notif_chats(payment_id, sent_refs)
                    messages.success(request, "رسید برای ادمین ارسال شد. پس از تأیید، موجودی شما شارژ می‌شود.")
                else:
                    messages.error(
                        request,
                        "ارسال رسید به ادمین ناموفق بود. لطفاً دوباره تلاش کنید یا رسید را مستقیم در ربات ارسال کنید.",
                    )
            return redirect("panel:user_wallet")

    pending_receipt_payment = None
    awaiting_review = []
    if db_user:
        pending_receipt_payment = bot_db.get_pending_deposit_awaiting_receipt(db_user["id"])
        awaiting_review = bot_db.get_pending_deposits_awaiting_review(db_user["id"])

    return render(request, "user/wallet.html", {
        "db_user": db_user, "tg_user": tg_user,
        "card_number": card_number, "card_holder": card_holder,
        "min_deposit": min_deposit, "is_admin": is_admin(request),
        "bot_username": bot_username,
        "pending_receipt_payment": pending_receipt_payment,
        "awaiting_review": awaiting_review,
    })


# ── Reseller panel (user side — Mini App) ───────────────────────────────────

@login_required
def reseller_panel(request: HttpRequest):
    tg_user = get_current_user(request)
    db_user = bot_db.get_user_by_telegram_id(int(tg_user["id"]))
    if not db_user:
        messages.error(request, "حساب کاربری شما در ربات ثبت نشده. ابتدا ربات را استارت کنید.")
        return redirect("panel:dashboard")

    reseller = bot_db.get_reseller_by_user_id(db_user["id"])
    if not reseller:
        messages.info(request, "شما هنوز پنل نمایندگی ندارید. برای خرید پلن نمایندگی از داخل ربات اقدام کنید.")
        return redirect("panel:dashboard")

    locked = reseller_core.reseller_locked(reseller)

    if request.method == "POST":
        if locked:
            messages.error(request, "پنل نمایندگی شما قفل است (غیرفعال یا منقضی‌شده). برای ادامه، پلن را از داخل ربات تمدید کنید.")
            return redirect("panel:reseller_panel")

        action = request.POST.get("action")

        if action == "create_config":
            label = (request.POST.get("label") or "").strip()
            try:
                volume_gb = float(request.POST.get("volume_gb", 0))
                duration_days = int(request.POST.get("duration_days", 0))
            except ValueError:
                messages.error(request, "مقادیر حجم/زمان نامعتبر است.")
                return redirect("panel:reseller_panel")

            result = reseller_core.create_config(
                reseller, int(tg_user["id"]), label, volume_gb, duration_days, source="panel",
            )
            if result["ok"]:
                messages.success(request, "✅ کانفیگ با موفقیت ساخته شد.")
            else:
                messages.error(request, result["error"])

        elif action in ("update_config", "rename_config", "toggle_config", "delete_config"):
            config_id = int(request.POST.get("config_id", 0) or 0)
            config = bot_db.get_reseller_config(config_id)
            if not config or config["reseller_id"] != reseller["id"]:
                messages.error(request, "کانفیگ پیدا نشد.")
                return redirect("panel:reseller_panel")

            if action == "rename_config":
                label = (request.POST.get("label") or "").strip()
                reseller_core.rename_config(config, label)
                messages.success(request, "✅ نام کانفیگ بروزرسانی شد.")

            elif action == "toggle_config":
                enable = config["status"] != "active"
                result = reseller_core.toggle_config(reseller, config, enable=enable)
                if result["ok"]:
                    messages.success(
                        request,
                        "✅ کانفیگ دوباره فعال شد." if enable else "✅ کانفیگ موقتاً غیرفعال شد.",
                    )
                else:
                    messages.error(request, result["error"])

            elif action == "delete_config":
                result = reseller_core.delete_config(reseller, config)
                if result["ok"]:
                    c = result["config"]
                    messages.success(
                        request,
                        f"✅ کانفیگ حذف شد. حجم مصرف‌شده «{c['_window_used_gb']:.2f} GB» برای همیشه از سقف نمایندگی شما کسر ماند "
                        f"و فقط حجم استفاده‌نشده «{c['_freed_gb']:.2f} GB» به حساب شما بازگشت.",
                    )
                else:
                    messages.error(request, "❌ " + result["error"])

            elif action == "update_config":
                try:
                    volume_gb = float(request.POST.get("volume_gb", 0))
                    duration_days = int(request.POST.get("duration_days", 0))
                except ValueError:
                    messages.error(request, "مقادیر حجم/زمان نامعتبر است.")
                    return redirect("panel:reseller_panel")

                result = reseller_core.update_config(reseller, config, volume_gb, duration_days)
                if result["ok"]:
                    messages.success(request, "✅ کانفیگ با موفقیت تمدید/ویرایش شد.")
                else:
                    messages.error(request, result["error"])

        return redirect("panel:reseller_panel")

    configs = bot_db.get_reseller_configs(reseller["id"])
    used_gb = bot_db.get_reseller_used_gb(reseller["id"])
    remaining_gb = max(0.0, reseller["quota_gb"] - used_gb)

    reseller_core.annotate_config_usage(reseller, configs)

    return render(request, "user/reseller.html", {
        "db_user": db_user, "tg_user": tg_user, "is_admin": is_admin(request),
        "reseller": reseller, "configs": configs, "locked": locked,
        "used_gb": used_gb, "remaining_gb": remaining_gb,
        "expires_at_text": reseller_core.format_ts(reseller["expires_at"]),
    })


# ── Reseller API keys management (web UI) ───────────────────────────────────

@login_required
def reseller_api_keys(request: HttpRequest):
    tg_user = get_current_user(request)
    db_user = bot_db.get_user_by_telegram_id(int(tg_user["id"]))
    if not db_user:
        messages.error(request, "حساب کاربری شما در ربات ثبت نشده. ابتدا ربات را استارت کنید.")
        return redirect("panel:dashboard")

    reseller = bot_db.get_reseller_by_user_id(db_user["id"])
    if not reseller:
        messages.info(request, "شما هنوز پنل نمایندگی ندارید.")
        return redirect("panel:dashboard")

    new_raw_key = None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_key":
            label = (request.POST.get("label") or "").strip()
            if bot_db.count_active_api_keys(reseller["id"]) >= 10:
                messages.error(request, "حداکثر ۱۰ کلید فعال مجاز است. ابتدا یکی از کلیدهای قبلی را باطل کنید.")
                return redirect("panel:reseller_api_keys")
            raw_key, key_id, key_hash = apikeys.generate_api_key()
            bot_db.create_api_key(reseller["id"], key_id, key_hash, label)
            new_raw_key = raw_key
            messages.warning(request, "⚠️ این کلید فقط همین یک‌بار نمایش داده می‌شود. آن را همین حالا در جای امنی ذخیره کنید.")
        elif action == "revoke_key":
            pk_id = int(request.POST.get("key_pk", 0) or 0)
            if bot_db.revoke_api_key(pk_id, reseller["id"]):
                messages.success(request, "✅ کلید باطل شد.")
            else:
                messages.error(request, "کلید پیدا نشد یا قبلاً باطل شده است.")
            return redirect("panel:reseller_api_keys")

    keys = bot_db.list_api_keys(reseller["id"])
    logs = bot_db.get_api_logs(reseller["id"], limit=30)

    return render(request, "user/reseller_api_keys.html", {
        "db_user": db_user, "tg_user": tg_user, "is_admin": is_admin(request),
        "reseller": reseller, "keys": keys, "logs": logs, "new_raw_key": new_raw_key,
        "api_base_url": f"{request.scheme}://{request.get_host()}{settings.WEB_PATH}/api/v1",
    })


# ── Admin: Reseller plans ────────────────────────────────────────────────────

@admin_required
def admin_reseller_plans(request: HttpRequest):
    plans = bot_db.get_reseller_plans(active_only=False)
    panels = bot_db.get_panels()
    return render(request, "admin/reseller_plans.html", {
        "plans": plans, "panels": panels, "is_admin": True,
    })


@admin_required
def admin_reseller_plan_edit(request: HttpRequest, plan_id: int = 0):
    panels = bot_db.get_panels()
    plan = bot_db.get_reseller_plan(plan_id) if plan_id else None

    if request.method == "POST":
        data = {
            "name": request.POST["name"],
            "panel_id": int(request.POST["panel_id"]),
            "volume_gb": float(request.POST["volume_gb"]),
            "duration_days": int(request.POST["duration_days"]),
            "price": int(request.POST["price"]),
            "description": request.POST.get("description", ""),
            "is_active": 1 if request.POST.get("is_active") else 0,
        }
        if plan_id:
            bot_db.update_reseller_plan(plan_id, **data)
            messages.success(request, "پلن نمایندگی ویرایش شد.")
        else:
            bot_db.add_reseller_plan(**{k: v for k, v in data.items() if k != "is_active"})
            messages.success(request, "پلن نمایندگی اضافه شد.")
        return redirect("panel:admin_reseller_plans")

    return render(request, "admin/reseller_plan_edit.html", {
        "plan": plan, "panels": panels, "is_admin": True,
    })


@admin_required
@require_POST
def admin_reseller_plan_delete(request: HttpRequest, plan_id: int):
    try:
        bot_db.delete_reseller_plan(plan_id)
        messages.success(request, "پلن نمایندگی حذف شد.")
    except Exception:
        messages.error(request, "این پلن توسط نماینده‌ای استفاده شده و قابل حذف کامل نیست.")
    return redirect("panel:admin_reseller_plans")


# ── Admin: Resellers review ──────────────────────────────────────────────────

@admin_required
def admin_resellers(request: HttpRequest):
    resellers = bot_db.get_all_resellers()
    now = int(time.time())
    for r in resellers:
        r["used_gb"] = bot_db.get_reseller_used_gb(r["id"])
        r["remaining_gb"] = max(0.0, r["quota_gb"] - r["used_gb"])
        r["expired"] = bool(r["expires_at"]) and r["expires_at"] < now
        r["expires_at_text"] = _format_ts(r["expires_at"])
    return render(request, "admin/resellers.html", {
        "resellers": resellers, "is_admin": True,
    })


@admin_required
def admin_reseller_detail(request: HttpRequest, reseller_id: int):
    reseller = bot_db.get_reseller(reseller_id)
    if not reseller:
        messages.error(request, "نماینده پیدا نشد.")
        return redirect("panel:admin_resellers")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "disable":
            bot_db.set_reseller_status(reseller_id, "disabled")
            telegram_api.send_message(
                int(reseller["telegram_id"]),
                "🚫 حساب نمایندگی شما توسط ادمین غیرفعال شد. پنل تحت وب نمایندگی شما قفل شده است.",
            )
            messages.warning(request, "حساب نماینده غیرفعال شد.")
        elif action == "enable":
            bot_db.set_reseller_status(reseller_id, "active")
            telegram_api.send_message(
                int(reseller["telegram_id"]),
                "✅ حساب نمایندگی شما دوباره فعال شد.",
            )
            messages.success(request, "حساب نماینده فعال شد.")
        elif action == "edit_quota":
            try:
                new_quota = float(request.POST.get("quota_gb", "").strip())
                if new_quota <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                messages.error(request, "مقدار حجم نامعتبر است.")
                return redirect("panel:admin_reseller_detail", reseller_id=reseller_id)
            bot_db.update_reseller(reseller_id, quota_gb=new_quota)
            messages.success(request, f"حجم نماینده به {new_quota} GB بروزرسانی شد.")
        elif action == "edit_expiry":
            try:
                days = int(request.POST.get("expiry_days", "").strip())
                if days < 0:
                    raise ValueError
            except (TypeError, ValueError):
                messages.error(request, "مقدار روز نامعتبر است.")
                return redirect("panel:admin_reseller_detail", reseller_id=reseller_id)
            new_expires_at = int(time.time()) + days * 86400 if days > 0 else 0
            bot_db.update_reseller(reseller_id, expires_at=new_expires_at)
            messages.success(request, "تاریخ انقضای نماینده بروزرسانی شد.")
        elif action == "delete":
            # Best-effort removal from the actual VPN panel first; a
            # panel-side failure doesn't block deleting the bot.db records
            # (the admin explicitly confirmed this), but we surface exactly
            # which configs may need manual cleanup on the panel so nothing
            # is silently orphaned.
            configs = bot_db.get_reseller_configs(reseller_id, include_deleted=False)
            failed_emails = []
            for cfg in configs:
                try:
                    ok = xui_client.delete_client(reseller["panel_url"], reseller["api_token"], cfg["email"])
                    if not ok:
                        failed_emails.append(cfg["email"])
                except Exception:
                    failed_emails.append(cfg["email"])

            bot_db.delete_reseller(reseller_id)
            try:
                telegram_api.send_message(
                    int(reseller["telegram_id"]),
                    "🗑 حساب نمایندگی شما توسط ادمین حذف شد. برای اطلاعات بیشتر با پشتیبانی تماس بگیرید.",
                )
            except Exception:
                pass

            if failed_emails:
                messages.warning(
                    request,
                    f"نماینده حذف شد، ولی حذف {len(failed_emails)} کانفیگ از روی پنل ناموفق بود "
                    "(ممکن است لازم باشد دستی از پنل پاک شوند): " + ", ".join(failed_emails[:10]),
                )
            else:
                messages.success(request, "نماینده و همه‌ی کانفیگ‌های آن با موفقیت حذف شدند.")
            return redirect("panel:admin_resellers")
        return redirect("panel:admin_reseller_detail", reseller_id=reseller_id)

    configs = bot_db.get_reseller_configs(reseller_id)
    used_gb = bot_db.get_reseller_used_gb(reseller_id)
    _annotate_config_usage(reseller, configs)
    return render(request, "admin/reseller_detail.html", {
        "reseller": reseller, "configs": configs, "used_gb": used_gb,
        "remaining_gb": max(0.0, reseller["quota_gb"] - used_gb),
        "expires_at_text": _format_ts(reseller["expires_at"]),
        "is_admin": True,
    })
