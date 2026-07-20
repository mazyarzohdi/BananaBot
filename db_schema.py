"""Canonical BananaBot database schema + a generic schema reconciler.

Why this file exists
---------------------
Whenever the bot's code is updated, new tables or columns sometimes get
added to the schema. That's normally harmless — but if an admin restores
an OLDER backup of data/bot.db (taken before those tables/columns existed)
on top of a NEWER version of the code, every query that touches the new
table/column would fail immediately, and the bot / web panel would crash
or misbehave.

`reconcile()` fixes this generically: it compares what SCHEMA below says
should exist against what's actually in the target .db file, creates any
missing tables, and ADDs any missing columns to existing tables — no
matter how old the backup is, and without needing a manually-maintained
list of every past change. It's safe to run repeatedly (creating/adding
something that already exists is just skipped).

This module intentionally has ZERO third-party dependencies (stdlib
`sqlite3` only), so it can be imported or run standalone from either the
bot's process (which uses aiosqlite) or the separate web panel process
(a totally different Python venv with only Django installed), and even
directly from the command line during a manual DB restore.
"""

import re
import sqlite3
import sys
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    full_name TEXT,
    phone TEXT,
    balance INTEGER DEFAULT 0,
    is_banned INTEGER DEFAULT 0,
    referred_by INTEGER DEFAULT NULL,
    referral_code TEXT DEFAULT NULL,
    admin_note TEXT DEFAULT '',
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
    auto_renew INTEGER NOT NULL DEFAULT 0,
    reminder_sent_at TEXT DEFAULT NULL,
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
    reseller_plan_id INTEGER,
    amount INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    payment_method TEXT DEFAULT 'card',
    receipt_file_id TEXT,
    admin_note TEXT,
    handled_by INTEGER,
    notif_chats TEXT DEFAULT '[]',
    expected_amount INTEGER DEFAULT NULL,
    expires_at TEXT DEFAULT NULL,
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

CREATE TABLE IF NOT EXISTS reseller_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    panel_id INTEGER NOT NULL,
    volume_gb REAL NOT NULL,
    duration_days INTEGER NOT NULL,
    price INTEGER NOT NULL,
    is_active INTEGER DEFAULT 1,
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (panel_id) REFERENCES panels(id)
);

CREATE TABLE IF NOT EXISTS resellers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE NOT NULL,
    plan_id INTEGER,
    panel_id INTEGER NOT NULL,
    quota_gb REAL NOT NULL DEFAULT 0,
    expires_at INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    reminder_sent_at TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (plan_id) REFERENCES reseller_plans(id),
    FOREIGN KEY (panel_id) REFERENCES panels(id)
);

CREATE TABLE IF NOT EXISTS reseller_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reseller_id INTEGER NOT NULL,
    label TEXT DEFAULT '',
    email TEXT NOT NULL,
    sub_id TEXT,
    volume_gb REAL NOT NULL,
    expiry_time INTEGER DEFAULT 0,
    config_link TEXT,
    config_links TEXT DEFAULT '[]',
    sub_link TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    consumed_gb REAL NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (reseller_id) REFERENCES resellers(id)
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

CREATE TABLE IF NOT EXISTS support_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS support_ticket_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    sender TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (ticket_id) REFERENCES support_tickets(id)
);

CREATE TABLE IF NOT EXISTS referral_earnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_user_id INTEGER NOT NULL,
    referred_user_id INTEGER NOT NULL,
    order_id INTEGER DEFAULT NULL,
    amount INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (referrer_user_id) REFERENCES users(id),
    FOREIGN KEY (referred_user_id) REFERENCES users(id),
    FOREIGN KEY (order_id) REFERENCES orders(id)
);
"""


DEFAULT_SETTINGS = {
    "welcome_text": "سلام! به ربات فروش VPN خوش آمدید.",
    "support_text": "برای پشتیبانی با ادمین تماس بگیرید.",
    "support_username": "",
    "support_contact_enabled": "1",
    "trial_enabled": "1",
    "trial_product_id": "0",
    "trial_panel_id": "",
    "trial_volume_gb": "1",
    "trial_duration_days": "1",
    "channel_required": "",
    "channel_invite_link": "",
    "min_deposit": "10000",
    "auto_payment_enabled": "0",
    "auto_payment_secret": "",
    "auto_payment_port": "8100",
    "expiry_reminder_enabled": "1",
    "expiry_reminder_days_before": "3",
    "referral_enabled": "0",
    # نوع پاداش معرفی: "percent" (درصدی از مبلغ هر خرید کاربر معرفی‌شده)
    # یا "fixed" (مبلغ ثابت به ازای هر خرید کاربر معرفی‌شده).
    "referral_reward_type": "percent",
    "referral_reward_value": "0",
    "backup_schedule_enabled": "0",
    "backup_schedule_interval_hours": "24",
    "backup_schedule_retention_count": "14",
    "backup_last_run_at": "0",
}

# Historical migrations that predate the generic column-reconciler below, or
# that need something more than a plain "add this column" (kept only for
# backward compatibility with very old backups). New schema changes should
# just be added to SCHEMA above — reconcile() picks them up automatically,
# nothing needs to be added here anymore.
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


def _split_top_level(body: str) -> list[str]:
    """Split a CREATE TABLE(...) body on commas, ignoring commas that are
    nested inside parentheses (e.g. inside a default expression)."""
    parts, current, depth = [], [], 0
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def parse_schema_columns(schema_sql: str = SCHEMA) -> dict[str, list[str]]:
    """Extract {table_name: [full column definition, ...]} from every
    `CREATE TABLE IF NOT EXISTS` statement in SCHEMA. Table-level
    constraints (PRIMARY KEY(...), FOREIGN KEY(...), UNIQUE(...), CHECK(...))
    are skipped since they aren't valid in ALTER TABLE ADD COLUMN and don't
    correspond to an actual column."""
    tables: dict[str, list[str]] = {}
    for match in re.finditer(
        r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\)\s*;", schema_sql, re.DOTALL
    ):
        table_name, body = match.group(1), match.group(2)
        columns = []
        for part in _split_top_level(body):
            line = part.strip()
            if not line:
                continue
            if line.upper().startswith(("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK")):
                continue
            columns.append(line)
        tables[table_name] = columns
    return tables


def reconcile(db_path: str) -> dict:
    """Bring an existing (possibly old/restored-from-backup) database up to
    date with the current SCHEMA: create any missing tables, add any
    missing columns, apply legacy MIGRATIONS, and seed any DEFAULT_SETTINGS
    that aren't already present. Returns a report of what changed so
    callers (e.g. manage.sh) can show the admin what happened."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    report = {"tables_created": [], "columns_added": [], "settings_seeded": []}

    conn = sqlite3.connect(db_path, timeout=30)
    try:
        # Three separate processes now touch this file concurrently (the
        # bot, the web panel, and the auto-payment webhook server). The
        # default SQLite journal mode blocks readers while a write is in
        # progress (and vice versa), which gets more likely to cause
        # "database is locked" errors as concurrent access increases.
        # WAL mode lets reads and writes proceed concurrently in the
        # common case. This is stored in the DB file itself, so it only
        # really needs to succeed once, but is cheap/idempotent to repeat.
        conn.execute("PRAGMA journal_mode=WAL")

        existing_tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        expected = parse_schema_columns(SCHEMA)
        for table_name in expected:
            if table_name not in existing_tables:
                report["tables_created"].append(table_name)
        conn.executescript(SCHEMA)  # CREATE TABLE IF NOT EXISTS — no-op for existing tables

        # referral_earnings used to have UNIQUE(referred_user_id) — one
        # reward per referred user, ever. The referral system now pays a
        # commission on EVERY purchase the referred user makes, so that
        # constraint has to go. SQLite can't drop a UNIQUE constraint with
        # ALTER TABLE, so on databases created before this change we
        # rebuild the table (preserving all existing rows) the one time
        # it's needed; harmless / skipped on fresh or already-migrated DBs.
        if "referral_earnings" in existing_tables:
            unique_cols = set()
            for idx in conn.execute("PRAGMA index_list(referral_earnings)").fetchall():
                idx_name, is_unique = idx[1], idx[2]
                if not is_unique:
                    continue
                for info in conn.execute(f"PRAGMA index_info({idx_name})").fetchall():
                    unique_cols.add(info[2])
            if "referred_user_id" in unique_cols:
                conn.execute("ALTER TABLE referral_earnings RENAME TO referral_earnings_old")
                conn.execute(
                    "CREATE TABLE referral_earnings ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "referrer_user_id INTEGER NOT NULL,"
                    "referred_user_id INTEGER NOT NULL,"
                    "order_id INTEGER DEFAULT NULL,"
                    "amount INTEGER NOT NULL,"
                    "source TEXT NOT NULL DEFAULT '',"
                    "created_at TEXT DEFAULT (datetime('now')),"
                    "FOREIGN KEY (referrer_user_id) REFERENCES users(id),"
                    "FOREIGN KEY (referred_user_id) REFERENCES users(id),"
                    "FOREIGN KEY (order_id) REFERENCES orders(id)"
                    ")"
                )
                old_cols = {
                    row[1] for row in conn.execute(
                        "PRAGMA table_info(referral_earnings_old)"
                    ).fetchall()
                }
                copy_cols = [
                    c for c in
                    ("id", "referrer_user_id", "referred_user_id", "amount", "source", "created_at")
                    if c in old_cols
                ]
                conn.execute(
                    f"INSERT INTO referral_earnings ({', '.join(copy_cols)}) "
                    f"SELECT {', '.join(copy_cols)} FROM referral_earnings_old"
                )
                conn.execute("DROP TABLE referral_earnings_old")
                report.setdefault("migrated", []).append(
                    "referral_earnings: removed UNIQUE(referred_user_id) — رفرال حالا به‌ازای هر خرید پاداش می‌ده"
                )

        for table, columns in expected.items():
            existing_cols = {
                row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for col_def in columns:
                col_name = col_def.split()[0].strip('"')
                if col_name in existing_cols:
                    continue
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
                    report["columns_added"].append(f"{table}.{col_name}")
                except sqlite3.OperationalError:
                    # e.g. a NOT NULL column without a DEFAULT on a
                    # non-empty table — SQLite can't ADD COLUMN that way.
                    # Every column currently in SCHEMA is nullable or has a
                    # DEFAULT, so this should only ever trip on a custom
                    # column a developer added without one; logged so it's
                    # not silently lost.
                    report.setdefault("failed", []).append(f"{table}.{col_name}")

        for stmt in MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists

        # این ایندکس عمداً اینجا (بعد از حلقه‌ی ADD COLUMN بالا) اجرا می‌شه،
        # نه به‌صورت inline توی SCHEMA — چون روی دیتابیس‌های قدیمی که ستون
        # referral_code هنوز وجود نداره، اگه زودتر اجرا بشه (قبل از اضافه
        # شدن ستون) با خطا مواجه می‌شه.
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code "
                "ON users(referral_code) WHERE referral_code IS NOT NULL"
            )
        except sqlite3.OperationalError:
            pass

        for key, value in DEFAULT_SETTINGS.items():
            cur = conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value),
            )
            if cur.rowcount:
                report["settings_seeded"].append(key)

        conn.commit()
    finally:
        conn.close()

    return report


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "data/bot.db"
    print(f"Reconciling schema for: {target}")
    result = reconcile(target)
    if result["tables_created"]:
        print(f"  + Tables created: {', '.join(result['tables_created'])}")
    if result["columns_added"]:
        print(f"  + Columns added: {', '.join(result['columns_added'])}")
    if result.get("failed"):
        print(f"  ! Columns that could NOT be added automatically: {', '.join(result['failed'])}")
    if result.get("migrated"):
        for m in result["migrated"]:
            print(f"  ~ Migrated: {m}")
    if (
        not result["tables_created"] and not result["columns_added"]
        and not result.get("failed") and not result.get("migrated")
    ):
        print("  Already up to date — no changes needed.")
