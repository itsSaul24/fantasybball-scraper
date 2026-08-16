import os
import sys
import time

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from core.scraper import scrape_all
from core.llm import run_analysis, LLM_PROVIDER, GEMINI_MODEL, OLLAMA_MODEL, format_posts_for_prompt, last_token_usage
from core.discord_bot import send_digest, send_notice
from core.espn_data import (
    get_free_agents, get_my_team, get_league, format_free_agents_for_prompt, format_roster_for_prompt,
    get_recent_activity, format_activity_for_prompt,
)
from core.schedule import get_team_games_this_week, attach_schedule
from core.player_trends import get_recent_form, attach_trends
from core.semantic_match import build_chunks, embed_and_store
from core.matchup import get_matchup_context, format_matchup_for_log
from core.logger import log, log_section, log_run_summary, log_reddit_scrape, log_roster, log_free_agents, log_token_usage
from core.db import start_run, update_run, finish_run
from core.budget import is_budget_exceeded, estimate_cost, DAILY_BUDGET_USD

def run_digest(run_id, start_time):
    # 1. Scrape Reddit
    log("Scraping Reddit...")
    posts = scrape_all()
    if not posts:
        log("No posts found. Exiting.", level="ERROR")
        finish_run(run_id, status="error", error_message="No posts found", duration_seconds=time.time() - start_time)
        return
    log_reddit_scrape(posts)

    # 1b. Persist today's scrape into the shared vector store. Each daily run adds to a
    # corpus that draft prep and longitudinal sentiment analysis both read from, so the
    # archive compounds instead of being thrown away after every run.
    try:
        chunks = build_chunks(posts)
        _, _, embed_cost, store_stats = embed_and_store(chunks, run_id=run_id)
        log(f"Archived {store_stats['total']} chunks "
            f"({store_stats['newly_embedded']} new, {store_stats['reused']} already stored, "
            f"${embed_cost:.4f})")
    except Exception as e:
        embed_cost = 0.0
        log(f"Vector archive step failed: {e}", level="WARN")

    # 2. Fetch NBA schedule
    log("Fetching NBA schedule...")
    team_games = get_team_games_this_week()
    log(f"Got schedule for {len(team_games)} teams")

    # 3. Fetch ESPN data (share one league object to avoid multiple API calls)
    log("Fetching ESPN data...")
    league = get_league()

    free_agents = get_free_agents(top=50, league=league)
    free_agents = attach_schedule(free_agents, team_games)

    roster = get_my_team(league=league)
    roster = attach_schedule(roster, team_games)

    # 3b. Fetch recent-form trends and attach to both lists
    log("Fetching recent-form player trends...")
    trends = get_recent_form(last_n_games=10)
    log(f"Got trend data for {len(trends)} players")
    free_agents = attach_trends(free_agents, trends)
    roster = attach_trends(roster, trends)
    log_free_agents(free_agents)
    log_roster(roster)

    # 3c. Fetch league transaction feed
    log("Fetching league transaction feed...")
    activity = get_recent_activity(league, size=25)
    activity_text = format_activity_for_prompt(activity)
    log(f"Got {len(activity)} recent league transactions")

    update_run(
        run_id,
        posts_scraped=len(posts),
        free_agents_fetched=len(free_agents),
        roster_size=len(roster),
        league_transactions=len(activity),
    )

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

    # 5. Format for prompt
    free_agents_text = format_free_agents_for_prompt(free_agents)
    roster_text = format_roster_for_prompt(roster)
    posts_text = format_posts_for_prompt(posts)

    # 6. Run LLM
    log(f"Running LLM analysis via {LLM_PROVIDER}...")
    waiver_analysis, roster_analysis = run_analysis(posts, free_agents_text, roster_text, matchup_text, activity_text)
    log("LLM analysis complete")
    log_token_usage(last_token_usage)

    # 7. Send Discord digest
    model = OLLAMA_MODEL if LLM_PROVIDER == "ollama" else GEMINI_MODEL
    cost = estimate_cost(
        last_token_usage.get("prompt_tokens", 0),
        last_token_usage.get("output_tokens", 0),
        last_token_usage.get("thinking_tokens", 0),
    ) if LLM_PROVIDER == "gemini" else 0.0
    cost += embed_cost
    log("Sending Discord digest...")
    send_digest(waiver_analysis, roster_analysis, cost=cost)

    # 8. Log summary
    duration = time.time() - start_time
    finish_run(
        run_id,
        status="success",
        duration_seconds=duration,
        llm_provider=LLM_PROVIDER,
        llm_model=model,
        prompt_tokens=last_token_usage.get("prompt_tokens", 0),
        output_tokens=last_token_usage.get("output_tokens", 0),
        thinking_tokens=last_token_usage.get("thinking_tokens", 0),
        total_tokens=last_token_usage.get("total_tokens", 0),
        estimated_cost_usd=cost,
    )
    log_run_summary(posts, free_agents, roster, free_agents_text, roster_text, posts_text, LLM_PROVIDER, model, duration)
    log(f"✅ Done in {duration:.1f}s (est. cost ${cost:.4f})")

def main():
    start_time = time.time()
    log_section("FANTASY BBALL DAILY DIGEST")
    log("Starting run...")
    run_id = start_run()

    if is_budget_exceeded():
        log(f"Daily budget (${DAILY_BUDGET_USD:.2f}) already reached — skipping this run.", level="WARN")
        finish_run(run_id, status="skipped_budget", duration_seconds=time.time() - start_time)
        send_notice(f"⚠️ Skipped today's digest — daily budget (${DAILY_BUDGET_USD:.2f}) already reached.")
        return

    try:
        run_digest(run_id, start_time)
    except Exception as e:
        log(f"Run failed: {e}", level="ERROR")
        finish_run(run_id, status="error", error_message=str(e)[:500], duration_seconds=time.time() - start_time)
        raise

if __name__ == "__main__":
    main()
