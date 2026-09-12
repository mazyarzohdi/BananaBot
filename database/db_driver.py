import os
import re

def _convert_query(query: str, db_type: str) -> str:
    if db_type == "sqlite":
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
            if "RETURNING id" not in q:
                q += " RETURNING id"
            try:
                row = await self.conn.fetchrow(q, *self.params)
                self.lastrowid = row['id'] if row else 0
                self.rowcount = 1 if row else 0
            except Exception as e:
                # E.g. tables with no ID or composite primary keys
                status = await self.conn.execute(self.query, *self.params)
                try:
                    self.rowcount = int(status.split()[-1])
                except:
                    self.rowcount = 0
        else:
            status = await self.conn.execute(self.query, *self.params)
            try:
                self.rowcount = int(status.split()[-1])
            except:
                self.rowcount = 0

    async def fetchone(self):
        row = await self.conn.fetchrow(self.query, *self.params)
        return dict(row) if row else None
        
    async def fetchall(self):
        rows = await self.conn.fetch(self.query, *self.params)
        return [dict(r) for r in rows]

class DBConnectionWrapper:
    def __init__(self, conn, db_type):
        self.conn = conn
        self.db_type = db_type
        self.pg_tr = None

    async def execute(self, query, params=()):
        q = _convert_query(query, self.db_type)
        if self.db_type == "sqlite":
            return await self.conn.execute(q, params)
        
        if "BEGIN" in q.upper():
            self.pg_tr = self.conn.transaction()
            await self.pg_tr.start()
            return AsyncpgCursorWrapper(self.conn, "", ())
            
        wrapper = AsyncpgCursorWrapper(self.conn, q, params)
        if not q.strip().upper().startswith("SELECT"):
            await wrapper._run()
        return wrapper

    async def commit(self):
        if self.db_type == "sqlite":
            await self.conn.commit()
        elif self.pg_tr:
            await self.pg_tr.commit()
            self.pg_tr = None
            
    async def rollback(self):
        if self.db_type == "sqlite":
            await self.conn.rollback()
        elif self.pg_tr:
            await self.pg_tr.rollback()
            self.pg_tr = None
            
    async def close(self):
        await self.conn.close()

async def get_db_connection(path: str) -> DBConnectionWrapper:
    db_type = os.environ.get("DB_TYPE", "sqlite").strip().lower()
    if db_type == "postgres":
        import asyncpg
        conn = await asyncpg.connect(
            database=os.environ.get("DB_NAME", "bananabot"),
            user=os.environ.get("DB_USER", "bananabot"),
            password=os.environ.get("DB_PASS", ""),
            host=os.environ.get("DB_HOST", "127.0.0.1"),
            port=os.environ.get("DB_PORT", "5432"),
            timeout=30.0
        )
        return DBConnectionWrapper(conn, db_type)
    else:
        import aiosqlite
        conn = await aiosqlite.connect(path, timeout=30.0)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        return DBConnectionWrapper(conn, db_type)
