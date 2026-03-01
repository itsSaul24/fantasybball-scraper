import os
from dotenv import load_dotenv
load_dotenv()

from scraper import scrape_all
from llm import run_analysis
from emailer import send_digest

def main():
    print("🏀 Starting Fantasy BBall Daily Digest...\n")

    # 1. Scrape Reddit
    posts = scrape_all()
    if not posts:
        print("No posts found. Exiting.")
        return

    # 2. Run LLM analysis
    waiver_analysis, roster_analysis = run_analysis(posts)

    # 3. Send email
    send_digest(waiver_analysis, roster_analysis)

    print("\n✅ Done!")

if __name__ == "__main__":
    main()
