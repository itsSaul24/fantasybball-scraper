import json
import os
import time
from datetime import datetime

from core.scraper import fetch_posts, fetch_top_comments, search_posts
from core.vector_store import stored_comments_by_post

# Targeted queries carry far higher signal density than generic hot/top sorts, which fill up
# with league-admin chatter and memes. These aim at the discourse that actually moves a
# draft valuation: role changes, hype, fades, and published rankings.
DRAFT_QUERIES = [
    "auction values", "auction draft strategy", "sleeper", "breakout candidate",
    "bust candidate", "rankings", "ADP", "draft targets", "avoid this year",
    "post hype", "role change", "usage", "minutes", "depth chart",
    "rookie impact", "trade impact fantasy", "points league rankings", "buy low",
]

# (subreddit, sort, limit, time_filter)
GENERAL_SORTS = [
    ("fantasybball", "new", 100, None),
    ("fantasybball", "hot", 100, None),
    ("fantasybball", "top", 100, "month"),
    ("fantasybball", "top", 50, "week"),
    ("nba", "top", 50, "month"),
    ("nba", "hot", 40, None),
]

CHECKPOINT_MAX_AGE_HOURS = 24

def _load_checkpoint(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        state = json.load(f)
    age_h = (datetime.now() - datetime.fromisoformat(state["started"])).total_seconds() / 3600
    if age_h > CHECKPOINT_MAX_AGE_HOURS:
        print(f"  Checkpoint is {age_h:.0f}h old — starting a fresh scrape.")
        return None
    return state

def _save_checkpoint(path, state):
    if not path:
        return
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, path)   # atomic: a kill mid-write can't corrupt the checkpoint

def scrape_for_draft(comment_fetch_limit=110, checkpoint_path=None, time_budget_s=None):
    """Broad draft-prep scrape: targeted searches, general sorts, then comment threads on the
    highest-signal posts. Comments are where the analysis lives, so they are the main lever.

    Weighted toward RECENT content: a year-sorted feed is dominated by last season's
    in-season chatter about rosters that have since changed.

    Resumable. Reddit's unauthenticated RSS allows roughly one request per ~50s, so a full
    scrape takes about two hours. Progress is checkpointed after every request; with a
    time_budget_s the call stops cleanly at the deadline and a later call picks up where it
    left off. Comment threads already archived in the vector store are reused rather than
    re-fetched.

    Returns (posts, complete). posts is None while incomplete."""
    state = _load_checkpoint(checkpoint_path) or {
        "started": datetime.now().isoformat(), "queries": {}, "sorts": {}, "comments": {},
    }
    deadline = time.time() + time_budget_s if time_budget_s else None

    def out_of_time():
        return deadline is not None and time.time() > deadline

    def stop():
        _save_checkpoint(checkpoint_path, state)
        done = (len(state["queries"]) + len(state["sorts"]) + len(state["comments"]))
        print(f"  Time budget reached — checkpoint saved ({done} requests done). Run again to resume.")
        return None, False

    pending = [q for q in DRAFT_QUERIES if q not in state["queries"]]
    if pending:
        print(f"  Searches: {len(DRAFT_QUERIES) - len(pending)}/{len(DRAFT_QUERIES)} done")
    for q in pending:
        if out_of_time():
            return stop()
        results = search_posts("fantasybball", q, limit=25, time_filter="month", sort="new")
        if len(results) < 8:   # thin query — widen the window rather than lose the topic
            results += search_posts("fantasybball", q, limit=25, time_filter="year", sort="top")
        state["queries"][q] = results
        _save_checkpoint(checkpoint_path, state)
        print(f"  [search {len(state['queries'])}/{len(DRAFT_QUERIES)}] '{q}' -> {len(results)} posts")

    for sub, sort, limit, tf in GENERAL_SORTS:
        key = f"{sub}/{sort}/{tf or 'all'}"
        if key in state["sorts"]:
            continue
        if out_of_time():
            return stop()
        state["sorts"][key] = fetch_posts(sub, sort=sort, limit=limit, time_filter=tf)
        _save_checkpoint(checkpoint_path, state)
        print(f"  [sort] {key} -> {len(state['sorts'][key])} posts")

    searched = [p for q in DRAFT_QUERIES for p in state["queries"].get(q, [])]
    general = [p for v in state["sorts"].values() for p in v]

    # Search hits first: they are the most on-topic threads.
    priority, seen_ids = [], set()
    for p in searched + general:
        if p["id"] and p["id"] not in seen_ids:
            seen_ids.add(p["id"])
            priority.append(p)
    to_fetch = priority[:comment_fetch_limit]

    archived = stored_comments_by_post()
    reused = 0
    for post in to_fetch:
        if post["id"] not in state["comments"] and post["id"] in archived:
            state["comments"][post["id"]] = archived[post["id"]]
            reused += 1
    remaining = [p for p in to_fetch if p["id"] not in state["comments"]]
    print(f"  Comment threads: {len(to_fetch) - len(remaining)}/{len(to_fetch)} in hand "
          f"({reused} reused from the archive), {len(remaining)} to fetch")

    for i, post in enumerate(remaining):
        if out_of_time():
            return stop()
        state["comments"][post["id"]] = fetch_top_comments(post["subreddit"], post["id"], limit=8)
        _save_checkpoint(checkpoint_path, state)
        if (i + 1) % 10 == 0:
            print(f"    [{i + 1}/{len(remaining)}] comment threads fetched")

    seen, unique = set(), []
    for p in searched + general:
        if p["title"] not in seen:
            seen.add(p["title"])
            unique.append(dict(p, comments=state["comments"].get(p["id"], [])))

    total_comments = sum(len(p["comments"]) for p in unique)
    with_comments = sum(1 for p in unique if p["comments"])
    print(f"Scrape complete: {len(unique)} posts, {with_comments} with comments, "
          f"{total_comments} comments total.")
    return unique, True
