import argparse
import asyncio
import os
import sys
import sqlite3
try:
    import asyncpg
except ImportError:
    asyncpg = None
from pathlib import Path

# Add the parent directory to sys.path so we can import config and db_schema
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_settings
from db_schema import SCHEMA, get_dialect_schema

async def get_pg_conn():
    if asyncpg is None:
        raise ImportError("asyncpg is required for PostgreSQL migration. Install asyncpg.")
    settings = get_settings()
    db_name = os.environ.get("DB_NAME") or settings.db_name
    db_user = os.environ.get("DB_USER") or settings.db_user
    db_pass = os.environ.get("DB_PASS") or settings.db_pass
    db_host = os.environ.get("DB_HOST") or settings.db_host
    db_port = os.environ.get("DB_PORT") or settings.db_port

    print(f"Connecting to PostgreSQL ({db_user}@{db_host}:{db_port}/{db_name})...")
    try:
        return await asyncpg.connect(
            database=db_name,
            user=db_user,
            password=db_pass,
            host=db_host,
            port=db_port,
            timeout=10.0
        )
    except asyncpg.exceptions.InvalidPasswordError:
        print("\n" + "="*60)
        print("ERROR: PostgreSQL password authentication failed!")
        print(f"User: {db_user}")
        print(f"Host: {db_host}:{db_port}")
        print(f"Database: {db_name}")
        print("="*60 + "\n")
        raise

def get_sqlite_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def get_sqlite_tables(sl_conn):
    rows = sl_conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    return [r[0] for r in rows]

ALL_TABLES = [
    "settings", "users", "panels", "products", "reseller_plans", 
    "resellers", "reseller_configs", "coupons", "coupon_uses", "orders", 
    "subscriptions", "payments", "trial_apps", "faq", "tutorials", 
    "api_keys", "api_nonces", "api_request_log", "support_tickets", 
    "support_ticket_messages", "referral_earnings", "game_seasons", 
    "game_profiles", "game_upgrades", "game_winners"
]

async def get_tables(pg_conn):
    rows = await pg_conn.fetch("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public'
    """)
    return [r['table_name'] for r in rows if r['table_name'] in ALL_TABLES]

async def migrate_sqlite_to_postgres():
    settings = get_settings()
    from config import BASE_DIR
    sqlite_path = str(BASE_DIR / settings.database_path)
    
    pg_conn = await get_pg_conn()
    
    # Drop existing tables to ensure schema updates (like BIGINT) are applied
    existing_tables = await get_tables(pg_conn)
    for t in existing_tables:
        await pg_conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
        
    schema_pg = get_dialect_schema("postgres")
    for stmt in schema_pg.split(';'):
        if stmt.strip():
            await pg_conn.execute(stmt)
            
    tables = await get_tables(pg_conn)
    sl_conn = get_sqlite_conn(sqlite_path)
    sl_tables = get_sqlite_tables(sl_conn)
    
    print("Migrating from SQLite to Postgres...")
    try:
        await pg_conn.execute("SET session_replication_role = 'replica';")
    except Exception as e:
        print(f" -> [Note] Could not set session_replication_role to replica: {e}")

    try:
        for table in ALL_TABLES:
            if table not in tables or table not in sl_tables:
                continue
            print(f" -> Migrating table {table}...")
            await pg_conn.execute(f"TRUNCATE TABLE {table} CASCADE")
            
            rows = sl_conn.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"    (0 rows)")
                continue
                
            columns = rows[0].keys()
            col_names = ", ".join(columns)
            placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
            query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
            
            values = [tuple(dict(r).values()) for r in rows]
            await pg_conn.executemany(query, values)
            print(f"    (migrated {len(values)} rows)")
            
            if "id" in columns:
                try:
                    await pg_conn.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM {table}")
                except Exception as seq_err:
                    print(f" -> [Note] Sequence setval skipped for {table}: {seq_err}")
    finally:
        try:
            await pg_conn.execute("SET session_replication_role = 'origin';")
        except Exception:
            pass
            
    print("Migration complete!")
    await pg_conn.close()

async def migrate_postgres_to_sqlite():
    settings = get_settings()
    from config import BASE_DIR
    sqlite_path = str(BASE_DIR / settings.database_path)
    
    pg_conn = await get_pg_conn()
    sl_conn = get_sqlite_conn(sqlite_path)
    
    for stmt in get_dialect_schema("sqlite").split(';'):
        if stmt.strip():
            sl_conn.execute(stmt)
            
    tables = await get_tables(pg_conn)
    if not tables:
        print("Notice: No matching tables found in PostgreSQL to migrate from.")
        await pg_conn.close()
        return

    sl_tables = get_sqlite_tables(sl_conn)
    ordered_tables = ALL_TABLES
                      
    print("Migrating from Postgres to SQLite...")
    sl_conn.execute("PRAGMA foreign_keys = OFF")
    for table in ordered_tables:
        if table not in tables or table not in sl_tables:
            print(f" -> Skipping table {table} (not found in PostgreSQL)")
            continue
            
        print(f" -> Migrating table {table}...")
        rows = await pg_conn.fetch(f"SELECT * FROM {table}")
        if not rows:
            print(f"    (0 rows)")
            continue
            
        sl_conn.execute(f"DELETE FROM {table}")
        columns = tuple(rows[0].keys())
        col_names = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
        
        def _serialize_val(val):
            if hasattr(val, "strftime"):
                return val.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(val, bool):
                return 1 if val else 0
            return val

        values = [tuple(_serialize_val(v) for v in dict(r).values()) for r in rows]
        sl_conn.executemany(query, values)
        print(f"    (migrated {len(values)} rows)")
        
    sl_conn.execute("PRAGMA foreign_keys = ON")
    sl_conn.commit()
    print("Migration complete!")
    await pg_conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", choices=["sqlite_to_pg", "pg_to_sqlite"], required=True)
    args = parser.parse_args()
    
    if args.direction == "sqlite_to_pg":
        asyncio.run(migrate_sqlite_to_postgres())
    else:
        asyncio.run(migrate_postgres_to_sqlite())
