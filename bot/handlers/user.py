"""User-facing bot handlers."""

import json
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.keyboards import (
    admin_coupons_inline,
    back_kb,
    balance_inline,
    cancel_kb,
    channel_required_inline,
    complete_purchase_inline,
    confirm_buy_inline,
    faq_inline,
    insufficient_balance_inline,
    insufficient_balance_renew_inline,
    main_menu,
    panels_buy_inline,
    payment_actions_inline,
    products_by_panel_inline,
    products_inline,
    renew_confirm_inline,
    service_actions_inline,
    services_inline,
    tutorials_inline,
)
from bot.messages import t
from config import get_settings
from database import get_db
from services.subscription import SubscriptionService
from utils.helpers import format_expiry, load_config_links, parse_positive_int

logger = logging.getLogger(__name__)
router = Router()
sub_service = SubscriptionService()


class DepositForm(StatesGroup):
    amount = State()


class CouponForm(StatesGroup):
    code = State()


async def check_channel(member_check, user_id: int, channel: str) -> bool:
    if not channel:
        return True
    try:
        member = await member_check(chat_id=channel, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


def _build_product_preview(product: dict, coupon_code: str | None = None, discount_amount: int = 0):
    """Build the text + confirm/coupon keyboard shown before a purchase.

    Shared between the in-bot "buy:<id>" callback (tapping a product in the
    list) and the /start buy_<id> deep link (coming from the Mini App's
    خرید از ربات button), so both entry points show the exact same screen.
    """
    discount_amount = discount_amount or 0
    final_price = product["price"] - discount_amount
    text = (
        f"📦 {product['name']}\n"
        f"📊 حجم: {product['volume_gb']} GB\n"
        f"⏱ مدت: {product['duration_days']} روز\n"
        f"💰 قیمت: {product['price']:,} تومان\n"
        f"📡 پنل: {product['panel_name']}\n"
    )
    if coupon_code and discount_amount:
        text += f"🎟 کوپن: {coupon_code} (−{discount_amount:,} تومان)\n"
        text += f"💵 قیمت نهایی: {final_price:,} تومان\n"
    if product.get("description"):
        text += f"\n📝 {product['description']}"
    markup = confirm_buy_inline(
        product["id"],
        product.get("panel_id"),
        coupon_code=coupon_code,
        discount_amount=discount_amount,
    )
    return text, markup


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    db_user: dict,
    is_admin: bool,
    command: CommandObject,
    state: FSMContext,
):
    db = get_db()
    args = (command.args or "").strip()

    # Deep link from the Mini App's "خرید از ربات" button:
    # https://t.me/<bot>?start=buy_<product_id>
    if args.startswith("buy_"):
        raw_id = args[len("buy_"):]
        if raw_id.isdigit():
            settings = get_settings()
            channel = await db.get_setting("channel_required") or settings.required_channel
            if channel and not await check_channel(
                message.bot.get_chat_member, message.from_user.id, channel
            ):
                invite_link = await db.get_setting("channel_invite_link", "")
                await message.answer(
                    t("channel_required"),
                    reply_markup=channel_required_inline(invite_link, "recheck:buy"),
                )
                return
            product = await db.get_product(int(raw_id))
            if product and product.get("is_active"):
                text, markup = _build_product_preview(product)
                await message.answer(text, reply_markup=markup)
                return
            await message.answer("❌ این محصول یافت نشد یا دیگر فعال نیست.")
            return

    # Deep link from the Mini App's wallet page "ارسال رسید در ربات" button:
    # https://t.me/<bot>?start=deposit
    if args == "deposit":
        await _start_deposit_flow(message.answer, state)
        return

    welcome = await db.get_setting("welcome_text", t("welcome"))
    await message.answer(welcome, reply_markup=main_menu(is_admin))


@router.message(F.text == t("back"))
async def cmd_back(message: Message, is_admin: bool):
    await message.answer(t("main_menu"), reply_markup=main_menu(is_admin))


@router.message(F.text == t("cancel"))
async def cmd_cancel(message: Message, is_admin: bool):
    await message.answer(t("operation_cancelled"), reply_markup=main_menu(is_admin))


async def _send_buy_panel_list(answer, db_user: dict):
    """ابتدا لیست پنل‌های فعال رو نشون می‌ده تا کاربر یکی رو انتخاب کنه."""
    db = get_db()
    # فقط پنل‌هایی که حداقل یه محصول فعال دارن نشون بده
    panels_raw = await db.get_panels(active_only=True)
    products_all = await db.get_products(active_only=True, trial=False)

    panel_has_products = {p["panel_id"] for p in products_all}
    panels = [p for p in panels_raw if p["id"] in panel_has_products]

    if not panels:
        await answer(t("no_products"))
        return

    if len(panels) == 1:
        # فقط یه پنل داریم، مستقیم محصولاتش رو نشون بده
        panel = panels[0]
        prods = [p for p in products_all if p["panel_id"] == panel["id"]]
        await answer(
            f"🖥 {panel['name']}\n\n📦 یک پلن را انتخاب کنید:",
            reply_markup=products_by_panel_inline(prods, panel["name"]),
        )
        return

    await answer(
        "🖥 ابتدا یک پنل را انتخاب کنید:",
        reply_markup=panels_buy_inline(panels),
    )


@router.message(F.text == t("buy_service"))
async def buy_service(message: Message, db_user: dict):
    db = get_db()
    settings = get_settings()
    channel = await db.get_setting("channel_required") or settings.required_channel
    if channel and not await check_channel(message.bot.get_chat_member, message.from_user.id, channel):
        invite_link = await db.get_setting("channel_invite_link", "")
        await message.answer(
            t("channel_required"),
            reply_markup=channel_required_inline(invite_link, "recheck:buy"),
        )
        return

    await _send_buy_panel_list(message.answer, db_user)


@router.callback_query(F.data == "recheck:buy")
async def recheck_buy_channel(callback: CallbackQuery, db_user: dict):
    db = get_db()
    settings = get_settings()
    channel = await db.get_setting("channel_required") or settings.required_channel
    if channel and not await check_channel(callback.bot.get_chat_member, callback.from_user.id, channel):
        await callback.answer("❌ هنوز در کانال عضو نشده‌اید.", show_alert=True)
        return
    await callback.answer("✅ عضویت تأیید شد.")
    await _send_buy_panel_list(callback.message.answer, db_user)


@router.callback_query(F.data.startswith("buy_panel:"))
async def buy_panel_selected(callback: CallbackQuery):
    """کاربر یک پنل رو انتخاب کرد — محصولات اون پنل رو نشون بده."""
    panel_id = int(callback.data.split(":")[1])
    db = get_db()
    panel = await db.get_panel(panel_id)
    if not panel:
        await callback.answer("پنل پیدا نشد", show_alert=True)
        return

    products = await db.get_products(active_only=True, trial=False)
    panel_products = [p for p in products if p["panel_id"] == panel_id]

    if not panel_products:
        await callback.answer("❌ در این پنل محصول فعالی وجود ندارد.", show_alert=True)
        return

    await callback.message.edit_text(
        f"🖥 {panel['name']}\n\n📦 یک پلن را انتخاب کنید:",
        reply_markup=products_by_panel_inline(panel_products, panel["name"]),
    )
    await callback.answer()


@router.callback_query(F.data == "buy_back_panels")
async def buy_back_to_panels(callback: CallbackQuery):
    """برگشت به صفحه انتخاب پنل."""
    db = get_db()
    panels_raw = await db.get_panels(active_only=True)
    products_all = await db.get_products(active_only=True, trial=False)
    panel_has_products = {p["panel_id"] for p in products_all}
    panels = [p for p in panels_raw if p["id"] in panel_has_products]

    if not panels:
        await callback.answer(t("no_products"), show_alert=True)
        return

    await callback.message.edit_text(
        "🖥 ابتدا یک پنل را انتخاب کنید:",
        reply_markup=panels_buy_inline(panels),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy:"))
async def buy_product_preview(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    db = get_db()
    product = await db.get_product(product_id)
    if not product:
        await callback.answer("محصول پیدا نشد", show_alert=True)
        return

    # کوپن احتمالی که کاربر قبلاً وارد کرده
    fsm_data = await state.get_data()
    coupon_code = fsm_data.get("coupon_code")
    discount_amount = fsm_data.get("discount_amount", 0)

    text, markup = _build_product_preview(product, coupon_code, discount_amount)
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("enter_coupon:"))
async def enter_coupon_start(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    await state.update_data(coupon_product_id=product_id)
    await state.set_state(CouponForm.code)
    await callback.message.answer(
        "🎟 کد کوپن تخفیف خود را وارد کنید:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(CouponForm.code)
async def enter_coupon_code(message: Message, state: FSMContext, db_user: dict):
    if message.text == t("cancel"):
        await state.set_state(None)
        await state.update_data(coupon_code=None, discount_amount=0, coupon_id=None)
        data = await state.get_data()
        product_id = data.get("coupon_product_id")
        await message.answer(t("operation_cancelled"))
        if product_id:
            db = get_db()
            product = await db.get_product(product_id)
            if product:
                await message.answer(
                    f"📦 {product['name']}\n💰 قیمت: {product['price']:,} تومان",
                    reply_markup=confirm_buy_inline(product_id, product.get("panel_id")),
                )
        return

    code = (message.text or "").strip()
    db = get_db()
    coupon, err = await db.validate_coupon(code, db_user["id"])
    if err:
        await message.answer(err)
        await state.set_state(None)
        data = await state.get_data()
        product_id = data.get("coupon_product_id")
        if product_id:
            product = await db.get_product(product_id)
            if product:
                await message.answer(
                    f"📦 {product['name']}\n💰 قیمت: {product['price']:,} تومان",
                    reply_markup=confirm_buy_inline(product_id, product.get("panel_id")),
                )
        return

    data = await state.get_data()
    product_id = data.get("coupon_product_id")
    product = await db.get_product(product_id) if product_id else None
    if not product:
        await message.answer("❌ محصول پیدا نشد.")
        await state.clear()
        return

    discount = db.calc_discount(coupon, product["price"])
    final_price = product["price"] - discount

    await state.set_state(None)
    await state.update_data(
        coupon_code=coupon["code"],
        coupon_id=coupon["id"],
        discount_amount=discount,
    )

    text = (
        f"✅ کوپن «{coupon['code']}» اعمال شد!\n\n"
        f"📦 {product['name']}\n"
        f"📊 حجم: {product['volume_gb']} GB\n"
        f"⏱ مدت: {product['duration_days']} روز\n"
        f"💰 قیمت اصلی: {product['price']:,} تومان\n"
        f"🎟 تخفیف: −{discount:,} تومان\n"
        f"💵 قیمت نهایی: {final_price:,} تومان\n"
        f"📡 پنل: {product['panel_name']}\n"
    )
    await message.answer(
        text,
        reply_markup=confirm_buy_inline(
            product_id,
            product.get("panel_id"),
            coupon_code=coupon["code"],
            discount_amount=discount,
        ),
    )


@router.callback_query(F.data.startswith("confirm_buy:"))
async def confirm_buy(callback: CallbackQuery, db_user: dict, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    db = get_db()
    product = await db.get_product(product_id)
    if not product:
        await callback.answer("محصول پیدا نشد", show_alert=True)
        return

    # کوپن از FSM state
    fsm_data = await state.get_data()
    coupon_code = fsm_data.get("coupon_code")
    coupon_id = fsm_data.get("coupon_id")
    discount_amount = int(fsm_data.get("discount_amount", 0))

    final_price = max(0, product["price"] - discount_amount)

    # Re-fetch the user's current balance — db_user may be stale if they just topped up.
    fresh_user = await db._fetchone("SELECT * FROM users WHERE id = ?", (db_user["id"],))
    balance = fresh_user["balance"] if fresh_user else db_user["balance"]

    if balance < final_price:
        deficit = final_price - balance
        await callback.message.edit_text(
            t(
                "insufficient_balance",
                balance=balance,
                price=final_price,
                deficit=deficit,
            ),
            reply_markup=insufficient_balance_inline(product_id),
        )
        await callback.answer()
        return

    try:
        result = await sub_service.create_from_product(
            db_user["id"],
            callback.from_user.id,
            product,
        )
        await db.update_user_balance(db_user["id"], -final_price)
        await db.create_order(
            db_user["id"],
            product_id,
            final_price,
            "balance",
            f"خرید {product['name']}"
            + (f" (کوپن: {coupon_code}، تخفیف: {discount_amount:,} تومان)" if coupon_code else ""),
        )
        # ثبت استفاده از کوپن
        if coupon_id and coupon_code:
            await db.apply_coupon(coupon_id, db_user["id"])
        # پاک کردن کوپن از state
        await state.update_data(coupon_code=None, coupon_id=None, discount_amount=0)

        success_text = t(
            "purchase_success",
            email=result["email"],
            volume=product["volume_gb"],
            days=product["duration_days"],
        )
        if coupon_code and discount_amount:
            success_text += f"\n\n🎟 کوپن «{coupon_code}» اعمال شد — {discount_amount:,} تومان تخفیف"

        await callback.message.edit_text(
            success_text,
            parse_mode="Markdown",
            reply_markup=service_actions_inline(result["id"], show_back=False),
        )
    except ValueError as e:
        await callback.message.edit_text(str(e))
    except Exception as e:
        logger.exception("Purchase failed")
        await callback.message.edit_text(f"❌ خطا در خرید: {e}")

    await callback.answer()


@router.callback_query(F.data.startswith("card_topup:"))
async def card_topup_start(callback: CallbackQuery, db_user: dict, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    db = get_db()
    product = await db.get_product(product_id)
    if not product:
        await callback.answer("محصول پیدا نشد", show_alert=True)
        return

    # کوپن احتمالی
    fsm_data = await state.get_data()
    coupon_code = fsm_data.get("coupon_code")
    coupon_id = fsm_data.get("coupon_id")
    discount_amount = int(fsm_data.get("discount_amount", 0))
    final_price = max(0, product["price"] - discount_amount)

    fresh_user = await db._fetchone("SELECT * FROM users WHERE id = ?", (db_user["id"],))
    balance = fresh_user["balance"] if fresh_user else db_user["balance"]
    deficit = final_price - balance
    if deficit <= 0:
        await callback.answer("موجودی شما کافی است، دوباره روی تأیید خرید بزنید.", show_alert=True)
        return

    settings = get_settings()
    card = settings.card_number or await db.get_setting("card_number", "")
    holder = settings.card_holder or await db.get_setting("card_holder", "")
    if not card:
        await callback.answer("❌ شماره کارت تنظیم نشده. با ادمین تماس بگیرید.", show_alert=True)
        return

    payment_id = await db.create_payment(
        db_user["id"], deficit, "card", product_id=product_id,
    )
    # ذخیره اطلاعات کوپن روی پرداخت
    if coupon_code and discount_amount:
        await db._execute(
            "UPDATE payments SET coupon_code = ?, discount_amount = ? WHERE id = ?",
            (coupon_code, discount_amount, payment_id),
        )

    await callback.message.answer(
        t("deposit_card_info", amount=deficit, card=card, holder=holder),
        parse_mode="Markdown",
    )
    await callback.message.answer(
        "📸 لطفاً تصویر رسید پرداخت را ارسال کنید. به محض تأیید ادمین، موجودی شما شارژ "
        "می‌شود و می‌توانید همان خرید را تکمیل کنید.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def callback_cancel(callback: CallbackQuery):
    await callback.message.edit_text(t("operation_cancelled"))
    await callback.answer()


async def _resolve_trial_product(db) -> dict | None:
    """Build the product-like dict used to provision a trial account.

    Prefers a dedicated trial product (is_trial=1) if one exists, applying any
    admin-configured volume/duration overrides on top of it. Falls back to a
    fully settings-driven trial (trial_panel_id/trial_volume_gb/trial_duration_days)
    so admins can configure trials without needing to create a product at all.
    """
    vol_override = await db.get_setting("trial_volume_gb", "")
    days_override = await db.get_setting("trial_duration_days", "")

    trial_product_id = int(await db.get_setting("trial_product_id", "0") or 0)
    product = None
    if trial_product_id:
        product = await db.get_product(trial_product_id)
    if not product:
        products = await db.get_products(active_only=True, trial=True)
        if products:
            product = products[0]

    if product:
        product = dict(product)
        if vol_override:
            product["volume_gb"] = float(vol_override)
        if days_override:
            product["duration_days"] = int(days_override)
        return product

    panel_id_setting = await db.get_setting("trial_panel_id", "")
    if not panel_id_setting:
        return None
    panel = await db.get_panel(int(panel_id_setting))
    if not panel:
        return None
    return {
        "id": None,
        "panel_id": panel["id"],
        "volume_gb": float(vol_override) if vol_override else 1.0,
        "duration_days": int(days_override) if days_override else 1,
        "name": "اکانت تست",
        "price": 0,
        "is_trial": 1,
    }


@router.message(F.text == t("trial"))
async def trial_account(message: Message, db_user: dict):
    db = get_db()
    if await db.user_has_trial(db_user["id"]):
        await message.answer(t("trial_used"))
        return

    trial_enabled = await db.get_setting("trial_enabled", "1")
    if trial_enabled != "1":
        await message.answer(t("trial_disabled"))
        return

    product = await _resolve_trial_product(db)
    if not product:
        await message.answer(t("trial_disabled"))
        return

    try:
        result = await sub_service.create_from_product(
            db_user["id"],
            message.from_user.id,
            product,
            is_trial=True,
        )
        await message.answer(
            t(
                "trial_success",
                email=result["email"],
                volume=product["volume_gb"],
                days=product["duration_days"],
            ),
            parse_mode="Markdown",
            reply_markup=service_actions_inline(result["id"], show_back=False, renewable=False),
        )
    except ValueError as e:
        await message.answer(str(e))
    except Exception as e:
        logger.exception("Trial failed")
        await message.answer(f"❌ خطا: {e}")


@router.message(F.text == t("my_services"))
async def my_services(message: Message, db_user: dict):
    db = get_db()
    services = await db.get_user_subscriptions(db_user["id"])
    active = [s for s in services if s["status"] == "active"]
    if not active:
        await message.answer(t("no_services"))
        return
    await message.answer("📦 سرویس‌های شما:", reply_markup=services_inline(active))


@router.callback_query(F.data == "back_services")
async def back_services(callback: CallbackQuery, db_user: dict):
    db = get_db()
    services = await db.get_user_subscriptions(db_user["id"])
    active = [s for s in services if s["status"] == "active"]
    await callback.message.edit_text(
        "📦 سرویس‌های شما:",
        reply_markup=services_inline(active),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("service:"))
async def service_detail(callback: CallbackQuery, db_user: dict):
    sub_id = int(callback.data.split(":")[1])
    db = get_db()
    sub = await db.get_subscription(sub_id)
    if not sub or sub["user_id"] != db_user["id"]:
        await callback.answer("سرویس پیدا نشد", show_alert=True)
        return

    try:
        usage = await sub_service.get_usage(sub_id)
        used = usage["used_gb"]
        expiry = format_expiry(usage["expiry_time"])
    except Exception:
        used = "—"
        expiry = format_expiry(sub.get("expiry_time", 0))

    text = t(
        "service_detail",
        id=sub["id"],
        email=sub["email"],
        volume=sub["volume_gb"],
        used=used,
        expiry=expiry,
        panel=sub.get("panel_name", ""),
    )
    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=service_actions_inline(
            sub_id, renewable=not sub.get("is_trial") and bool(sub.get("product_id"))
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("getconfig:"))
async def get_config(callback: CallbackQuery, db_user: dict):
    sub_id = int(callback.data.split(":")[1])
    db = get_db()
    sub = await db.get_subscription(sub_id)
    if not sub or sub["user_id"] != db_user["id"]:
        await callback.answer("سرویس پیدا نشد", show_alert=True)
        return

    links = load_config_links(sub)
    if not links:
        await callback.answer("❌ کانفیگی برای این سرویس ثبت نشده است.", show_alert=True)
        return

    for i, link in enumerate(links, 1):
        label = f"🔧 کانفیگ {i} از {len(links)}" if len(links) > 1 else "🔧 کانفیگ شما"
        await callback.message.answer(f"{label}:\n`{link}`", parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("getsublink:"))
async def get_sub_link(callback: CallbackQuery, db_user: dict):
    sub_id = int(callback.data.split(":")[1])
    db = get_db()
    sub = await db.get_subscription(sub_id)
    if not sub or sub["user_id"] != db_user["id"]:
        await callback.answer("سرویس پیدا نشد", show_alert=True)
        return

    sub_link = sub.get("sub_link")
    if not sub_link:
        await callback.answer("❌ لینک ساب برای این سرویس ثبت نشده است.", show_alert=True)
        return

    await callback.message.answer(f"🔗 لینک سابسکریپشن:\n`{sub_link}`", parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("refresh:"))
async def refresh_link(callback: CallbackQuery, db_user: dict):
    sub_id = int(callback.data.split(":")[1])
    db = get_db()
    sub = await db.get_subscription(sub_id)
    if not sub or sub["user_id"] != db_user["id"]:
        await callback.answer("سرویس پیدا نشد", show_alert=True)
        return

    try:
        await sub_service.refresh_links(sub_id)
        await callback.message.answer(
            "🔄 کانفیگ‌ها و لینک ساب بروزرسانی شد. برای دریافت نسخه جدید از دکمه‌های "
            "«دریافت کانفیگ» یا «دریافت لینک ساب» استفاده کنید."
        )
    except Exception as e:
        await callback.message.answer(f"❌ خطا: {e}")
    await callback.answer()


@router.callback_query(F.data.startswith("svc_renew:"))
async def renew_service_confirm(callback: CallbackQuery, db_user: dict):
    sub_id = int(callback.data.split(":")[1])
    db = get_db()
    sub = await db.get_subscription(sub_id)
    if not sub or sub["user_id"] != db_user["id"]:
        await callback.answer("سرویس پیدا نشد", show_alert=True)
        return
    if sub.get("is_trial"):
        await callback.answer("❌ سرویس‌های تستی قابل تمدید نیستند.", show_alert=True)
        return
    if not sub.get("product_id"):
        await callback.answer("❌ این سرویس به محصولی متصل نیست و قابل تمدید نیست.", show_alert=True)
        return
    product = await db.get_product(sub["product_id"])
    if not product:
        await callback.answer("❌ محصول مرتبط با این سرویس دیگر موجود نیست.", show_alert=True)
        return

    text = (
        f"🔁 تمدید سرویس «{sub['email']}»\n"
        f"📊 حجم اضافه: {product['volume_gb']} GB\n"
        f"⏱ مدت اضافه: {product['duration_days']} روز\n"
        f"💰 هزینه: {product['price']:,} تومان\n\n"
        "آیا تأیید می‌کنید؟"
    )
    await callback.message.answer(text, reply_markup=renew_confirm_inline(sub_id))
    await callback.answer()


@router.callback_query(F.data.startswith("svc_renew_ok:"))
async def renew_service_execute(callback: CallbackQuery, db_user: dict):
    sub_id = int(callback.data.split(":")[1])
    db = get_db()
    sub = await db.get_subscription(sub_id)
    if not sub or sub["user_id"] != db_user["id"]:
        await callback.answer("سرویس پیدا نشد", show_alert=True)
        return
    product = await db.get_product(sub["product_id"]) if sub.get("product_id") else None
    if not product:
        await callback.answer("❌ این سرویس قابل تمدید نیست.", show_alert=True)
        return

    fresh_user = await db._fetchone("SELECT * FROM users WHERE id = ?", (db_user["id"],))
    balance = fresh_user["balance"] if fresh_user else db_user["balance"]

    if balance < product["price"]:
        deficit = product["price"] - balance
        await callback.message.edit_text(
            t("insufficient_balance", balance=balance, price=product["price"], deficit=deficit),
            reply_markup=insufficient_balance_renew_inline(sub_id),
        )
        await callback.answer()
        return

    try:
        result = await sub_service.renew_subscription(
            sub_id, product["duration_days"], product["volume_gb"]
        )
        await db.update_user_balance(db_user["id"], -product["price"])
        await db.create_order(
            db_user["id"],
            product["id"],
            product["price"],
            "balance",
            f"تمدید {product['name']} (سرویس #{sub_id})",
        )
        await callback.message.edit_text(
            f"✅ سرویس با موفقیت تمدید شد!\n\n"
            f"📊 حجم فعلی: {result['volume_gb']} GB\n"
            f"⏱ انقضای جدید: {format_expiry(result['expiry_time'])}",
            reply_markup=service_actions_inline(sub_id, show_back=False),
        )
    except ValueError as e:
        await callback.message.edit_text(str(e))
    except Exception as e:
        logger.exception("Renew failed")
        await callback.message.edit_text(f"❌ خطا در تمدید: {e}")
    await callback.answer()


@router.callback_query(F.data.startswith("card_topup_renew:"))
async def card_topup_renew_start(callback: CallbackQuery, db_user: dict):
    sub_id = int(callback.data.split(":")[1])
    db = get_db()
    sub = await db.get_subscription(sub_id)
    if not sub or sub["user_id"] != db_user["id"]:
        await callback.answer("سرویس پیدا نشد", show_alert=True)
        return
    product = await db.get_product(sub["product_id"]) if sub.get("product_id") else None
    if not product:
        await callback.answer("❌ این سرویس قابل تمدید نیست.", show_alert=True)
        return

    fresh_user = await db._fetchone("SELECT * FROM users WHERE id = ?", (db_user["id"],))
    balance = fresh_user["balance"] if fresh_user else db_user["balance"]
    deficit = product["price"] - balance
    if deficit <= 0:
        await callback.answer("موجودی شما کافی است، دوباره روی تأیید تمدید بزنید.", show_alert=True)
        return

    settings = get_settings()
    card = settings.card_number or await db.get_setting("card_number", "")
    holder = settings.card_holder or await db.get_setting("card_holder", "")
    if not card:
        await callback.answer("❌ شماره کارت تنظیم نشده. با ادمین تماس بگیرید.", show_alert=True)
        return

    await db.create_payment(db_user["id"], deficit, "card", renew_sub_id=sub_id)
    await callback.message.answer(
        t("deposit_card_info", amount=deficit, card=card, holder=holder),
        parse_mode="Markdown",
    )
    await callback.message.answer(
        "📸 لطفاً تصویر رسید پرداخت را ارسال کنید. به محض تأیید ادمین، موجودی شما شارژ "
        "می‌شود و می‌توانید همان تمدید را تکمیل کنید.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("usage:"))
async def show_usage(callback: CallbackQuery, db_user: dict):
    sub_id = int(callback.data.split(":")[1])
    db = get_db()
    sub = await db.get_subscription(sub_id)
    if not sub or sub["user_id"] != db_user["id"]:
        await callback.answer("سرویس پیدا نشد", show_alert=True)
        return

    try:
        usage = await sub_service.get_usage(sub_id)
        text = (
            f"📊 مصرف سرویس #{sub_id}\n"
            f"⬆️ آپلود: {usage['used_gb']:.2f} GB (از {usage['total_gb']} GB)\n"
            f"⏱ انقضا: {format_expiry(usage['expiry_time'])}"
        )
        await callback.message.answer(text)
    except Exception as e:
        await callback.message.answer(f"❌ خطا: {e}")
    await callback.answer()


@router.message(F.text == t("balance"))
async def show_balance(message: Message, db_user: dict):
    await message.answer(
        t("balance_info", balance=db_user["balance"]),
        reply_markup=balance_inline(),
    )


async def _start_deposit_flow(answer, state: FSMContext):
    db = get_db()
    min_dep = int(await db.get_setting("min_deposit", "10000"))
    await state.set_state(DepositForm.amount)
    await answer(t("enter_deposit_amount", min=min_dep), reply_markup=cancel_kb())


@router.message(F.text == t("deposit"))
async def deposit_start(message: Message, state: FSMContext):
    await _start_deposit_flow(message.answer, state)


@router.callback_query(F.data == "deposit_start_cb")
async def deposit_start_callback(callback: CallbackQuery, state: FSMContext):
    await _start_deposit_flow(callback.message.answer, state)
    await callback.answer()


@router.message(DepositForm.amount)
async def deposit_amount(message: Message, state: FSMContext, db_user: dict):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=main_menu())
        return

    db = get_db()
    min_dep = int(await db.get_setting("min_deposit", "10000"))
    amount = parse_positive_int(message.text or "")
    if not amount or amount < min_dep:
        await message.answer(t("invalid_amount"))
        return

    settings = get_settings()
    card = settings.card_number or await db.get_setting("card_number", "")
    holder = settings.card_holder or await db.get_setting("card_holder", "")
    if not card:
        await message.answer("❌ شماره کارت تنظیم نشده. با ادمین تماس بگیرید.")
        await state.clear()
        return

    await db.create_payment(db_user["id"], amount, "card")
    await state.clear()
    await message.answer(
        t("deposit_card_info", amount=amount, card=card, holder=holder),
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )
    await message.answer(
        "📸 لطفاً تصویر رسید پرداخت را ارسال کنید.",
        reply_markup=cancel_kb(),
    )


@router.message(F.photo)
async def deposit_receipt(message: Message, db_user: dict):
    db = get_db()
    pending = await db._fetchall(
        "SELECT * FROM payments WHERE user_id = ? AND status = 'pending' AND receipt_file_id IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (db_user["id"],),
    )
    if not pending:
        return

    payment = pending[0]
    file_id = message.photo[-1].file_id
    await db._execute(
        "UPDATE payments SET receipt_file_id = ? WHERE id = ?",
        (file_id, payment["id"]),
    )

    caption = (
        f"💳 درخواست افزایش موجودی\n"
        f"👤 کاربر: {message.from_user.id}\n"
        f"💰 مبلغ پرداختی: {payment['amount']:,} تومان"
    )
    if payment.get("coupon_code") and payment.get("discount_amount"):
        original = payment["amount"] + payment["discount_amount"]
        caption += (
            f"\n🎟 کوپن تخفیف: {payment['coupon_code']}"
            f"\n📉 مقدار تخفیف: −{payment['discount_amount']:,} تومان"
            f"\n🏷 قیمت اصلی: {original:,} تومان"
        )
    if payment.get("renew_sub_id"):
        caption += f"\n🔁 برای تکمیل تمدید سرویس: #{payment['renew_sub_id']}"
    elif payment.get("product_id"):
        product = await db.get_product(payment["product_id"])
        if product:
            caption += f"\n🛒 برای تکمیل خرید: {product['name']}"

    settings = get_settings()
    sent_refs = []
    for admin_id in settings.admin_ids:
        try:
            sent = await message.bot.send_photo(
                admin_id,
                file_id,
                caption=caption,
                reply_markup=payment_actions_inline(payment["id"]),
            )
            sent_refs.append({"chat_id": sent.chat.id, "message_id": sent.message_id})
        except Exception:
            pass
    if sent_refs:
        await db.set_payment_notif_chats(payment["id"], sent_refs)

    await message.answer(t("deposit_pending"), reply_markup=main_menu())


@router.message(F.text == t("support"))
async def support(message: Message):
    db = get_db()
    text = await db.get_setting("support_text", t("support"))
    username = await db.get_setting("support_username", "")
    if username:
        text += f"\n\n@{username}"
    await message.answer(text)


@router.message(F.text == t("faq"))
async def show_faq(message: Message):
    db = get_db()
    faqs = await db.get_faqs()
    if not faqs:
        await message.answer("❓ هنوز سوالی ثبت نشده.")
        return
    await message.answer("❓ سوالات متداول:", reply_markup=faq_inline(faqs))


@router.callback_query(F.data.startswith("faq:"))
async def faq_detail(callback: CallbackQuery):
    faq_id = int(callback.data.split(":")[1])
    db = get_db()
    faq = await db._fetchone("SELECT * FROM faq WHERE id = ?", (faq_id,))
    if not faq:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    await callback.message.answer(f"❓ {faq['question']}\n\n{faq['answer']}")
    await callback.answer()


@router.message(F.text == t("tutorials"))
async def show_tutorials(message: Message):
    db = get_db()
    items = await db.get_tutorials()
    if not items:
        await message.answer("📖 هنوز آموزشی ثبت نشده.")
        return
    await message.answer("📖 آموزش‌ها:", reply_markup=tutorials_inline(items))


@router.callback_query(F.data.startswith("tutorial:"))
async def tutorial_detail(callback: CallbackQuery):
    tid = int(callback.data.split(":")[1])
    db = get_db()
    item = await db._fetchone("SELECT * FROM tutorials WHERE id = ?", (tid,))
    if not item:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    await callback.message.answer(f"📖 {item['title']}\n\n{item['content']}")
    await callback.answer()
