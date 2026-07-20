"""User-facing bot handlers."""

import logging
import random
import time
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.keyboards import (
    admin_ticket_notify_inline,
    auto_payment_copy_inline,
    balance_inline,
    cancel_kb,
    channel_required_inline,
    confirm_buy_inline,
    faq_inline,
    insufficient_balance_inline,
    insufficient_balance_renew_inline,
    main_menu,
    panels_buy_inline,
    payment_actions_inline,
    products_by_panel_inline,
    renew_confirm_inline,
    reseller_confirm_inline,
    reseller_insufficient_balance_inline,
    reseller_plans_inline,
    reseller_status_inline,
    service_actions_inline,
    services_inline,
    support_menu_inline,
    ticket_detail_inline,
    ticket_list_inline,
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


async def _reward_referral_and_notify(bot, db, buyer_user_id: int, purchase_amount: int, order_id: int | None, source: str):
    """بعد از هر خرید موفق (خرید جدید، تمدید سرویس، یا خرید/تمدید نمایندگی)
    صدا زده می‌شه. اگه خریدار با لینک معرفی وارد ربات شده باشه و سیستم
    رفرال فعال باشه، درصد/مبلغ پاداشی که ادمین از پنل تنظیمات مشخص کرده
    محاسبه و به کیف پول معرف واریز می‌شه و بلافاصله پیام واریزی هم براش
    ارسال می‌شه."""
    try:
        referral = await db.reward_referral_purchase(buyer_user_id, purchase_amount, order_id=order_id, source=source)
    except Exception:
        logger.exception("Referral purchase reward failed")
        return
    if not referral:
        return
    try:
        await bot.send_message(
            referral["referrer_telegram_id"],
            "🤝 پاداش معرفی\n\n"
            f"«{referral['referred_name']}» که با لینک معرفی شما وارد ربات شده، خریدی به مبلغ "
            f"{referral['purchase_amount']:,} تومان انجام داد.\n"
            f"💰 {referral['reward']:,} تومان پاداش معرفی به کیف پول شما واریز شد.\n"
            f"💳 موجودی جدید: {referral['referrer_new_balance']:,} تومان",
        )
    except Exception:
        pass


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


AUTO_PAYMENT_EXPIRY_MINUTES = 20


def _expiry_timestamp() -> str:
    """20 minutes from now, formatted to match SQLite's datetime('now')
    (UTC, 'YYYY-MM-DD HH:MM:SS') so the two can be compared as strings."""
    dt = datetime.now(timezone.utc) + timedelta(minutes=AUTO_PAYMENT_EXPIRY_MINUTES)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


async def _generate_auto_payment_rial(db, base_amount_toman: int) -> int:
    """Turns a base amount in Toman (e.g. 65,000 تومان) into a unique RIAL
    amount the user must transfer instead (e.g. 656,755 ریال): converts to
    Rial (×10, since 1 Toman = 10 Rial) and replaces the last 4 digits with
    a random verification code, so the bank-SMS webhook can match this
    exact payment by amount alone, without the user typing any reference
    number. Retries if another currently-pending auto-payment happens to
    be expecting the exact same amount already."""
    base_rial = base_amount_toman * 10
    base_rial_truncated = (base_rial // 10000) * 10000
    for _ in range(50):
        code = random.randint(0, 9999)
        candidate = base_rial_truncated + code
        if not await db.expected_amount_taken(candidate):
            return candidate
    return base_rial_truncated + random.randint(0, 9999)  # extremely unlikely fallback


async def _send_card_payment_instructions(
    answer, db, user_id: int, base_amount: int, *,
    product_id: int | None = None, renew_sub_id: int | None = None,
    reseller_plan_id: int | None = None,
) -> int:
    """Creates the payment record and shows the user what to pay —
    branching on whether auto-payment (bank SMS matching) is currently
    enabled. `answer` is either `message.answer` or `callback.message.answer`.
    Returns the created payment's id."""
    settings = get_settings()
    card = settings.card_number or await db.get_setting("card_number", "")
    holder = settings.card_holder or await db.get_setting("card_holder", "")

    auto_enabled = (await db.get_setting("auto_payment_enabled", "0")) == "1"

    if auto_enabled:
        pay_amount_rial = await _generate_auto_payment_rial(db, base_amount)
        expires_at = _expiry_timestamp()
        payment_id = await db.create_payment(
            user_id, base_amount, "card", product_id=product_id, renew_sub_id=renew_sub_id,
            reseller_plan_id=reseller_plan_id,
            expected_amount=pay_amount_rial, expires_at=expires_at,
        )
        await answer(
            f"💳 لطفاً دقیقاً مبلغ زیر را به شماره کارت زیر واریز کنید:\n\n"
            f"مبلغ: *{pay_amount_rial:,} ریال*\n"
            f"شماره کارت: `{card}`\n"
            f"به نام: {holder}\n\n"
            f"⚠️ *مبلغ باید دقیقاً همین عدد باشد، نه یک ریال کمتر یا بیشتر.* "
            f"چهار رقم آخر مبلغ، شناسه‌ی پرداخت شماست و برای شناسایی خودکار واریزی شما استفاده می‌شود.\n"
            f"اگر مبلغ اشتباه واریز شود، سیستم نمی‌تواند پرداخت شما را تشخیص دهد و موجودی شما شارژ نخواهد شد.\n\n"
            f"✅ به محض ثبت تراکنش در بانک، ظرف چند ثانیه به‌صورت خودکار تأیید و موجودی شما شارژ می‌شود.\n"
            f"⏰ این مبلغ فقط تا {AUTO_PAYMENT_EXPIRY_MINUTES} دقیقه معتبر است.",
            parse_mode="Markdown",
            reply_markup=auto_payment_copy_inline(pay_amount_rial, card),
        )
        # کیبورد پایینی (انصراف) روی پیام بالا قابل تنظیم نیست چون خودش کیبورد
        # شیشه‌ای (inline) دارد؛ برای همین در یک پیام کوتاه جدا نشان داده می‌شود.
        await answer("برای انصراف از این پرداخت:", reply_markup=cancel_kb())
    else:
        payment_id = await db.create_payment(
            user_id, base_amount, "card", product_id=product_id, renew_sub_id=renew_sub_id,
            reseller_plan_id=reseller_plan_id,
        )
        await answer(
            t("deposit_card_info", amount=base_amount, card=card, holder=holder),
            parse_mode="Markdown",
        )
        await answer(
            "📸 لطفاً تصویر رسید پرداخت را ارسال کنید. به محض تأیید ادمین، موجودی شما شارژ "
            "می‌شود و می‌توانید همان خرید را تکمیل کنید.",
            reply_markup=cancel_kb(),
        )
    return payment_id


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

    # /start always means "abandon whatever flow you were in and go to the
    # main menu" — without this, a state left over from e.g. an in-progress
    # deposit (DepositForm.amount) or coupon entry (CouponForm.code) would
    # keep intercepting the user's next message (any plain text, including
    # main-menu button taps) and misinterpret it as that flow's input
    # (e.g. "❌ مبلغ نامعتبر است" when tapping "📖 آموزش").
    await state.clear()
    await _cancel_dangling_payment(db_user)

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

    # Deep link from a referral share link: https://t.me/<bot>?start=ref_<referral_code>
    # (کد کوتاه و تصادفی — نه آیدی عددی تلگرام، تا لینک قابل‌حدس/شمارش نباشه)
    if args.startswith("ref_"):
        raw_ref = args[len("ref_"):]
        referrer = await db.get_user_by_referral_code(raw_ref)
        if referrer and referrer["id"] != db_user["id"]:
            await db.set_user_referred_by(db_user["id"], referrer["id"])

    welcome = await db.get_setting("welcome_text", t("welcome"))
    await message.answer(welcome, reply_markup=main_menu(is_admin))


async def _cancel_dangling_payment(db_user: dict):
    """If the user picked card-to-card (for a top-up, a purchase, or a
    renewal) and then backed out — via /start, "🔙 بازگشت", or "❌ انصراف"
    — before ever sending a receipt photo, the payment record created for
    that attempt was previously left sitting in the DB as 'pending'
    forever: still showing up in the admin's pending-payments list with
    working ✅/❌ buttons, even though the user explicitly cancelled and
    nothing was actually paid. This finds that exact dangling payment (if
    any — most of the time there isn't one) and marks it cancelled so it
    stops showing up for admin review."""
    db = get_db()
    payment = await db.get_latest_unreceipted_pending_payment(db_user["id"])
    if payment:
        await db.cancel_payment_if_unreceipted(payment["id"])


@router.message(F.text == t("back"))
async def cmd_back(message: Message, is_admin: bool, state: FSMContext, db_user: dict):
    await state.clear()
    await _cancel_dangling_payment(db_user)
    await message.answer(t("main_menu"), reply_markup=main_menu(is_admin))


@router.message(F.text == t("cancel"))
async def cmd_cancel(message: Message, is_admin: bool, state: FSMContext, db_user: dict):
    await state.clear()
    await _cancel_dangling_payment(db_user)
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
        order_id, _order_code = await db.create_order(
            db_user["id"],
            product_id,
            final_price,
            "balance",
            f"خرید {product['name']}"
            + (f" (کوپن: {coupon_code}، تخفیف: {discount_amount:,} تومان)" if coupon_code else ""),
        )
        await _reward_referral_and_notify(
            callback.bot, db, db_user["id"], final_price, order_id, f"خرید {product['name']}"
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
    if not card:
        await callback.answer("❌ شماره کارت تنظیم نشده. با ادمین تماس بگیرید.", show_alert=True)
        return

    payment_id = await _send_card_payment_instructions(
        callback.message.answer, db, db_user["id"], deficit, product_id=product_id,
    )
    if coupon_code and discount_amount:
        await db._execute(
            "UPDATE payments SET coupon_code = ?, discount_amount = ? WHERE id = ?",
            (coupon_code, discount_amount, payment_id),
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
            sub_id,
            renewable=not sub.get("is_trial") and bool(sub.get("product_id")),
            auto_renew=bool(sub.get("auto_renew")),
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("svc_autorenew:"))
async def toggle_auto_renew(callback: CallbackQuery, db_user: dict):
    sub_id = int(callback.data.split(":")[1])
    db = get_db()
    sub = await db.get_subscription(sub_id)
    if not sub or sub["user_id"] != db_user["id"]:
        await callback.answer("سرویس پیدا نشد", show_alert=True)
        return
    if sub.get("is_trial") or not sub.get("product_id"):
        await callback.answer("❌ تمدید خودکار برای این سرویس در دسترس نیست.", show_alert=True)
        return

    new_state = not bool(sub.get("auto_renew"))
    await db.set_subscription_auto_renew(sub_id, new_state)
    sub = await db.get_subscription(sub_id)

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
            sub_id,
            renewable=not sub.get("is_trial") and bool(sub.get("product_id")),
            auto_renew=new_state,
        ),
    )
    if new_state:
        await callback.answer(
            "🟢 تمدید خودکار روشن شد. اگر موجودی کیف پولتان کافی باشد، سرویس در زمان انقضا خودکار تمدید می‌شود.",
            show_alert=True,
        )
    else:
        await callback.answer("⚪️ تمدید خودکار خاموش شد.")


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
        order_id, _order_code = await db.create_order(
            db_user["id"],
            product["id"],
            product["price"],
            "balance",
            f"تمدید {product['name']} (سرویس #{sub_id})",
        )
        await _reward_referral_and_notify(
            callback.bot, db, db_user["id"], product["price"], order_id, f"تمدید {product['name']}"
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
    if not card:
        await callback.answer("❌ شماره کارت تنظیم نشده. با ادمین تماس بگیرید.", show_alert=True)
        return

    await _send_card_payment_instructions(
        callback.message.answer, db, db_user["id"], deficit, renew_sub_id=sub_id,
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
    if not card:
        await message.answer("❌ شماره کارت تنظیم نشده. با ادمین تماس بگیرید.")
        await state.clear()
        return

    await state.clear()
    await _send_card_payment_instructions(message.answer, db, db_user["id"], amount)


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
    elif payment.get("reseller_plan_id"):
        plan = await db.get_reseller_plan(payment["reseller_plan_id"])
        if plan:
            caption += f"\n🤝 برای تکمیل خرید/تمدید نمایندگی: {plan['name']}"
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


def _format_reseller_expiry(ts: int) -> str:
    if not ts:
        return "نامحدود"
    if ts < int(time.time()):
        return "منقضی شده"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _reseller_panel_url() -> str:
    panel_url = (get_settings().panel_url or "").strip()
    if not panel_url.startswith("https://"):
        return ""
    return panel_url.rstrip("/") + "/reseller/"


async def _send_reseller_plans(answer):
    db = get_db()
    plans = await db.get_reseller_plans(active_only=True)
    if not plans:
        await answer("❌ در حال حاضر پلن نمایندگی‌ای تعریف نشده است.")
        return
    await answer(
        "🤝 پلن‌های نمایندگی موجود:\nیک پلن را انتخاب کنید:",
        reply_markup=reseller_plans_inline(plans),
    )


@router.message(F.text == t("reseller_panel"))
async def reseller_panel_entry(message: Message, db_user: dict):
    db = get_db()
    reseller = await db.get_reseller_by_user(db_user["id"])
    if not reseller:
        await message.answer(
            "🤝 پنل نمایندگی\n\n"
            "با خرید یکی از پلن‌های نمایندگی، حجم و زمان مشخصی در اختیار شما قرار می‌گیرد. "
            "می‌توانید از طریق پنل تحت وب (Mini App) در همان سقف حجم/زمان، به دلخواه خودتان "
            "کانفیگ بسازید، آن‌ها را مدیریت (تمدید، تغییر حجم، غیرفعال‌سازی موقت یا حذف) کنید."
        )
        await _send_reseller_plans(message.answer)
        return

    now = int(time.time())
    expired = bool(reseller["expires_at"]) and reseller["expires_at"] < now
    disabled = reseller["status"] != "active"
    used = await db.get_reseller_used_gb(reseller["id"])
    remaining = max(0.0, reseller["quota_gb"] - used)

    status_text = (
        f"🤝 پنل نمایندگی شما\n\n"
        f"📦 پلن: {reseller.get('plan_name') or '—'}\n"
        f"📊 حجم کل: {reseller['quota_gb']} GB\n"
        f"📈 حجم تخصیص‌یافته به کانفیگ‌ها: {used:.2f} GB\n"
        f"📉 حجم باقیمانده: {remaining:.2f} GB\n"
        f"⏱ انقضا: {_format_reseller_expiry(reseller['expires_at'])}\n"
        f"وضعیت: "
    )
    if disabled:
        status_text += "🚫 غیرفعال‌شده توسط ادمین\n\n⚠️ برای اطلاعات بیشتر با پشتیبانی تماس بگیرید."
    elif expired:
        status_text += "⛔️ منقضی شده\n\n⚠️ مهلت پلن نمایندگی شما تمام شده و پنل تحت وب قفل شده. برای ادامه، پلن را تمدید کنید."
    else:
        status_text += "✅ فعال"

    await message.answer(
        status_text,
        reply_markup=reseller_status_inline(_reseller_panel_url(), expired or disabled),
    )


@router.callback_query(F.data == "res_renew_start")
async def reseller_renew_start(callback: CallbackQuery):
    await _send_reseller_plans(callback.message.answer)
    await callback.answer()


@router.callback_query(F.data == "res_back_plans")
async def reseller_back_to_plans(callback: CallbackQuery):
    db = get_db()
    plans = await db.get_reseller_plans(active_only=True)
    if not plans:
        await callback.answer("❌ پلنی وجود ندارد", show_alert=True)
        return
    await callback.message.edit_text(
        "🤝 پلن‌های نمایندگی موجود:\nیک پلن را انتخاب کنید:",
        reply_markup=reseller_plans_inline(plans),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("res_plan:"))
async def reseller_plan_preview(callback: CallbackQuery, db_user: dict):
    plan_id = int(callback.data.split(":")[1])
    db = get_db()
    plan = await db.get_reseller_plan(plan_id)
    if not plan:
        await callback.answer("پلن پیدا نشد", show_alert=True)
        return

    reseller = await db.get_reseller_by_user(db_user["id"])
    renew = bool(reseller)

    text = (
        f"🤝 {plan['name']}\n"
        f"📊 حجم: {plan['volume_gb']} GB\n"
        f"⏱ مدت: {plan['duration_days']} روز\n"
        f"💰 قیمت: {plan['price']:,} تومان\n"
        f"📡 پنل: {plan['panel_name']}\n"
    )
    if plan.get("description"):
        text += f"\n📝 {plan['description']}"
    if renew:
        text += (
            "\n\n⚠️ توجه: با تأیید این پلن، حجم و زمان پنل نمایندگی فعلی شما با این پلن "
            "جایگزین می‌شود (جمع نمی‌شود)."
        )
    await callback.message.edit_text(text, reply_markup=reseller_confirm_inline(plan_id, renew=renew))
    await callback.answer()


@router.callback_query(F.data.startswith("res_confirm:"))
async def reseller_confirm(callback: CallbackQuery, db_user: dict):
    plan_id = int(callback.data.split(":")[1])
    db = get_db()
    plan = await db.get_reseller_plan(plan_id)
    if not plan:
        await callback.answer("پلن پیدا نشد", show_alert=True)
        return

    fresh_user = await db._fetchone("SELECT * FROM users WHERE id = ?", (db_user["id"],))
    balance = fresh_user["balance"] if fresh_user else db_user["balance"]

    existing_reseller = await db.get_reseller_by_user(db_user["id"])
    if existing_reseller and existing_reseller["panel_id"] != plan["panel_id"]:
        configs_count = await db.get_reseller_configs_count(existing_reseller["id"])
        if configs_count > 0:
            await callback.answer(
                "❌ این پلن روی پنل دیگری است. ابتدا کانفیگ‌های فعلی خود را حذف کنید یا "
                "پلنی از همان پنل قبلی انتخاب کنید.",
                show_alert=True,
            )
            return

    if balance < plan["price"]:
        deficit = plan["price"] - balance
        await callback.message.edit_text(
            f"❌ موجودی کیف پول کافی نیست.\nموجودی شما: {balance:,} تومان\n"
            f"مبلغ مورد نیاز: {plan['price']:,} تومان\nمبلغ کسری: {deficit:,} تومان",
            reply_markup=reseller_insufficient_balance_inline(plan_id),
        )
        await callback.answer()
        return

    now = int(time.time())
    expires_at = now + plan["duration_days"] * 86400
    await db.update_user_balance(db_user["id"], -plan["price"])
    await db.create_or_renew_reseller(
        db_user["id"], plan_id, plan["panel_id"], plan["volume_gb"], expires_at,
    )
    order_id, _order_code = await db.create_order(
        db_user["id"], None, plan["price"], "balance",
        f"خرید/تمدید نمایندگی: {plan['name']}",
    )
    await _reward_referral_and_notify(
        callback.bot, db, db_user["id"], plan["price"], order_id, f"نمایندگی: {plan['name']}"
    )

    text = (
        f"✅ پلن نمایندگی «{plan['name']}» با موفقیت فعال شد!\n\n"
        f"📊 حجم: {plan['volume_gb']} GB\n"
        f"⏱ مدت: {plan['duration_days']} روز\n"
        f"⏰ انقضا: {_format_reseller_expiry(expires_at)}\n\n"
        f"از دکمه زیر برای باز کردن پنل نمایندگی خود استفاده کنید 👇"
    )
    await callback.message.edit_text(text, reply_markup=reseller_status_inline(_reseller_panel_url(), False))
    await callback.answer("✅ فعال شد.")


@router.callback_query(F.data.startswith("res_topup:"))
async def reseller_card_topup_start(callback: CallbackQuery, db_user: dict):
    plan_id = int(callback.data.split(":")[1])
    db = get_db()
    plan = await db.get_reseller_plan(plan_id)
    if not plan:
        await callback.answer("پلن پیدا نشد", show_alert=True)
        return

    fresh_user = await db._fetchone("SELECT * FROM users WHERE id = ?", (db_user["id"],))
    balance = fresh_user["balance"] if fresh_user else db_user["balance"]
    deficit = plan["price"] - balance
    if deficit <= 0:
        await callback.answer("موجودی شما کافی است، دوباره روی تأیید بزنید.", show_alert=True)
        return

    settings = get_settings()
    card = settings.card_number or await db.get_setting("card_number", "")
    if not card:
        await callback.answer("❌ شماره کارت تنظیم نشده. با ادمین تماس بگیرید.", show_alert=True)
        return

    await _send_card_payment_instructions(
        callback.message.answer, db, db_user["id"], deficit, reseller_plan_id=plan_id,
    )
    await callback.answer()


@router.message(F.text == t("support"))
async def support(message: Message):
    db = get_db()
    contact_enabled = await db.get_setting("support_contact_enabled", "1") == "1"
    text = ""
    if contact_enabled:
        text = await db.get_setting("support_text", t("support"))
        username = await db.get_setting("support_username", "")
        if username:
            text += f"\n\n@{username}"
        text += "\n\n"
    text += "برای پیگیری اختصاصی می‌توانید یک تیکت پشتیبانی ثبت کنید 👇"
    await message.answer(text, reply_markup=support_menu_inline(contact_enabled))


class TicketForm(StatesGroup):
    subject = State()
    message = State()
    reply = State()


@router.callback_query(F.data == "ticket_new")
async def ticket_new_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TicketForm.subject)
    await callback.message.answer(
        "🎫 موضوع تیکت را در یک خط کوتاه بنویسید (مثلاً «مشکل اتصال به سرویس»):",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(TicketForm.subject)
async def ticket_new_subject(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=main_menu())
        return
    await state.update_data(subject=(message.text or "").strip()[:100])
    await state.set_state(TicketForm.message)
    await message.answer("✍️ حالا توضیح کامل مشکل یا درخواستتان را بنویسید:", reply_markup=cancel_kb())


@router.message(TicketForm.message)
async def ticket_new_message(message: Message, state: FSMContext, db_user: dict, is_admin: bool):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=main_menu(is_admin))
        return
    data = await state.get_data()
    db = get_db()
    ticket_id = await db.create_ticket(db_user["id"], data.get("subject", ""), (message.text or "").strip())
    await state.clear()
    await message.answer(
        f"✅ تیکت شما با شماره #{ticket_id} ثبت شد. به‌محض پاسخ پشتیبانی، پیام دریافت خواهید کرد.",
        reply_markup=main_menu(is_admin),
    )
    for admin_id in get_settings().admin_ids:
        try:
            await message.bot.send_message(
                admin_id,
                f"🎫 تیکت جدید #{ticket_id}\n"
                f"👤 {db_user.get('full_name') or ''} (@{db_user.get('username') or '-'}) — {db_user['telegram_id']}\n"
                f"📝 موضوع: {data.get('subject', '')}\n\n{message.text}",
                reply_markup=admin_ticket_notify_inline(ticket_id),
            )
        except Exception:
            pass


async def _ticket_detail_text(db, ticket: dict) -> str:
    msgs = await db.get_ticket_messages(ticket["id"])
    status_fa = {"open": "🟢 باز", "answered": "🔵 پاسخ داده‌شده", "closed": "⚪️ بسته‌شده"}
    lines = [
        f"🎫 تیکت #{ticket['id']} — {status_fa.get(ticket['status'], ticket['status'])}",
        f"📝 موضوع: {ticket.get('subject') or '—'}\n",
    ]
    for m in msgs:
        who = "👤 شما" if m["sender"] == "user" else "🛠 پشتیبانی"
        lines.append(f"{who}:\n{m['text']}\n")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("ticket_list:"))
async def ticket_list(callback: CallbackQuery, db_user: dict):
    db = get_db()
    tickets = await db.get_user_tickets(db_user["id"])
    if not tickets:
        await callback.message.edit_text(
            "📭 هنوز تیکتی ثبت نکرده‌اید.\n\nبرای ثبت تیکت جدید:",
            reply_markup=support_menu_inline(True),
        )
        await callback.answer()
        return
    await callback.message.edit_text("📋 تیکت‌های شما:", reply_markup=ticket_list_inline(tickets))
    await callback.answer()


@router.callback_query(F.data.startswith("ticket_view:"))
async def ticket_view(callback: CallbackQuery, db_user: dict):
    ticket_id = int(callback.data.split(":")[1])
    db = get_db()
    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket["user_id"] != db_user["id"]:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    text = await _ticket_detail_text(db, ticket)
    await callback.message.edit_text(text, reply_markup=ticket_detail_inline(ticket_id, ticket["status"]))
    await callback.answer()


@router.callback_query(F.data.startswith("ticket_reply:"))
async def ticket_reply_start(callback: CallbackQuery, state: FSMContext, db_user: dict):
    ticket_id = int(callback.data.split(":")[1])
    db = get_db()
    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket["user_id"] != db_user["id"]:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    if ticket["status"] == "closed":
        await callback.answer("این تیکت بسته شده است. لطفاً تیکت جدید ثبت کنید.", show_alert=True)
        return
    await state.update_data(ticket_id=ticket_id)
    await state.set_state(TicketForm.reply)
    await callback.message.answer("✍️ پاسخ خود را بنویسید:", reply_markup=cancel_kb())
    await callback.answer()


@router.message(TicketForm.reply)
async def ticket_reply_save(message: Message, state: FSMContext, db_user: dict, is_admin: bool):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=main_menu(is_admin))
        return
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    db = get_db()
    ticket = await db.get_ticket(ticket_id) if ticket_id else None
    if not ticket or ticket["user_id"] != db_user["id"]:
        await state.clear()
        await message.answer("این تیکت دیگر در دسترس نیست.", reply_markup=main_menu(is_admin))
        return
    await db.add_ticket_message(ticket_id, "user", (message.text or "").strip())
    if ticket["status"] == "closed":
        await db.set_ticket_status(ticket_id, "open")
    await state.clear()
    await message.answer(f"✅ پاسخ شما به تیکت #{ticket_id} ارسال شد.", reply_markup=main_menu(is_admin))
    for admin_id in get_settings().admin_ids:
        try:
            await message.bot.send_message(
                admin_id,
                f"🎫 پاسخ جدید روی تیکت #{ticket_id} از طرف کاربر:\n\n{message.text}",
                reply_markup=admin_ticket_notify_inline(ticket_id),
            )
        except Exception:
            pass


# --- Referral ---

@router.message(F.text == t("referral"))
async def referral_menu(message: Message, db_user: dict):
    db = get_db()
    if await db.get_setting("referral_enabled", "0") != "1":
        await message.answer("سیستم معرفی در حال حاضر غیرفعال است.")
        return
    me = await message.bot.get_me()
    ref_code = await db.get_or_create_referral_code(db_user["id"])
    link = f"https://t.me/{me.username}?start=ref_{ref_code}"
    stats = await db.get_referral_stats(db_user["id"])
    reward_type = await db.get_setting("referral_reward_type", "percent")
    reward_value_raw = await db.get_setting("referral_reward_value", "0")
    try:
        reward_value_num = float(reward_value_raw or "0")
    except ValueError:
        reward_value_num = 0
    if reward_type == "fixed":
        reward_desc = f"{int(reward_value_num):,} تومان به ازای هر خرید موفق"
    else:
        reward_desc = f"{reward_value_num:g}٪ از مبلغ هر خرید موفق"
    text = (
        "🤝 دعوت از دوستان\n\n"
        f"با اشتراک‌گذاری لینک زیر، به ازای هر خریدی که هرکسی با این لینک وارد ربات شود انجام می‌دهد، "
        f"{reward_desc} به کیف پول شما اضافه می‌شود:\n\n"
        f"`{link}`\n\n"
        f"👥 تعداد افراد معرفی‌شده: {stats['referred_count']}\n"
        f"💰 مجموع پاداش دریافتی: {stats['total_earned']:,} تومان"
    )
    await message.answer(text, parse_mode="Markdown")


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
