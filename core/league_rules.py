# From league-rulebook.html — 14-team H2H points auction, 2026-27 season.
# Custom scoring deliberately zeroes shooting attempts/makes (no efficiency penalty)
# and pays defense (STL/BLK) and playmaking (AST) above ESPN's default weights.

SCORING = {
    "PTS": 1.0,
    "FG3M": 0.5,  # bonus, on top of the 3 points already counted in PTS
    "REB": 1.2,
    "AST": 1.5,
    "STL": 3.0,
    "BLK": 3.0,
    "TOV": -1.0,
}

import os

# League size is set at draft time and can change between seasons — override with env
# vars rather than editing code.
NUM_TEAMS = int(os.environ.get("LEAGUE_NUM_TEAMS", "14"))
ROSTER_SPOTS = int(os.environ.get("LEAGUE_ROSTER_SPOTS", "13"))  # excludes the 2 IR slots
AUCTION_BUDGET_PER_TEAM = int(os.environ.get("LEAGUE_AUCTION_BUDGET", "200"))
TOTAL_LEAGUE_BUDGET = NUM_TEAMS * AUCTION_BUDGET_PER_TEAM  # 2800
TOTAL_ROSTERED = NUM_TEAMS * ROSTER_SPOTS  # 182
MIN_BID = 1

def format_scoring_for_prompt():
    """The scoring table plus the two strategic consequences that follow from it. Generic
    fantasy advice assumes efficiency matters and undervalues defense; both are wrong here."""
    return f"""LEAGUE SCORING ({NUM_TEAMS}-team head-to-head POINTS league, {ROSTER_SPOTS} roster spots):
  Point scored      {SCORING['PTS']:+.1f}      Steal        {SCORING['STL']:+.1f}
  Rebound           {SCORING['REB']:+.1f}      Block        {SCORING['BLK']:+.1f}
  Assist            {SCORING['AST']:+.1f}      Turnover     {SCORING['TOV']:+.1f}
  3PM bonus         {SCORING['FG3M']:+.1f}      FGA/FGM/FTA/FTM   0.0 (ZEROED)

TWO CONSEQUENCES THAT OVERRIDE GENERIC FANTASY ADVICE:
1. Shooting efficiency is IRRELEVANT — misses cost nothing. High-volume, inefficient
   scorers are materially more valuable here than in standard formats or ESPN defaults.
   Never downgrade a player for a poor FG% or FT%.
2. Defense is heavily paid — steals and blocks are worth {SCORING['STL']:.1f} each. A player with
   2.0 combined stocks earns 6.0 fpts from that alone, more than 5 rebounds. Low-usage
   rim protectors and ball-hawk guards carry real value that category-league advice misses.
Assists ({SCORING['AST']:+.1f}) and rebounds ({SCORING['REB']:+.1f}) also outweigh raw points, so playmakers and
bigs rate higher than a points-only reading would suggest."""

def custom_fantasy_score(pts, reb, ast, stl, blk, tov, fg3m):
    return (
        pts * SCORING["PTS"]
        + fg3m * SCORING["FG3M"]
        + reb * SCORING["REB"]
        + ast * SCORING["AST"]
        + stl * SCORING["STL"]
        + blk * SCORING["BLK"]
        + tov * SCORING["TOV"]
    )
