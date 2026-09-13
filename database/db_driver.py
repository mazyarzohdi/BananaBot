import os
import re

def _convert_query(query: str, db_type: str) -> str:
    if db_type != "postgres":
        return query
    parts = query.split('?')
    if len(parts) == 1:
        res = query
    else:
        res = parts[0]
        for i, part in enumerate(parts[1:], 1):
            res += f"${i}" + part
    res = res.replace("MAX(", "GREATEST(")
    res = res.replace("datetime('now')", "CURRENT_TIMESTAMP")
    res = res.replace("BEGIN EXCLUSIVE", "BEGIN")
    if "INSERT OR REPLACE INTO settings (key, value) VALUES" in res:
        res = res.replace(
            "INSERT OR REPLACE INTO settings (key, value) VALUES",
            "INSERT INTO settings (key, value) VALUES"
        )
        res += " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    return res

class AsyncpgCursorWrapper:
    def __init__(self, conn, query, params):
        self.conn = conn
        self.query = query
        self.params = params
        self.rowcount = 0
        self.lastrowid = 0

    async def _run(self):
        q = self.query.strip()
        if q.upper().startswith("INSERT"):
            if "RETURNING id" not in q and "ON CONFLICT" not in q.upper():
                q += " RETURNING id"
            try:
                row = await self.conn.fetchrow(q, *self.params)
                self.lastrowid = row['id'] if row and 'id' in row else 0
                self.rowcount = 1 if row else 0
            except Exception:
                status = await self.conn.execute(self.query, *self.params)
                try:
                    self.rowcount = int(status.split()[-1])
                except Exception:
                    self.rowcount = 0
        else:
            status = await self.conn.execute(self.query, *self.params)
            try:
                self.rowcount = int(status.split()[-1])
            except Exception:
                self.rowcount = 0

    async def fetchone(self):
        row = await self.conn.fetchrow(self.query, *self.params)
        return dict(row) if row else None
        
    async def fetchall(self):
        rows = await self.conn.fetch(self.query, *self.params)
        return [dict(r) for r in rows]

class DBConnectionWrapper:
    def __init__(self, conn, db_type: str):
        self.conn = conn
        self.db_type = "postgres" if db_type.strip().lower() == "postgres" else "sqlite"
        self.pg_tr = None

    async def execute(self, query, params=()):
        if self.db_type != "postgres":
            return await self.conn.execute(query, params)
        
        q = _convert_query(query, "postgres")
        if "BEGIN" in q.upper():
            self.pg_tr = self.conn.transaction()
            await self.pg_tr.start()
            return AsyncpgCursorWrapper(self.conn, "", ())
            
        wrapper = AsyncpgCursorWrapper(self.conn, q, params)
        if not q.strip().upper().startswith("SELECT"):
            await wrapper._run()
        return wrapper

    async def commit(self):
        if self.db_type != "postgres":
            await self.conn.commit()
        elif self.pg_tr:
            await self.pg_tr.commit()
            self.pg_tr = None
            
    async def rollback(self):
        if self.db_type != "postgres":
            await self.conn.rollback()
        elif self.pg_tr:
            await self.pg_tr.rollback()
            self.pg_tr = None
            
    async def close(self):
        await self.conn.close()

async def get_db_connection(path: str) -> DBConnectionWrapper:
    from config import get_settings
    settings = get_settings()
    
    raw_type = (os.environ.get("DB_TYPE") or getattr(settings, "db_type", None) or "sqlite").strip().lower()
    
    if raw_type == "postgres":
        import asyncpg
        db_name = os.environ.get("DB_NAME") or getattr(settings, "db_name", "bananabot")
        db_user = os.environ.get("DB_USER") or getattr(settings, "db_user", "bananabot")
        db_pass = os.environ.get("DB_PASS") or getattr(settings, "db_pass", "")
        db_host = os.environ.get("DB_HOST") or getattr(settings, "db_host", "127.0.0.1")
        db_port = os.environ.get("DB_PORT") or getattr(settings, "db_port", "5432")
        
        conn = await asyncpg.connect(
            database=db_name,
            user=db_user,
            password=db_pass,
            host=db_host,
            port=db_port,
            timeout=30.0
        )
        return DBConnectionWrapper(conn, "postgres")
    else:
        import aiosqlite
        conn = await aiosqlite.connect(path, timeout=30.0)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        return DBConnectionWrapper(conn, "sqlite")
