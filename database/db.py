import asyncio
import json
import logging

import aiosqlite
from pathlib import Path

from config import get_settings
from db_schema import DEFAULT_SETTINGS, reconcile  # noqa: F401 (DEFAULT_SETTINGS kept for anything importing it from here)

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, path: str | None = None):
        settings = get_settings()
        self.path = path or settings.database_path
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    async def connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        return conn

    async def init(self):
        # reconcile() is plain sync sqlite3 (see db_schema.py for why), so
        # it's run in a worker thread to avoid blocking the event loop.
        # It creates any missing tables/columns — including ones added in
        # a newer version of the code than whatever data/bot.db currently
        # has (e.g. right after restoring an older backup) — so the bot
        # never crashes on a stale schema.
        report = await asyncio.to_thread(reconcile, self.path)
        if report["tables_created"] or report["columns_added"]:
            logger.info(
                "Database schema updated — tables created: %s, columns added: %s",
                report["tables_created"], report["columns_added"],
            )

    async def _fetchone(self, query: str, params: tuple = ()) -> dict | None:
        conn = await self.connect()
        try:
            cursor = await conn.execute(query, params)
            row = await cursor.fetchone()
            return dict(row) if row else None
        finally:
            await conn.close()

    async def _fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        conn = await self.connect()
        try:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def _execute(self, query: str, params: tuple = ()) -> int:
        conn = await self.connect()
        try:
            cursor = await conn.execute(query, params)
            await conn.commit()
            return cursor.lastrowid or 0
        finally:
            await conn.close()

    # --- Users ---
    async def get_or_create_user(
        self, telegram_id: int, username: str | None, full_name: str | None
    ) -> dict:
        user = await self._fetchone(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        if user:
            if username and user["username"] != username:
                await self._execute(
                    "UPDATE users SET username = ? WHERE id = ?",
                    (username, user["id"]),
                )
                user["username"] = username
            return user
        uid = await self._execute(
            "INSERT INTO users (telegram_id, username, full_name) VALUES (?, ?, ?)",
            (telegram_id, username or "", full_name or ""),
        )
        return await self._fetchone("SELECT * FROM users WHERE id = ?", (uid,))

    async def get_user_by_telegram_id(self, telegram_id: int) -> dict | None:
        return await self._fetchone(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )

    async def update_user_balance(self, user_id: int, amount: int) -> int:
        await self._execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (amount, user_id),
        )
        user = await self._fetchone("SELECT balance FROM users WHERE id = ?", (user_id,))
        return user["balance"] if user else 0

    async def set_user_banned(self, user_id: int, banned: bool):
        await self._execute(
            "UPDATE users SET is_banned = ? WHERE id = ?",
            (1 if banned else 0, user_id),
        )

    async def set_user_phone(self, user_id: int, phone: str):
        await self._execute(
            "UPDATE users SET phone = ? WHERE id = ?", (phone, user_id)
        )

    async def get_all_users_count(self, search: str = "") -> int:
        if search:
            row = await self._fetchone(
                "SELECT COUNT(*) as c FROM users WHERE "
                "CAST(telegram_id AS TEXT) LIKE ? OR username LIKE ? OR full_name LIKE ?",
                (f"%{search}%", f"%{search}%", f"%{search}%"),
            )
        else:
            row = await self._fetchone("SELECT COUNT(*) as c FROM users")
        return row["c"] if row else 0

    async def get_users_page(self, page: int, per_page: int = 10, search: str = "") -> list[dict]:
        offset = (page - 1) * per_page
        if search:
            return await self._fetchall(
                "SELECT * FROM users WHERE "
                "CAST(telegram_id AS TEXT) LIKE ? OR username LIKE ? OR full_name LIKE ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (f"%{search}%", f"%{search}%", f"%{search}%", per_page, offset),
            )
        return await self._fetchall(
            "SELECT * FROM users ORDER BY id DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        )

    # --- Settings ---
    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self._fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str):
        await self._execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    # --- Panels ---
    async def get_panels(self, active_only: bool = True) -> list[dict]:
        if active_only:
            return await self._fetchall(
                "SELECT * FROM panels WHERE is_active = 1 ORDER BY id"
            )
        return await self._fetchall("SELECT * FROM panels ORDER BY id")

    async def get_panel(self, panel_id: int) -> dict | None:
        return await self._fetchone("SELECT * FROM panels WHERE id = ?", (panel_id,))

    async def add_panel(
        self, name: str, url: str, api_token: str, inbound_ids: str, on_hold: int = 0
    ) -> int:
        return await self._execute(
            "INSERT INTO panels (name, url, api_token, inbound_ids, on_hold) VALUES (?, ?, ?, ?, ?)",
            (name, url.rstrip("/"), api_token, inbound_ids, on_hold),
        )

    async def update_panel(self, panel_id: int, **fields):
        allowed = {"name", "url", "api_token", "inbound_ids", "on_hold", "is_active", "sub_link_template"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        cols = ", ".join(f"{k} = ?" for k in updates)
        await self._execute(
            f"UPDATE panels SET {cols} WHERE id = ?",
            (*updates.values(), panel_id),
        )

    async def delete_panel(self, panel_id: int):
        await self._execute("DELETE FROM panels WHERE id = ?", (panel_id,))

    # --- Products ---
    async def get_products(self, active_only: bool = True, trial: bool | None = None) -> list[dict]:
        query = "SELECT p.*, pn.name as panel_name FROM products p JOIN panels pn ON p.panel_id = pn.id"
        conditions = []
        if active_only:
            conditions.append("p.is_active = 1")
        if trial is not None:
            conditions.append(f"p.is_trial = {1 if trial else 0}")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY p.price"
        return await self._fetchall(query)

    async def get_product(self, product_id: int) -> dict | None:
        return await self._fetchone(
            "SELECT p.*, pn.name as panel_name, pn.url as panel_url, "
            "pn.api_token, pn.inbound_ids, pn.on_hold "
            "FROM products p JOIN panels pn ON p.panel_id = pn.id "
            "WHERE p.id = ?",
            (product_id,),
        )

    async def add_product(
        self,
        name: str,
        panel_id: int,
        volume_gb: float,
        duration_days: int,
        price: int,
        is_trial: int = 0,
        description: str = "",
    ) -> int:
        return await self._execute(
            "INSERT INTO products (name, panel_id, volume_gb, duration_days, price, is_trial, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, panel_id, volume_gb, duration_days, price, is_trial, description),
        )

    async def update_product(self, product_id: int, **fields):
        allowed = {
            "name", "panel_id", "volume_gb", "duration_days",
            "price", "is_trial", "is_active", "description",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        cols = ", ".join(f"{k} = ?" for k in updates)
        await self._execute(
            f"UPDATE products SET {cols} WHERE id = ?",
            (*updates.values(), product_id),
        )

    async def delete_product(self, product_id: int):
        await self._execute("DELETE FROM products WHERE id = ?", (product_id,))

    # --- Subscriptions ---
    async def add_subscription(self, **data) -> int:
        return await self._execute(
            "INSERT INTO subscriptions "
            "(user_id, product_id, panel_id, email, sub_id, volume_gb, expiry_time, "
            "config_link, config_links, sub_link, status, is_trial) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["user_id"],
                data.get("product_id"),
                data["panel_id"],
                data["email"],
                data.get("sub_id", ""),
                data["volume_gb"],
                data.get("expiry_time", 0),
                data.get("config_link", ""),
                data.get("config_links", "[]"),
                data.get("sub_link", ""),
                data.get("status", "active"),
                data.get("is_trial", 0),
            ),
        )

    async def get_user_subscriptions(self, user_id: int) -> list[dict]:
        return await self._fetchall(
            "SELECT s.*, pn.name as panel_name, pn.url as panel_url, pn.api_token "
            "FROM subscriptions s JOIN panels pn ON s.panel_id = pn.id "
            "WHERE s.user_id = ? ORDER BY s.created_at DESC",
            (user_id,),
        )

    async def get_subscription(self, sub_id: int) -> dict | None:
        return await self._fetchone(
            "SELECT s.*, pn.name as panel_name, pn.url as panel_url, "
            "pn.api_token, pn.inbound_ids, pn.sub_link_template "
            "FROM subscriptions s JOIN panels pn ON s.panel_id = pn.id "
            "WHERE s.id = ?",
            (sub_id,),
        )

    async def update_subscription(self, sub_id: int, **fields):
        allowed = {
            "config_link", "config_links", "sub_link", "status", "expiry_time",
            "volume_gb", "email", "sub_id",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        cols = ", ".join(f"{k} = ?" for k in updates)
        await self._execute(
            f"UPDATE subscriptions SET {cols} WHERE id = ?",
            (*updates.values(), sub_id),
        )

    async def user_has_trial(self, user_id: int) -> bool:
        row = await self._fetchone(
            "SELECT COUNT(*) as c FROM subscriptions WHERE user_id = ? AND is_trial = 1",
            (user_id,),
        )
        return (row["c"] if row else 0) > 0

    async def get_active_subscriptions_count(self) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) as c FROM subscriptions WHERE status = 'active'"
        )
        return row["c"] if row else 0

    # --- Orders ---
    async def create_order(
        self, user_id: int, product_id: int | None, amount: int,
        payment_method: str, description: str = "",
    ) -> tuple[int, str]:
        import random
        import string
        code = "".join(random.choices(string.digits, k=8))
        oid = await self._execute(
            "INSERT INTO orders (user_id, product_id, order_code, amount, payment_method, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, product_id, code, amount, payment_method, description),
        )
        return oid, code

    async def get_order(self, order_id: int) -> dict | None:
        return await self._fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))

    async def get_order_by_code(self, code: str) -> dict | None:
        return await self._fetchone(
            "SELECT * FROM orders WHERE order_code = ?", (code,)
        )

    async def update_order_status(self, order_id: int, status: str):
        await self._execute(
            "UPDATE orders SET status = ? WHERE id = ?", (status, order_id)
        )

    # --- Payments ---
    async def get_latest_unreceipted_pending_payment(self, user_id: int) -> dict | None:
        """The user's most recent pending payment with no receipt uploaded
        yet — i.e. they picked card-to-card (for a deposit, a purchase, or
        a renewal) and haven't sent a photo of the receipt. Used to find
        what to cancel if they back out instead of paying."""
        return await self._fetchone(
            "SELECT * FROM payments WHERE user_id = ? AND status = 'pending' "
            "AND receipt_file_id IS NULL ORDER BY id DESC LIMIT 1",
            (user_id,),
        )

    async def cancel_payment_if_unreceipted(self, payment_id: int) -> bool:
        """Cancels a payment, but ONLY if it's still pending and has no
        receipt attached — never touches one a receipt has already been
        sent for (that must go through normal admin approve/reject)."""
        conn = await self.connect()
        try:
            cursor = await conn.execute(
                "UPDATE payments SET status = 'cancelled' WHERE id = ? "
                "AND status = 'pending' AND receipt_file_id IS NULL",
                (payment_id,),
            )
            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await conn.close()

    async def create_payment(
        self, user_id: int, amount: int, payment_method: str = "card",
        order_id: int | None = None, receipt_file_id: str | None = None,
        product_id: int | None = None, renew_sub_id: int | None = None,
        expected_amount: int | None = None, expires_at: str | None = None,
        reseller_plan_id: int | None = None,
    ) -> int:
        return await self._execute(
            "INSERT INTO payments (user_id, order_id, product_id, renew_sub_id, reseller_plan_id, "
            "amount, payment_method, receipt_file_id, expected_amount, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, order_id, product_id, renew_sub_id, reseller_plan_id, amount, payment_method,
             receipt_file_id, expected_amount, expires_at),
        )

    async def expected_amount_taken(self, expected_amount: int) -> bool:
        """Used while generating the random 3-digit verification code, to
        avoid handing two different users the same exact amount to pay at
        the same time (which would make the SMS webhook unable to tell
        who paid)."""
        row = await self._fetchone(
            "SELECT 1 FROM payments WHERE expected_amount = ? AND status = 'pending'",
            (expected_amount,),
        )
        return row is not None

    async def get_payment_by_expected_amount(self, expected_amount: int) -> dict | None:
        """Finds the (single) pending, not-yet-expired auto-payment whose
        verification amount matches what showed up in a bank SMS."""
        return await self._fetchone(
            "SELECT * FROM payments WHERE expected_amount = ? AND status = 'pending' "
            "AND (expires_at IS NULL OR expires_at > datetime('now')) "
            "ORDER BY id DESC LIMIT 1",
            (expected_amount,),
        )

    async def expire_stale_payments(self) -> list[dict]:
        """Marks pending auto-payments whose 20-minute window has passed as
        'expired', and returns the rows that were just expired so the
        caller can notify each user. Payments without an expiry (manual
        receipt-based ones) are never touched."""
        conn = await self.connect()
        try:
            cursor = await conn.execute(
                "SELECT * FROM payments WHERE status = 'pending' "
                "AND expires_at IS NOT NULL AND expires_at <= datetime('now')"
            )
            rows = await cursor.fetchall()
            expired = [dict(r) for r in rows]
            if expired:
                await conn.execute(
                    "UPDATE payments SET status = 'expired' WHERE status = 'pending' "
                    "AND expires_at IS NOT NULL AND expires_at <= datetime('now')"
                )
                await conn.commit()
            return expired
        finally:
            await conn.close()

    async def approve_payment_auto(self, payment_id: int) -> dict | None:
        """Atomically approve a payment matched by the SMS webhook and
        credit the user's balance — mirrors what admin approval does, but
        only acts if the payment is still pending (safe against a human
        admin approving/rejecting it at the same moment). Returns the
        updated payment row on success, or None if it was no longer
        pending by the time this ran."""
        conn = await self.connect()
        try:
            cursor = await conn.execute(
                "UPDATE payments SET status = 'approved', admin_note = 'تایید خودکار (پیامک بانکی)' "
                "WHERE id = ? AND status = 'pending'",
                (payment_id,),
            )
            if cursor.rowcount == 0:
                await conn.commit()
                return None
            fetch_cursor = await conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
            payment_row = await fetch_cursor.fetchone()
            payment = dict(payment_row)
            await conn.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?",
                (payment["amount"], payment["user_id"]),
            )
            await conn.commit()
            return payment
        finally:
            await conn.close()

    async def get_payment(self, payment_id: int) -> dict | None:
        return await self._fetchone("SELECT * FROM payments WHERE id = ?", (payment_id,))

    async def get_pending_payments(self) -> list[dict]:
        return await self._fetchall(
            "SELECT py.*, u.telegram_id, u.username "
            "FROM payments py JOIN users u ON py.user_id = u.id "
            "WHERE py.status = 'pending' ORDER BY py.created_at"
        )

    async def update_payment(self, payment_id: int, status: str, admin_note: str = ""):
        await self._execute(
            "UPDATE payments SET status = ?, admin_note = ? WHERE id = ?",
            (status, admin_note, payment_id),
        )

    async def claim_payment(self, payment_id: int, status: str, admin_id: int) -> bool:
        """Atomically move a payment from 'pending' to status, recording who claimed it.

        Returns False if the payment was no longer pending (i.e. another admin
        already approved/rejected it) — callers must not act on the payment
        again in that case. This is what makes multi-admin approval race-safe.
        """
        conn = await self.connect()
        try:
            cursor = await conn.execute(
                "UPDATE payments SET status = ?, handled_by = ? WHERE id = ? AND status = 'pending'",
                (status, admin_id, payment_id),
            )
            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await conn.close()

    async def get_payment_notif_chats(self, payment_id: int) -> list[dict]:
        row = await self._fetchone(
            "SELECT notif_chats FROM payments WHERE id = ?", (payment_id,)
        )
        if not row or not row.get("notif_chats"):
            return []
        try:
            return json.loads(row["notif_chats"])
        except (json.JSONDecodeError, TypeError):
            return []

    async def set_payment_notif_chats(self, payment_id: int, chats: list[dict]):
        await self._execute(
            "UPDATE payments SET notif_chats = ? WHERE id = ?",
            (json.dumps(chats), payment_id),
        )

    async def append_payment_notif_chat(self, payment_id: int, chat_id: int, message_id: int):
        chats = await self.get_payment_notif_chats(payment_id)
        chats.append({"chat_id": chat_id, "message_id": message_id})
        await self.set_payment_notif_chats(payment_id, chats)

    # --- FAQ ---
    async def get_faqs(self) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM faq ORDER BY sort_order, id"
        )

    async def add_faq(self, question: str, answer: str) -> int:
        return await self._execute(
            "INSERT INTO faq (question, answer) VALUES (?, ?)", (question, answer)
        )

    async def delete_faq(self, faq_id: int):
        await self._execute("DELETE FROM faq WHERE id = ?", (faq_id,))

    # --- Tutorials ---
    async def get_tutorials(self) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM tutorials ORDER BY sort_order, id"
        )

    async def add_tutorial(self, title: str, content: str) -> int:
        return await self._execute(
            "INSERT INTO tutorials (title, content) VALUES (?, ?)", (title, content)
        )

    async def delete_tutorial(self, tutorial_id: int):
        await self._execute("DELETE FROM tutorials WHERE id = ?", (tutorial_id,))

    # --- Coupons ---
    async def add_coupon(
        self,
        code: str,
        discount_type: str,
        discount_value: int,
        usage_type: str,
        max_uses: int = 0,
        expires_at: str | None = None,
    ) -> int:
        return await self._execute(
            "INSERT INTO coupons (code, discount_type, discount_value, usage_type, max_uses, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (code.upper(), discount_type, discount_value, usage_type, max_uses, expires_at),
        )

    async def get_coupons(self) -> list[dict]:
        return await self._fetchall("SELECT * FROM coupons ORDER BY id DESC")

    async def get_coupon(self, coupon_id: int) -> dict | None:
        return await self._fetchone("SELECT * FROM coupons WHERE id = ?", (coupon_id,))

    async def get_coupon_by_code(self, code: str) -> dict | None:
        return await self._fetchone("SELECT * FROM coupons WHERE code = ?", (code.upper(),))

    async def update_coupon(self, coupon_id: int, **fields):
        allowed = {"is_active", "discount_value", "discount_type", "usage_type", "max_uses", "expires_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        cols = ", ".join(f"{k} = ?" for k in updates)
        await self._execute(
            f"UPDATE coupons SET {cols} WHERE id = ?",
            (*updates.values(), coupon_id),
        )

    async def delete_coupon(self, coupon_id: int):
        await self._execute("DELETE FROM coupon_uses WHERE coupon_id = ?", (coupon_id,))
        await self._execute("DELETE FROM coupons WHERE id = ?", (coupon_id,))

    async def validate_coupon(self, code: str, user_id: int) -> tuple[dict | None, str]:
        """
        کوپن رو اعتبارسنجی می‌کنه.
        Returns: (coupon_dict, error_message)
        اگه error_message خالی باشه یعنی کوپن معتبره.
        """
        coupon = await self.get_coupon_by_code(code)
        if not coupon:
            return None, "❌ کوپن تخفیف یافت نشد."
        if not coupon["is_active"]:
            return None, "❌ این کوپن غیرفعال است."
        if coupon["expires_at"]:
            from datetime import datetime
            try:
                exp = datetime.fromisoformat(coupon["expires_at"])
                if datetime.now() > exp:
                    return None, "❌ مدت اعتبار این کوپن به پایان رسیده است."
            except ValueError:
                pass
        if coupon["max_uses"] > 0 and coupon["used_count"] >= coupon["max_uses"]:
            return None, "❌ ظرفیت استفاده از این کوپن تکمیل شده است."
        if coupon["usage_type"] in ("once_per_user", "one_time"):
            already = await self._fetchone(
                "SELECT id FROM coupon_uses WHERE coupon_id = ? AND user_id = ?",
                (coupon["id"], user_id),
            )
            if already:
                return None, "❌ شما قبلاً از این کوپن استفاده کرده‌اید."
        return coupon, ""

    async def apply_coupon(self, coupon_id: int, user_id: int):
        """ثبت استفاده از کوپن و افزایش شمارنده."""
        await self._execute(
            "INSERT INTO coupon_uses (coupon_id, user_id) VALUES (?, ?)",
            (coupon_id, user_id),
        )
        await self._execute(
            "UPDATE coupons SET used_count = used_count + 1 WHERE id = ?",
            (coupon_id,),
        )

    def calc_discount(self, coupon: dict, price: int) -> int:
        """مبلغ تخفیف رو محاسبه می‌کنه (حداکثر برابر قیمت)."""
        if coupon["discount_type"] == "percent":
            discount = int(price * coupon["discount_value"] / 100)
        else:
            discount = coupon["discount_value"]
        return min(discount, price)


    # --- Reseller plans (defined by main admins) ---
    async def get_reseller_plans(self, active_only: bool = True) -> list[dict]:
        query = (
            "SELECT rp.*, pn.name as panel_name FROM reseller_plans rp "
            "JOIN panels pn ON rp.panel_id = pn.id"
        )
        if active_only:
            query += " WHERE rp.is_active = 1"
        query += " ORDER BY rp.price"
        return await self._fetchall(query)

    async def get_reseller_plan(self, plan_id: int) -> dict | None:
        return await self._fetchone(
            "SELECT rp.*, pn.name as panel_name, pn.url as panel_url, "
            "pn.api_token, pn.inbound_ids, pn.on_hold "
            "FROM reseller_plans rp JOIN panels pn ON rp.panel_id = pn.id "
            "WHERE rp.id = ?",
            (plan_id,),
        )

    async def add_reseller_plan(
        self, name: str, panel_id: int, volume_gb: float,
        duration_days: int, price: int, description: str = "",
    ) -> int:
        return await self._execute(
            "INSERT INTO reseller_plans (name, panel_id, volume_gb, duration_days, price, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, panel_id, volume_gb, duration_days, price, description),
        )

    async def update_reseller_plan(self, plan_id: int, **fields):
        allowed = {
            "name", "panel_id", "volume_gb", "duration_days",
            "price", "is_active", "description",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        cols = ", ".join(f"{k} = ?" for k in updates)
        await self._execute(
            f"UPDATE reseller_plans SET {cols} WHERE id = ?",
            (*updates.values(), plan_id),
        )

    async def delete_reseller_plan(self, plan_id: int):
        await self._execute("DELETE FROM reseller_plans WHERE id = ?", (plan_id,))

    # --- Resellers ---
    async def get_reseller_by_user(self, user_id: int) -> dict | None:
        return await self._fetchone(
            "SELECT r.*, pn.name as panel_name, pn.url as panel_url, pn.api_token, "
            "pn.inbound_ids, pn.on_hold, pn.sub_link_template, rp.name as plan_name "
            "FROM resellers r JOIN panels pn ON r.panel_id = pn.id "
            "LEFT JOIN reseller_plans rp ON r.plan_id = rp.id "
            "WHERE r.user_id = ?",
            (user_id,),
        )

    async def get_reseller(self, reseller_id: int) -> dict | None:
        return await self._fetchone(
            "SELECT r.*, pn.name as panel_name, pn.url as panel_url, pn.api_token, "
            "pn.inbound_ids, pn.on_hold, pn.sub_link_template, rp.name as plan_name, "
            "u.telegram_id, u.username, u.full_name "
            "FROM resellers r JOIN panels pn ON r.panel_id = pn.id "
            "JOIN users u ON r.user_id = u.id "
            "LEFT JOIN reseller_plans rp ON r.plan_id = rp.id "
            "WHERE r.id = ?",
            (reseller_id,),
        )

    async def get_all_resellers(self) -> list[dict]:
        return await self._fetchall(
            "SELECT r.*, u.telegram_id, u.username, u.full_name, rp.name as plan_name "
            "FROM resellers r JOIN users u ON r.user_id = u.id "
            "LEFT JOIN reseller_plans rp ON r.plan_id = rp.id "
            "ORDER BY r.id DESC"
        )

    async def create_or_renew_reseller(
        self, user_id: int, plan_id: int, panel_id: int,
        quota_gb: float, expires_at: int,
    ) -> int:
        """درخواست خرید/تمدید پنل نمایندگی: اگه نماینده از قبل وجود داشته
        باشه، حجم/زمان/پنل/وضعیتش ریست میشه (مثل تمدید سرویس عادی)، وگرنه
        یک رکورد جدید ساخته میشه."""
        existing = await self._fetchone(
            "SELECT id FROM resellers WHERE user_id = ?", (user_id,)
        )
        if existing:
            await self._execute(
                "UPDATE resellers SET plan_id = ?, panel_id = ?, quota_gb = ?, "
                "expires_at = ?, status = 'active' WHERE id = ?",
                (plan_id, panel_id, quota_gb, expires_at, existing["id"]),
            )
            return existing["id"]
        return await self._execute(
            "INSERT INTO resellers (user_id, plan_id, panel_id, quota_gb, expires_at, status) "
            "VALUES (?, ?, ?, ?, ?, 'active')",
            (user_id, plan_id, panel_id, quota_gb, expires_at),
        )

    async def set_reseller_status(self, reseller_id: int, status: str):
        await self._execute(
            "UPDATE resellers SET status = ? WHERE id = ?", (status, reseller_id)
        )

    async def get_reseller_used_gb(self, reseller_id: int) -> float:
        row = await self._fetchone(
            "SELECT COALESCE(SUM("
            "  CASE WHEN status = 'deleted' THEN consumed_gb ELSE volume_gb + consumed_gb END"
            "), 0) as used "
            "FROM reseller_configs WHERE reseller_id = ?",
            (reseller_id,),
        )
        return row["used"] if row else 0.0

    async def get_reseller_configs(self, reseller_id: int, include_deleted: bool = False) -> list[dict]:
        query = "SELECT * FROM reseller_configs WHERE reseller_id = ?"
        if not include_deleted:
            query += " AND status != 'deleted'"
        query += " ORDER BY id DESC"
        return await self._fetchall(query, (reseller_id,))

    async def get_reseller_configs_count(self, reseller_id: int) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) as c FROM reseller_configs WHERE reseller_id = ? AND status != 'deleted'",
            (reseller_id,),
        )
        return row["c"] if row else 0

    async def get_reseller_config(self, config_id: int) -> dict | None:
        return await self._fetchone(
            "SELECT rc.*, r.user_id, r.panel_id, r.quota_gb, r.expires_at as reseller_expires_at, "
            "r.status as reseller_status, pn.url as panel_url, pn.api_token, pn.inbound_ids, "
            "pn.sub_link_template, pn.on_hold "
            "FROM reseller_configs rc "
            "JOIN resellers r ON rc.reseller_id = r.id "
            "JOIN panels pn ON r.panel_id = pn.id "
            "WHERE rc.id = ?",
            (config_id,),
        )

    async def add_reseller_config(self, **data) -> int:
        return await self._execute(
            "INSERT INTO reseller_configs "
            "(reseller_id, label, email, sub_id, volume_gb, expiry_time, "
            "config_link, config_links, sub_link, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["reseller_id"],
                data.get("label", ""),
                data["email"],
                data.get("sub_id", ""),
                data["volume_gb"],
                data.get("expiry_time", 0),
                data.get("config_link", ""),
                data.get("config_links", "[]"),
                data.get("sub_link", ""),
                data.get("status", "active"),
            ),
        )

    async def update_reseller_config(self, config_id: int, **fields):
        allowed = {
            "label", "volume_gb", "expiry_time", "config_link",
            "config_links", "sub_link", "status", "sub_id", "consumed_gb",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        cols = ", ".join(f"{k} = ?" for k in updates)
        await self._execute(
            f"UPDATE reseller_configs SET {cols} WHERE id = ?",
            (*updates.values(), config_id),
        )


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
