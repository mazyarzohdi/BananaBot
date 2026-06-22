"""Bot middlewares."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import get_settings
from database import get_db


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, (Message, CallbackQuery)) and event.from_user:
            db = get_db()
            user = await db.get_or_create_user(
                event.from_user.id,
                event.from_user.username,
                event.from_user.full_name,
            )
            data["db_user"] = user
            settings = get_settings()
            is_admin = event.from_user.id in settings.admin_ids
            data["is_admin"] = is_admin

            if user.get("is_banned") and not is_admin:
                block_text = "🚫 شما توسط مدیریت از استفاده از این ربات مسدود شده‌اید."
                try:
                    if isinstance(event, CallbackQuery):
                        await event.answer(block_text, show_alert=True)
                    else:
                        await event.answer(block_text)
                except Exception:
                    pass
                return  # short-circuit: banned users never reach a handler
        return await handler(event, data)
