# 🍌 BananaBot — ربات تلگرام مدیریت و فروش سرویس VPN

ربات تلگرامی برای فروش و مدیریت خودکار سرویس‌های VPN روی پنل sanaei  **3x-ui**.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)

---

## ✨ امکانات

### 👤 کاربر
- خرید سرویس با ایجاد خودکار کانفیگ روی پنل
- اکانت تست رایگان
- مشاهده سرویس‌ها، لینک کانفیگ، مصرف و به‌روزرسانی لینک
- کیف پول و افزایش موجودی (کارت به کارت)
- FAQ و آموزش
- پشتیبانی

### 🔧 ادمین
- مولتی ادمین
- آمار کلی ربات
- مدیریت پنل‌ها (افزودن، تست اتصال، لیست Inbound)
- مدیریت محصولات
- تأیید/رد پرداخت‌های کارت به کارت
- جستجوی کاربر و تغییر موجودی
- ارسال همگانی (Broadcast)
- تنظیمات (متن خوش‌آمد، کانال اجباری، اکانت تست و ...)

---

## 📋 پیش‌نیازها

| مورد | نسخه |
|------|-------|
| سیستم‌عامل | Ubuntu 20.04+ / Debian 11+ |
| Python | 3.11 یا بالاتر |
| پنل | [3x-ui](https://github.com/MHSanaei/3x-ui) با API Token فعال |
| دسترسی | root یا sudo |

---

## 🚀 نصب سریع (توصیه‌شده)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/mazyarzohdi/BananaBot/main/install.sh)
```

یا دستی:

```bash
git clone https://github.com/mazyarzohdi/BananaBot.git
cd BananaBot
sudo bash install.sh
```

اسکریپت به‌صورت خودکار:
1. ✅ پیش‌نیازهای سیستم را نصب می‌کند
2. ✅ محیط مجازی Python می‌سازد
3. ✅ کتابخانه‌ها را نصب می‌کند
4. ✅ از شما می‌خواهد توکن ربات، آیدی ادمین و سایر تنظیمات را وارد کنید
5. ✅ فایل `.env` را می‌سازد
6. ✅ سرویس systemd ایجاد می‌کند و ربات را راه‌اندازی می‌کند

---

## ⚙️ پیکربندی دستی

فایل `.env` را در ریشه پروژه بسازید:

```env
# توکن ربات از @BotFather
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ

# آیدی عددی ادمین (یک یا چند عدد با کاما)
ADMIN_IDS=123456789,987654321

# مسیر پایگاه داده
DATABASE_PATH=data/bot.db

# زبان پیش‌فرض (fa یا en)
DEFAULT_LANG=fa

# شماره کارت برای پرداخت (اختیاری)
CARD_NUMBER=6037-XXXX-XXXX-XXXX
CARD_HOLDER=نام صاحب کارت

# کانال اجباری برای خرید (اختیاری)
REQUIRED_CHANNEL=@mychannel
```

---

## 🎛️ اسکریپت مدیریت

پس از نصب، برای مدیریت ربات:

```bash
sudo bash /opt/BananaBot/manage.sh
```

### امکانات پنل مدیریت:

| گزینه | عملکرد |
|-------|---------|
| روشن کردن | `systemctl start bananabot` |
| خاموش کردن | `systemctl stop bananabot` |
| ریستارت | `systemctl restart bananabot` |
| لاگ زنده | `journalctl -u bananabot -f` |
| تغییر توکن | ویرایش `BOT_TOKEN` در `.env` |
| تغییر ادمین | ویرایش `ADMIN_IDS` در `.env` |
| تغییر کارت | ویرایش `CARD_NUMBER` و `CARD_HOLDER` |
| به‌روزرسانی | `git pull` + نصب مجدد کتابخانه‌ها |
| حذف کامل | حذف سرویس، فایل‌ها و پایگاه داده |

---

## 🤖 دستورات ادمین (داخل ربات)

| دستور | توضیح |
|-------|--------|
| `/add_panel` | افزودن پنل 3x-ui |
| `/user <id>` | اطلاعات کاربر |
| `/addbalance <id> <amount>` | تغییر موجودی |
| `/add_faq` | افزودن سوال متداول |
| `/del_faq <id>` | حذف سوال متداول |
| `/set <key> <value>` | تغییر تنظیمات |

---

## 📡 API پنل 3x-ui

برای فعال‌سازی API در پنل:
1. وارد پنل 3x-ui شوید
2. به **Settings → Security** بروید
3. **API Token** را فعال کنید و کپی کنید

| عملیات | Endpoint |
|--------|----------|
| ایجاد کلاینت | `POST /panel/api/clients/add` |
| دریافت لینک | `GET /panel/api/clients/links/{email}` |
| مصرف | `GET /panel/api/clients/traffic/{email}` |
| وضعیت سرور | `GET /panel/api/server/status` |
| لیست Inbound | `GET /panel/api/inbounds/options` |

احراز هویت: `Authorization: Bearer <API_TOKEN>`

---

## 📁 ساختار پروژه

```
BananaBot/
├── install.sh              # اسکریپت نصب خودکار
├── manage.sh               # اسکریپت مدیریت ربات
├── main.py                 # نقطه ورود
├── config.py               # خواندن تنظیمات از .env
├── requirements.txt        # کتابخانه‌های Python
├── .env.example            # نمونه فایل تنظیمات
├── bot/
│   ├── handlers/
│   │   ├── admin.py        # هندلرهای ادمین
│   │   └── user.py         # هندلرهای کاربر
│   ├── keyboards.py        # کیبوردهای اینلاین و ریپلای
│   ├── messages.py         # متون پیام‌ها
│   └── middlewares.py      # میدلویرها
├── database/
│   └── db.py               # عملیات SQLite
├── services/
│   ├── xui_client.py       # کلاینت API پنل
│   └── subscription.py     # ایجاد/تمدید سرویس
└── utils/
    └── helpers.py          # توابع کمکی
```

---

## 🔄 دستورات مدیریت سریع

```bash
# وضعیت ربات
systemctl status bananabot

# شروع / توقف / ریستارت
systemctl start bananabot
systemctl stop bananabot
systemctl restart bananabot

# مشاهده لاگ زنده
journalctl -u bananabot -f

# لاگ آخرین اجرا
journalctl -u bananabot -n 100 --no-pager
```

---

## 📝 نکات مهم

- برای **On-Hold** (فعال شدن پس از اولین اتصال)، هنگام افزودن پنل فیلد `on_hold` را فعال کنید.
- فایل `.env` پس از نصب فقط توسط `root` قابل خواندن است (chmod 600).
- پایگاه داده SQLite در مسیر `data/bot.db` ذخیره می‌شود.
- قبل از به‌روزرسانی از طریق `manage.sh`، یک نسخه پشتیبان از `data/` بگیرید.

---

## 📄 مجوز

MIT License — آزاد برای استفاده شخصی و تجاری.
