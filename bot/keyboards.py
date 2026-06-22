"""Keyboard builders."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from bot.messages import t


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=t("buy_service")), KeyboardButton(text=t("my_services"))],
        [KeyboardButton(text=t("trial")), KeyboardButton(text=t("balance"))],
        [KeyboardButton(text=t("deposit")), KeyboardButton(text=t("support"))],
        [KeyboardButton(text=t("faq")), KeyboardButton(text=t("tutorials"))],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=t("admin_menu"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_menu() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=t("admin_stats")), KeyboardButton(text=t("admin_panels"))],
        [KeyboardButton(text=t("admin_products")), KeyboardButton(text=t("admin_users"))],
        [KeyboardButton(text=t("admin_payments")), KeyboardButton(text=t("admin_settings"))],
        [KeyboardButton(text=t("admin_faq")), KeyboardButton(text=t("admin_tutorials"))],
        [KeyboardButton(text=t("admin_coupons")), KeyboardButton(text=t("admin_broadcast"))],
        [KeyboardButton(text=t("back"))],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("cancel"))]],
        resize_keyboard=True,
    )


def back_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("back"))]],
        resize_keyboard=True,
    )


def products_inline(products: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for p in products:
        label = f"{p['name']} — {p['price']:,} تومان"
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"buy:{p['id']}")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def panels_buy_inline(panels: list[dict]) -> InlineKeyboardMarkup:
    """دکمه‌های شیشه‌ای انتخاب پنل هنگام خرید."""
    buttons = []
    for p in panels:
        buttons.append([
            InlineKeyboardButton(text=f"🖥 {p['name']}", callback_data=f"buy_panel:{p['id']}")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def products_by_panel_inline(products: list[dict], panel_name: str) -> InlineKeyboardMarkup:
    """دکمه‌های شیشه‌ای محصولات یک پنل + دکمه بازگشت به انتخاب پنل."""
    buttons = []
    for p in products:
        label = f"{p['name']} — {p['price']:,} تومان"
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"buy:{p['id']}")
        ])
    buttons.append([
        InlineKeyboardButton(text="🔙 بازگشت به انتخاب پنل", callback_data="buy_back_panels")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_buy_inline(
    product_id: int,
    panel_id: int | None = None,
    coupon_code: str | None = None,
    discount_amount: int = 0,
) -> InlineKeyboardMarkup:
    back_data = f"buy_panel:{panel_id}" if panel_id else "buy_back_panels"
    coupon_label = (
        f"✅ کوپن: {coupon_code} (−{discount_amount:,} تومان)"
        if coupon_code
        else "🎟 وارد کردن کوپن تخفیف"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("confirm_buy"),
                    callback_data=f"confirm_buy:{product_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=coupon_label,
                    callback_data=f"enter_coupon:{product_id}",
                ),
            ],
            [
                InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_data),
            ],
        ]
    )


def admin_coupons_inline(coupons: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for c in coupons:
        status = "✅" if c["is_active"] else "🚫"
        dtype = "%" if c["discount_type"] == "percent" else "T"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {c['code']} — {c['discount_value']}{dtype} | {c['used_count']} بار",
                callback_data=f"adm_coup:{c['id']}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ افزودن کوپن جدید", callback_data="adm_coup_add")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_coupon_detail_inline(coupon: dict) -> InlineKeyboardMarkup:
    cid = coupon["id"]
    toggle_btn = (
        InlineKeyboardButton(text="🚫 غیرفعال کردن", callback_data=f"adm_coup_dis:{cid}")
        if coupon["is_active"]
        else InlineKeyboardButton(text="✅ فعال کردن", callback_data=f"adm_coup_en:{cid}")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [toggle_btn],
            [InlineKeyboardButton(text="🗑 حذف کوپن", callback_data=f"adm_coup_del:{cid}")],
            [InlineKeyboardButton(text="🔙 بازگشت به لیست", callback_data="adm_coup_list")],
        ]
    )


def services_inline(services: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for s in services:
        if s["status"] != "active":
            continue
        label = f"#{s['id']} — {s['email']}"
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"service:{s['id']}")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def service_actions_inline(sub_id: int, show_back: bool = True, renewable: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="🔧 دریافت کانفیگ", callback_data=f"getconfig:{sub_id}"),
            InlineKeyboardButton(text="🔗 دریافت لینک ساب", callback_data=f"getsublink:{sub_id}"),
        ],
        [
            InlineKeyboardButton(text="📊 مصرف", callback_data=f"usage:{sub_id}"),
            InlineKeyboardButton(text="🔄 بروزرسانی لینک", callback_data=f"refresh:{sub_id}"),
        ],
    ]
    if renewable:
        rows.append([InlineKeyboardButton(text="🔁 تمدید سرویس", callback_data=f"svc_renew:{sub_id}")])
    if show_back:
        rows.append([InlineKeyboardButton(text=t("back"), callback_data="back_services")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def balance_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 افزایش موجودی", callback_data="deposit_start_cb")],
        ]
    )


def renew_confirm_inline(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأیید و تمدید", callback_data=f"svc_renew_ok:{sub_id}"),
                InlineKeyboardButton(text="❌ انصراف", callback_data="cancel"),
            ]
        ]
    )


def insufficient_balance_renew_inline(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 پرداخت کارت به کارت", callback_data=f"card_topup_renew:{sub_id}")],
            [InlineKeyboardButton(text=t("cancel"), callback_data="cancel")],
        ]
    )


def renew_complete_inline(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 تکمیل تمدید سرویس", callback_data=f"svc_renew_ok:{sub_id}")],
        ]
    )


def insufficient_balance_inline(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 پرداخت کارت به کارت", callback_data=f"card_topup:{product_id}")],
            [InlineKeyboardButton(text=t("cancel"), callback_data="cancel")],
        ]
    )


def channel_required_inline(invite_link: str, recheck_data: str) -> InlineKeyboardMarkup:
    rows = []
    if invite_link:
        rows.append([InlineKeyboardButton(text="📢 عضویت در کانال", url=invite_link)])
    rows.append([InlineKeyboardButton(text="✅ بررسی مجدد عضویت", callback_data=recheck_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def complete_purchase_inline(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 تکمیل خرید", callback_data=f"confirm_buy:{product_id}")],
        ]
    )


def panels_inline(panels: list[dict], prefix: str = "panel") -> InlineKeyboardMarkup:
    buttons = []
    for p in panels:
        status = "✅" if p.get("is_active") else "❌"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {p['name']}",
                callback_data=f"{prefix}:{p['id']}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def panel_actions_inline(panel_id: int, is_active: bool = True) -> InlineKeyboardMarkup:
    toggle_btn = (
        InlineKeyboardButton(text="🚫 غیرفعال کردن", callback_data=f"panel_dis:{panel_id}")
        if is_active
        else InlineKeyboardButton(text="✅ فعال کردن", callback_data=f"panel_en:{panel_id}")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔍 تست اتصال", callback_data=f"test_panel:{panel_id}"),
                InlineKeyboardButton(text="📋 Inbounds", callback_data=f"inbounds:{panel_id}"),
            ],
            [
                InlineKeyboardButton(text="🔗 تنظیم لینک ساب", callback_data=f"set_sublink:{panel_id}"),
            ],
            [toggle_btn],
            [
                InlineKeyboardButton(text="❌ حذف", callback_data=f"del_panel:{panel_id}"),
            ],
            [InlineKeyboardButton(text=t("back"), callback_data="admin_panels_back")],
        ]
    )


def products_admin_inline(products: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for p in products:
        status = "✅" if p.get("is_active") else "❌"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {p['name']} — {p['price']:,}",
                callback_data=f"prod:{p['id']}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ افزودن محصول", callback_data="add_product")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def product_actions_inline(product: dict) -> InlineKeyboardMarkup:
    product_id = product["id"]
    if product.get("is_active"):
        toggle_btn = InlineKeyboardButton(
            text="🚫 غیرفعال کردن", callback_data=f"prod_dis:{product_id}"
        )
    else:
        toggle_btn = InlineKeyboardButton(
            text="✅ فعال کردن", callback_data=f"prod_en:{product_id}"
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [toggle_btn],
            [InlineKeyboardButton(text="✏️ ویرایش محصول", callback_data=f"prod_edit:{product_id}")],
            [InlineKeyboardButton(text="🗑 حذف کامل", callback_data=f"prod_del:{product_id}")],
            [InlineKeyboardButton(text=t("back"), callback_data="admin_products_back")],
        ]
    )


def product_edit_menu_inline(product_id: int) -> InlineKeyboardMarkup:
    fields = [
        ("نام", "name"),
        ("حجم (GB)", "volume_gb"),
        ("مدت (روز)", "duration_days"),
        ("قیمت", "price"),
        ("توضیحات", "description"),
        ("پنل", "panel_id"),
    ]
    buttons = [
        [InlineKeyboardButton(text=f"✏️ {label}", callback_data=f"prod_editf:{product_id}:{field}")]
        for label, field in fields
    ]
    buttons.append([InlineKeyboardButton(text=t("back"), callback_data=f"prod:{product_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def product_delete_confirm_inline(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ بله، حذف کن", callback_data=f"prod_del_yes:{product_id}"),
                InlineKeyboardButton(text="❌ انصراف", callback_data=f"prod_del_no:{product_id}"),
            ]
        ]
    )


def payment_actions_inline(payment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأیید", callback_data=f"pay_ok:{payment_id}"),
                InlineKeyboardButton(text="❌ رد", callback_data=f"pay_no:{payment_id}"),
            ]
        ]
    )


def faq_inline(faqs: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for f in faqs:
        buttons.append([
            InlineKeyboardButton(text=f["question"], callback_data=f"faq:{f['id']}")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def tutorials_inline(items: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for item in items:
        buttons.append([
            InlineKeyboardButton(text=item["title"], callback_data=f"tutorial:{item['id']}")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_tutorials_inline(items: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for item in items:
        buttons.append([
            InlineKeyboardButton(
                text=f"📖 {item['title']}",
                callback_data=f"adm_tut_view:{item['id']}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ افزودن آموزش جدید", callback_data="adm_tut_add")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_tutorial_detail_inline(tutorial_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 حذف", callback_data=f"adm_tut_del:{tutorial_id}"),
            ],
            [InlineKeyboardButton(text="🔙 بازگشت به لیست", callback_data="adm_tut_list")],
        ]
    )


def user_admin_card_inline(tid: int, banned: bool) -> InlineKeyboardMarkup:
    ban_btn = (
        InlineKeyboardButton(text="✅ آن‌بن کردن", callback_data=f"uadm_unban:{tid}")
        if banned
        else InlineKeyboardButton(text="🚫 بن کردن", callback_data=f"uadm_ban:{tid}")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📦 سرویس‌های کاربر", callback_data=f"uadm_subs:{tid}"),
                InlineKeyboardButton(text="✉️ ارسال پیام", callback_data=f"uadm_msg:{tid}"),
            ],
            [
                InlineKeyboardButton(text="➕ افزایش موجودی", callback_data=f"uadm_addbal:{tid}"),
                InlineKeyboardButton(text="➖ کاهش موجودی", callback_data=f"uadm_subbal:{tid}"),
            ],
            [ban_btn],
            [InlineKeyboardButton(text="🔄 بروزرسانی", callback_data=f"uadm_refresh:{tid}")],
        ]
    )


def admin_user_services_inline(subs: list[dict], tid: int) -> InlineKeyboardMarkup:
    rows = []
    for s in subs:
        status_icon = "✅" if s["status"] == "active" else "⛔️"
        rows.append([
            InlineKeyboardButton(
                text=f"{status_icon} #{s['id']} - {s['email']}",
                callback_data=f"uadm_sub:{s['id']}:{tid}",
            )
        ])
    rows.append([InlineKeyboardButton(text=t("back"), callback_data=f"uadm_refresh:{tid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_sub_actions_inline(sub_id: int, tid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔧 دریافت کانفیگ", callback_data=f"admin_getconfig:{sub_id}"),
                InlineKeyboardButton(text="🔗 دریافت لینک ساب", callback_data=f"admin_getsublink:{sub_id}"),
            ],
            [InlineKeyboardButton(text=t("back"), callback_data=f"uadm_subs:{tid}")],
        ]
    )
