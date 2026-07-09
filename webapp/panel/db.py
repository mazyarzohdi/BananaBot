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
        base = (
            "FROM payments py JOIN users u ON py.user_id = u.id "
            + (f"WHERE py.status='{status}' " if status else "")
        )
        rows = conn.execute(
            f"SELECT py.*, u.full_name, u.username, u.telegram_id {base}"
            f"ORDER BY py.id DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()
        total = conn.execute(f"SELECT COUNT(*) {base}").fetchone()[0]
    return rows_to_list(rows), total


def get_payment(payment_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT py.*, u.full_name, u.username, u.telegram_id "
            "FROM payments py JOIN users u ON py.user_id = u.id WHERE py.id=?",
            (payment_id,),
        ).fetchone()
    return row_to_dict(row)


def create_payment(user_id: int, amount: int, payment_method: str = "card") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO payments (user_id, amount, payment_method) VALUES (?, ?, ?)",
            (user_id, amount, payment_method),
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


def approve_payment(payment_id: int, admin_note: str = ""):
    with get_conn() as conn:
        payment = row_to_dict(
            conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        )
        if not payment or payment["status"] != "pending":
            return False
        conn.execute(
            "UPDATE payments SET status='approved', admin_note=? WHERE id=?",
            (admin_note, payment_id),
        )
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE id=?",
            (payment["amount"], payment["user_id"]),
        )
        return True


def reject_payment(payment_id: int, admin_note: str = "") -> bool:
    with get_conn() as conn:
        payment = row_to_dict(
            conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        )
        if not payment or payment["status"] != "pending":
            return False
        conn.execute(
            "UPDATE payments SET status='rejected', admin_note=? WHERE id=?",
            (admin_note, payment_id),
        )
        return True


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
        total = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='approved'"
        ).fetchone()[0]
        today = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments "
            "WHERE status='approved' AND date(created_at)=date('now')"
        ).fetchone()[0]
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE status='pending'"
        ).fetchone()[0]
    return {"total": total, "today": today, "pending_count": pending_count}
