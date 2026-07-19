"""Application entry point."""

import asyncio
import logging
import sqlite3
import sys
import time
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BufferedInputFile, MenuButtonWebApp, WebAppInfo

from bot.handlers import admin_router, user_router
from bot.middlewares import UserMiddleware
from config import get_settings
from database import get_db
from services.subscription import SubscriptionService
from services.xui_client import XUIClient, XUIError
from utils.helpers import format_expiry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

PAYMENT_EXPIRY_CHECK_INTERVAL_SECONDS = 60


async def _expire_payments_loop(bot: Bot, db):
    """Auto-payments (card-to-card top-ups matched via bank SMS) are only
    valid for a 20-minute window (see bot/handlers/user.py, where that
    window is set at creation time). This periodically cancels any that
    ran out the clock without a matching SMS ever arriving, and lets the
    user know instead of leaving them wondering why their balance never
    got topped up."""
    while True:
        try:
            expired = await db.expire_stale_payments()
            for payment in expired:
                user = await db._fetchone(
                    "SELECT telegram_id FROM users WHERE id = ?", (payment["user_id"],)
                )
                if user and user.get("telegram_id"):
                    try:
                        await bot.send_message(
                            user["telegram_id"],
                            "⏰ مهلت ۲۰ دقیقه‌ای این پرداخت به پایان رسید و درخواست به‌صورت خودکار لغو شد.\n\n"
                            "اگر مبلغ را واریز کرده‌اید ولی موجودی شما شارژ نشد، لطفاً با پشتیبانی تماس بگیرید. "
                            "در غیر این صورت می‌توانید از منوی اصلی دوباره اقدام کنید.",
                        )
                    except Exception:
                        pass  # bot blocked by user, etc. — not fatal
        except Exception:
            logger.exception("Payment expiry loop failed")
        await asyncio.sleep(PAYMENT_EXPIRY_CHECK_INTERVAL_SECONDS)


EXPIRY_REMINDER_CHECK_INTERVAL_SECONDS = 30 * 60
AUTO_RENEW_CHECK_INTERVAL_SECONDS = 15 * 60
BACKUP_SCHEDULE_CHECK_INTERVAL_SECONDS = 15 * 60


async def _expiry_reminder_loop(bot: Bot, db):
    """به کاربران و نمایندگانی که سرویس/نمایندگی‌شان رو به انقضاست
    (و هنوز یادآوری نگرفته‌اند) یک پیام یادآوری می‌فرستد. هر بار که سرویس
    تمدید بشه، پرچم یادآوری خودکار ریست می‌شه (نگاه کن به
    update_subscription/update_reseller در database/db.py) پس این حلقه
    برای هر دوره‌ی انقضا فقط یک‌بار پیام می‌فرسته."""
    while True:
        try:
            if await db.get_setting("expiry_reminder_enabled", "1") == "1":
                try:
                    days_before = int(await db.get_setting("expiry_reminder_days_before", "3"))
                except ValueError:
                    days_before = 3

                subs = await db.get_subscriptions_due_for_reminder(days_before)
                for sub in subs:
                    try:
                        await bot.send_message(
                            sub["telegram_id"],
                            f"⏰ سرویس «{sub['email']}» شما تا {format_expiry(sub['expiry_time'])} "
                            "منقضی می‌شود. برای جلوگیری از قطعی، از منوی «سرویس‌های من» تمدید کنید.",
                        )
                    except Exception:
                        pass
                    await db.mark_subscription_reminder_sent(sub["id"])

                resellers = await db.get_resellers_due_for_reminder(days_before)
                for r in resellers:
                    try:
                        days_left = max(0, (r["expires_at"] - int(time.time())) // 86400)
                        await bot.send_message(
                            r["telegram_id"],
                            f"⏰ نمایندگی شما تا {days_left} روز دیگر منقضی می‌شود. "
                            "برای جلوگیری از قطعی سرویس مشتریانتان، از پنل نمایندگی تمدید کنید.",
                        )
                    except Exception:
                        pass
                    await db.mark_reseller_reminder_sent(r["id"])
        except Exception:
            logger.exception("Expiry reminder loop failed")
        await asyncio.sleep(EXPIRY_REMINDER_CHECK_INTERVAL_SECONDS)


async def _auto_renew_loop(bot: Bot, db):
    """سرویس‌هایی که کاربر تمدید خودکار را روشن کرده و الان منقضی شده‌اند
    را، در صورت کافی بودن موجودی کیف پول، خودکار تمدید می‌کند — دقیقاً با
    همان منطق تمدید دستی (renew_subscription + کسر موجودی + ثبت سفارش).
    اگر موجودی کافی نبود یا محصول دیگر موجود نبود، تمدید خودکار را برای آن
    سرویس خاموش می‌کند و یک‌بار به کاربر اطلاع می‌دهد — نه اینکه هر ۱۵
    دقیقه دوباره تلاش کند و کاربر را با پیام‌های تکراری اذیت کند."""
    sub_service = SubscriptionService()
    while True:
        try:
            due = await db.get_subscriptions_due_for_auto_renew()
            for sub in due:
                price = sub.get("product_price")
                if not sub.get("product_is_active") or price is None:
                    await db.set_subscription_auto_renew(sub["id"], False)
                    try:
                        await bot.send_message(
                            sub["telegram_id"],
                            f"⚠️ تمدید خودکار سرویس «{sub['email']}» ممکن نشد (محصول مرتبط دیگر موجود نیست) "
                            "و خاموش شد. لطفاً به‌صورت دستی تمدید کنید.",
                        )
                    except Exception:
                        pass
                    continue

                if sub["user_balance"] < price:
                    await db.set_subscription_auto_renew(sub["id"], False)
                    try:
                        await bot.send_message(
                            sub["telegram_id"],
                            f"⚠️ تمدید خودکار سرویس «{sub['email']}» به‌دلیل موجودی ناکافی انجام نشد "
                            f"(موجودی: {sub['user_balance']:,} / هزینه تمدید: {price:,} تومان) و خاموش شد. "
                            "لطفاً کیف پول را شارژ کرده و دوباره روشنش کنید.",
                        )
                    except Exception:
                        pass
                    continue

                try:
                    result = await sub_service.renew_subscription(
                        sub["id"], sub["product_duration_days"], sub["product_volume_gb"]
                    )
                    await db.update_user_balance(sub["user_id"], -price)
                    await db.create_order(
                        sub["user_id"], sub["product_id"], price, "balance",
                        f"تمدید خودکار {sub.get('product_name') or ''} (سرویس #{sub['id']})",
                    )
                    try:
                        await bot.send_message(
                            sub["telegram_id"],
                            f"🔁 سرویس «{sub['email']}» شما به‌صورت خودکار تمدید شد.\n"
                            f"📊 حجم: {result['volume_gb']} GB\n"
                            f"⏱ انقضای جدید: {format_expiry(result['expiry_time'])}\n"
                            f"💳 {price:,} تومان از کیف پول شما کسر شد.",
                        )
                    except Exception:
                        pass
                except Exception:
                    logger.exception("Auto-renew failed for subscription #%s", sub["id"])
        except Exception:
            logger.exception("Auto-renew loop failed")
        await asyncio.sleep(AUTO_RENEW_CHECK_INTERVAL_SECONDS)


def _safe_sqlite_backup(src_path: str, dest_path: str):
    """کپی امن یک دیتابیس sqlite در حال استفاده (با WAL) — دقیقاً همون
    مکانیزم .backup که manage.sh هم برای بکاپ سمت سرور استفاده می‌کنه،
    نه یک `cp` خام که ممکنه وسط نوشتن یه تراکنش بگیردش."""
    src = sqlite3.connect(src_path)
    try:
        dest = sqlite3.connect(dest_path)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()


async def _scheduled_backup_loop(bot: Bot, db):
    """طبق فاصله‌ی زمانی تنظیم‌شده توسط ادمین، از دیتابیس خود ربات و از
    دیتابیس هر پنل X-UI بکاپ می‌گیره، توی data/backups (با پیشوند auto_
    که جدا از بکاپ‌های دستی manage.sh باشه، ولی همچنان با الگوی bot_*.db
    سازگاره تا از طریق منوی ریستور manage.sh هم قابل انتخاب باشه) ذخیره
    می‌کنه، برای همه‌ی ادمین‌ها توی تلگرام می‌فرسته، و بکاپ‌های خودکار
    قدیمی‌تر از حد نگه‌داری رو پاک می‌کنه."""
    admin_ids = get_settings().admin_ids
    while True:
        try:
            if await db.get_setting("backup_schedule_enabled", "0") == "1":
                try:
                    interval_hours = float(await db.get_setting("backup_schedule_interval_hours", "24"))
                except ValueError:
                    interval_hours = 24.0
                try:
                    last_run = float(await db.get_setting("backup_last_run_at", "0"))
                except ValueError:
                    last_run = 0.0

                now = time.time()
                if now - last_run >= interval_hours * 3600:
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    backups_dir = Path(db.path).parent / "backups"
                    backups_dir.mkdir(parents=True, exist_ok=True)

                    bot_backup_path = backups_dir / f"bot_auto_{ts}.db"
                    try:
                        await asyncio.to_thread(_safe_sqlite_backup, db.path, str(bot_backup_path))
                        with open(bot_backup_path, "rb") as f:
                            bot_backup_bytes = f.read()
                        for admin_id in admin_ids:
                            try:
                                await bot.send_document(
                                    admin_id,
                                    BufferedInputFile(bot_backup_bytes, filename=bot_backup_path.name),
                                    caption=f"🗄 بکاپ خودکار دیتابیس ربات — {ts}",
                                )
                            except Exception:
                                pass
                    except Exception:
                        logger.exception("Scheduled bot.db backup failed")

                    panels = await db.get_panels(active_only=False)
                    for panel in panels:
                        try:
                            client = XUIClient(panel["url"], panel["api_token"])
                            xui_bytes = await client.get_db_backup()
                        except XUIError as e:
                            logger.warning("XUI backup unavailable for panel '%s': %s", panel["name"], e)
                            continue
                        except Exception:
                            logger.exception("XUI backup failed for panel '%s'", panel["name"])
                            continue
                        xui_dir = backups_dir / "xui"
                        xui_dir.mkdir(parents=True, exist_ok=True)
                        safe_name = "".join(c if c.isalnum() else "_" for c in panel["name"])
                        xui_backup_path = xui_dir / f"xui_{safe_name}_{ts}.db"
                        try:
                            with open(xui_backup_path, "wb") as f:
                                f.write(xui_bytes)
                        except Exception:
                            logger.exception("Could not save XUI backup file for panel '%s'", panel["name"])
                            continue
                        for admin_id in admin_ids:
                            try:
                                await bot.send_document(
                                    admin_id,
                                    BufferedInputFile(xui_bytes, filename=xui_backup_path.name),
                                    caption=f"🗄 بکاپ خودکار پنل «{panel['name']}» — {ts}",
                                )
                            except Exception:
                                pass

                    # retention: keep only the newest N auto-backups of each kind
                    try:
                        retention = int(await db.get_setting("backup_schedule_retention_count", "14"))
                    except ValueError:
                        retention = 14
                    for pattern, directory in (
                        ("bot_auto_*.db", backups_dir),
                        ("xui_*.db", backups_dir / "xui"),
                    ):
                        if not directory.exists():
                            continue
                        files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
                        for old_file in files[retention:]:
                            try:
                                old_file.unlink()
                            except Exception:
                                pass

                    await db.set_setting("backup_last_run_at", str(int(now)))
        except Exception:
            logger.exception("Scheduled backup loop failed")
        await asyncio.sleep(BACKUP_SCHEDULE_CHECK_INTERVAL_SECONDS)


async def main():
    settings = get_settings()
    if not settings.bot_token or settings.bot_token == "your_bot_token_here":
        logger.error("BOT_TOKEN is not set. Copy .env.example to .env and configure it.")
        sys.exit(1)

    if not settings.admin_ids:
        logger.warning("ADMIN_IDS is empty — no admin access configured.")

    db = get_db()
    await db.init()
    logger.info("Database initialized.")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    user_middleware = UserMiddleware()
    dp.message.middleware(user_middleware)
    dp.callback_query.middleware(user_middleware)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    # Save the bot's own username so the web panel's "Login with Telegram"
    # widget (which needs data-telegram-login=<username>) always has it,
    # without requiring the admin to enter it manually anywhere.
    me = await bot.get_me()
    await db.set_setting("bot_username", me.username or "")
    logger.info(f"Bot username: @{me.username}")

    # The bot prefers CARD_NUMBER/CARD_HOLDER from .env over the DB setting
    # (see bot/handlers/user.py: `settings.card_number or await db.get_setting(...)`),
    # but the web panel has no access to this process's .env and only ever
    # reads the DB `settings` table. Without this sync, an admin who set the
    # card via install.sh/manage.sh would see deposits work fine in the bot
    # while the web panel's wallet page kept showing "not configured yet".
    if settings.card_number:
        await db.set_setting("card_number", settings.card_number)
    if settings.card_holder:
        await db.set_setting("card_holder", settings.card_holder)

    # Register the Mini App (Web App) button in Telegram's chat menu, so the
    # panel can be opened directly from the bot's chat, not just a browser.
    # Telegram only accepts HTTPS URLs for web_app menu buttons.
    panel_url = settings.panel_url.strip()
    if panel_url.startswith("https://"):
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="پنل وب", web_app=WebAppInfo(url=panel_url))
            )
            logger.info(f"Web App menu button registered: {panel_url}")
        except Exception as exc:
            logger.warning(f"Could not register Web App menu button: {exc}")
    elif panel_url:
        logger.warning(
            "PANEL_URL is set but is not HTTPS — Telegram Web Apps require HTTPS. "
            "The web panel button will not be shown in Telegram."
        )

    logger.info("Bot starting...")
    asyncio.create_task(_expire_payments_loop(bot, db))
    asyncio.create_task(_expiry_reminder_loop(bot, db))
    asyncio.create_task(_auto_renew_loop(bot, db))
    asyncio.create_task(_scheduled_backup_loop(bot, db))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
