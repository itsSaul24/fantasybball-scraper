from core.scraper import fetch_posts, fetch_top_comments, search_posts

# Targeted queries carry far higher signal density than generic hot/top sorts, which fill up
# with league-admin chatter and memes. These aim at the discourse that actually moves a
# draft valuation: role changes, hype, fades, and published rankings.
DRAFT_QUERIES = [
    "auction values", "auction draft strategy", "sleeper", "breakout candidate",
    "bust candidate", "rankings", "ADP", "draft targets", "avoid this year",
    "post hype", "role change", "usage", "minutes", "depth chart",
    "rookie impact", "trade impact fantasy", "points league rankings", "buy low",
]

def scrape_for_draft(comment_fetch_limit=110):
    """One-time broad scrape for pre-draft prep. Combines targeted searches with general
    sorts, then pulls comment threads on the highest-signal posts. Comments are where the
    actual analysis lives, so the comment budget is the main quality lever here.

    Deliberately weighted toward RECENT content: a year-sorted feed is dominated by last
    season's in-season chatter describing rosters that trades and free agency have since
    changed. The discourse that matters for an upcoming draft is happening right now.
    Slow by nature — Reddit's unauthenticated RSS allows roughly one request per ~10-50s."""
    print("Broad draft-prep scrape starting (slow: Reddit rate limits)...")

    searched = []
    for i, q in enumerate(DRAFT_QUERIES):
        # 'month' + 'new' surfaces live offseason draft prep; 'year'+top would return
        # last season's greatest hits instead.
        results = search_posts("fantasybball", q, limit=25, time_filter="month", sort="new")
        if len(results) < 8:  # thin query — widen the window rather than lose the topic
            results += search_posts("fantasybball", q, limit=25, time_filter="year", sort="top")
        print(f"  [search {i+1}/{len(DRAFT_QUERIES)}] '{q}' -> {len(results)} posts")
        searched.extend(results)

    print("  Fetching general sorts...")
    general = (
        fetch_posts("fantasybball", sort="new", limit=100)
        + fetch_posts("fantasybball", sort="hot", limit=100)
        + fetch_posts("fantasybball", sort="top", limit=100, time_filter="month")
        + fetch_posts("fantasybball", sort="top", limit=50, time_filter="week")
        + fetch_posts("nba", sort="top", limit=50, time_filter="month")
        + fetch_posts("nba", sort="hot", limit=40)
    )

    seen, unique = set(), []
    for p in searched + general:          # search results first — they rank higher for comments
        if p["title"] not in seen:
            seen.add(p["title"])
            unique.append(p)

    # Prioritize search hits for comment fetching; they are the most on-topic threads.
    priority, seen_ids = [], set()
    for p in searched + general:
        if p["id"] not in seen_ids and p["id"]:
            seen_ids.add(p["id"])
            priority.append(p)
    to_fetch = priority[:comment_fetch_limit]

    print(f"  Fetching comments for {len(to_fetch)} posts (the slow part)...")
    by_id = {p["id"]: p for p in unique}
    for i, post in enumerate(to_fetch):
        comments = fetch_top_comments(post["subreddit"], post["id"], limit=8)
        if post["id"] in by_id:
            by_id[post["id"]]["comments"] = comments
        if comments and (i + 1) % 10 == 0:
            print(f"    [{i+1}/{len(to_fetch)}] ...")

    for p in unique:
        p.setdefault("comments", [])

    total_comments = sum(len(p["comments"]) for p in unique)
    with_comments = sum(1 for p in unique if p["comments"])
    print(f"Scrape complete: {len(unique)} posts, {with_comments} with comments, {total_comments} comments total.")
    return unique
