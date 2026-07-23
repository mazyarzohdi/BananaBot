"""Synchronous SQLite helpers for the web panel.

The bot uses aiosqlite (async). The web panel uses the same .db file
but accesses it via the standard synchronous sqlite3 module — so no
event loop conflicts.
"""

import json
import sqlite3
from contextlib import contextmanager
from django.conf import settings


@contextmanager
def get_conn():
    conn = sqlite3.connect(settings.BOT_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


# ── Settings ─────────────────────────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_all_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


# ── Users ─────────────────────────────────────────────────────────────────────

def get_user_by_telegram_id(telegram_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
    return row_to_dict(row)


def get_users_page(page: int, per_page: int = 20, search: str = "") -> tuple[list[dict], int]:
    offset = (page - 1) * per_page
    with get_conn() as conn:
        if search:
            q = (f"%{search}%",) * 3
            rows = conn.execute(
                "SELECT * FROM users WHERE CAST(telegram_id AS TEXT) LIKE ? "
                "OR username LIKE ? OR full_name LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (*q, per_page, offset),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM users WHERE CAST(telegram_id AS TEXT) LIKE ? "
                "OR username LIKE ? OR full_name LIKE ?",
                q,
            ).fetchone()[0]
        else:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY id DESC LIMIT ? OFFSET ?",
                (per_page, offset),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return rows_to_list(rows), total


def update_user_balance(user_id: int, delta: int) -> int:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET balance = MAX(0, balance + ?) WHERE id = ?",
            (delta, user_id),
        )
        row = conn.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["balance"] if row else 0


def set_user_banned(user_id: int, banned: bool):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET is_banned = ? WHERE id = ?",
            (1 if banned else 0, user_id),
        )


def get_users_stats() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        banned = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM users WHERE date(created_at) = date('now')"
        ).fetchone()[0]
    return {"total": total, "banned": banned, "today": today}


# ── Products ──────────────────────────────────────────────────────────────────

def get_products(active_only: bool = True) -> list[dict]:
    with get_conn() as conn:
        q = "SELECT p.*, pn.name as panel_name FROM products p JOIN panels pn ON p.panel_id = pn.id"
        if active_only:
            q += " WHERE p.is_active = 1"
        q += " ORDER BY p.price"
        rows = conn.execute(q).fetchall()
    return rows_to_list(rows)


def get_product(product_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT p.*, pn.name as panel_name FROM products p "
            "JOIN panels pn ON p.panel_id = pn.id WHERE p.id = ?",
            (product_id,),
        ).fetchone()
    return row_to_dict(row)


def add_product(name, panel_id, volume_gb, duration_days, price, description=""):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO products (name, panel_id, volume_gb, duration_days, price, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, panel_id, volume_gb, duration_days, price, description),
        )
        return cur.lastrowid


def update_product(product_id: int, **fields):
    allowed = {"name", "panel_id", "volume_gb", "duration_days", "price", "is_active", "description"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    cols = ", ".join(f"{k}=?" for k in updates)
    with get_conn() as conn:
        conn.execute(f"UPDATE products SET {cols} WHERE id=?", (*updates.values(), product_id))


def delete_product(product_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))


# ── Panels ────────────────────────────────────────────────────────────────────

def get_panels(active_only: bool = False) -> list[dict]:
    with get_conn() as conn:
        q = "SELECT * FROM panels"
        if active_only:
            q += " WHERE is_active=1"
        rows = conn.execute(q).fetchall()
    return rows_to_list(rows)


def get_panel(panel_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM panels WHERE id=?", (panel_id,)).fetchone()
    return row_to_dict(row)


def update_panel(panel_id: int, **fields):
    allowed = {"name", "url", "api_token", "inbound_ids", "on_hold", "is_active", "sub_link_template"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    cols = ", ".join(f"{k}=?" for k in updates)
    with get_conn() as conn:
        conn.execute(f"UPDATE panels SET {cols} WHERE id=?", (*updates.values(), panel_id))


def delete_panel(panel_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM panels WHERE id=?", (panel_id,))


# ── Subscriptions ─────────────────────────────────────────────────────────────

def get_user_subscriptions(user_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT s.*, p.name as product_name, pn.name as panel_name "
            "FROM subscriptions s "
            "LEFT JOIN products p ON s.product_id = p.id "
            "LEFT JOIN panels pn ON s.panel_id = pn.id "
            "WHERE s.user_id = ? ORDER BY s.id DESC",
            (user_id,),
        ).fetchall()
    return rows_to_list(rows)


def get_active_subscriptions_count() -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE status='active'"
        ).fetchone()[0]


def get_subscription(sub_id: int) -> dict | None:
    """Mirrors database/db.py's async get_subscription join, so the panel
    has everything needed (panel url/token, client email) to delete the
    client on the actual x-ui panel, not just in our own DB."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT s.*, u.telegram_id, u.full_name, "
            "pn.name as panel_name, pn.url as panel_url, pn.api_token "
            "FROM subscriptions s "
            "JOIN users u ON s.user_id = u.id "
            "JOIN panels pn ON s.panel_id = pn.id "
            "WHERE s.id = ?",
            (sub_id,),
        ).fetchone()
    return row_to_dict(row)


def delete_subscription_record(sub_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE subscriptions SET status='deleted' WHERE id=?", (sub_id,))


# ── Reseller plans ────────────────────────────────────────────────────────────

def get_reseller_plans(active_only: bool = True) -> list[dict]:
    with get_conn() as conn:
        q = (
            "SELECT rp.*, pn.name as panel_name FROM reseller_plans rp "
            "JOIN panels pn ON rp.panel_id = pn.id"
        )
        if active_only:
            q += " WHERE rp.is_active = 1"
        q += " ORDER BY rp.price"
        rows = conn.execute(q).fetchall()
    return rows_to_list(rows)


def get_reseller_plan(plan_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT rp.*, pn.name as panel_name FROM reseller_plans rp "
            "JOIN panels pn ON rp.panel_id = pn.id WHERE rp.id = ?",
            (plan_id,),
        ).fetchone()
    return row_to_dict(row)


def add_reseller_plan(name, panel_id, volume_gb, duration_days, price, description=""):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO reseller_plans (name, panel_id, volume_gb, duration_days, price, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, panel_id, volume_gb, duration_days, price, description),
        )
        return cur.lastrowid


def update_reseller_plan(plan_id: int, **fields):
    allowed = {"name", "panel_id", "volume_gb", "duration_days", "price", "is_active", "description"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    cols = ", ".join(f"{k}=?" for k in updates)
    with get_conn() as conn:
        conn.execute(f"UPDATE reseller_plans SET {cols} WHERE id=?", (*updates.values(), plan_id))


def delete_reseller_plan(plan_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM reseller_plans WHERE id=?", (plan_id,))


# ── Resellers ─────────────────────────────────────────────────────────────────

def get_reseller_by_user_id(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT r.*, pn.name as panel_name, pn.url as panel_url, pn.api_token, "
            "pn.inbound_ids, pn.on_hold, pn.sub_link_template, rp.name as plan_name "
            "FROM resellers r JOIN panels pn ON r.panel_id = pn.id "
            "LEFT JOIN reseller_plans rp ON r.plan_id = rp.id "
            "WHERE r.user_id = ?",
            (user_id,),
        ).fetchone()
    return row_to_dict(row)


def get_reseller(reseller_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT r.*, pn.name as panel_name, pn.url as panel_url, pn.api_token, "
            "pn.inbound_ids, pn.on_hold, pn.sub_link_template, rp.name as plan_name, "
            "u.telegram_id, u.username, u.full_name "
            "FROM resellers r JOIN panels pn ON r.panel_id = pn.id "
            "JOIN users u ON r.user_id = u.id "
            "LEFT JOIN reseller_plans rp ON r.plan_id = rp.id "
            "WHERE r.id = ?",
            (reseller_id,),
        ).fetchone()
    return row_to_dict(row)


def get_all_resellers() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.*, u.telegram_id, u.username, u.full_name, rp.name as plan_name, "
            "(SELECT COUNT(*) FROM reseller_configs rc "
            " WHERE rc.reseller_id = r.id AND rc.status != 'deleted') as configs_count "
            "FROM resellers r JOIN users u ON r.user_id = u.id "
            "LEFT JOIN reseller_plans rp ON r.plan_id = rp.id "
            "ORDER BY r.id DESC"
        ).fetchall()
    return rows_to_list(rows)


def create_reseller_manual(user_id: int, panel_id: int, quota_gb: float, expires_at: int) -> int:
    """تبدیل دستی یک کاربر عادی به نماینده توسط ادمین (بدون عبور از
    فرآیند خرید پلن). اگر کاربر از قبل نماینده باشد، رکورد موجود
    برگردانده می‌شود و تغییری در آن اعمال نمی‌شود — حذف/ویرایش نماینده‌ی
    موجود باید صریحاً و جداگانه از صفحه‌ی مدیریت نماینده‌ها انجام شود."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM resellers WHERE user_id = ?", (user_id,)
        ).fetchone()
        if existing:
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO resellers (user_id, plan_id, panel_id, quota_gb, expires_at, status) "
            "VALUES (?, NULL, ?, ?, ?, 'active')",
            (user_id, panel_id, quota_gb, expires_at),
        )
        return cur.lastrowid


def set_reseller_status(reseller_id: int, status: str):
    with get_conn() as conn:
        conn.execute("UPDATE resellers SET status=? WHERE id=?", (status, reseller_id))


def update_reseller(reseller_id: int, **fields):
    """اصلاح دستی حجم/تاریخ‌انقضای یک نماینده توسط ادمین."""
    allowed = {"quota_gb", "expires_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    cols = ", ".join(f"{k} = ?" for k in updates)
    with get_conn() as conn:
        conn.execute(f"UPDATE resellers SET {cols} WHERE id = ?", (*updates.values(), reseller_id))


def delete_reseller(reseller_id: int):
    """حذف کامل نماینده و رکوردهای کانفیگ آن از دیتابیس (اتمیک، یک
    اتصال). مثل نسخه‌ی ربات، کاری با پنل X-UI واقعی ندارد — کانفیگ‌های
    فعال باید قبلش جداگانه از روی پنل حذف شوند."""
    with get_conn() as conn:
        conn.execute("DELETE FROM reseller_configs WHERE reseller_id = ?", (reseller_id,))
        conn.execute("DELETE FROM resellers WHERE id = ?", (reseller_id,))


def get_reseller_used_gb(reseller_id: int) -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM("
            "  CASE WHEN status = 'deleted' THEN consumed_gb ELSE volume_gb + consumed_gb END"
            "), 0) as used "
            "FROM reseller_configs WHERE reseller_id = ?",
            (reseller_id,),
        ).fetchone()
    return row["used"] if row else 0.0


def get_reseller_configs(reseller_id: int, include_deleted: bool = False) -> list[dict]:
    with get_conn() as conn:
        q = "SELECT * FROM reseller_configs WHERE reseller_id = ?"
        if not include_deleted:
            q += " AND status != 'deleted'"
        q += " ORDER BY id DESC"
        rows = conn.execute(q, (reseller_id,)).fetchall()
    return rows_to_list(rows)


def get_reseller_config(config_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT rc.*, r.user_id, r.panel_id, r.quota_gb, r.expires_at as reseller_expires_at, "
            "r.status as reseller_status, pn.url as panel_url, pn.api_token, pn.inbound_ids, "
            "pn.sub_link_template, pn.on_hold "
            "FROM reseller_configs rc "
            "JOIN resellers r ON rc.reseller_id = r.id "
            "JOIN panels pn ON r.panel_id = pn.id "
            "WHERE rc.id = ?",
            (config_id,),
        ).fetchone()
    return row_to_dict(row)


def add_reseller_config(**data) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO reseller_configs "
            "(reseller_id, label, email, sub_id, volume_gb, expiry_time, "
            "config_link, config_links, sub_link, status, source, api_key_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                data.get("source", "panel"),
                data.get("api_key_id"),
            ),
        )
        return cur.lastrowid


def update_reseller_config(config_id: int, **fields):
    allowed = {"label", "volume_gb", "expiry_time", "config_link", "config_links", "sub_link", "status", "sub_id", "consumed_gb"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    cols = ", ".join(f"{k}=?" for k in updates)
    with get_conn() as conn:
        conn.execute(f"UPDATE reseller_configs SET {cols} WHERE id=?", (*updates.values(), config_id))


# ── Payments ──────────────────────────────────────────────────────────────────

def get_pending_payments() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT py.*, u.full_name, u.username, u.telegram_id "
            "FROM payments py JOIN users u ON py.user_id = u.id "
            "WHERE py.status='pending' ORDER BY py.id DESC"
        ).fetchall()
    return rows_to_list(rows)


def get_payments_page(page: int, per_page: int = 20, status: str = "") -> tuple[list[dict], int]:
    offset = (page - 1) * per_page
    with get_conn() as conn:
        base = "FROM payments py JOIN users u ON py.user_id = u.id "
        params: list = []
        if status:
            base += "WHERE py.status = ? "
            params.append(status)
        rows = conn.execute(
            f"SELECT py.*, u.full_name, u.username, u.telegram_id {base}"
            f"ORDER BY py.id DESC LIMIT ? OFFSET ?",
            (*params, per_page, offset),
        ).fetchall()
        total = conn.execute(f"SELECT COUNT(*) {base}", tuple(params)).fetchone()[0]
    return rows_to_list(rows), total


def get_payment(payment_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT py.*, u.full_name, u.username, u.telegram_id "
            "FROM payments py JOIN users u ON py.user_id = u.id WHERE py.id=?",
            (payment_id,),
        ).fetchone()
    return row_to_dict(row)


def create_payment(user_id: int, amount: int, payment_method: str = "card", reseller_plan_id: int | None = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO payments (user_id, amount, payment_method, reseller_plan_id) VALUES (?, ?, ?, ?)",
            (user_id, amount, payment_method, reseller_plan_id),
        )
        return cur.lastrowid


def get_pending_deposit_awaiting_receipt(user_id: int) -> dict | None:
    """The user's most recent pending top-up that has no receipt yet —
    mirrors the exact query the bot uses in its own `deposit_receipt`
    handler, so both surfaces agree on which payment a new receipt
    belongs to."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM payments WHERE user_id = ? AND status = 'pending' "
            "AND receipt_file_id IS NULL AND product_id IS NULL AND renew_sub_id IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return row_to_dict(row)


def get_pending_deposits_awaiting_review(user_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM payments WHERE user_id = ? AND status = 'pending' "
            "AND receipt_file_id IS NOT NULL ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return rows_to_list(rows)


def set_payment_receipt(payment_id: int, file_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET receipt_file_id = ? WHERE id = ?",
            (file_id, payment_id),
        )


def set_payment_notif_chats(payment_id: int, chats: list[dict]):
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET notif_chats = ? WHERE id = ?",
            (json.dumps(chats), payment_id),
        )


def approve_payment(payment_id: int, admin_note: str = "", handled_by: int | None = None) -> bool:
    """Atomically moves a payment from 'pending' to 'approved'. The WHERE
    clause on the UPDATE itself (not a separate SELECT check beforehand) is
    what makes this race-safe: two concurrent callers (e.g. an admin
    clicking approve at the same instant the auto-payment webhook approves
    the same payment) can't both succeed — only the first UPDATE actually
    matches a 'pending' row; the second gets rowcount=0 and returns False."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE payments SET status='approved', admin_note=?, handled_by=? "
            "WHERE id=? AND status='pending'",
            (admin_note, handled_by, payment_id),
        )
        if cur.rowcount == 0:
            return False
        payment = row_to_dict(
            conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        )
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE id=?",
            (payment["amount"], payment["user_id"]),
        )
        return True


def reject_payment(payment_id: int, admin_note: str = "", handled_by: int | None = None) -> bool:
    """Same atomicity reasoning as approve_payment above."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE payments SET status='rejected', admin_note=?, handled_by=? "
            "WHERE id=? AND status='pending'",
            (admin_note, handled_by, payment_id),
        )
        return cur.rowcount > 0


# ── Orders ────────────────────────────────────────────────────────────────────

def get_orders_page(page: int, per_page: int = 20) -> tuple[list[dict], int]:
    offset = (page - 1) * per_page
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT o.*, u.full_name, u.telegram_id FROM orders o "
            "JOIN users u ON o.user_id = u.id ORDER BY o.id DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    return rows_to_list(rows), total


def get_revenue_stats() -> dict:
    with get_conn() as conn:
        computed_total = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='approved'"
        ).fetchone()[0]
        today = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments "
            "WHERE status='approved' AND date(created_at)=date('now')"
        ).fetchone()[0]
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE status='pending'"
        ).fetchone()[0]
        adj_row = conn.execute("SELECT value FROM settings WHERE key='revenue_adjustment'").fetchone()
    try:
        adjustment = int(adj_row["value"]) if adj_row and adj_row["value"] else 0
    except (TypeError, ValueError):
        adjustment = 0
    return {
        "total": computed_total + adjustment,
        "today": today,
        "pending_count": pending_count,
        "computed_total": computed_total,
        "adjustment": adjustment,
    }


# ── Reseller API keys ─────────────────────────────────────────────────────────

def create_api_key(reseller_id: int, key_id: str, key_hash: str, label: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO api_keys (reseller_id, key_id, key_hash, label) VALUES (?, ?, ?, ?)",
            (reseller_id, key_id, key_hash, label),
        )
        return cur.lastrowid


def get_api_key_by_key_id(key_id: str) -> dict | None:
    """برای احراز هویت درخواست‌های API: کلید را همراه با اطلاعات کامل
    نماینده و پنل مرتبط برمی‌گرداند تا تمام چک‌های امنیتی (وضعیت، انقضا،
    سهمیه) بدون کوئری اضافه انجام شود."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT ak.*, r.user_id as reseller_user_id, r.quota_gb, r.expires_at as reseller_expires_at, "
            "r.status as reseller_status, r.panel_id, u.telegram_id as telegram_id, "
            "pn.url as panel_url, pn.api_token as api_token, pn.inbound_ids, "
            "pn.sub_link_template, pn.on_hold, pn.is_active as panel_is_active "
            "FROM api_keys ak "
            "JOIN resellers r ON ak.reseller_id = r.id "
            "JOIN users u ON r.user_id = u.id "
            "JOIN panels pn ON r.panel_id = pn.id "
            "WHERE ak.key_id = ?",
            (key_id,),
        ).fetchone()
    return row_to_dict(row)


def list_api_keys(reseller_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, key_id, label, is_active, last_used_at, last_used_ip, revoked_at, created_at "
            "FROM api_keys WHERE reseller_id = ? ORDER BY id DESC",
            (reseller_id,),
        ).fetchall()
    return rows_to_list(rows)


def get_api_key(pk_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (pk_id,)).fetchone()
    return row_to_dict(row)


def revoke_api_key(pk_id: int, reseller_id: int) -> bool:
    """فقط کلید متعلق به همین نماینده را غیرفعال می‌کند (rowcount اتمیک
    تضمین می‌کند نماینده‌ی دیگری نتواند کلید این یکی را باطل کند)."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE api_keys SET is_active = 0, revoked_at = datetime('now') "
            "WHERE id = ? AND reseller_id = ? AND is_active = 1",
            (pk_id, reseller_id),
        )
        return cur.rowcount > 0


def touch_api_key_usage(pk_id: int, ip: str = ""):
    with get_conn() as conn:
        conn.execute(
            "UPDATE api_keys SET last_used_at = datetime('now'), last_used_ip = ? WHERE id = ?",
            (ip, pk_id),
        )


def count_active_api_keys(reseller_id: int) -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM api_keys WHERE reseller_id = ? AND is_active = 1",
            (reseller_id,),
        ).fetchone()[0]


# ── API replay protection (nonces) ───────────────────────────────────────────

def check_and_consume_nonce(api_key_id: int, nonce: str) -> bool:
    """اگر nonce برای این کلید تازه باشد آن را ثبت کرده و True برمی‌گرداند؛
    اگر قبلاً استفاده شده باشد (تلاش برای Replay) False برمی‌گرداند. با
    تکیه بر محدودیت UNIQUE(api_key_id, nonce) در دیتابیس، این عملیات حتی
    زیر بار همزمان هم اتمیک و امن است."""
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO api_nonces (api_key_id, nonce) VALUES (?, ?)",
                (api_key_id, nonce),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def cleanup_old_nonces(older_than_seconds: int = 900):
    """پاک‌سازی nonce های قدیمی‌تر از پنجره‌ی زمانی معتبر، تا جدول رشد
    نامحدود پیدا نکند. صرفاً یک بهینه‌سازی نگهداشتی است؛ صحتِ چک replay به
    آن وابسته نیست."""
    with get_conn() as conn:
        conn.execute(
            f"DELETE FROM api_nonces WHERE created_at < datetime('now', '-{int(older_than_seconds)} seconds')"
        )


def cleanup_old_api_logs(older_than_seconds: int):
    """پاک‌سازی اختیاری لاگ‌های قدیمی درخواست‌های API (برای کنترل حجم
    دیتابیس در دیپلوی‌های پرترافیک). با فراخوانی صریح از مدیریت اجرا
    می‌شود؛ به‌صورت پیش‌فرض هیچ لاگی خودکار حذف نمی‌شود."""
    with get_conn() as conn:
        conn.execute(
            f"DELETE FROM api_request_log WHERE created_at < datetime('now', '-{int(older_than_seconds)} seconds')"
        )


# ── API request log / rate limiting ──────────────────────────────────────────

def log_api_request(
    api_key_id: int | None, reseller_id: int | None, endpoint: str, method: str, path: str,
    status_code: int, error_code: str = "", ip: str = "", user_agent: str = "", duration_ms: int = 0,
):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO api_request_log "
            "(api_key_id, reseller_id, endpoint, method, path, status_code, error_code, ip, user_agent, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (api_key_id, reseller_id, endpoint, method, path, status_code, error_code, ip, user_agent[:255], duration_ms),
        )


def count_recent_requests(api_key_id: int, window_seconds: int, endpoint: str | None = None) -> int:
    """شمارش درخواست‌های این کلید در N ثانیه‌ی اخیر، برای Rate Limiting.
    اگر endpoint داده شود، فقط همان دسته از درخواست‌ها شمرده می‌شود
    (مثلاً محدودیت سخت‌گیرانه‌تر روی ساخت کانفیگ نسبت به کل API)."""
    with get_conn() as conn:
        if endpoint:
            row = conn.execute(
                "SELECT COUNT(*) FROM api_request_log "
                "WHERE api_key_id = ? AND endpoint = ? AND created_at >= datetime('now', ?)",
                (api_key_id, endpoint, f"-{int(window_seconds)} seconds"),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM api_request_log "
                "WHERE api_key_id = ? AND created_at >= datetime('now', ?)",
                (api_key_id, f"-{int(window_seconds)} seconds"),
            ).fetchone()
    return row[0] if row else 0


def get_api_logs(reseller_id: int, limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM api_request_log WHERE reseller_id = ? ORDER BY id DESC LIMIT ?",
            (reseller_id, limit),
        ).fetchall()
    return rows_to_list(rows)
