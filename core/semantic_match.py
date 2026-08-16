import os
import unicodedata
from datetime import datetime
import numpy as np
from google import genai
from google.genai import types
from dotenv import load_dotenv
load_dotenv()

from core.vector_store import (
    EMBED_DIM, upsert_documents, save_embeddings, load_embeddings, record_mentions,
)

EMBED_MODEL = "gemini-embedding-001"
EMBED_BATCH_SIZE = 100
EMBED_PRICE_PER_1M = 0.20
MIN_CHUNK_CHARS = 60

def _client():
    return genai.Client(api_key=os.environ["GEMINI_KEY"])

def _norm(text):
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()

def embed_texts(texts, dim=EMBED_DIM):
    """Batched embeddings. Returns (N, dim) array and an estimated token count
    (the API does not expose exact usage for embeddings)."""
    client = _client()
    config = types.EmbedContentConfig(output_dimensionality=dim)
    vectors = []
    char_count = 0
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        result = client.models.embed_content(model=EMBED_MODEL, contents=batch, config=config)
        vectors.extend(e.values for e in result.embeddings)
        char_count += sum(len(t) for t in batch)
    return np.array(vectors), char_count // 4

def embed_and_store(chunks, run_id=None):
    """Persists chunks and embeds only the ones we have never seen before. Returns
    (document_ids, texts, cost_usd, stats)."""
    records = upsert_documents(chunks, run_id=run_id)
    missing = [(doc_id, text) for doc_id, text, has_vec in records if not has_vec]

    cost = 0.0
    if missing:
        vecs, tokens = embed_texts([t for _, t in missing])
        save_embeddings(list(zip([d for d, _ in missing], vecs)), EMBED_MODEL)
        cost = estimate_embedding_cost(tokens)

    doc_ids = [doc_id for doc_id, _, _ in records]
    texts = [text for _, text, _ in records]
    stats = {"total": len(records), "newly_embedded": len(missing),
             "reused": len(records) - len(missing)}
    return doc_ids, texts, cost, stats

def estimate_embedding_cost(total_tokens):
    return round(total_tokens / 1_000_000 * EMBED_PRICE_PER_1M, 6)

def build_chunks(posts, max_chunk_chars=1400):
    """Splits the corpus into independently-searchable units: each post's title+body is one
    chunk, and EVERY COMMENT is its own chunk. Embedding a post together with all its
    comments averages distinct opinions into one blurred vector — chunking keeps a single
    sharp take ('JJ is pedestrian since the CJ trade') retrievable on its own."""
    chunks = []
    for p in posts:
        header = p.get("title", "")
        body = " ".join(t for t in [header, p.get("body", "")] if t).strip()
        meta = {"subreddit": p.get("subreddit"), "post_id": p.get("id"), "title": header,
                "published": p.get("published", "")}
        if len(body) >= MIN_CHUNK_CHARS:
            chunks.append({"text": body[:max_chunk_chars], "kind": "post", **meta})
        for c in p.get("comments", []):
            if len(c) >= MIN_CHUNK_CHARS:
                chunks.append({"text": f"[re: {header}] {c}"[:max_chunk_chars],
                               "kind": "comment", **meta})
    return chunks

def _drop_near_duplicates(indices, texts, threshold=0.82):
    """Megathreads and quoted replies repeat heavily; exact-hash dedup misses them. Keeps
    the first occurrence and skips later chunks with high token overlap, so a player's
    limited context slots hold distinct opinions rather than the same take three times."""
    kept, kept_sets = [], []
    for j in indices:
        words = set(texts[j].lower().split())
        if not words:
            continue
        if any(len(words & prev) / min(len(words), len(prev)) >= threshold for prev in kept_sets):
            continue
        kept.append(j)
        kept_sets.append(words)
    return kept

def _recency_weight(published, half_life_days=75.0, floor=0.35):
    """Exponential decay on publish date. Floored rather than zeroed so a strongly relevant
    older post still beats a weakly relevant new one."""
    if not published:
        return 0.7  # unknown date — mild penalty, not a disqualification
    try:
        age = (datetime.now().date() - datetime.fromisoformat(published[:10]).date()).days
    except ValueError:
        return 0.7
    return float(max(floor, 0.5 ** (max(age, 0) / half_life_days)))

def semantic_match_context(
    players_df, posts, top_k=8, min_raw_similarity=0.55, min_distinctiveness=0.012,
    run_id=None, history_days=400, use_history=True, half_life_days=75.0,
):
    """Chunk-level AI semantic search over the accumulated Reddit corpus.

    Chunks are persisted and embedded once — later runs reuse the stored vectors and search
    the whole accumulated history, not just today's scrape. Scores by DISTINCTIVENESS (how
    much more relevant a chunk is to this player than to the average player) rather than raw
    similarity, since generic threads like 'my top 100 rankings' otherwise rank highly for
    every star and crowd out specific discussion.
    Returns ({player_id: [snippets]}, estimated_cost_usd, stats_dict)."""
    chunks = build_chunks(posts)
    if not chunks and not use_history:
        return {pid: [] for pid in players_df["PLAYER_ID"]}, 0.0, {"chunks": 0}

    n_comments = sum(1 for c in chunks if c["kind"] == "comment")
    doc_ids, texts, embed_cost, store_stats = embed_and_store(chunks, run_id=run_id)
    print(f"  Corpus: {store_stats['total']} chunks this run ({n_comments} comment-level) — "
          f"{store_stats['newly_embedded']} newly embedded, {store_stats['reused']} reused from store")

    if use_history:
        doc_ids, texts, dates, chunk_vecs = load_embeddings(since_days=history_days)
        print(f"  Searching {len(doc_ids)} chunks published within {history_days} days")
    else:
        doc_ids, texts, dates, chunk_vecs = load_embeddings(document_ids=doc_ids)

    if len(doc_ids) == 0:
        return {pid: [] for pid in players_df["PLAYER_ID"]}, embed_cost, {"chunks": 0}

    chunk_norms = chunk_vecs / np.linalg.norm(chunk_vecs, axis=1, keepdims=True)

    queries = [
        f"{row['PLAYER_NAME']} ({row['current_team']}) NBA fantasy basketball outlook this season"
        for _, row in players_df.iterrows()
    ]
    q_vecs, q_tokens = embed_texts(queries)
    q_norms = q_vecs / np.linalg.norm(q_vecs, axis=1, keepdims=True)

    raw = q_norms @ chunk_norms.T
    distinctive = raw - raw.mean(axis=0, keepdims=True)

    # Recency weighting: an August post about next season outranks an equally-similar
    # take from mid-season, which describes rosters that have since changed.
    recency = np.array([_recency_weight(d, half_life_days) for d in dates])
    ranked = distinctive * recency[np.newaxis, :]

    context = {}
    mentions = []
    matched = 0
    for i, (_, row) in enumerate(players_df.iterrows()):
        order = [j for j in np.argsort(-ranked[i])[:top_k * 3]
                 if distinctive[i][j] >= min_distinctiveness and raw[i][j] >= min_raw_similarity]
        keep = _drop_near_duplicates(order, texts)[:top_k]
        context[row["PLAYER_ID"]] = [
            f"({dates[j]}) {texts[j]}" if dates[j] else texts[j] for j in keep
        ]
        mentions.extend(
            (doc_ids[j], int(row["PLAYER_ID"]), row["PLAYER_NAME"], raw[i][j], distinctive[i][j])
            for j in keep
        )
        if keep:
            matched += 1

    record_mentions(mentions, run_id=run_id)

    stats = {"chunks": len(doc_ids), "comment_chunks": n_comments, "players_matched": matched,
             "newly_embedded": store_stats["newly_embedded"], "reused": store_stats["reused"],
             "mentions_recorded": len(mentions)}
    return context, embed_cost + estimate_embedding_cost(q_tokens), stats
