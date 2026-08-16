import hashlib
import numpy as np
from datetime import datetime, timedelta

from core.db import get_connection

# 768 dims via Matryoshka truncation: 8x smaller than the 3072 default at negligible
# retrieval loss. Vectors are stored float16 (1.5 KB/chunk), so a full season of daily
# runs lands around 40 MB rather than 300 MB+.
EMBED_DIM = 768
STORE_DTYPE = np.float16

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT 'reddit',
    subreddit TEXT,
    post_id TEXT,
    kind TEXT,
    title TEXT,
    text TEXT NOT NULL,
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    run_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_documents_first_seen ON documents(first_seen_at);

CREATE TABLE IF NOT EXISTS embeddings (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS player_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL,
    player_name TEXT,
    similarity REAL,
    distinctiveness REAL,
    seen_at TEXT NOT NULL,
    run_id INTEGER,
    UNIQUE(document_id, player_id)
);
CREATE INDEX IF NOT EXISTS idx_mentions_player ON player_mentions(player_id, seen_at);
"""

def _connect():
    conn = get_connection()
    conn.executescript(SCHEMA)
    # Migrate before indexing: a pre-existing table skips CREATE TABLE, so an index on a
    # newly added column must wait until the ALTER has run.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(documents)")}
    if "published_at" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN published_at TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_published ON documents(published_at)")
    conn.commit()
    return conn

def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def upsert_documents(chunks, run_id=None):
    """Stores chunks, deduplicating by content hash. Re-seeing a chunk only bumps
    last_seen_at. Returns [(document_id, text, already_embedded)] in input order."""
    conn = _connect()
    now = datetime.now().isoformat()
    out = []
    for c in chunks:
        h = content_hash(c["text"])
        row = conn.execute(
            "SELECT d.id, (e.document_id IS NOT NULL) AS has_vec FROM documents d "
            "LEFT JOIN embeddings e ON e.document_id = d.id WHERE d.content_hash = ?",
            (h,),
        ).fetchone()
        if row:
            # Backfill published_at for rows stored before dates were captured.
            conn.execute(
                "UPDATE documents SET last_seen_at = ?,"
                " published_at = COALESCE(published_at, ?) WHERE id = ?",
                (now, c.get("published") or None, row["id"]),
            )
            out.append((row["id"], c["text"], bool(row["has_vec"])))
        else:
            cur = conn.execute(
                "INSERT INTO documents (content_hash, source, subreddit, post_id, kind, title,"
                " text, published_at, first_seen_at, last_seen_at, run_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (h, c.get("source", "reddit"), c.get("subreddit"), c.get("post_id"),
                 c.get("kind"), c.get("title"), c["text"], c.get("published") or None,
                 now, now, run_id),
            )
            out.append((cur.lastrowid, c["text"], False))
    conn.commit()
    conn.close()
    return out

def save_embeddings(doc_vectors, model):
    """doc_vectors: [(document_id, np.ndarray)]"""
    conn = _connect()
    conn.executemany(
        "INSERT OR REPLACE INTO embeddings (document_id, model, dim, vector) VALUES (?,?,?,?)",
        [(doc_id, model, len(v), np.asarray(v, dtype=STORE_DTYPE).tobytes())
         for doc_id, v in doc_vectors],
    )
    conn.commit()
    conn.close()

def load_embeddings(document_ids=None, since_days=None):
    """Returns (ids, texts, dates, matrix).

    Recency filters on published_at — when the content was WRITTEN — not on when we
    happened to scrape it. Filtering on scrape time would keep year-old posts alive
    forever simply because we re-saw them today. Rows with no known publish date are
    kept, since dropping them would silently discard the pre-date-capture corpus."""
    conn = _connect()
    sql = (
        "SELECT d.id, d.text, d.published_at, e.vector FROM documents d "
        "JOIN embeddings e ON e.document_id = d.id"
    )
    clauses, params = [], []
    if document_ids is not None:
        if not document_ids:
            conn.close()
            return [], [], [], np.zeros((0, EMBED_DIM))
        clauses.append(f"d.id IN ({','.join('?' * len(document_ids))})")
        params.extend(document_ids)
    if since_days:
        cutoff = (datetime.now() - timedelta(days=since_days)).date().isoformat()
        clauses.append("(d.published_at IS NULL OR d.published_at >= ?)")
        params.append(cutoff)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    if not rows:
        return [], [], [], np.zeros((0, EMBED_DIM))
    ids = [r["id"] for r in rows]
    texts = [r["text"] for r in rows]
    dates = [r["published_at"] or "" for r in rows]
    mat = np.vstack([np.frombuffer(r["vector"], dtype=STORE_DTYPE).astype(np.float32) for r in rows])
    return ids, texts, dates, mat

def record_mentions(mentions, run_id=None):
    """mentions: [(document_id, player_id, player_name, similarity, distinctiveness)]"""
    if not mentions:
        return
    conn = _connect()
    now = datetime.now().isoformat()
    conn.executemany(
        "INSERT INTO player_mentions (document_id, player_id, player_name, similarity,"
        " distinctiveness, seen_at, run_id) VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(document_id, player_id) DO NOTHING",
        [(d, p, n, float(s), float(x), now, run_id) for d, p, n, s, x in mentions],
    )
    conn.commit()
    conn.close()

def player_mention_history(player_id, days=45):
    """Daily mention counts for one player — the longitudinal signal that only exists
    once the corpus accumulates across runs."""
    conn = _connect()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT date(seen_at) AS day, COUNT(*) AS n, AVG(distinctiveness) AS avg_distinct "
        "FROM player_mentions WHERE player_id = ? AND seen_at >= ? GROUP BY day ORDER BY day",
        (player_id, cutoff),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def store_stats():
    conn = _connect()
    stats = {
        "documents": conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"],
        "embeddings": conn.execute("SELECT COUNT(*) c FROM embeddings").fetchone()["c"],
        "mentions": conn.execute("SELECT COUNT(*) c FROM player_mentions").fetchone()["c"],
        "oldest": conn.execute("SELECT MIN(first_seen_at) d FROM documents").fetchone()["d"],
    }
    conn.close()
    return stats
