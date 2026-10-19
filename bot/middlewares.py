"""Bot middlewares."""

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import get_settings
from database import get_db

# User in-memory cache to reduce redundant get_or_create_user queries
_user_cache: dict[int, tuple[dict, float]] = {}
_USER_CACHE_TTL = 3.0  # short TTL ensures UI reflects fresh balance rapidly while eliminating burst queries


class ThrottlingMiddleware(BaseMiddleware):
    """Anti-Flood rate limiting middleware."""

    def __init__(self, rate_limit_seconds: float = 0.5):
        self.rate_limit_seconds = rate_limit_seconds
        self._user_last_action: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, (Message, CallbackQuery)) and event.from_user:
            user_id = event.from_user.id
            settings = get_settings()

            # Admins are exempt from rate limiting
            if user_id not in settings.admin_ids:
                now = time.time()
                last_time = self._user_last_action.get(user_id, 0.0)
                if now - last_time < self.rate_limit_seconds:
                    if isinstance(event, CallbackQuery):
                        try:
                            await event.answer("⚠️ لطفاً کمی با فاصله کلیک کنید...", show_alert=False)
                        except Exception:
                            pass
                    return  # Drop spam request

                self._user_last_action[user_id] = now

                # Cleanup old entries if map grows large
                if len(self._user_last_action) > 5000:
                    cutoff = now - 60.0
                    self._user_last_action = {
                        uid: ts for uid, ts in self._user_last_action.items() if ts > cutoff
                    }

        return await handler(event, data)


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, (Message, CallbackQuery)) and event.from_user:
            user_id = event.from_user.id
            username = event.from_user.username
            full_name = event.from_user.full_name
            now = time.time()

            user = None
            if user_id in _user_cache:
                cached_user, exp = _user_cache[user_id]
                if now < exp and cached_user.get("username") == username:
                    user = cached_user

            if user is None:
                db = get_db()
                user = await db.get_or_create_user(
                    user_id,
                    username,
                    full_name,
                )
                _user_cache[user_id] = (user, now + _USER_CACHE_TTL)

            data["db_user"] = user
            settings = get_settings()
            is_admin = user_id in settings.admin_ids
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