import os
from datetime import datetime

LOG_DIR = "logs"

def get_log_path():
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.log")

def log(message, level="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] [{level}] {message}"
    print(line)
    with open(get_log_path(), "a", encoding="utf-8") as f:
        f.write(line + "\n")

def log_section(title):
    separator = "=" * 50
    with open(get_log_path(), "a", encoding="utf-8") as f:
        f.write(f"\n{separator}\n{title}\n{separator}\n")
    print(f"\n{'=' * 50}\n{title}\n{'=' * 50}")

def estimate_tokens(text):
    return len(text) // 4

def log_reddit_scrape(posts):
    log_section("REDDIT SCRAPE DETAILS")
    log(f"Total unique posts: {len(posts)}")
    log(f"Search parameters:")
    log(f"  - r/fantasybball: hot (75), top?t=day (50), new (50)")
    log(f"  - r/nba: top?t=day (30)")
    log(f"  - Score filter: > 10 upvotes")
    log(f"  - Body truncated to: 600 chars")
    log(f"")
    flairs = {}
    for p in posts:
        flair = p.get("flair") or "No Flair"
        flairs[flair] = flairs.get(flair, 0) + 1
    log(f"Post breakdown by flair:")
    for flair, count in sorted(flairs.items(), key=lambda x: -x[1])[:10]:
        log(f"  [{count}] {flair}")
    log(f"")
    log(f"Top 5 posts by score:")
    for p in sorted(posts, key=lambda x: x["score"], reverse=True)[:5]:
        log(f"  ({p['score']}) {p['title'][:80]}")

def log_roster(roster):
    log_section("ROSTER PLAYERS")
    for p in roster:
        injury = f" [{p['injury_status']}]" if p.get("injured") else ""
        games = f" | {p['games_this_week']} games ({p['game_days']})"
        log(f"  {p['name']} ({p['position']}, {p['pro_team']}) — {p['avg_points']} avg pts{games}{injury}")

def log_free_agents(free_agents):
    log_section("TOP FREE AGENTS FETCHED")
    for p in free_agents[:20]:
        status = f" [{p['injury_status']}]" if p['injury_status'] not in ("ACTIVE", "NORMAL", "", None) else ""
        games = f" | {p['games_this_week']} games ({p['game_days']})"
        log(f"  {p['name']} ({p['position']}, {p['pro_team']}) — {p['avg_points']} avg pts{games}{status}")

def log_run_summary(posts, free_agents, roster, free_agents_text, roster_text, posts_text, llm_provider, model, duration_seconds):
    total_prompt_chars = len(free_agents_text) + len(roster_text) + len(posts_text)
    estimated_tokens = total_prompt_chars // 4

    log_section("RUN SUMMARY")
    log(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Duration: {duration_seconds:.1f} seconds")
    log(f"LLM Provider: {llm_provider} ({model})")
    log(f"Total posts scraped: {len(posts)}")
    log(f"Reddit text chars: {len(posts_text):,} (~{len(posts_text) // 4:,} tokens)")
    log(f"Free agents fetched: {len(free_agents)}")
    log(f"Roster players: {len(roster)}")
    log(f"Total prompt chars: {total_prompt_chars:,} (~{estimated_tokens:,} tokens)")
    log_section("END OF RUN")

def log_token_usage(token_usage):
    if token_usage["total_tokens"] > 0:
        log(f"Token usage (Gemini) — Input: {token_usage['prompt_tokens']:,} | Output: {token_usage['output_tokens']:,} | Total: {token_usage['total_tokens']:,}")
    else:
        log("Token usage — N/A (Ollama, no token tracking)")