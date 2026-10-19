import asyncio
import os
import re
from typing import Any

_asyncpg_pool = None
_pool_lock = asyncio.Lock()


def _replace_placeholders(query: str) -> str:
    """Safely replace ? with $1, $2, ... for Postgres, skipping string literals."""
    result = []
    idx = 1
    in_str = False
    str_char = ''
    i = 0
    n = len(query)
    while i < n:
        c = query[i]
        if not in_str:
            if c in ("'", '"'):
                in_str = True
                str_char = c
                result.append(c)
            elif c == '?':
                result.append(f"${idx}")
                idx += 1
            else:
                result.append(c)
        else:
            result.append(c)
            if c == str_char:
                # Check for escaped quote in SQL (e.g. 'O''Reilly')
                if i + 1 < n and query[i + 1] == str_char:
                    result.append(query[i + 1])
                    i += 1
                else:
                    in_str = False
        i += 1
    return "".join(result)


def _convert_query(query: str, db_type: str) -> str:
    if db_type != "postgres":
        return query

    res = _replace_placeholders(query)

    # Translate SQLite datetime('now', X) to Postgres CURRENT_TIMESTAMP + CAST(X AS INTERVAL)
    res = re.sub(
        r"datetime\('now',\s*([^)]+)\)",
        r"TO_CHAR((CURRENT_TIMESTAMP AT TIME ZONE 'UTC') + CAST(\1 AS INTERVAL), 'YYYY-MM-DD HH24:MI:SS')",
        res,
    )
    res = res.replace("datetime('now')", "TO_CHAR(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")
    res = res.replace("date('now')", "CURRENT_DATE")
    # Translate SQLite date(column) to Postgres (column)::DATE
    res = re.sub(r'\bdate\((\w+)\)', r'(\1)::DATE', res)
    res = res.replace("BEGIN EXCLUSIVE", "BEGIN")
    if "INSERT OR REPLACE INTO settings (key, value) VALUES" in res:
        res = res.replace(
            "INSERT OR REPLACE INTO settings (key, value) VALUES",
            "INSERT INTO settings (key, value) VALUES",
        )
        res += " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    return res


class AsyncpgCursorWrapper:
    def __init__(self, conn, query: str, params: tuple | list):
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
    def __init__(self, conn, db_type: str, pool=None):
        self.conn = conn
        self.db_type = "postgres" if db_type.strip().lower() == "postgres" else "sqlite"
        self.pool = pool
        self.pg_tr = None

    async def execute(self, query: str, params: tuple | list = ()):
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
        if self.db_type == "postgres" and self.pool:
            await self.pool.release(self.conn)
        else:
            await self.conn.close()


async def get_db_connection(path: str) -> DBConnectionWrapper:
    global _asyncpg_pool
    from config import get_settings
    settings = get_settings()

    raw_type = (os.environ.get("DB_TYPE") or getattr(settings, "db_type", None) or "sqlite").strip().strip('\'"').lower()

    if raw_type == "postgres":
        import asyncpg
        if _asyncpg_pool is None:
            async with _pool_lock:
                if _asyncpg_pool is None:
                    db_name = os.environ.get("DB_NAME") or getattr(settings, "db_name", "bananabot")
                    db_user = os.environ.get("DB_USER") or getattr(settings, "db_user", "bananabot")
                    db_pass = os.environ.get("DB_PASS") or getattr(settings, "db_pass", "")
                    db_host = os.environ.get("DB_HOST") or getattr(settings, "db_host", "127.0.0.1")
                    db_port = os.environ.get("DB_PORT") or getattr(settings, "db_port", "5432")
                    _asyncpg_pool = await asyncpg.create_pool(
                        database=db_name,
                        user=db_user,
                        password=db_pass,
                        host=db_host,
                        port=db_port,
                        min_size=2,
                        max_size=20,
                        timeout=30.0,
                    )
        conn = await _asyncpg_pool.acquire()
        return DBConnectionWrapper(conn, "postgres", pool=_asyncpg_pool)
    else:
        import aiosqlite
        conn = await aiosqlite.connect(path, timeout=30.0)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA synchronous = NORMAL")
        await conn.execute("PRAGMA busy_timeout = 30000")
        await conn.execute("PRAGMA foreign_keys = ON")
        return DBConnectionWrapper(conn, "sqlite")