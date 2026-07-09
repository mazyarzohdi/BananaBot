"""Views for BananaBot Web Panel."""

import json
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
        if action == "approve":
            if bot_db.approve_payment(payment_id, note):
                _notify_payment_status(payment, "approved", note)
                messages.success(request, "پرداخت تأیید و موجودی شارژ شد. به کاربر اطلاع داده شد.")
            else:
                messages.warning(request, "این پرداخت قبلاً بررسی شده بود.")
        elif action == "reject":
            if bot_db.reject_payment(payment_id, note):
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

    if request.method == "POST":
        for key in SETTINGS_META:
            if key in request.POST:
                bot_db.set_setting(key, request.POST[key])
        messages.success(request, "تنظیمات ذخیره شد.")
        return redirect("panel:admin_settings")

    fields = [
        {"key": k, **meta, "value": current.get(k, "")}
        for k, meta in SETTINGS_META.items()
    ]
    return render(request, "admin/settings.html", {
        "fields": fields, "is_admin": True,
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
