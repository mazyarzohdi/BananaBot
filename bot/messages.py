"""Persian UI texts."""

TEXTS = {
    "welcome": "🌐 به ربات فروش VPN خوش آمدید!\n\nاز منوی زیر استفاده کنید.",
    "main_menu": "📋 منوی اصلی",
    "buy_service": "🛒 خرید سرویس",
    "my_services": "📦 سرویس‌های من",
    "trial": "🎁 اکانت تست",
    "balance": "💰 کیف پول",
    "deposit": "💳 افزایش موجودی",
    "support": "📞 پشتیبانی",
    "referral": "🤝 دعوت از دوستان",
    "new_ticket": "🎫 ارسال تیکت جدید",
    "my_tickets": "📋 تیکت‌های من",
    "faq": "❓ سوالات متداول",
    "tutorials": "📖 آموزش",
    "web_panel": "🌐 پنل وب",
    "channel_required": "⚠️ برای استفاده از ربات باید در کانال ما عضو شوید.",
    "no_products": "❌ در حال حاضر محصولی برای فروش وجود ندارد.",
    "select_product": "📦 یک محصول را انتخاب کنید:",
    "confirm_buy": "✅ تأیید و خرید",
    "cancel": "❌ انصراف",
    "back": "🔙 بازگشت",
    "insufficient_balance": "❌ موجودی کیف پول کافی نیست.\nموجودی شما: {balance:,} تومان\nمبلغ مورد نیاز: {price:,} تومان\nمبلغ کسری: {deficit:,} تومان",
    "purchase_success": "✅ خرید با موفقیت انجام شد!\n\n📧 ایمیل: `{email}`\n📊 حجم: {volume} GB\n⏱ مدت: {days} روز\n\nبرای دریافت کانفیگ یا لینک ساب از دکمه‌های زیر استفاده کنید 👇",
    "trial_used": "❌ شما قبلاً اکانت تست دریافت کرده‌اید.",
    "trial_disabled": "❌ اکانت تست در حال حاضر فعال نیست.",
    "trial_success": "🎁 اکانت تست شما آماده است!\n\n📧 ایمیل: `{email}`\n📊 حجم: {volume} GB\n⏱ مدت: {days} روز\n\nبرای دریافت کانفیگ یا لینک ساب از دکمه‌های زیر استفاده کنید 👇",
    "no_services": "📭 شما هنوز سرویسی خریداری نکرده‌اید.",
    "service_detail": (
        "📦 سرویس #{id}\n"
        "📧 ایمیل: `{email}`\n"
        "📊 حجم: {volume} GB\n"
        "📈 مصرف: {used} GB\n"
        "⏱ انقضا: {expiry}\n"
        "📡 پنل: {panel}"
    ),
    "balance_info": "💰 موجودی کیف پول: {balance:,} تومان",
    "enter_deposit_amount": "💳 مبلغ افزایش موجودی را به تومان وارد کنید (حداقل {min:,}):",
    "deposit_card_info": (
        "💳 اطلاعات پرداخت کارت به کارت:\n\n"
        "💰 مبلغ: {amount:,} تومان\n"
        "🔢 شماره کارت: `{card}`\n"
        "👤 به نام: {holder}\n\n"
        "پس از پرداخت، تصویر رسید را ارسال کنید."
    ),
    "deposit_pending": "⏳ درخواست شما ثبت شد. پس از تأیید ادمین موجودی شما افزایش می‌یابد.",
    "admin_menu": "🔧 پنل مدیریت",
    "admin_stats": "📊 آمار",
    "admin_panels": "🖥 مدیریت پنل‌ها",
    "admin_products": "📦 مدیریت محصولات",
    "admin_users": "👥 کاربران",
    "admin_payments": "💳 پرداخت‌های در انتظار",
    "admin_settings": "⚙️ تنظیمات",
    "admin_faq": "❓ مدیریت FAQ",
    "admin_tutorials": "📖 مدیریت آموزش‌ها",
    "admin_coupons": "🎟 مدیریت کوپن‌ها",
    "admin_broadcast": "📢 ارسال همگانی",
    "reseller_panel": "🤝 پنل نمایندگی",
    "admin_reseller": "🤝 مدیریت نمایندگی",
    "admin_tickets": "🎫 تیکت‌های پشتیبانی",
    "not_admin": "❌ دسترسی ادمین ندارید.",
    "operation_cancelled": "❌ عملیات لغو شد.",
    "invalid_amount": "❌ مبلغ نامعتبر است.",
    "panel_added": "✅ پنل با موفقیت اضافه شد.",
    "product_added": "✅ محصول با موفقیت اضافه شد.",
    "payment_confirmed": "✅ پرداخت تأیید شد.",
    "payment_rejected": "❌ پرداخت رد شد.",
}


def t(key: str, **kwargs) -> str:
    text = TEXTS.get(key, key)
    if kwargs:
        return text.format(**kwargs)
    return text
