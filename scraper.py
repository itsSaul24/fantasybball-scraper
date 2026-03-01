import requests
import time

HEADERS = {"User-Agent": "fantasybball-digest-bot/1.0 (personal project)"}

SUBREDDITS = ["fantasybball", "nba"]

def fetch_posts(subreddit, sort="hot", limit=75, time_filter=None):
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit={limit}"
    if time_filter:
        url += f"&t={time_filter}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        data = res.json()
        posts = []
        for post in data["data"]["children"]:
            p = post["data"]
            if p.get("score", 0) < 10:
                continue
            posts.append({
                "title": p.get("title", ""),
                "body": p.get("selftext", "")[:600],
                "score": p.get("score", 0),
                "flair": p.get("link_flair_text", ""),
                "url": p.get("url", ""),
                "num_comments": p.get("num_comments", 0),
            })
        return posts
    except Exception as e:
        print(f"Error fetching r/{subreddit}: {e}")
        return []

def fetch_top_comments(subreddit, post_id, limit=5):
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json?limit={limit}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        data = res.json()
        comments = []
        for c in data[1]["data"]["children"]:
            body = c["data"].get("body", "")
            if body and len(body) > 20:
                comments.append(body[:300])
        return comments
    except:
        return []

def scrape_all():
    print("Scraping r/fantasybball...")
    fb_hot = fetch_posts("fantasybball", sort="hot", limit=75)
    time.sleep(2)
    fb_top = fetch_posts("fantasybball", sort="top", limit=50, time_filter="day")
    time.sleep(2)
    fb_new = fetch_posts("fantasybball", sort="new", limit=50)
    time.sleep(2)

    print("Scraping r/nba for injury news...")
    nba_posts = fetch_posts("nba", sort="top", limit=30, time_filter="day")

    all_posts = fb_hot + fb_top + fb_new + nba_posts

    # Deduplicate by title
    seen = set()
    unique = []
    for p in all_posts:
        if p["title"] not in seen:
            seen.add(p["title"])
            unique.append(p)

    print(f"Fetched {len(unique)} unique posts.")
    return unique