import os
import time
from dotenv import load_dotenv
load_dotenv()

from core.scraper import scrape_all
from core.llm import run_analysis, LLM_PROVIDER, OLLAMA_MODEL, format_posts_for_prompt, last_token_usage
from core.emailer import send_digest
from core.espn_data import get_free_agents, get_my_team, get_league, format_free_agents_for_prompt, format_roster_for_prompt
from core.schedule import get_team_games_this_week, attach_schedule
from core.matchup import get_matchup_context, format_matchup_for_log
from core.logger import log, log_section, log_run_summary, log_reddit_scrape, log_roster, log_free_agents, log_token_usage

def main():
    start_time = time.time()
    log_section("FANTASY BBALL DAILY DIGEST")
    log("Starting run...")

    # 1. Scrape Reddit
    log("Scraping Reddit...")
    posts = scrape_all()
    if not posts:
        log("No posts found. Exiting.", level="ERROR")
        return
    log_reddit_scrape(posts)

    # 2. Fetch NBA schedule
    log("Fetching NBA schedule...")
    team_games = get_team_games_this_week()
    log(f"Got schedule for {len(team_games)} teams")

    # 3. Fetch ESPN data (share one league object to avoid multiple API calls)
    log("Fetching ESPN data...")
    league = get_league()

    free_agents = get_free_agents(top=50, league=league)
    free_agents = attach_schedule(free_agents, team_games)
    log_free_agents(free_agents)

    roster = get_my_team(league=league)
    roster = attach_schedule(roster, team_games)
    log_roster(roster)

    # 4. Fetch matchup context
    log("Fetching current matchup...")
    try:
        matchup_text, matchup_info = get_matchup_context(league)
        if matchup_info:
            log(f"Matchup: {format_matchup_for_log(matchup_info)}")
        else:
            log("Could not fetch matchup data", level="WARN")
            matchup_text = matchup_text or ""
    except Exception as e:
        log(f"Matchup fetch failed: {e}", level="WARN")
        matchup_text = ""
        matchup_info = None

    # 5. Format for prompt
    free_agents_text = format_free_agents_for_prompt(free_agents)
    roster_text = format_roster_for_prompt(roster)
    posts_text = format_posts_for_prompt(posts)

    # 6. Run LLM
    log(f"Running LLM analysis via {LLM_PROVIDER}...")
    waiver_analysis, roster_analysis = run_analysis(posts, free_agents_text, roster_text, matchup_text)
    log("LLM analysis complete")
    log_token_usage(last_token_usage)

    # 7. Send email
    log("Sending email digest...")
    send_digest(waiver_analysis, roster_analysis)

    # 8. Log summary
    duration = time.time() - start_time
    model = OLLAMA_MODEL if LLM_PROVIDER == "ollama" else "gemini-2.5-flash"
    log_run_summary(posts, free_agents, roster, free_agents_text, roster_text, posts_text, LLM_PROVIDER, model, duration)
    log(f"✅ Done in {duration:.1f}s")

if __name__ == "__main__":
    main()