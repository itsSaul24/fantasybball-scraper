import sys
import time
import json
import os
from datetime import datetime

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

import pandas as pd

from core.draft_valuation import (
    get_player_pool, get_rookie_pool, compute_auction_values, describe_trend,
)
from core.draft_scraper import scrape_for_draft
from core.draft_llm import match_player_context, merge_context, refine_valuations
from core.semantic_match import semantic_match_context
from core.positions import (
    get_position_map, attach_positions, positional_scarcity, format_scarcity_for_prompt,
)
from core.player_history import get_multiyear_history, attach_history, add_rate_metrics
from core.dream_draft import build_position_board, budget_shape, strategy_notes
from core.excel_export import write_draft_workbook
from core.db import start_run, finish_run

OUTPUT_CSV = "draft_plan.csv"
OUTPUT_XLSX = "draft_plan.xlsx"
LLM_REFINE_TOP_N = None     # None = analyze the entire pool
BATCH_SIZE = 10             # smaller batches = more context room per player
COMMENT_FETCH_LIMIT = 110   # comments carry the real analysis; main quality lever
SCRAPE_CACHE = "draft_scrape_cache.json"
CACHE_MAX_AGE_HOURS = 24
MIN_CACHE_COMMENTS = 300    # a cache from the old shallow scrape is not worth reusing
MIN_CACHE_DATED = 0.5       # re-scrape if most cached posts predate publish-date capture

def _load_cached_posts():
    if not os.path.exists(SCRAPE_CACHE):
        return None
    age_hours = (time.time() - os.path.getmtime(SCRAPE_CACHE)) / 3600
    if age_hours > CACHE_MAX_AGE_HOURS:
        return None
    with open(SCRAPE_CACHE, "r", encoding="utf-8") as f:
        posts = json.load(f)
    total_comments = sum(len(p.get("comments", [])) for p in posts)
    if total_comments < MIN_CACHE_COMMENTS:
        print(f"  Cached scrape has only {total_comments} comments — re-scraping deeper.")
        return None
    dated = sum(1 for p in posts if p.get("published"))
    if dated / max(len(posts), 1) < MIN_CACHE_DATED:
        print("  Cached scrape predates publish-date capture — re-scraping for dates.")
        return None
    return posts

def _save_cached_posts(posts):
    with open(SCRAPE_CACHE, "w", encoding="utf-8") as f:
        json.dump(posts, f)

def main():
    start_time = time.time()
    run_id = start_run(run_type="draft_prep")
    try:
        run_draft_prep(run_id, start_time)
    except Exception as e:
        print(f"❌ Draft prep failed: {e}")
        finish_run(run_id, status="error", error_message=str(e)[:500], duration_seconds=time.time() - start_time)
        raise

def run_draft_prep(run_id, start_time):
    print("=" * 60)
    print("DRAFT PREP — one-time auction valuation build")
    print("=" * 60)

    print("\n[1/6] Computing values and trajectory from the last two seasons...")
    pool = get_player_pool()
    pool = compute_auction_values(pool)
    pool["is_rookie"] = False
    print(f"  {len(pool)} players with NBA production")

    print("\n[1b] Joining five seasons of history and rate metrics...")
    pool = attach_history(pool, get_multiyear_history())
    pool = add_rate_metrics(pool)

    print("\n[2/6] Adding ESPN positions and computing positional scarcity...")
    position_map = get_position_map()
    pool = attach_positions(pool, position_map)
    scarcity = positional_scarcity(pool)
    scarcity_text = format_scarcity_for_prompt(scarcity)
    print("  " + scarcity_text.replace("\n", "\n  "))

    print("\n[3/6] Broad Reddit scrape...")
    posts = _load_cached_posts()
    if posts is not None:
        n_comments = sum(len(p.get("comments", [])) for p in posts)
        print(f"  Using cached scrape ({len(posts)} posts, {n_comments} comments, <{CACHE_MAX_AGE_HOURS}h old)")
    else:
        posts = scrape_for_draft(comment_fetch_limit=COMMENT_FETCH_LIMIT)
        _save_cached_posts(posts)

    # Incoming rookies have no box score, so they never appear in the stats pool. Carry
    # forward only the ones the community actually discusses — if Reddit is silent on a
    # rookie, he is not getting drafted in a 14-team league.
    rookies = get_rookie_pool(pool, position_map)
    if len(rookies):
        rookies = attach_positions(rookies, position_map)
        for col in ("durability", "adj_score", "surplus", "mechanical_value"):
            rookies[col] = 1.0 if col == "durability" else 0.0
        rookies["mechanical_value"] = 1.0
        print(f"  {len(rookies)} incoming rookies to screen for discussion")

    print("\n[4/6] Matching Reddit context (keyword + chunk-level semantic search)...")
    candidates = pd.concat([pool, rookies], ignore_index=True) if len(rookies) else pool
    keyword_context = match_player_context(candidates, posts)
    semantic_context, embed_cost, sem_stats = semantic_match_context(
        candidates, posts, run_id=run_id
    )
    context = merge_context(keyword_context, semantic_context, max_snippets=8)
    matched = sum(1 for v in context.values() if v)
    print(f"  {sem_stats['chunks']} chunks searched; {matched} players have context "
          f"(embedding ${embed_cost:.4f})")

    if len(rookies):
        discussed = rookies[rookies["PLAYER_ID"].map(lambda p: bool(context.get(p)))]
        print(f"  {len(discussed)}/{len(rookies)} rookies have real discussion — keeping those")
        pool = pd.concat([pool, discussed], ignore_index=True)

    refine_n = LLM_REFINE_TOP_N or len(pool)
    print(f"\n[5/6] LLM-refining {refine_n} players in batches of {BATCH_SIZE}...")
    result_df, llm_cost = refine_valuations(
        pool, context, top_n=refine_n, batch_size=BATCH_SIZE, scarcity_text=scarcity_text
    )
    total_cost = embed_cost + llm_cost

    print("\n[6/6] Writing workbook...")
    result_df = result_df.sort_values(
        ["mechanical_value", "target"], ascending=False
    ).reset_index(drop=True)
    result_df.insert(0, "rank", result_df.index + 1)
    result_df["trajectory"] = result_df.apply(describe_trend, axis=1)

    history_cols = [c for c in result_df.columns if c.startswith(("fp_20", "gp_20"))]
    columns = [
        "rank", "PLAYER_NAME", "position", "eligible", "current_team", "team_changed",
        "AGE", "is_rookie", "tier", "trend", "market_vs_value",
        "steal", "target", "walk_away", "mechanical_value",
        "community_read", "why", "risk", "live_note", "trajectory",
        "career_arc", "fp_trend_5y", "fp_peak", "fp_peak_season", "pct_of_peak",
        "fp_consistency", "seasons_of_data", "avg_gp_5y", *history_cols,
        "fp_per_36", "stocks_pg", "stock_fpts", "stock_share", "ast_fpts", "reb_fpts", "tov_drag",
        "custom_score_pg", "adj_score", "durability", "GP", "MIN",
        "PTS", "REB", "AST", "STL", "BLK", "TOV",
        "yoy_trend", "late_trend", "min_trend",
    ]
    out = result_df[[c for c in columns if c in result_df.columns]].rename(
        columns={"PLAYER_NAME": "player", "current_team": "team", "AGE": "age"}
    )

    out.to_csv(OUTPUT_CSV, index=False)
    duration = time.time() - start_time

    board = build_position_board(out)
    extra = {
        "Draft Board": board,
        "Budget Shape": budget_shape(board),
        "Draft Strategy": strategy_notes(board),
    }
    print(f"  Draft board: {len(board)} targets across "
          f"{board['Position'].nunique()} positions")

    written = write_draft_workbook(out, OUTPUT_XLSX, scarcity_text=scarcity_text, extra_sheets=extra, meta={
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "players": len(out),
        "rookies": int(out["is_rookie"].sum()) if "is_rookie" in out else 0,
        "reddit posts in corpus": len(posts),
        "chunks searched": sem_stats.get("chunks", 0),
        "LLM model": "gemini-3.7-flash (thinking: high)",
        "estimated cost USD": round(total_cost, 4),
        "runtime minutes": round(duration / 60, 1),
    })

    finish_run(
        run_id,
        status="success",
        duration_seconds=duration,
        llm_provider="gemini",
        llm_model="gemini-3.7-flash",
        estimated_cost_usd=total_cost,
    )

    print(f"\n✅ Draft plan written to {written} and {OUTPUT_CSV} "
          f"({len(out)} players, {duration/60:.1f} min, ${total_cost:.4f} total cost)")

if __name__ == "__main__":
    main()

