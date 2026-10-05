"""Runs the draft-prep Reddit scrape in resumable, time-boxed segments.

A full scrape takes about two hours because of Reddit's rate limits. Use this when that
can't run in one sitting: each invocation works for --minutes, checkpoints, and exits with
code 3 if work remains. Re-run until it exits 0. On completion it writes the scrape cache,
which draft_prep.py then picks up instead of scraping again.

    python scrape_draft_corpus.py --minutes 20
"""
import argparse
import json
import os
import sys

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from core.draft_scraper import scrape_for_draft
from draft_prep import SCRAPE_CACHE, SCRAPE_CHECKPOINT, COMMENT_FETCH_LIMIT

INCOMPLETE = 3

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--minutes", type=float, default=20, help="time budget for this segment")
    args = parser.parse_args()

    posts, complete = scrape_for_draft(
        comment_fetch_limit=COMMENT_FETCH_LIMIT,
        checkpoint_path=SCRAPE_CHECKPOINT,
        time_budget_s=args.minutes * 60,
    )
    if not complete:
        sys.exit(INCOMPLETE)

    with open(SCRAPE_CACHE, "w", encoding="utf-8") as f:
        json.dump(posts, f)
    if os.path.exists(SCRAPE_CHECKPOINT):
        os.remove(SCRAPE_CHECKPOINT)
    print(f"CACHE WRITTEN: {SCRAPE_CACHE}")

if __name__ == "__main__":
    main()
