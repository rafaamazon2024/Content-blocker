"""
Database abstraction layer.
- DATABASE_URL set → PostgreSQL (Render/VPS)
- Otherwise       → SQLite local (blocker.db)
"""
import os, sqlite3
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
DB_PATH      = os.getenv("DB_PATH", "blocker.db")

_pg_conn = None

def get_pg_conn():
    global _pg_conn
    import psycopg2, psycopg2.extras
    try:
        if _pg_conn is None or _pg_conn.closed:
            _pg_conn = psycopg2.connect(DATABASE_URL)
            _pg_conn.autocommit = False
        else:
            _pg_conn.isolation_level
    except Exception:
        _pg_conn = psycopg2.connect(DATABASE_URL)
        _pg_conn.autocommit = False
    return _pg_conn

def _ph():
    """Return the right placeholder for the active backend."""
    return "%s" if DATABASE_URL else "?"

def fetchall(sql, params=()):
    if DATABASE_URL:
        global _pg_conn
        import psycopg2.extras
        for attempt in range(3):
            try:
                conn = get_pg_conn()
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, params)
                    return [dict(r) for r in cur.fetchall()]
            except Exception:
                _pg_conn = None
                if attempt == 2:
                    raise
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

def fetchone(sql, params=()):
    rows = fetchall(sql, params)
    return rows[0] if rows else None

def execute(sql, params=()):
    if DATABASE_URL:
        global _pg_conn
        for attempt in range(3):
            try:
                conn = get_pg_conn()
                cur = conn.cursor()
                cur.execute(sql, params)
                conn.commit()
                return
            except Exception:
                _pg_conn = None
                if attempt == 2:
                    raise
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(sql, params)
        conn.commit()

def executemany(sql, data):
    if DATABASE_URL:
        global _pg_conn
        import time as _time
        BATCH = 500
        for i in range(0, len(data), BATCH):
            lote = data[i:i + BATCH]
            for attempt in range(5):
                try:
                    conn = get_pg_conn()
                    cur = conn.cursor()
                    cur.executemany(sql, lote)
                    conn.commit()
                    break
                except Exception:
                    _pg_conn = None
                    _time.sleep(3)
                    if attempt == 4:
                        raise
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.executemany(sql, data)
        conn.commit()

def init_db():
    if DATABASE_URL:
        _init_pg()
    else:
        _init_sqlite()

def _init_sqlite():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS blocklist (
        domain      TEXT PRIMARY KEY,
        category    TEXT DEFAULT 'adult',
        source      TEXT DEFAULT 'manual',
        created_at  TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS query_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        domain      TEXT NOT NULL,
        client_ip   TEXT,
        blocked     INTEGER DEFAULT 0,
        ts          TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS settings (
        key         TEXT PRIMARY KEY,
        value       TEXT
    );
    CREATE TABLE IF NOT EXISTS unlock_requests (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        reason          TEXT,
        requested_at    TEXT DEFAULT (datetime('now')),
        unlock_at       TEXT,
        status          TEXT DEFAULT 'pending'
    );
    CREATE INDEX IF NOT EXISTS idx_logs_domain ON query_logs(domain);
    CREATE INDEX IF NOT EXISTS idx_logs_ts     ON query_logs(ts);
    """)
    conn.commit()

def _init_pg():
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS blocklist (
        domain      TEXT PRIMARY KEY,
        category    TEXT DEFAULT 'adult',
        source      TEXT DEFAULT 'manual',
        created_at  TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS query_logs (
        id          SERIAL PRIMARY KEY,
        domain      TEXT NOT NULL,
        client_ip   TEXT,
        blocked     BOOLEAN DEFAULT FALSE,
        ts          TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS settings (
        key         TEXT PRIMARY KEY,
        value       TEXT
    );
    CREATE TABLE IF NOT EXISTS unlock_requests (
        id              SERIAL PRIMARY KEY,
        reason          TEXT,
        requested_at    TIMESTAMPTZ DEFAULT NOW(),
        unlock_at       TIMESTAMPTZ,
        status          TEXT DEFAULT 'pending'
    );
    """)
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_domain ON query_logs(domain)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_ts     ON query_logs(ts)")
    except Exception:
        pass
    conn.commit()
    conn.close()
