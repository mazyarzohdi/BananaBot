"""Application entry point."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

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

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
