import argparse
import asyncio
import os
import sqlite3
import asyncpg
from pathlib import Path
from config import get_settings
from db_schema import SCHEMA, get_dialect_schema

async def get_pg_conn():
    return await asyncpg.connect(
        database=os.environ.get("DB_NAME", "bananabot"),
        user=os.environ.get("DB_USER", "bananabot"),
        password=os.environ.get("DB_PASS", ""),
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=os.environ.get("DB_PORT", "5432"),
        timeout=10.0
    )

def get_sqlite_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

async def get_tables(pg_conn):
    rows = await pg_conn.fetch("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public'
    """)
    schema_tables = ["users", "panels", "products", "subscriptions", "orders", 
                     "payments", "coupons", "coupon_uses", "settings", 
                     "reseller_plans", "resellers", "trial_apps"]
    return [r['table_name'] for r in rows if r['table_name'] in schema_tables]

async def migrate_sqlite_to_postgres():
    settings = get_settings()
    sqlite_path = settings.database_path
    
    pg_conn = await get_pg_conn()
    schema_pg = get_dialect_schema("postgres")
    for stmt in schema_pg.split(';'):
        if stmt.strip():
            await pg_conn.execute(stmt)
            
    tables = await get_tables(pg_conn)
    sl_conn = get_sqlite_conn(sqlite_path)
    
    ordered_tables = ["settings", "users", "panels", "products", "reseller_plans", 
                      "coupons", "coupon_uses", "orders", "subscriptions", "resellers", 
                      "payments", "trial_apps"]
    
    print("Migrating from SQLite to Postgres...")
    for table in ordered_tables:
        if table not in tables:
            continue
        print(f" -> Migrating table {table}...")
        await pg_conn.execute(f"TRUNCATE TABLE {table} CASCADE")
        
        rows = sl_conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            continue
            
        columns = rows[0].keys()
        col_names = ", ".join(columns)
        placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
        query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
        
        values = [tuple(dict(r).values()) for r in rows]
        await pg_conn.executemany(query, values)
        
        if "id" in columns:
            await pg_conn.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM {table}")
            
    print("Migration complete!")
    await pg_conn.close()

async def migrate_postgres_to_sqlite():
    settings = get_settings()
    sqlite_path = settings.database_path
    
    pg_conn = await get_pg_conn()
    sl_conn = get_sqlite_conn(sqlite_path)
    
    for stmt in get_dialect_schema("sqlite").split(';'):
        if stmt.strip():
            sl_conn.execute(stmt)
            
    ordered_tables = ["settings", "users", "panels", "products", "reseller_plans", 
                      "coupons", "coupon_uses", "orders", "subscriptions", "resellers", 
                      "payments", "trial_apps"]
                      
    print("Migrating from Postgres to SQLite...")
    sl_conn.execute("PRAGMA foreign_keys = OFF")
    for table in ordered_tables:
        print(f" -> Migrating table {table}...")
        sl_conn.execute(f"DELETE FROM {table}")
        
        rows = await pg_conn.fetch(f"SELECT * FROM {table}")
        if not rows:
            continue
            
        columns = rows[0].keys()
        col_names = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
        
        values = [tuple(dict(r).values()) for r in rows]
        sl_conn.executemany(query, values)
        
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
