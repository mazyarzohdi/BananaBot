"""Keyboard builders."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    CopyTextButton,
)

from bot.messages import t
from config import get_settings


def _panel_button() -> KeyboardButton | None:
    """Return a Web App keyboard button for the panel, if properly configured.

    Telegram only allows web_app buttons to point to HTTPS URLs, so if the
    admin only set up a plain-HTTP or IP-only panel, this returns None and the
    button is silently omitted instead of crashing the bot.
    """
    panel_url = (get_settings().panel_url or "").strip()
    if panel_url.startswith("https://"):
        return KeyboardButton(text=t("web_panel"), web_app=WebAppInfo(url=panel_url))
    return None


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=t("buy_service")), KeyboardButton(text=t("my_services"))],
        [KeyboardButton(text=t("trial")), KeyboardButton(text=t("balance"))],
        [KeyboardButton(text=t("deposit")), KeyboardButton(text=t("support"))],
        [KeyboardButton(text=t("faq")), KeyboardButton(text=t("tutorials"))],
        [KeyboardButton(text=t("reseller_panel"))],
    ]
    panel_btn = _panel_button()
    if panel_btn:
        rows.append([panel_btn])
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
        [KeyboardButton(text=t("admin_reseller"))],
        [KeyboardButton(text=t("back"))],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("cancel"))]],
        resize_keyboard=True,
    )


def auto_payment_copy_inline(amount_rial: int, card_number: str) -> InlineKeyboardMarkup:
    """Two 'glass' (inline) buttons under the auto-payment instructions:
    tapping either just copies the raw value (no thousands separators, no
    dashes/spaces) to the user's clipboard via Telegram's native copy_text
    button — nothing sent back to the bot, no round-trip needed."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 کپی مبلغ", copy_text=CopyTextButton(text=str(amount_rial)))],
        [InlineKeyboardButton(text="📋 کپی شماره کارت", copy_text=CopyTextButton(text=card_number))],
    ])


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
                InlineKeyboardButton(text="✏️ ویرایش Inbounds", callback_data=f"edit_inbounds:{panel_id}"),
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


# ─── Users list pagination ────────────────────────────────────────────────────

def users_list_inline(users: list[dict], page: int, total_pages: int, search: str = "") -> InlineKeyboardMarkup:
    """لیست کاربران با pagination و دکمه‌های ناوبری."""
    rows = []

    for u in users:
        banned = "🚫 " if u.get("is_banned") else ""
        uname = f"@{u['username']}" if u.get("username") else "—"
        label = f"{banned}👤 {u['full_name'] or uname} | {u['telegram_id']}"
        rows.append([
            InlineKeyboardButton(text=label[:60], callback_data=f"ulist_view:{u['telegram_id']}:{page}")
        ])

    # ناوبری صفحه‌بندی
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"ulist_page:{page - 1}:{search}"))
    nav.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="ulist_noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"ulist_page:{page + 1}:{search}"))
    if nav:
        rows.append(nav)

    # دکمه‌های پایین
    rows.append([InlineKeyboardButton(text="🔍 جستجو", callback_data="ulist_search")])
    if search:
        rows.append([InlineKeyboardButton(text="❌ پاک کردن جستجو", callback_data="ulist_page:1:")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── Reseller panel (user side) ───────────────────────────────────────────────

def reseller_plans_inline(plans: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for p in plans:
        label = f"{p['name']} — {p['volume_gb']}GB/{p['duration_days']}روزه — {p['price']:,} تومان"
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"res_plan:{p['id']}")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def reseller_confirm_inline(plan_id: int, renew: bool = False) -> InlineKeyboardMarkup:
    label = "✅ تأیید و تمدید نمایندگی" if renew else "✅ تأیید و خرید نمایندگی"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"res_confirm:{plan_id}")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="res_back_plans")],
        ]
    )

def reseller_complete_inline(plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤝 تکمیل خرید/تمدید نمایندگی", callback_data=f"res_confirm:{plan_id}")],
        ]
    )


def reseller_insufficient_balance_inline(plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 پرداخت کارت به کارت", callback_data=f"res_topup:{plan_id}")],
            [InlineKeyboardButton(text=t("cancel"), callback_data="cancel")],
        ]
    )


def reseller_status_inline(panel_url: str, expired_or_disabled: bool) -> InlineKeyboardMarkup:
    rows = []
    if panel_url.startswith("https://") and not expired_or_disabled:
        rows.append([InlineKeyboardButton(text="🌐 باز کردن پنل نمایندگی", web_app=WebAppInfo(url=panel_url))])
    rows.append([InlineKeyboardButton(text="🔁 تمدید / ارتقاء پلن", callback_data="res_renew_start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── Reseller plans (admin CRUD — mirrors product management) ─────────────────

def reseller_plans_admin_inline(plans: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for p in plans:
        status = "✅" if p.get("is_active") else "❌"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {p['name']} — {p['price']:,}",
                callback_data=f"resplan:{p['id']}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ افزودن پلن نمایندگی", callback_data="add_resplan")
    ])
    buttons.append([
        InlineKeyboardButton(text="📋 لیست نمایندگان", callback_data="resellers_list")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def reseller_plan_actions_inline(plan: dict) -> InlineKeyboardMarkup:
    plan_id = plan["id"]
    if plan.get("is_active"):
        toggle_btn = InlineKeyboardButton(text="🚫 غیرفعال کردن", callback_data=f"resplan_dis:{plan_id}")
    else:
        toggle_btn = InlineKeyboardButton(text="✅ فعال کردن", callback_data=f"resplan_en:{plan_id}")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [toggle_btn],
            [InlineKeyboardButton(text="✏️ ویرایش پلن", callback_data=f"resplan_edit:{plan_id}")],
            [InlineKeyboardButton(text="🗑 حذف کامل", callback_data=f"resplan_del:{plan_id}")],
            [InlineKeyboardButton(text=t("back"), callback_data="admin_resplans_back")],
        ]
    )


def reseller_plan_edit_menu_inline(plan_id: int) -> InlineKeyboardMarkup:
    fields = [
        ("نام", "name"),
        ("حجم (GB)", "volume_gb"),
        ("مدت (روز)", "duration_days"),
        ("قیمت", "price"),
        ("توضیحات", "description"),
        ("پنل", "panel_id"),
    ]
    buttons = [
        [InlineKeyboardButton(text=f"✏️ {label}", callback_data=f"resplan_editf:{plan_id}:{field}")]
        for label, field in fields
    ]
    buttons.append([InlineKeyboardButton(text=t("back"), callback_data=f"resplan:{plan_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def reseller_plan_delete_confirm_inline(plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ بله، حذف کن", callback_data=f"resplan_del_yes:{plan_id}"),
                InlineKeyboardButton(text="❌ انصراف", callback_data=f"resplan_del_no:{plan_id}"),
            ]
        ]
    )


# ─── Resellers list (admin review) ─────────────────────────────────────────────

def resellers_admin_inline(resellers: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for r in resellers:
        status = "✅" if r.get("status") == "active" else "🚫"
        uname = f"@{r['username']}" if r.get("username") else r.get("full_name") or r["telegram_id"]
        cfg_count = r.get("configs_count") or 0
        cfg_badge = f" ({cfg_count} کانفیگ)" if cfg_count else " (بدون کانفیگ)"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} {uname} — {r['quota_gb']}GB{cfg_badge}",
                callback_data=f"resv:{r['id']}",
            )
        ])
    buttons.append([InlineKeyboardButton(text=t("back"), callback_data="admin_resplans_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def reseller_admin_detail_inline(reseller: dict) -> InlineKeyboardMarkup:
    rid = reseller["id"]
    if reseller.get("status") == "active":
        toggle_btn = InlineKeyboardButton(text="🚫 غیرفعال کردن حساب نماینده", callback_data=f"resv_dis:{rid}")
    else:
        toggle_btn = InlineKeyboardButton(text="✅ فعال کردن حساب نماینده", callback_data=f"resv_en:{rid}")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [toggle_btn],
            [
                InlineKeyboardButton(text="✏️ ویرایش حجم", callback_data=f"resv_editq:{rid}"),
                InlineKeyboardButton(text="✏️ ویرایش انقضا", callback_data=f"resv_edite:{rid}"),
            ],
            [InlineKeyboardButton(text="🗑 حذف کامل نماینده", callback_data=f"resv_del:{rid}")],
            [InlineKeyboardButton(text="🔄 بروزرسانی", callback_data=f"resv:{rid}")],
            [InlineKeyboardButton(text="🔙 بازگشت به لیست", callback_data="resellers_list")],
        ]
    )


def reseller_delete_confirm_inline(reseller_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ بله، کامل حذف کن", callback_data=f"resv_del_yes:{reseller_id}"),
                InlineKeyboardButton(text="❌ انصراف", callback_data=f"resv_del_no:{reseller_id}"),
            ]
        ]
    )


def user_admin_card_inline_with_back(tid: int, banned: bool, back_page: int = 1) -> InlineKeyboardMarkup:
    """کارت کاربر با دکمه بازگشت به لیست."""
    ban_btn = (
        InlineKeyboardButton(text="✅ آن‌بن کردن", callback_data=f"uadm_unban:{tid}")
        if banned
        else InlineKeyboardButton(text="🚫 بن کردن", callback_data=f"uadm_ban:{tid}")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📦 سرویس‌ها", callback_data=f"uadm_subs:{tid}"),
                InlineKeyboardButton(text="✉️ ارسال پیام", callback_data=f"uadm_msg:{tid}"),
            ],
            [
                InlineKeyboardButton(text="➕ افزایش موجودی", callback_data=f"uadm_addbal:{tid}"),
                InlineKeyboardButton(text="➖ کاهش موجودی", callback_data=f"uadm_subbal:{tid}"),
            ],
            [ban_btn],
            [InlineKeyboardButton(text="🔄 بروزرسانی", callback_data=f"uadm_refresh:{tid}")],
            [InlineKeyboardButton(text="🔙 بازگشت به لیست", callback_data=f"ulist_page:{back_page}:")],
        ]
    )
