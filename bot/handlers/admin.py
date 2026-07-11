"""Admin panel handlers."""

import html
import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards import (
    admin_coupon_detail_inline,
    admin_coupons_inline,
    admin_menu,
    admin_sub_actions_inline,
    admin_tutorial_detail_inline,
    admin_tutorials_inline,
    admin_user_services_inline,
    back_kb,
    cancel_kb,
    complete_purchase_inline,
    main_menu,
    panel_actions_inline,
    panels_inline,
    payment_actions_inline,
    product_actions_inline,
    product_delete_confirm_inline,
    product_edit_menu_inline,
    products_admin_inline,
    renew_complete_inline,
    user_admin_card_inline,
    user_admin_card_inline_with_back,
    users_list_inline,
)
from bot.messages import t
from config import get_settings
from database import get_db
from services.xui_client import XUIClient
from utils.helpers import (
    build_sub_link_template,
    load_config_links,
    parse_positive_float,
    parse_positive_int,
)

logger = logging.getLogger(__name__)
router = Router()


class AdminPanelForm(StatesGroup):
    name = State()
    url = State()
    api_token = State()
    inbound_ids = State()
    sub_link_sample = State()


class AdminPanelEditInboundsForm(StatesGroup):
    panel_id = State()
    inbound_ids = State()


class AdminPanelSubLinkForm(StatesGroup):
    value = State()


class AdminProductForm(StatesGroup):
    name = State()
    panel_id = State()
    volume_gb = State()
    duration_days = State()
    price = State()


class AdminProductEditForm(StatesGroup):
    value = State()


class AdminChannelForm(StatesGroup):
    channel_id = State()
    invite_link = State()


class AdminMsgToUserForm(StatesGroup):
    text = State()


class AdminBalanceAdjustForm(StatesGroup):
    amount = State()


class AdminFAQForm(StatesGroup):
    question = State()
    answer = State()


class AdminTutorialForm(StatesGroup):
    title = State()
    content = State()


class AdminCouponForm(StatesGroup):
    code_mode = State()       # 'manual' | 'random'
    code = State()
    discount_type = State()
    discount_value = State()
    usage_type = State()
    max_uses = State()


class AdminBroadcastForm(StatesGroup):
    text = State()


class AdminUserSearchForm(StatesGroup):
    query = State()


class AdminSettingsForm(StatesGroup):
    key = State()
    value = State()


def admin_only(handler):
    async def wrapper(event, *args, **kwargs):
        user_id = event.from_user.id
        if user_id not in get_settings().admin_ids:
            if isinstance(event, Message):
                await event.answer(t("not_admin"))
            elif isinstance(event, CallbackQuery):
                await event.answer(t("not_admin"), show_alert=True)
            return
        return await handler(event, *args, **kwargs)
    return wrapper


@router.message(F.text == t("admin_menu"))
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id not in get_settings().admin_ids:
        await message.answer(t("not_admin"))
        return
    await state.clear()
    await message.answer(t("admin_menu"), reply_markup=admin_menu())


@router.message(F.text == t("admin_stats"))
async def admin_stats(message: Message):
    if message.from_user.id not in get_settings().admin_ids:
        return
    db = get_db()
    users = await db.get_all_users_count()
    subs = await db.get_active_subscriptions_count()
    panels = len(await db.get_panels(active_only=False))
    products = len(await db.get_products(active_only=False))
    pending = len(await db.get_pending_payments())
    await message.answer(
        f"📊 آمار ربات\n\n"
        f"👥 کاربران: {users}\n"
        f"📦 سرویس‌های فعال: {subs}\n"
        f"🖥 پنل‌ها: {panels}\n"
        f"🏷 محصولات: {products}\n"
        f"💳 پرداخت در انتظار: {pending}"
    )


# --- Panels ---
@router.message(F.text == t("admin_panels"))
async def admin_panels(message: Message):
    if message.from_user.id not in get_settings().admin_ids:
        return
    db = get_db()
    panels = await db.get_panels(active_only=False)
    if not panels:
        await message.answer(
            "🖥 هیچ پنلی ثبت نشده.\nبرای افزودن: /add_panel",
            reply_markup=admin_menu(),
        )
        return
    await message.answer("🖥 پنل‌ها:", reply_markup=panels_inline(panels))


@router.message(Command("add_panel"))
async def add_panel_start(message: Message, state: FSMContext):
    if message.from_user.id not in get_settings().admin_ids:
        return
    await state.set_state(AdminPanelForm.name)
    await message.answer("📝 نام پنل را وارد کنید:", reply_markup=cancel_kb())


@router.message(AdminPanelForm.name)
async def add_panel_name(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(AdminPanelForm.url)
    await message.answer("🌐 آدرس پنل (مثال: https://panel.example.com):")


@router.message(AdminPanelForm.url)
async def add_panel_url(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    await state.update_data(url=message.text.strip().rstrip("/"))
    await state.set_state(AdminPanelForm.api_token)
    await message.answer("🔑 API Token (از Settings → Security → API Token):")


@router.message(AdminPanelForm.api_token)
async def add_panel_token(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    await state.update_data(api_token=message.text.strip())
    await state.set_state(AdminPanelForm.inbound_ids)
    await message.answer(
        "📋 IDهای Inbound را وارد کنید (با کاما جدا — مثال: 1,2,3):\n"
        "می‌توانید از دکمه Inbounds در لیست پنل‌ها IDها را ببینید."
    )


@router.message(AdminPanelForm.inbound_ids)
async def add_panel_inbounds(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return

    try:
        ids = [int(x.strip()) for x in message.text.split(",") if x.strip()]
    except ValueError:
        await message.answer("❌ فرمت نامعتبر. مثال: 1,2")
        return

    await state.update_data(inbound_ids=json.dumps(ids))
    await state.set_state(AdminPanelForm.sub_link_sample)
    await message.answer(
        "🔗 یک نمونه لینک سابسکریپشن از پنل خودتان (برای هر کلاینتی) کپی و اینجا ارسال کنید "
        "تا ربات بتواند لینک ساب صحیح برای کاربران بسازد.\n"
        "مثال: https://domain.com:2090/sub/abcdefgh12345678\n\n"
        "اگر لینک ساب ندارید یا نمی‌خواهید این قابلیت فعال باشد، علامت - را ارسال کنید."
    )


@router.message(AdminPanelForm.sub_link_sample)
async def add_panel_sub_link(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return

    text = (message.text or "").strip()
    sub_link_template = ""
    if text != "-":
        try:
            sub_link_template = build_sub_link_template(text)
        except ValueError as e:
            await message.answer(f"❌ {e}\nدوباره ارسال کنید یا - را بفرستید تا رد شود.")
            return

    data = await state.get_data()
    db = get_db()
    panel_id = await db.add_panel(
        data["name"],
        data["url"],
        data["api_token"],
        data["inbound_ids"],
    )
    if sub_link_template:
        await db.update_panel(panel_id, sub_link_template=sub_link_template)
    await state.clear()

    client = XUIClient(data["url"], data["api_token"])
    ok = await client.test_connection()
    status = "✅ اتصال موفق" if ok else "⚠️ اتصال ناموفق — تنظیمات را بررسی کنید"
    sub_status = "✅ لینک ساب تنظیم شد" if sub_link_template else "⚠️ لینک ساب تنظیم نشد"

    await message.answer(
        f"{t('panel_added')}\nID: {panel_id}\n{status}\n{sub_status}",
        reply_markup=admin_menu(),
    )


@router.callback_query(F.data.startswith("set_sublink:"))
async def set_sublink_start(callback: CallbackQuery, state: FSMContext):
    panel_id = int(callback.data.split(":")[1])
    db = get_db()
    panel = await db.get_panel(panel_id)
    if not panel:
        await callback.answer("پیدا نشد", show_alert=True)
        return

    await state.update_data(panel_id=panel_id)
    await state.set_state(AdminPanelSubLinkForm.value)
    await callback.message.answer(
        "🔗 یک نمونه لینک سابسکریپشن از پنل کپی و ارسال کنید.\n"
        "مثال: https://domain.com:2090/sub/abcdefgh12345678",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminPanelSubLinkForm.value)
async def set_sublink_save(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return

    try:
        template = build_sub_link_template((message.text or "").strip())
    except ValueError as e:
        await message.answer(f"❌ {e}\nدوباره ارسال کنید یا لغو کنید.")
        return

    data = await state.get_data()
    db = get_db()
    await db.update_panel(data["panel_id"], sub_link_template=template)
    await state.clear()
    await message.answer("✅ لینک ساب پنل بروزرسانی شد.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("panel:"))
async def panel_detail(callback: CallbackQuery):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    panel_id = int(callback.data.split(":")[1])
    db = get_db()
    panel = await db.get_panel(panel_id)
    if not panel:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    text = (
        f"🖥 {panel['name']}\n"
        f"🌐 {panel['url']}\n"
        f"📋 Inbounds: {panel['inbound_ids']}\n"
        f"🔗 لینک ساب: {'✅ تنظیم شده' if panel.get('sub_link_template') else '❌ تنظیم نشده'}\n"
        f"On-Hold: {'بله' if panel.get('on_hold') else 'خیر'}\n"
        f"وضعیت: {'فعال' if panel.get('is_active') else 'غیرفعال'}"
    )
    await callback.message.edit_text(text, reply_markup=panel_actions_inline(panel_id, bool(panel.get("is_active", 1))))
    await callback.answer()


@router.callback_query(F.data == "admin_panels_back")
async def admin_panels_back(callback: CallbackQuery):
    db = get_db()
    panels = await db.get_panels(active_only=False)
    await callback.message.edit_text("🖥 پنل‌ها:", reply_markup=panels_inline(panels))
    await callback.answer()


@router.callback_query(F.data.startswith("test_panel:"))
async def test_panel(callback: CallbackQuery):
    panel_id = int(callback.data.split(":")[1])
    db = get_db()
    panel = await db.get_panel(panel_id)
    if not panel:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    client = XUIClient(panel["url"], panel["api_token"])
    try:
        status = await client.get_server_status()
        xray = status.get("xray", {}).get("state", "—")
        await callback.answer(f"✅ Xray: {xray}", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ {e}", show_alert=True)


@router.callback_query(F.data.startswith("inbounds:"))
async def list_inbounds(callback: CallbackQuery):
    panel_id = int(callback.data.split(":")[1])
    db = get_db()
    panel = await db.get_panel(panel_id)
    if not panel:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    client = XUIClient(panel["url"], panel["api_token"])
    try:
        options = await client.list_inbound_options()
        lines = [f"ID {o['id']}: {o.get('remark', '')} ({o.get('protocol', '')})" for o in options]
        text = "📋 Inbounds:\n" + "\n".join(lines) if lines else "خالی"
        await callback.message.answer(text)
    except Exception as e:
        await callback.message.answer(f"❌ {e}")
    await callback.answer()


@router.callback_query(F.data.startswith("edit_inbounds:"))
async def edit_inbounds_start(callback: CallbackQuery, state: FSMContext):
    """شروع فلوی ویرایش Inbounds — نمایش لیست فعلی + درخواست ورودی جدید."""
    if callback.from_user.id not in get_settings().admin_ids:
        return
    panel_id = int(callback.data.split(":")[1])
    db = get_db()
    panel = await db.get_panel(panel_id)
    if not panel:
        await callback.answer("پنل پیدا نشد", show_alert=True)
        return

    # پارس Inbounds فعلی برای نمایش
    try:
        current_ids = json.loads(panel["inbound_ids"]) if panel["inbound_ids"] else []
    except (json.JSONDecodeError, TypeError):
        current_ids = []

    # تلاش برای گرفتن لیست Inbounds از پنل (اگر اتصال برقرار باشد)
    live_list = ""
    try:
        client = XUIClient(panel["url"], panel["api_token"])
        options = await client.list_inbound_options()
        if options:
            lines = [f"  ID {o['id']}: {o.get('remark', '---')} ({o.get('protocol', '---')})" for o in options]
            live_list = "\n\n📡 Inbounds موجود در پنل:\n" + "\n".join(lines)
    except Exception:
        live_list = "\n\n⚠️ اتصال به پنل برقرار نشد — IDها را دستی وارد کنید."

    await state.update_data(panel_id=panel_id)
    await state.set_state(AdminPanelEditInboundsForm.inbound_ids)

    msg_text = (
        f"✏️ ویرایش Inbounds — پنل: {panel['name']}\n"
        f"📋 مقدار فعلی: {current_ids}"
        f"{live_list}\n\n"
        "IDهای جدید را با کاما وارد کنید:\n"
        "مثال: 54,81,83"
    )
    await callback.message.answer(msg_text, reply_markup=cancel_kb())
    await callback.answer()


@router.message(AdminPanelEditInboundsForm.inbound_ids)
async def edit_inbounds_save(message: Message, state: FSMContext):
    """ذخیره Inbounds جدید در دیتابیس."""
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return

    raw = (message.text or "").strip()
    # حذف bracket اگر کاربر به فرمت [54,81,83] وارد کرد
    raw = raw.strip("[]")

    try:
        ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
        if not ids:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ فرمت نامعتبر. باید IDهای عددی با کاما باشد.\n"
            "مثال: 54,81,83"
        )
        return

    data = await state.get_data()
    panel_id = data["panel_id"]
    db = get_db()
    await db.update_panel(panel_id, inbound_ids=json.dumps(ids))
    await state.clear()

    panel = await db.get_panel(panel_id)
    success_text = (
        f"✅ Inbounds پنل «{panel['name']}» بروز شد.\n"
        f"📋 مقدار جدید: {ids}"
    )
    await message.answer(success_text, reply_markup=admin_menu())


@router.callback_query(F.data.startswith("del_panel:"))
async def del_panel(callback: CallbackQuery):
    panel_id = int(callback.data.split(":")[1])
    db = get_db()
    await db.delete_panel(panel_id)
    await callback.message.edit_text("✅ پنل حذف شد.")
    await callback.answer()


@router.callback_query(F.data.startswith("panel_en:"))
async def enable_panel(callback: CallbackQuery):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    panel_id = int(callback.data.split(":")[1])
    db = get_db()
    await db.update_panel(panel_id, is_active=1)
    panel = await db.get_panel(panel_id)
    if not panel:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    text = (
        f"🖥 {panel['name']}\n"
        f"🌐 {panel['url']}\n"
        f"📋 Inbounds: {panel['inbound_ids']}\n"
        f"🔗 لینک ساب: {'✅ تنظیم شده' if panel.get('sub_link_template') else '❌ تنظیم نشده'}\n"
        f"On-Hold: {'بله' if panel.get('on_hold') else 'خیر'}\n"
        f"وضعیت: فعال"
    )
    await callback.message.edit_text(text, reply_markup=panel_actions_inline(panel_id, True))
    await callback.answer("✅ پنل فعال شد.")


@router.callback_query(F.data.startswith("panel_dis:"))
async def disable_panel(callback: CallbackQuery):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    panel_id = int(callback.data.split(":")[1])
    db = get_db()
    await db.update_panel(panel_id, is_active=0)
    panel = await db.get_panel(panel_id)
    if not panel:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    text = (
        f"🖥 {panel['name']}\n"
        f"🌐 {panel['url']}\n"
        f"📋 Inbounds: {panel['inbound_ids']}\n"
        f"🔗 لینک ساب: {'✅ تنظیم شده' if panel.get('sub_link_template') else '❌ تنظیم نشده'}\n"
        f"On-Hold: {'بله' if panel.get('on_hold') else 'خیر'}\n"
        f"وضعیت: 🚫 غیرفعال"
    )
    await callback.message.edit_text(text, reply_markup=panel_actions_inline(panel_id, False))
    await callback.answer("🚫 پنل غیرفعال شد.")


# --- Products ---
@router.message(F.text == t("admin_products"))
async def admin_products(message: Message):
    if message.from_user.id not in get_settings().admin_ids:
        return
    db = get_db()
    products = await db.get_products(active_only=False)
    await message.answer("📦 محصولات:", reply_markup=products_admin_inline(products))


@router.callback_query(F.data == "admin_products_back")
async def admin_products_back(callback: CallbackQuery):
    db = get_db()
    products = await db.get_products(active_only=False)
    await callback.message.edit_text("📦 محصولات:", reply_markup=products_admin_inline(products))
    await callback.answer()


@router.callback_query(F.data == "add_product")
async def add_product_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminProductForm.name)
    await callback.message.answer("📝 نام محصول:", reply_markup=cancel_kb())
    await callback.answer()


@router.message(AdminProductForm.name)
async def add_product_name(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    await state.update_data(name=message.text.strip())
    db = get_db()
    panels = await db.get_panels()
    if not panels:
        await state.clear()
        await message.answer("❌ ابتدا یک پنل اضافه کنید.", reply_markup=admin_menu())
        return
    lines = "\n".join(f"{p['id']}: {p['name']}" for p in panels)
    await state.set_state(AdminProductForm.panel_id)
    await message.answer(f"🖥 ID پنل را انتخاب کنید:\n{lines}")


@router.message(AdminProductForm.panel_id)
async def add_product_panel(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    pid = parse_positive_int(message.text)
    if not pid:
        await message.answer("❌ ID نامعتبر")
        return
    await state.update_data(panel_id=pid)
    await state.set_state(AdminProductForm.volume_gb)
    await message.answer("📊 حجم (GB):")


@router.message(AdminProductForm.volume_gb)
async def add_product_volume(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    vol = parse_positive_float(message.text)
    if not vol:
        await message.answer("❌ مقدار نامعتبر")
        return
    await state.update_data(volume_gb=vol)
    await state.set_state(AdminProductForm.duration_days)
    await message.answer("⏱ مدت (روز):")


@router.message(AdminProductForm.duration_days)
async def add_product_days(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    days = parse_positive_int(message.text)
    if not days:
        await message.answer("❌ مقدار نامعتبر")
        return
    await state.update_data(duration_days=days)
    await state.set_state(AdminProductForm.price)
    await message.answer("💰 قیمت (تومان):")


@router.message(AdminProductForm.price)
async def add_product_price(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    price = parse_positive_int(message.text)
    if not price:
        await message.answer("❌ مقدار نامعتبر")
        return
    data = await state.get_data()
    db = get_db()
    pid = await db.add_product(
        data["name"],
        data["panel_id"],
        data["volume_gb"],
        data["duration_days"],
        price,
    )
    await state.clear()
    await message.answer(f"{t('product_added')}\nID: {pid}", reply_markup=admin_menu())


def _product_detail_text(product: dict) -> str:
    return (
        f"📦 {product['name']}\n"
        f"📊 {product['volume_gb']} GB / {product['duration_days']} روز\n"
        f"💰 {product['price']:,} تومان\n"
        f"📡 {product.get('panel_name', '')}\n"
        f"تست: {'بله' if product.get('is_trial') else 'خیر'}\n"
        f"وضعیت: {'✅ فعال' if product.get('is_active') else '🚫 غیرفعال'}"
    )


@router.callback_query(F.data.startswith("prod:"))
async def product_detail(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    db = get_db()
    product = await db.get_product(product_id)
    if not product:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    await callback.message.edit_text(
        _product_detail_text(product),
        reply_markup=product_actions_inline(product),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prod_en:"))
async def enable_product(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    db = get_db()
    await db.update_product(product_id, is_active=1)
    product = await db.get_product(product_id)
    await callback.message.edit_text(
        _product_detail_text(product),
        reply_markup=product_actions_inline(product),
    )
    await callback.answer("✅ محصول فعال شد.")


@router.callback_query(F.data.startswith("prod_dis:"))
async def disable_product(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    db = get_db()
    await db.update_product(product_id, is_active=0)
    product = await db.get_product(product_id)
    await callback.message.edit_text(
        _product_detail_text(product),
        reply_markup=product_actions_inline(product),
    )
    await callback.answer("🚫 محصول غیرفعال شد.")


@router.callback_query(F.data.startswith("prod_del_yes:"))
async def delete_product_confirmed(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    db = get_db()
    try:
        await db.delete_product(product_id)
    except Exception:
        await callback.answer(
            "❌ این محصول سرویس یا سفارش فعالی دارد و قابل حذف کامل نیست. "
            "می‌توانید به جای آن آن را غیرفعال کنید.",
            show_alert=True,
        )
        return
    products = await db.get_products(active_only=False)
    await callback.message.edit_text("✅ محصول حذف شد.\n\n📦 محصولات:", reply_markup=products_admin_inline(products))
    await callback.answer()


@router.callback_query(F.data.startswith("prod_del_no:"))
async def delete_product_cancelled(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    db = get_db()
    product = await db.get_product(product_id)
    if not product:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    await callback.message.edit_text(
        _product_detail_text(product),
        reply_markup=product_actions_inline(product),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prod_del:"))
async def delete_product_ask(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    db = get_db()
    product = await db.get_product(product_id)
    if not product:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    await callback.message.edit_text(
        f"⚠️ آیا از حذف کامل محصول «{product['name']}» مطمئن هستید؟\n"
        "این عملیات قابل بازگشت نیست.",
        reply_markup=product_delete_confirm_inline(product_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prod_edit:"))
async def edit_product_menu(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    db = get_db()
    product = await db.get_product(product_id)
    if not product:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    await callback.message.edit_text(
        f"✏️ ویرایش محصول «{product['name']}»\nکدام فیلد را می‌خواهید ویرایش کنید؟",
        reply_markup=product_edit_menu_inline(product_id),
    )
    await callback.answer()


_EDIT_FIELD_PROMPTS = {
    "name": "📝 نام جدید را وارد کنید:",
    "volume_gb": "📊 حجم جدید را به GB وارد کنید:",
    "duration_days": "⏱ مدت جدید را به روز وارد کنید:",
    "price": "💰 قیمت جدید را به تومان وارد کنید:",
    "description": "📝 توضیحات جدید را وارد کنید:",
    "panel_id": "🖥 ID پنل جدید را وارد کنید (از لیست پنل‌ها):",
}


@router.callback_query(F.data.startswith("prod_editf:"))
async def edit_product_field_start(callback: CallbackQuery, state: FSMContext):
    _, product_id, field = callback.data.split(":")
    product_id = int(product_id)
    db = get_db()
    product = await db.get_product(product_id)
    if not product:
        await callback.answer("پیدا نشد", show_alert=True)
        return

    prompt = _EDIT_FIELD_PROMPTS.get(field)
    if not prompt:
        await callback.answer("نامعتبر", show_alert=True)
        return

    if field == "panel_id":
        panels = await db.get_panels()
        lines = "\n".join(f"{p['id']}: {p['name']}" for p in panels)
        prompt = f"{prompt}\n{lines}"

    await state.update_data(product_id=product_id, field=field)
    await state.set_state(AdminProductEditForm.value)
    await callback.message.answer(prompt, reply_markup=cancel_kb())
    await callback.answer()


@router.message(AdminProductEditForm.value)
async def edit_product_field_save(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return

    data = await state.get_data()
    product_id = data["product_id"]
    field = data["field"]
    raw = (message.text or "").strip()

    if field == "volume_gb":
        value = parse_positive_float(raw)
        if value is None:
            await message.answer("❌ مقدار نامعتبر. دوباره وارد کنید:")
            return
    elif field in ("duration_days", "price", "panel_id"):
        value = parse_positive_int(raw)
        if value is None:
            await message.answer("❌ مقدار نامعتبر. دوباره وارد کنید:")
            return
    else:
        if not raw:
            await message.answer("❌ مقدار نمی‌تواند خالی باشد. دوباره وارد کنید:")
            return
        value = raw

    db = get_db()
    if field == "panel_id":
        panel = await db.get_panel(value)
        if not panel:
            await message.answer("❌ پنلی با این ID پیدا نشد. دوباره وارد کنید:")
            return

    await db.update_product(product_id, **{field: value})
    await state.clear()
    product = await db.get_product(product_id)
    await message.answer("✅ محصول بروزرسانی شد.", reply_markup=admin_menu())
    await message.answer(
        _product_detail_text(product),
        reply_markup=product_actions_inline(product),
    )


# --- Payments ---
@router.message(F.text == t("admin_payments"))
async def admin_payments(message: Message):
    if message.from_user.id not in get_settings().admin_ids:
        return
    db = get_db()
    payments = await db.get_pending_payments()
    if not payments:
        await message.answer("💳 پرداخت در انتظار وجود ندارد.")
        return
    for p in payments:
        text = (
            f"💳 پرداخت #{p['id']}\n"
            f"👤 {p['telegram_id']} (@{p.get('username', '')})\n"
            f"💰 {p['amount']:,} تومان"
        )
        if p.get("receipt_file_id"):
            sent = await message.answer_photo(
                p["receipt_file_id"],
                caption=text,
                reply_markup=payment_actions_inline(p["id"]),
            )
        else:
            sent = await message.answer(text, reply_markup=payment_actions_inline(p["id"]))
        await db.append_payment_notif_chat(p["id"], sent.chat.id, sent.message_id)


def _payment_status_text(payment: dict, status: str, admin_id: int) -> str:
    if status == "approved":
        return (
            f"✅ این پرداخت تأیید شد. (ادمین {admin_id})\n"
            f"💰 مبلغ: {payment['amount']:,} تومان"
        )
    if status == "rejected":
        return f"❌ این پرداخت رد شد. (ادمین {admin_id})"
    return f"💳 وضعیت این پرداخت: {status}"


async def _finalize_payment_messages(bot, db, payment: dict, status_text: str):
    """Disable the approve/reject buttons on every admin's copy of this
    payment notification, so a second admin can no longer act on it."""
    chats = await db.get_payment_notif_chats(payment["id"])
    for item in chats:
        try:
            await bot.edit_message_caption(
                chat_id=item["chat_id"], message_id=item["message_id"], caption=status_text,
            )
        except Exception:
            try:
                await bot.edit_message_text(
                    status_text, chat_id=item["chat_id"], message_id=item["message_id"],
                )
            except Exception:
                pass


@router.callback_query(F.data.startswith("pay_ok:"))
async def pay_confirm(callback: CallbackQuery, is_admin: bool):
    if not is_admin:
        await callback.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return
    payment_id = int(callback.data.split(":")[1])
    db = get_db()
    payment = await db.get_payment(payment_id)
    if not payment:
        await callback.answer("پیدا نشد", show_alert=True)
        return

    claimed = await db.claim_payment(payment_id, "approved", callback.from_user.id)
    if not claimed:
        fresh = await db.get_payment(payment_id)
        await callback.answer("⏱ این پرداخت قبلاً توسط ادمین دیگری بررسی شده است.", show_alert=True)
        await _finalize_payment_messages(
            callback.bot, db, fresh,
            _payment_status_text(fresh, fresh["status"], fresh.get("handled_by") or 0),
        )
        return

    new_balance = await db.update_user_balance(payment["user_id"], payment["amount"])
    user = await db._fetchone("SELECT * FROM users WHERE id = ?", (payment["user_id"],))
    if user:
        text = f"✅ پرداخت تأیید شد.\n💰 موجودی: {new_balance:,} تومان"
        markup = None
        if payment.get("renew_sub_id"):
            text += f"\n\nحالا می‌توانید تمدید سرویس #{payment['renew_sub_id']} را تکمیل کنید 👇"
            markup = renew_complete_inline(payment["renew_sub_id"])
        elif payment.get("product_id"):
            product = await db.get_product(payment["product_id"])
            if product:
                text += f"\n\nحالا می‌توانید خرید «{product['name']}» را تکمیل کنید 👇"
                markup = complete_purchase_inline(payment["product_id"])
        try:
            await callback.bot.send_message(user["telegram_id"], text, reply_markup=markup)
        except Exception:
            pass

    await _finalize_payment_messages(
        callback.bot, db, payment,
        _payment_status_text(payment, "approved", callback.from_user.id),
    )
    await callback.answer("✅ تأیید شد.")


@router.callback_query(F.data.startswith("pay_no:"))
async def pay_reject(callback: CallbackQuery, is_admin: bool):
    if not is_admin:
        await callback.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return
    payment_id = int(callback.data.split(":")[1])
    db = get_db()
    payment = await db.get_payment(payment_id)
    if not payment:
        await callback.answer("پیدا نشد", show_alert=True)
        return

    claimed = await db.claim_payment(payment_id, "rejected", callback.from_user.id)
    if not claimed:
        fresh = await db.get_payment(payment_id)
        await callback.answer("⏱ این پرداخت قبلاً توسط ادمین دیگری بررسی شده است.", show_alert=True)
        await _finalize_payment_messages(
            callback.bot, db, fresh,
            _payment_status_text(fresh, fresh["status"], fresh.get("handled_by") or 0),
        )
        return

    user = await db._fetchone("SELECT * FROM users WHERE id = ?", (payment["user_id"],))
    if user:
        try:
            await callback.bot.send_message(user["telegram_id"], t("payment_rejected"))
        except Exception:
            pass

    await _finalize_payment_messages(
        callback.bot, db, payment,
        _payment_status_text(payment, "rejected", callback.from_user.id),
    )
    await callback.answer("❌ رد شد.")


# --- Users ---
async def _render_user_card(db, tid: int):
    user = await db.get_user_by_telegram_id(tid)
    if not user:
        return None, None
    subs = await db.get_user_subscriptions(user["id"])
    active = [s for s in subs if s["status"] == "active"]
    name = html.escape(user.get("full_name") or "—")
    username = f"@{html.escape(user['username'])}" if user.get("username") else "—"
    banned = bool(user.get("is_banned"))
    text = (
        f"👤 کاربر {tid}\n"
        f"نام: {name}\n"
        f"یوزرنیم: {username}\n"
        f"💰 موجودی: {user['balance']:,} تومان\n"
        f"📦 سرویس‌های فعال: {len(active)} (کل: {len(subs)})\n"
        f"وضعیت: {'🚫 بن‌شده' if banned else '✅ فعال'}"
    )
    markup = user_admin_card_inline(tid, banned)
    return text, markup


_USERS_PER_PAGE = 10


async def _send_users_page(target, page: int, search: str = "", edit: bool = False):
    """رندر یک صفحه از لیست کاربران — target می‌تواند Message یا CallbackQuery باشد."""
    db = get_db()
    total = await db.get_all_users_count(search=search)
    total_pages = max(1, -(-total // _USERS_PER_PAGE))  # ceil division
    page = max(1, min(page, total_pages))
    users = await db.get_users_page(page, _USERS_PER_PAGE, search=search)

    search_label = f" | جستجو: «{search}»" if search else ""
    text = (
        f"👥 لیست کاربران{search_label}\n"
        f"تعداد کل: {total} نفر | صفحه {page} از {total_pages}"
    )
    markup = users_list_inline(users, page, total_pages, search=search)

    if edit:
        msg = target.message if hasattr(target, "message") else target
        await msg.edit_text(text, reply_markup=markup)
    else:
        msg = target if isinstance(target, Message) else target.message
        await msg.answer(text, reply_markup=markup)


@router.message(F.text == t("admin_users"))
async def admin_users_info(message: Message):
    if message.from_user.id not in get_settings().admin_ids:
        return
    await _send_users_page(message, page=1)


@router.callback_query(F.data.startswith("ulist_page:"))
async def ulist_page(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    parts = callback.data.split(":", 2)
    page = int(parts[1])
    search = parts[2] if len(parts) > 2 else ""
    await _send_users_page(callback, page=page, search=search, edit=True)
    await callback.answer()


@router.callback_query(F.data == "ulist_noop")
async def ulist_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "ulist_search")
async def ulist_search_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    await state.set_state(AdminUserSearchForm.query)
    await callback.message.answer(
        "🔍 عبارت جستجو را وارد کنید:\n"
        "(آیدی عددی، یوزرنیم یا نام کاربر)",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminUserSearchForm.query)
async def ulist_search_do(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    query = (message.text or "").strip()
    await state.clear()
    await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
    await _send_users_page(message, page=1, search=query)


@router.callback_query(F.data.startswith("ulist_view:"))
async def ulist_view_user(callback: CallbackQuery):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    parts = callback.data.split(":")
    tid = int(parts[1])
    back_page = int(parts[2]) if len(parts) > 2 else 1
    db = get_db()
    text, _ = await _render_user_card(db, tid)
    if not text:
        await callback.answer("کاربر پیدا نشد", show_alert=True)
        return
    user = await db.get_user_by_telegram_id(tid)
    banned = bool(user.get("is_banned")) if user else False
    await callback.message.edit_text(
        text,
        reply_markup=user_admin_card_inline_with_back(tid, banned, back_page=back_page),
    )
    await callback.answer()


@router.message(Command("user"))
async def admin_user_lookup(message: Message, is_admin: bool):
    if not is_admin:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("استفاده: /user [telegram_id]")
        return
    try:
        tid = int(parts[1])
    except ValueError:
        await message.answer("ID نامعتبر")
        return
    db = get_db()
    text, markup = await _render_user_card(db, tid)
    if not text:
        await message.answer("کاربر پیدا نشد")
        return
    await message.answer(text, reply_markup=markup)


@router.message(Command("addbalance"))
async def admin_add_balance(message: Message, is_admin: bool):
    if not is_admin:
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("استفاده: /addbalance [telegram_id] [amount]")
        return
    try:
        tid = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.answer("مقادیر نامعتبر")
        return
    db = get_db()
    user = await db.get_user_by_telegram_id(tid)
    if not user:
        await message.answer("کاربر پیدا نشد")
        return
    new_bal = await db.update_user_balance(user["id"], amount)
    await message.answer(f"✅ موجودی جدید: {new_bal:,} تومان")
    try:
        await message.bot.send_message(
            tid, f"💰 موجودی شما {amount:+,} تومان تغییر کرد.\nموجودی: {new_bal:,} تومان"
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("uadm_refresh:"))
async def uadm_refresh(callback: CallbackQuery, is_admin: bool):
    if not is_admin:
        return
    tid = int(callback.data.split(":")[1])
    db = get_db()
    text, markup = await _render_user_card(db, tid)
    if not text:
        await callback.answer("کاربر پیدا نشد", show_alert=True)
        return
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("uadm_ban:"))
async def uadm_ban(callback: CallbackQuery, is_admin: bool):
    if not is_admin:
        return
    tid = int(callback.data.split(":")[1])
    db = get_db()
    user = await db.get_user_by_telegram_id(tid)
    if not user:
        await callback.answer("کاربر پیدا نشد", show_alert=True)
        return
    await db.set_user_banned(user["id"], True)
    text, markup = await _render_user_card(db, tid)
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer("🚫 کاربر بن شد.")
    try:
        await callback.bot.send_message(tid, "🚫 دسترسی شما به این ربات توسط مدیریت مسدود شد.")
    except Exception:
        pass


@router.callback_query(F.data.startswith("uadm_unban:"))
async def uadm_unban(callback: CallbackQuery, is_admin: bool):
    if not is_admin:
        return
    tid = int(callback.data.split(":")[1])
    db = get_db()
    user = await db.get_user_by_telegram_id(tid)
    if not user:
        await callback.answer("کاربر پیدا نشد", show_alert=True)
        return
    await db.set_user_banned(user["id"], False)
    text, markup = await _render_user_card(db, tid)
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer("✅ کاربر آن‌بن شد.")
    try:
        await callback.bot.send_message(tid, "✅ دسترسی شما به ربات مجدداً فعال شد.")
    except Exception:
        pass


@router.callback_query(F.data.startswith("uadm_msg:"))
async def uadm_msg_start(callback: CallbackQuery, is_admin: bool, state: FSMContext):
    if not is_admin:
        return
    tid = int(callback.data.split(":")[1])
    await state.update_data(target_tid=tid)
    await state.set_state(AdminMsgToUserForm.text)
    await callback.message.answer(
        f"✉️ متن پیام برای کاربر {tid} را ارسال کنید:", reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(AdminMsgToUserForm.text)
async def uadm_msg_send(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    data = await state.get_data()
    tid = data["target_tid"]
    try:
        await message.bot.send_message(tid, f"✉️ پیام از طرف مدیریت:\n\n{message.text}")
        await message.answer("✅ پیام ارسال شد.", reply_markup=admin_menu())
    except Exception as e:
        await message.answer(f"❌ ارسال پیام ناموفق بود: {e}", reply_markup=admin_menu())
    await state.clear()


@router.callback_query(F.data.startswith("uadm_addbal:"))
async def uadm_addbal_start(callback: CallbackQuery, is_admin: bool, state: FSMContext):
    if not is_admin:
        return
    tid = int(callback.data.split(":")[1])
    await state.update_data(target_tid=tid, mode="add")
    await state.set_state(AdminBalanceAdjustForm.amount)
    await callback.message.answer(
        f"➕ مقدار افزایش موجودی برای کاربر {tid} را به تومان وارد کنید:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uadm_subbal:"))
async def uadm_subbal_start(callback: CallbackQuery, is_admin: bool, state: FSMContext):
    if not is_admin:
        return
    tid = int(callback.data.split(":")[1])
    await state.update_data(target_tid=tid, mode="sub")
    await state.set_state(AdminBalanceAdjustForm.amount)
    await callback.message.answer(
        f"➖ مقدار کاهش موجودی برای کاربر {tid} را به تومان وارد کنید:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminBalanceAdjustForm.amount)
async def uadm_balance_apply(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    amount = parse_positive_int(message.text or "")
    if not amount:
        await message.answer("❌ مقدار نامعتبر. دوباره وارد کنید:")
        return
    data = await state.get_data()
    tid = data["target_tid"]
    mode = data["mode"]
    db = get_db()
    user = await db.get_user_by_telegram_id(tid)
    if not user:
        await message.answer("❌ کاربر پیدا نشد.", reply_markup=admin_menu())
        await state.clear()
        return
    delta = amount if mode == "add" else -amount
    new_bal = await db.update_user_balance(user["id"], delta)
    await state.clear()
    label = "افزایش" if mode == "add" else "کاهش"
    await message.answer(
        f"✅ موجودی {label} یافت.\nموجودی جدید: {new_bal:,} تومان", reply_markup=admin_menu()
    )
    try:
        await message.bot.send_message(
            tid, f"💰 موجودی شما {delta:+,} تومان تغییر کرد.\nموجودی جدید: {new_bal:,} تومان"
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("uadm_subs:"))
async def uadm_subs(callback: CallbackQuery, is_admin: bool):
    if not is_admin:
        return
    tid = int(callback.data.split(":")[1])
    db = get_db()
    user = await db.get_user_by_telegram_id(tid)
    if not user:
        await callback.answer("کاربر پیدا نشد", show_alert=True)
        return
    subs = await db.get_user_subscriptions(user["id"])
    if not subs:
        await callback.answer("این کاربر سرویسی ندارد.", show_alert=True)
        return
    await callback.message.edit_text(
        f"📦 سرویس‌های کاربر {tid}:",
        reply_markup=admin_user_services_inline(subs, tid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("uadm_sub:"))
async def uadm_sub_detail(callback: CallbackQuery, is_admin: bool):
    if not is_admin:
        return
    _, sub_id_s, tid_s = callback.data.split(":")
    sub_id, tid = int(sub_id_s), int(tid_s)
    db = get_db()
    sub = await db.get_subscription(sub_id)
    if not sub:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    text = (
        f"📦 سرویس #{sub['id']}\n"
        f"📧 {sub['email']}\n"
        f"📊 {sub['volume_gb']} GB\n"
        f"📡 {sub.get('panel_name', '')}\n"
        f"وضعیت: {sub['status']}"
    )
    await callback.message.edit_text(text, reply_markup=admin_sub_actions_inline(sub_id, tid))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_getconfig:"))
async def admin_get_config(callback: CallbackQuery, is_admin: bool):
    if not is_admin:
        return
    sub_id = int(callback.data.split(":")[1])
    db = get_db()
    sub = await db.get_subscription(sub_id)
    if not sub:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    links = load_config_links(sub)
    if not links:
        await callback.answer("❌ کانفیگی برای این سرویس ثبت نشده است.", show_alert=True)
        return
    for i, link in enumerate(links, 1):
        label = f"🔧 کانفیگ {i} از {len(links)}" if len(links) > 1 else "🔧 کانفیگ"
        await callback.message.answer(f"{label}:\n`{link}`", parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_getsublink:"))
async def admin_get_sub_link(callback: CallbackQuery, is_admin: bool):
    if not is_admin:
        return
    sub_id = int(callback.data.split(":")[1])
    db = get_db()
    sub = await db.get_subscription(sub_id)
    if not sub:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    sub_link = sub.get("sub_link")
    if not sub_link:
        await callback.answer("❌ لینک ساب برای این سرویس ثبت نشده است.", show_alert=True)
        return
    await callback.message.answer(f"🔗 لینک سابسکریپشن:\n`{sub_link}`", parse_mode="Markdown")
    await callback.answer()


# --- FAQ admin ---
@router.message(F.text == t("admin_faq"))
async def admin_faq(message: Message, state: FSMContext):
    if message.from_user.id not in get_settings().admin_ids:
        return
    await message.answer(
        "❓ برای افزودن FAQ: /add_faq\n"
        "برای حذف: /del_faq [id]"
    )


@router.message(Command("add_faq"))
async def add_faq_start(message: Message, state: FSMContext):
    if message.from_user.id not in get_settings().admin_ids:
        return
    await state.set_state(AdminFAQForm.question)
    await message.answer("سوال:", reply_markup=cancel_kb())


@router.message(AdminFAQForm.question)
async def add_faq_question(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    await state.update_data(question=message.text)
    await state.set_state(AdminFAQForm.answer)
    await message.answer("پاسخ:")


@router.message(AdminFAQForm.answer)
async def add_faq_answer(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    data = await state.get_data()
    db = get_db()
    fid = await db.add_faq(data["question"], message.text)
    await state.clear()
    await message.answer(f"✅ FAQ #{fid} اضافه شد.", reply_markup=admin_menu())


@router.message(Command("del_faq"))
async def del_faq(message: Message):
    if message.from_user.id not in get_settings().admin_ids:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("استفاده: /del_faq [id]")
        return
    db = get_db()
    await db.delete_faq(int(parts[1]))
    await message.answer("✅ حذف شد.")


# --- Broadcast ---
@router.message(F.text == t("admin_broadcast"))
async def broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id not in get_settings().admin_ids:
        return
    await state.set_state(AdminBroadcastForm.text)
    await message.answer("📢 متن پیام همگانی:", reply_markup=cancel_kb())


@router.message(AdminBroadcastForm.text)
async def broadcast_send(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    db = get_db()
    users = await db._fetchall("SELECT telegram_id FROM users")
    ok, fail = 0, 0
    for u in users:
        try:
            await message.bot.send_message(u["telegram_id"], message.text)
            ok += 1
        except Exception:
            fail += 1
    await state.clear()
    await message.answer(f"✅ ارسال شد: {ok} | ❌ ناموفق: {fail}", reply_markup=admin_menu())


# ─── Settings ────────────────────────────────────────────────────────────────

# تعریف مشخصات هر کلید تنظیمات
_SETTINGS_META = {
    "welcome_text":       {"label": "👋 متن خوش‌آمد",            "hint": "متن پیامی که کاربران تازه‌وارد دریافت می‌کنند."},
    "support_text":       {"label": "🆘 متن پشتیبانی",           "hint": "متن نمایش‌داده‌شده در بخش پشتیبانی."},
    "support_username":   {"label": "📱 یوزرنیم پشتیبان",        "hint": "یوزرنیم ادمین پشتیبانی (بدون @). مثال: MorsVpnAdmin"},
    "trial_enabled":      {"label": "🎁 اکانت تست (فعال/غیرفعال)", "hint": "فعال‌بودن اکانت تست: 1 = فعال، 0 = غیرفعال"},
    "trial_product_id":   {"label": "📦 ID محصول تست",            "hint": "آیدی عددی محصولی که برای اکانت تست استفاده می‌شود."},
    "trial_panel_id":     {"label": "🖥 ID پنل تست",              "hint": "آیدی عددی پنلی که اکانت تست روی آن ساخته می‌شود."},
    "trial_volume_gb":    {"label": "📊 حجم تست (GB)",            "hint": "حجم اکانت تست به گیگابایت. مثال: 0.1"},
    "trial_duration_days":{"label": "⏱ مدت تست (روز)",           "hint": "تعداد روزهای اکانت تست. مثال: 1"},
    "channel_required":   {"label": "🔒 کانال اجباری (ID)",       "hint": "آیدی عددی یا یوزرنیم کانال. مثال: -1001234567890 یا @channel\nبرای غیرفعال‌کردن - بفرستید."},
    "channel_invite_link":{"label": "🔗 لینک دعوت کانال",         "hint": "لینک دعوت کانال که به کاربران نمایش داده می‌شود.\nمثال: https://t.me/morsVPN"},
    "min_deposit":        {"label": "💰 حداقل شارژ (تومان)",      "hint": "کمترین مبلغ قابل شارژ کیف پول به تومان. مثال: 10000"},
}

_SETTINGS_KEYS = list(_SETTINGS_META.keys())


def settings_main_inline() -> InlineKeyboardMarkup:
    """منوی اصلی تنظیمات — یک دکمه به ازای هر کلید."""
    rows = []
    for key, meta in _SETTINGS_META.items():
        rows.append([InlineKeyboardButton(text=meta["label"], callback_data=f"cfg_edit:{key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _settings_overview_text(db) -> str:
    lines = ["⚙️ تنظیمات ربات\n"]
    for key, meta in _SETTINGS_META.items():
        v = await db.get_setting(key, "")
        v_safe = html.escape(v[:60]) + ("…" if len(v) > 60 else "")
        lines.append(f"{meta['label']}:\n  <code>{v_safe or '—'}</code>\n")
    lines.append("\nبرای تغییر هر مورد روی دکمه مربوطه بزنید 👇")
    return "\n".join(lines)


@router.message(F.text == t("admin_settings"))
async def admin_settings(message: Message):
    if message.from_user.id not in get_settings().admin_ids:
        return
    db = get_db()
    text = await _settings_overview_text(db)
    await message.answer(text, reply_markup=settings_main_inline(), parse_mode="HTML")


@router.callback_query(F.data == "cfg_back")
async def cfg_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    db = get_db()
    text = await _settings_overview_text(db)
    await callback.message.edit_text(text, reply_markup=settings_main_inline(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("cfg_edit:"))
async def cfg_edit_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    key = callback.data.split(":", 1)[1]
    if key not in _SETTINGS_META:
        await callback.answer("کلید نامعتبر", show_alert=True)
        return

    # کانال اجباری — فلو دو مرحله‌ای مخصوص خودش را دارد
    if key == "channel_required":
        await state.set_state(AdminChannelForm.channel_id)
        await callback.message.answer(
            "🔒 آیدی یا یوزرنیم کانال را برای بررسی عضویت ارسال کنید.\n"
            "مثال: @your_channel یا -1001234567890 (آیدی عددی برای کانال خصوصی)\n\n"
            "⚠️ ربات باید ادمین همان کانال باشد.\n"
            "برای غیرفعال‌کردن عضویت اجباری، علامت - را بفرستید.",
            reply_markup=cancel_kb(),
        )
        await callback.answer()
        return

    # لینک دعوت کانال — فلو تک‌مرحله‌ای
    if key == "channel_invite_link":
        await state.update_data(settings_key=key)
        await state.set_state(AdminSettingsForm.value)
        db = get_db()
        cur = await db.get_setting(key, "")
        await callback.message.answer(
            f"{_SETTINGS_META[key]['label']}\n\n"
            f"📌 مقدار فعلی: <code>{html.escape(cur) or '—'}</code>\n\n"
            f"💡 {_SETTINGS_META[key]['hint']}\n\n"
            "مقدار جدید را ارسال کنید:",
            reply_markup=cancel_kb(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    # بقیه کلیدها — تک‌مرحله‌ای عمومی
    await state.update_data(settings_key=key)
    await state.set_state(AdminSettingsForm.value)
    db = get_db()
    cur = await db.get_setting(key, "")
    await callback.message.answer(
        f"{_SETTINGS_META[key]['label']}\n\n"
        f"📌 مقدار فعلی: <code>{html.escape(cur) or '—'}</code>\n\n"
        f"💡 {_SETTINGS_META[key]['hint']}\n\n"
        "مقدار جدید را ارسال کنید:",
        reply_markup=cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminSettingsForm.value)
async def cfg_save_value(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return

    data = await state.get_data()
    key = data.get("settings_key")
    if not key:
        await state.clear()
        return

    value = (message.text or "").strip()

    # اعتبارسنجی‌های اختصاصی
    if key == "trial_enabled" and value not in ("0", "1"):
        await message.answer("❌ فقط 0 یا 1 قابل قبول است.")
        return
    if key in ("trial_product_id", "trial_panel_id", "min_deposit"):
        if not value.isdigit() or int(value) <= 0:
            await message.answer("❌ باید یک عدد صحیح مثبت باشد.")
            return
    if key in ("trial_volume_gb", "trial_duration_days"):
        try:
            assert float(value) > 0
        except (ValueError, AssertionError):
            await message.answer("❌ باید یک عدد مثبت باشد.")
            return
    if key == "channel_invite_link" and value != "-":
        if not (value.startswith("http://") or value.startswith("https://")):
            await message.answer("❌ لینک باید با http:// یا https:// شروع شود.")
            return
        if value == "-":
            value = ""

    db = get_db()
    await db.set_setting(key, value)
    await state.clear()

    label = _SETTINGS_META.get(key, {}).get("label", key)
    await message.answer(
        f"✅ {label} با موفقیت ذخیره شد.\n"
        f"مقدار جدید: <code>{html.escape(value)}</code>",
        reply_markup=admin_menu(),
        parse_mode="HTML",
    )


# --- کانال اجباری (فلو دو مرحله‌ای) ---
@router.callback_query(F.data == "set_channel")
async def set_channel_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    await state.set_state(AdminChannelForm.channel_id)
    await callback.message.answer(
        "🔒 آیدی یا یوزرنیم کانال را برای بررسی عضویت ارسال کنید.\n"
        "مثال: @your_channel یا -1001234567890 (آیدی عددی برای کانال خصوصی)\n\n"
        "⚠️ ربات باید ادمین همان کانال باشد تا بتواند عضویت کاربران را چک کند.\n"
        "برای غیرفعال‌کردن عضویت اجباری، علامت - را بفرستید.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminChannelForm.channel_id)
async def set_channel_id(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return

    text = (message.text or "").strip()
    db = get_db()
    if text == "-":
        await db.set_setting("channel_required", "")
        await db.set_setting("channel_invite_link", "")
        await state.clear()
        await message.answer("✅ عضویت اجباری غیرفعال شد.", reply_markup=admin_menu())
        return

    await state.update_data(channel_id=text)
    await state.set_state(AdminChannelForm.invite_link)
    await message.answer(
        "🔗 حالا لینک عضویت کانال (همانی که برای کاربران نمایش داده می‌شود) را ارسال کنید.\n"
        "مثال: https://t.me/your_channel\n"
        "یا برای کانال خصوصی: https://t.me/+AbCdEfGhIjKlMnOpQr\n\n"
        "اگر می‌خواهید فقط آیدی ثبت شود بدون نمایش دکمه لینک، علامت - را بفرستید."
    )


@router.message(AdminChannelForm.invite_link)
async def set_channel_invite_link(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return

    text = (message.text or "").strip()
    invite_link = "" if text == "-" else text
    if invite_link and not (invite_link.startswith("http://") or invite_link.startswith("https://")):
        await message.answer("❌ لینک باید با http:// یا https:// شروع شود. دوباره ارسال کنید یا - را بفرستید.")
        return

    data = await state.get_data()
    db = get_db()
    await db.set_setting("channel_required", data["channel_id"])
    await db.set_setting("channel_invite_link", invite_link)
    await state.clear()
    await message.answer(
        f"✅ عضویت اجباری تنظیم شد.\nکانال: {data['channel_id']}\nلینک: {invite_link or '—'}",
        reply_markup=admin_menu(),
    )


@router.message(Command("set"))
async def admin_set_setting(message: Message):
    """دستور مستقیم /set برای تغییر تنظیم — هنوز کار می‌کند."""
    if message.from_user.id not in get_settings().admin_ids:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("استفاده: /set [key] [value]")
        return
    db = get_db()
    await db.set_setting(parts[1], parts[2])
    await message.answer(f"✅ {parts[1]} بروز شد.")


# --- Tutorials admin ---
@router.message(F.text == t("admin_tutorials"))
async def admin_tutorials(message: Message):
    if message.from_user.id not in get_settings().admin_ids:
        return
    db = get_db()
    items = await db.get_tutorials()
    count = len(items)
    text = f"📖 مدیریت آموزش‌ها\n\nتعداد آموزش‌های ثبت‌شده: {count}"
    await message.answer(text, reply_markup=admin_tutorials_inline(items))


@router.callback_query(F.data == "adm_tut_list")
async def adm_tut_list(callback: CallbackQuery):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    db = get_db()
    items = await db.get_tutorials()
    count = len(items)
    text = f"📖 مدیریت آموزش‌ها\n\nتعداد آموزش‌های ثبت‌شده: {count}"
    await callback.message.edit_text(text, reply_markup=admin_tutorials_inline(items))
    await callback.answer()


@router.callback_query(F.data == "adm_tut_add")
async def adm_tut_add_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    await state.set_state(AdminTutorialForm.title)
    await callback.message.answer(
        "📖 عنوان آموزش را وارد کنید:\n(مثال: آموزش اتصال در اندروید)",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminTutorialForm.title)
async def adm_tut_title(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    title = (message.text or "").strip()
    if not title:
        await message.answer("❌ عنوان نمی‌تواند خالی باشد. دوباره وارد کنید:")
        return
    await state.update_data(title=title)
    await state.set_state(AdminTutorialForm.content)
    await message.answer(
        f"✅ عنوان ثبت شد: «{title}»\n\n📝 حالا متن آموزش را وارد کنید:\n"
        "(می‌توانید از فرمت‌بندی Markdown مثل **bold** یا `code` استفاده کنید)"
    )


@router.message(AdminTutorialForm.content)
async def adm_tut_content(message: Message, state: FSMContext):
    if message.text == t("cancel"):
        await state.clear()
        await message.answer(t("operation_cancelled"), reply_markup=admin_menu())
        return
    content = (message.text or "").strip()
    if not content:
        await message.answer("❌ متن آموزش نمی‌تواند خالی باشد. دوباره وارد کنید:")
        return
    data = await state.get_data()
    db = get_db()
    tid = await db.add_tutorial(data["title"], content)
    await state.clear()
    await message.answer(
        f"✅ آموزش «{data['title']}» با موفقیت اضافه شد! (شناسه: {tid})",
        reply_markup=admin_menu(),
    )


@router.callback_query(F.data.startswith("adm_tut_view:"))
async def adm_tut_view(callback: CallbackQuery):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    tid = int(callback.data.split(":")[1])
    db = get_db()
    item = await db._fetchone("SELECT * FROM tutorials WHERE id = ?", (tid,))
    if not item:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    text = f"📖 {item['title']}\n\n{item['content']}"
    await callback.message.edit_text(text, reply_markup=admin_tutorial_detail_inline(tid))
    await callback.answer()


@router.callback_query(F.data.startswith("adm_tut_del:"))
async def adm_tut_delete(callback: CallbackQuery):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    tid = int(callback.data.split(":")[1])
    db = get_db()
    item = await db._fetchone("SELECT * FROM tutorials WHERE id = ?", (tid,))
    title = item["title"] if item else f"#{tid}"
    await db.delete_tutorial(tid)
    items = await db.get_tutorials()
    count = len(items)
    await callback.message.edit_text(
        f"🗑 آموزش «{title}» حذف شد.\n\n📖 مدیریت آموزش‌ها\nتعداد: {count}",
        reply_markup=admin_tutorials_inline(items),
    )
    await callback.answer("✅ حذف شد.")


# ===================== COUPON MANAGEMENT =====================

import random
import string

def _gen_coupon_code(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def _coupon_detail_text(c: dict) -> str:
    dtype = "درصد" if c["discount_type"] == "percent" else "تومان ثابت"
    utype = {
        "unlimited": "نامحدود",
        "once_per_user": "یک بار برای هر کاربر",
        "one_time": "یک بار کلی",
    }.get(c["usage_type"], c["usage_type"])
    max_u = f"{c['max_uses']} بار" if c["max_uses"] > 0 else "نامحدود"
    status = "✅ فعال" if c["is_active"] else "🚫 غیرفعال"
    exp = c["expires_at"] or "ندارد"
    return (
        f"🎟 کوپن: {c['code']}\n"
        f"💸 تخفیف: {c['discount_value']} {dtype}\n"
        f"🔁 نوع استفاده: {utype}\n"
        f"🔢 حداکثر استفاده: {max_u}\n"
        f"📊 استفاده‌شده: {c['used_count']} بار\n"
        f"📅 انقضا: {exp}\n"
        f"وضعیت: {status}"
    )


@router.message(F.text == t("admin_coupons"))
async def admin_coupons(message: Message):
    if message.from_user.id not in get_settings().admin_ids:
        return
    db = get_db()
    coupons = await db.get_coupons()
    text = f"🎟 مدیریت کوپن‌های تخفیف\n\nتعداد: {len(coupons)}"
    await message.answer(text, reply_markup=admin_coupons_inline(coupons))


@router.callback_query(F.data == "adm_coup_list")
async def adm_coup_list(callback: CallbackQuery):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    db = get_db()
    coupons = await db.get_coupons()
    await callback.message.edit_text(
        f"🎟 مدیریت کوپن‌های تخفیف\n\nتعداد: {len(coupons)}",
        reply_markup=admin_coupons_inline(coupons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_coup:"))
async def adm_coup_detail(callback: CallbackQuery):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    cid = int(callback.data.split(":")[1])
    db = get_db()
    c = await db.get_coupon(cid)
    if not c:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    await callback.message.edit_text(_coupon_detail_text(c), reply_markup=admin_coupon_detail_inline(c))
    await callback.answer()


# --- Add coupon flow ---

@router.callback_query(F.data == "adm_coup_add")
async def adm_coup_add_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    await state.set_state(AdminCouponForm.code_mode)
    await callback.message.answer(
        "🎟 ساخت کوپن جدید\n\nکد کوپن چگونه باشد؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✍️ وارد کردن دستی", callback_data="coup_mode:manual")],
            [InlineKeyboardButton(text="🎲 تولید خودکار (رندوم)", callback_data="coup_mode:random")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("coup_mode:"), AdminCouponForm.code_mode)
async def adm_coup_mode(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[1]
    if mode == "random":
        code = _gen_coupon_code()
        await state.update_data(code=code)
        await state.set_state(AdminCouponForm.discount_type)
        await callback.message.edit_text(
            f"✅ کد تولید شد: <code>{code}</code>\n\nنوع تخفیف را انتخاب کنید:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📉 درصدی (%)", callback_data="coup_dtype:percent")],
                [InlineKeyboardButton(text="💵 مبلغ ثابت (تومان)", callback_data="coup_dtype:fixed")],
            ]),
        )
    else:
        await state.update_data(code=None)
        await state.set_state(AdminCouponForm.code)
        await callback.message.edit_text("✍️ کد کوپن دلخواه را وارد کنید (حروف انگلیسی/عدد):")
    await callback.answer()


@router.message(AdminCouponForm.code)
async def adm_coup_code(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    if not code or len(code) < 3:
        await message.answer("❌ کد باید حداقل ۳ کاراکتر باشد. دوباره وارد کنید:")
        return
    db = get_db()
    existing = await db.get_coupon_by_code(code)
    if existing:
        await message.answer("❌ این کد قبلاً ثبت شده. کد دیگری وارد کنید:")
        return
    await state.update_data(code=code)
    await state.set_state(AdminCouponForm.discount_type)
    await message.answer(
        f"✅ کد: <code>{code}</code>\n\nنوع تخفیف را انتخاب کنید:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📉 درصدی (%)", callback_data="coup_dtype:percent")],
            [InlineKeyboardButton(text="💵 مبلغ ثابت (تومان)", callback_data="coup_dtype:fixed")],
        ]),
    )


@router.callback_query(F.data.startswith("coup_dtype:"), AdminCouponForm.discount_type)
async def adm_coup_dtype(callback: CallbackQuery, state: FSMContext):
    dtype = callback.data.split(":")[1]
    await state.update_data(discount_type=dtype)
    await state.set_state(AdminCouponForm.discount_value)
    unit = "درصد (۱ تا ۱۰۰)" if dtype == "percent" else "مبلغ به تومان"
    await callback.message.edit_text(f"💸 مقدار تخفیف را وارد کنید ({unit}):")
    await callback.answer()


@router.message(AdminCouponForm.discount_value)
async def adm_coup_dvalue(message: Message, state: FSMContext):
    try:
        val = int((message.text or "").strip().replace(",", ""))
        assert val > 0
    except (ValueError, AssertionError):
        await message.answer("❌ عدد معتبر وارد کنید:")
        return
    data = await state.get_data()
    if data.get("discount_type") == "percent" and val > 100:
        await message.answer("❌ درصد نمی‌تواند بیشتر از ۱۰۰ باشد:")
        return
    await state.update_data(discount_value=val)
    await state.set_state(AdminCouponForm.usage_type)
    await message.answer(
        "🔁 نوع استفاده از کوپن را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="♾ نامحدود (همه کاربران، هر بار)", callback_data="coup_utype:unlimited")],
            [InlineKeyboardButton(text="👤 یک بار برای هر کاربر", callback_data="coup_utype:once_per_user")],
            [InlineKeyboardButton(text="1️⃣ فقط یک بار کلی", callback_data="coup_utype:one_time")],
        ]),
    )


@router.callback_query(F.data.startswith("coup_utype:"), AdminCouponForm.usage_type)
async def adm_coup_utype(callback: CallbackQuery, state: FSMContext):
    utype = callback.data.split(":")[1]
    await state.update_data(usage_type=utype)
    await state.set_state(AdminCouponForm.max_uses)
    await callback.message.edit_text(
        "🔢 حداکثر تعداد کل استفاده را وارد کنید:\n(۰ = نامحدود)"
    )
    await callback.answer()


@router.message(AdminCouponForm.max_uses)
async def adm_coup_maxuses(message: Message, state: FSMContext):
    try:
        max_u = int((message.text or "").strip())
        assert max_u >= 0
    except (ValueError, AssertionError):
        await message.answer("❌ عدد صحیح (۰ یا بیشتر) وارد کنید:")
        return
    data = await state.get_data()
    db = get_db()
    cid = await db.add_coupon(
        code=data["code"],
        discount_type=data["discount_type"],
        discount_value=data["discount_value"],
        usage_type=data["usage_type"],
        max_uses=max_u,
    )
    await state.clear()
    coupon = await db.get_coupon(cid)
    await message.answer(
        f"✅ کوپن با موفقیت ساخته شد!\n\n{_coupon_detail_text(coupon)}",
        reply_markup=admin_menu(),
    )


# --- Toggle / Delete ---

@router.callback_query(F.data.startswith("adm_coup_en:"))
async def adm_coup_enable(callback: CallbackQuery):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    cid = int(callback.data.split(":")[1])
    db = get_db()
    await db.update_coupon(cid, is_active=1)
    c = await db.get_coupon(cid)
    await callback.message.edit_text(_coupon_detail_text(c), reply_markup=admin_coupon_detail_inline(c))
    await callback.answer("✅ کوپن فعال شد.")


@router.callback_query(F.data.startswith("adm_coup_dis:"))
async def adm_coup_disable(callback: CallbackQuery):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    cid = int(callback.data.split(":")[1])
    db = get_db()
    await db.update_coupon(cid, is_active=0)
    c = await db.get_coupon(cid)
    await callback.message.edit_text(_coupon_detail_text(c), reply_markup=admin_coupon_detail_inline(c))
    await callback.answer("🚫 کوپن غیرفعال شد.")


@router.callback_query(F.data.startswith("adm_coup_del:"))
async def adm_coup_delete(callback: CallbackQuery):
    if callback.from_user.id not in get_settings().admin_ids:
        return
    cid = int(callback.data.split(":")[1])
    db = get_db()
    c = await db.get_coupon(cid)
    code = c["code"] if c else f"#{cid}"
    await db.delete_coupon(cid)
    coupons = await db.get_coupons()
    await callback.message.edit_text(
        f"🗑 کوپن «{code}» حذف شد.\n\n🎟 مدیریت کوپن‌ها\nتعداد: {len(coupons)}",
        reply_markup=admin_coupons_inline(coupons),
    )
    await callback.answer("✅ حذف شد.")
