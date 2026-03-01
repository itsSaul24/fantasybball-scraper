import os
from dotenv import load_dotenv
load_dotenv()

from scraper import scrape_all
from llm import run_analysis
from emailer import send_digest
from espn_data import get_free_agents, get_my_team, format_free_agents_for_prompt, format_roster_for_prompt

def main():
    print("🏀 Starting Fantasy BBall Daily Digest...\n")

    # 1. Scrape Reddit
    posts = scrape_all()
    if not posts:
        print("No posts found. Exiting.")
        return

    # 2. Fetch ESPN data
    print("Fetching ESPN free agents...")
    free_agents = get_free_agents(top=50)
    print(f"Found {len(free_agents)} free agents")

    print("Fetching your ESPN roster...")
    roster = get_my_team()
    print(f"Found {len(roster)} players on your roster")

    free_agents_text = format_free_agents_for_prompt(free_agents)
    roster_text = format_roster_for_prompt(roster)

    # 3. Run LLM analysis
    waiver_analysis, roster_analysis = run_analysis(posts, free_agents_text, roster_text)

    # 4. Send email
    send_digest(waiver_analysis, roster_analysis)

    print("\n✅ Done!")

if __name__ == "__main__":
    main()