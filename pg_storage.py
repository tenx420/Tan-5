# pg_storage.py
"""
Tiny helper: save one big TinyDB blob in row id = 1 of table `tinydb`
and read it back on startup.
"""
import json, os, contextlib, psycopg2

# Heroku gives you postgres:// – psycopg2 prefers postgresql://
URL = os.environ["DATABASE_URL"].replace("postgres://", "postgresql://")

def _conn():
    # sslmode=require is Heroku’s default
    return psycopg2.connect(URL, sslmode="require")

def load_db_json() -> dict:
    """Return previous TinyDB contents (or {} on first run)."""
    with contextlib.closing(_conn()) as c, c.cursor() as cur:
        # ➊ ensure the table exists
        cur.execute(
            "CREATE TABLE IF NOT EXISTS tinydb ("
            "id int primary key, "
            "data jsonb)"
        )
        c.commit()                          # <-- NEW: commit the DDL
        # ➋ fetch blob (row id = 1) if present
        cur.execute("SELECT data FROM tinydb WHERE id = 1")
        row = cur.fetchone()
        return row[0] if row else {}

def save_db_json(data: dict) -> None:
    """Overwrite row 1 with the fresh TinyDB JSON dump."""
    with contextlib.closing(_conn()) as c, c.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tinydb (id, data) VALUES (1, %s)
            ON CONFLICT (id) DO UPDATE
              SET data = EXCLUDED.data
            """,
            [json.dumps(data)],
        )
        c.commit()
