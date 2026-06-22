"""Subscription provisioning service."""

import json
import logging

from database import get_db
from services.xui_client import (
    XUIClient,
    XUIError,
    compute_expiry_ms,
    generate_client_email,
    generate_sub_id,
)

logger = logging.getLogger(__name__)


class SubscriptionService:
    def __init__(self):
        self.db = get_db()

    async def create_from_product(
        self,
        user_id: int,
        telegram_id: int,
        product: dict,
        is_trial: bool = False,
    ) -> dict:
        panel = await self.db.get_panel(product["panel_id"])
        if not panel:
            raise ValueError("پنل مرتبط با محصول پیدا نشد")

        inbound_ids = __import__("json").loads(panel["inbound_ids"])
        if not inbound_ids:
            raise ValueError("Inbound برای پنل تنظیم نشده")

        client = XUIClient(panel["url"], panel["api_token"])
        email = generate_client_email(telegram_id)
        sub_id = generate_sub_id()
        on_hold = bool(panel.get("on_hold", 0))
        expiry_ms = compute_expiry_ms(
            product["duration_days"], on_hold=on_hold
        )
        volume_gb = product["volume_gb"]

        try:
            await client.add_client(
                email=email,
                inbound_ids=inbound_ids,
                total_gb=volume_gb,
                expiry_time_ms=expiry_ms,
                sub_id=sub_id,
                comment=f"bot_user_{telegram_id}",
                tg_id=telegram_id,
                on_hold=on_hold,
            )
        except XUIError as e:
            logger.error("Failed to create client on panel: %s", e)
            raise ValueError(f"خطا در ایجاد کانفیگ روی پنل: {e}") from e

        links = await client.get_client_links(email)
        config_link = links[0] if links else ""
        sub_link = self._build_sub_link(panel, sub_id)

        sub_db_id = await self.db.add_subscription(
            user_id=user_id,
            product_id=product["id"],
            panel_id=panel["id"],
            email=email,
            sub_id=sub_id,
            volume_gb=volume_gb,
            expiry_time=expiry_ms,
            config_link=config_link,
            config_links=json.dumps(links),
            sub_link=sub_link,
            is_trial=1 if is_trial else 0,
        )

        return {
            "id": sub_db_id,
            "email": email,
            "sub_id": sub_id,
            "config_link": config_link,
            "config_links": links,
            "sub_link": sub_link,
            "volume_gb": volume_gb,
            "duration_days": product["duration_days"],
        }

    @staticmethod
    def _build_sub_link(panel: dict, sub_id: str) -> str:
        template = panel.get("sub_link_template") or ""
        if not template:
            return ""
        try:
            return template.format(sub_id=sub_id)
        except (KeyError, IndexError):
            return ""

    async def refresh_links(self, subscription_id: int) -> dict:
        sub = await self.db.get_subscription(subscription_id)
        if not sub:
            raise ValueError("سرویس پیدا نشد")

        client = XUIClient(sub["panel_url"], sub["api_token"])
        links = await client.get_client_links(sub["email"])
        config_link = links[0] if links else sub.get("config_link", "")

        sub_link = sub.get("sub_link", "")
        if sub.get("sub_id"):
            rebuilt = self._build_sub_link(sub, sub["sub_id"])
            if rebuilt:
                sub_link = rebuilt

        await self.db.update_subscription(
            subscription_id,
            config_link=config_link,
            config_links=json.dumps(links),
            sub_link=sub_link,
        )
        return {"config_link": config_link, "config_links": links, "sub_link": sub_link}

    async def get_usage(self, subscription_id: int) -> dict:
        sub = await self.db.get_subscription(subscription_id)
        if not sub:
            raise ValueError("سرویس پیدا نشد")

        client = XUIClient(sub["panel_url"], sub["api_token"])
        traffic = await client.get_client_traffic(sub["email"])
        up = traffic.get("up", 0)
        down = traffic.get("down", 0)
        total = traffic.get("total", 0)
        used_gb = (up + down) / (1024 ** 3)
        total_gb = total / (1024 ** 3) if total > 0 else sub["volume_gb"]

        return {
            "up": up,
            "down": down,
            "used_gb": round(used_gb, 2),
            "total_gb": round(total_gb, 2) if total_gb else sub["volume_gb"],
            "expiry_time": traffic.get("expiryTime", sub.get("expiry_time", 0)),
        }

    async def renew_subscription(
        self,
        subscription_id: int,
        extra_days: int,
        extra_gb: float = 0,
    ) -> dict:
        sub = await self.db.get_subscription(subscription_id)
        if not sub:
            raise ValueError("سرویس پیدا نشد")

        panel = await self.db.get_panel(sub["panel_id"])
        client = XUIClient(sub["panel_url"], sub["api_token"])

        try:
            client_data = await client.get_client(sub["email"])
        except XUIError as e:
            raise ValueError(f"خطا در دریافت اطلاعات سرویس از پنل: {e}") from e
        if not client_data:
            raise ValueError("کلاینت روی پنل پیدا نشد")

        on_hold = bool(panel and panel.get("on_hold", 0))

        # زمان انقضا از الان حساب می‌شه (ریست کامل)
        new_expiry_ms = compute_expiry_ms(extra_days, on_hold=on_hold)

        # حجم جدید بر اساس پلن تمدیدی (ریست کامل)
        product_volume = extra_gb if extra_gb > 0 else sub["volume_gb"]
        new_total_bytes = int(product_volume * (1024 ** 3))

        update_payload = {
            **client_data,
            "email": sub["email"],
            "expiryTime": new_expiry_ms,
            "totalGB": new_total_bytes,
            "enable": True,
        }

        try:
            await client.update_client(sub["email"], update_payload)
        except XUIError as e:
            raise ValueError(f"خطا در تمدید سرویس روی پنل: {e}") from e

        # ریست ترافیک مصرفی روی پنل
        try:
            await client.reset_client_traffic(sub["email"])
        except XUIError as e:
            logger.warning("reset_client_traffic failed (non-fatal): %s", e)

        new_volume_gb = product_volume
        await self.db.update_subscription(
            subscription_id,
            expiry_time=new_expiry_ms,
            volume_gb=new_volume_gb,
            status="active",
        )

        return {
            "id": subscription_id,
            "email": sub["email"],
            "volume_gb": new_volume_gb,
            "expiry_time": new_expiry_ms,
            "added_gb": extra_gb,
            "added_days": extra_days,
        }

    async def delete_subscription(self, subscription_id: int):
        sub = await self.db.get_subscription(subscription_id)
        if not sub:
            return

        xui = XUIClient(sub["panel_url"], sub["api_token"])
        try:
            await xui.delete_client(sub["email"])
        except XUIError as e:
            logger.warning("Panel delete failed: %s", e)

        await self.db.update_subscription(subscription_id, status="deleted")
