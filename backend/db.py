import sqlite3
from contextlib import contextmanager

DB_PATH = "/app/data/app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS tracks (
    uri TEXT PRIMARY KEY,
    title TEXT,
    album_name TEXT,
    image_url TEXT,
    artist_id TEXT,
    added_at TEXT,
    duration_ms INTEGER,
    is_hidden INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS artists (
    id TEXT PRIMARY KEY,
    name TEXT,
    genres TEXT
);

CREATE TABLE IF NOT EXISTS blocked_artists (
    artist_id TEXT PRIMARY KEY,
    name TEXT
);

CREATE TABLE IF NOT EXISTS blocked_genres (
    genre_name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS invites (
    jti TEXT PRIMARY KEY,
    email TEXT,
    created_at INTEGER,
    expires_at INTEGER,
    last_seen_at INTEGER,
    revoked_at INTEGER
);

CREATE TABLE IF NOT EXISTS error_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT,
    occurred_at INTEGER
);
"""


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()


def _migrate(conn):
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(tracks)")}
    if "duration_ms" not in columns:
        conn.execute("ALTER TABLE tracks ADD COLUMN duration_ms INTEGER")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_state(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_state(key: str, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()
