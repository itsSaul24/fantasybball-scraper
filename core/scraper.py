import re
import time
import requests
import xml.etree.ElementTree as ET
from html import unescape

HEADERS = {"User-Agent": "fantasybball-digest-bot/1.0 (personal project)"}
SUBREDDITS = ["fantasybball", "nba"]
ATOM_NS = "{http://www.w3.org/2005/Atom}"

# Unauthenticated Reddit RSS is tightly rate-limited (~1 request per ~7-10s as of Aug 2026).
# The old .json scraping endpoints are now challenge-walled entirely, so this project reads
# public subreddit/comment RSS feeds instead. No vote scores or comment counts are exposed
# via RSS, so "hot" ranking order is used as the engagement signal instead of a score filter.
MIN_REQUEST_INTERVAL = 10
_last_request_time = 0

def _throttled_get(url, retries=3):
    global _last_request_time
    for attempt in range(retries):
        elapsed = time.time() - _last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        res = requests.get(url, headers=HEADERS, timeout=10)
        _last_request_time = time.time()
        if res.status_code == 429:
            wait = int(res.headers.get("x-ratelimit-reset", 10)) + 2
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue
        return res
    return res

def _strip_html(html_text):
    text = re.sub(r"<!--.*?-->", "", html_text or "", flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def _parse_feed(res, subreddit):
    root = ET.fromstring(res.text)
    posts = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        title = entry.findtext(f"{ATOM_NS}title", "") or ""
        link_el = entry.find(f"{ATOM_NS}link")
        link = link_el.get("href") if link_el is not None else ""
        content_html = entry.findtext(f"{ATOM_NS}content", "") or ""
        full_id = entry.findtext(f"{ATOM_NS}id", "") or ""
        short_id = full_id.split("_")[-1] if "_" in full_id else full_id
        # When a post was actually written — essential for an offseason draft build, where
        # a year-sorted feed is dominated by last season's now-obsolete in-season chatter.
        published = (entry.findtext(f"{ATOM_NS}published", "")
                     or entry.findtext(f"{ATOM_NS}updated", "") or "")
        posts.append({
            "title": title,
            "body": _strip_html(content_html)[:1500],
            "score": None,       # not exposed via RSS
            "flair": "",         # not exposed via RSS
            "url": link,
            "num_comments": None,
            "id": short_id,
            "subreddit": subreddit,
            "published": published[:10],
        })
    return posts

def search_posts(subreddit, query, limit=25, time_filter="year", sort="top"):
    """Targeted subreddit search — far higher signal density for draft prep than
    generic hot/top sorts, which surface league-admin chatter and memes."""
    url = (
        f"https://www.reddit.com/r/{subreddit}/search.rss?q={requests.utils.quote(query)}"
        f"&restrict_sr=1&sort={sort}&t={time_filter}&limit={limit}"
    )
    try:
        res = _throttled_get(url)
        if res.status_code != 200:
            print(f"  search '{query}' failed: HTTP {res.status_code}")
            return []
        return _parse_feed(res, subreddit)
    except Exception as e:
        print(f"  search '{query}' failed: {e}")
        return []

def fetch_posts(subreddit, sort="hot", limit=40, time_filter=None):
    url = f"https://www.reddit.com/r/{subreddit}/{sort}/.rss?limit={limit}"
    if time_filter:
        url += f"&t={time_filter}"
    try:
        res = _throttled_get(url)
        if res.status_code != 200:
            print(f"Error fetching r/{subreddit}: HTTP {res.status_code}")
            return []
        return _parse_feed(res, subreddit)
    except Exception as e:
        print(f"Error fetching r/{subreddit}: {e}")
        return []

def fetch_top_comments(subreddit, post_id, limit=5):
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/.rss?limit={limit + 1}"
    try:
        res = _throttled_get(url)
        if res.status_code != 200:
            return []
        root = ET.fromstring(res.text)
        comments = []
        for entry in root.findall(f"{ATOM_NS}entry"):
            full_id = entry.findtext(f"{ATOM_NS}id", "") or ""
            if not full_id.startswith("t1_"):  # skip the submission itself (t3_)
                continue
            content_html = entry.findtext(f"{ATOM_NS}content", "") or ""
            body = _strip_html(content_html)
            if not body or len(body) < 30:
                continue
            comments.append(body[:400])
            if len(comments) >= limit:
                break
        return comments
    except Exception:
        return []

def scrape_all():
    print("Scraping r/fantasybball...")
    fb_hot = fetch_posts("fantasybball", sort="hot", limit=40)
    fb_new = fetch_posts("fantasybball", sort="new", limit=25)

    print("Scraping r/nba for injury news...")
    nba_posts = fetch_posts("nba", sort="top", limit=25, time_filter="day")

    all_posts = fb_hot + fb_new + nba_posts

    # Deduplicate by title
    seen = set()
    unique = []
    for p in all_posts:
        if p["title"] not in seen:
            seen.add(p["title"])
            unique.append(p)

    # Fetch comments for the top posts by hot-ranking (RSS has no score to filter on,
    # so hot-sort position is used as the engagement signal instead)
    top_for_comments = fb_hot[:10]
    print(f"Fetching comments for top {len(top_for_comments)} posts by hot ranking...")

    for i, post in enumerate(top_for_comments):
        comments = fetch_top_comments(post["subreddit"], post["id"], limit=5)
        for p in unique:
            if p["id"] == post["id"]:
                p["comments"] = comments
                break
        if comments:
            print(f"  [{i+1}] '{post['title'][:50]}...' — {len(comments)} comments")

    for p in unique:
        if "comments" not in p:
            p["comments"] = []

    print(f"Fetched {len(unique)} unique posts total.")
    return unique
