import json

import aiosqlite
from pathlib import Path

from config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    full_name TEXT,
    phone TEXT,
    balance INTEGER DEFAULT 0,
    is_banned INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS panels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    api_token TEXT NOT NULL,
    inbound_ids TEXT NOT NULL DEFAULT '[]',
    sub_link_template TEXT DEFAULT '',
    on_hold INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    panel_id INTEGER NOT NULL,
    volume_gb REAL NOT NULL,
    duration_days INTEGER NOT NULL,
    price INTEGER NOT NULL,
    is_trial INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (panel_id) REFERENCES panels(id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_id INTEGER,
    panel_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    sub_id TEXT,
    volume_gb REAL NOT NULL,
    expiry_time INTEGER DEFAULT 0,
    config_link TEXT,
    config_links TEXT DEFAULT '[]',
    sub_link TEXT,
    status TEXT DEFAULT 'active',
    is_trial INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES products(id),
    FOREIGN KEY (panel_id) REFERENCES panels(id)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_id INTEGER,
    order_code TEXT UNIQUE NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    payment_method TEXT DEFAULT 'balance',
    description TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    order_id INTEGER,
    product_id INTEGER,
    renew_sub_id INTEGER,
    amount INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    payment_method TEXT DEFAULT 'card',
    receipt_file_id TEXT,
    admin_note TEXT,
    handled_by INTEGER,
    notif_chats TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS coupons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    discount_type TEXT NOT NULL DEFAULT 'percent',
    discount_value INTEGER NOT NULL,
    usage_type TEXT NOT NULL DEFAULT 'unlimited',
    max_uses INTEGER DEFAULT 0,
    used_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    expires_at TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS coupon_uses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coupon_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    used_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (coupon_id) REFERENCES coupons(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS faq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tutorials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0
);
"""


DEFAULT_SETTINGS = {
    "welcome_text": "سلام! به ربات فروش VPN خوش آمدید.",
    "support_text": "برای پشتیبانی با ادمین تماس بگیرید.",
    "support_username": "",
    "trial_enabled": "1",
    "trial_product_id": "0",
    "trial_panel_id": "",
    "trial_volume_gb": "1",
    "trial_duration_days": "1",
    "channel_required": "",
    "channel_invite_link": "",
    "min_deposit": "10000",
}

# Lightweight migrations applied to existing databases created before these
# columns existed. Safe to re-run: duplicate-column errors are ignored.
MIGRATIONS = [
    "ALTER TABLE subscriptions ADD COLUMN config_links TEXT DEFAULT '[]'",
    "ALTER TABLE payments ADD COLUMN product_id INTEGER",
    "ALTER TABLE panels ADD COLUMN sub_link_template TEXT DEFAULT ''",
    "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
    "ALTER TABLE payments ADD COLUMN handled_by INTEGER",
    "ALTER TABLE payments ADD COLUMN notif_chats TEXT DEFAULT '[]'",
    "ALTER TABLE payments ADD COLUMN renew_sub_id INTEGER",
    "ALTER TABLE payments ADD COLUMN coupon_code TEXT DEFAULT NULL",
    "ALTER TABLE payments ADD COLUMN discount_amount INTEGER DEFAULT 0",
]


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
        conn = await self.connect()
        try:
            await conn.executescript(SCHEMA)
            for stmt in MIGRATIONS:
                try:
                    await conn.execute(stmt)
                except aiosqlite.OperationalError:
                    pass  # column already exists on a fresh/up-to-date database
            for key, value in DEFAULT_SETTINGS.items():
                await conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
            await conn.commit()
        finally:
            await conn.close()

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

    async def get_all_users_count(self) -> int:
        row = await self._fetchone("SELECT COUNT(*) as c FROM users")
        return row["c"] if row else 0

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
    async def create_payment(
        self, user_id: int, amount: int, payment_method: str = "card",
        order_id: int | None = None, receipt_file_id: str | None = None,
        product_id: int | None = None, renew_sub_id: int | None = None,
    ) -> int:
        return await self._execute(
            "INSERT INTO payments (user_id, order_id, product_id, renew_sub_id, amount, payment_method, receipt_file_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, order_id, product_id, renew_sub_id, amount, payment_method, receipt_file_id),
        )

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


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
