import os
import sqlite3
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "digest.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT NOT NULL DEFAULT 'daily_digest',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_seconds REAL,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    llm_provider TEXT,
    llm_model TEXT,
    posts_scraped INTEGER DEFAULT 0,
    free_agents_fetched INTEGER DEFAULT 0,
    roster_size INTEGER DEFAULT 0,
    league_transactions INTEGER DEFAULT 0,
    prompt_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    thinking_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0
);
"""

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
    if "run_type" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN run_type TEXT NOT NULL DEFAULT 'daily_digest'")
        conn.commit()
    return conn

def start_run(run_type="daily_digest"):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO runs (run_type, started_at, status) VALUES (?, ?, 'running')",
        (run_type, datetime.now().isoformat()),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id

def update_run(run_id, **fields):
    if not fields:
        return
    conn = get_connection()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE runs SET {cols} WHERE id = ?", (*fields.values(), run_id))
    conn.commit()
    conn.close()

def finish_run(run_id, status="success", error_message=None, **fields):
    fields["status"] = status
    fields["error_message"] = error_message
    fields["finished_at"] = datetime.now().isoformat()
    update_run(run_id, **fields)

def get_today_spend(run_type=None):
    """Spend today, optionally scoped to one run_type so draft prep and the daily
    digest are capped independently."""
    conn = get_connection()
    today = date.today().isoformat()
    sql = (
        "SELECT COALESCE(SUM(estimated_cost_usd), 0) AS total FROM runs "
        "WHERE date(started_at) = ? AND status IN ('success', 'error')"
    )
    params = [today]
    if run_type:
        sql += " AND run_type = ?"
        params.append(run_type)
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row["total"]

def get_recent_runs(limit=10):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
