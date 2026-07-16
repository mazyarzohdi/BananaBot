"""Application entry point."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonWebApp, WebAppInfo

from bot.handlers import admin_router, user_router
from bot.middlewares import UserMiddleware
from config import get_settings
from database import get_db

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
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
