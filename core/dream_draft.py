"""Builds a positional draft board: three ranked targets per position at descending
price tiers, so being outbid on the primary never leaves you improvising.

Everything here is derived from the current run's data rather than hardcoded names. A
re-run weeks later automatically drops players who retired, got traded into a worse role,
or fell out of the pool, and promotes whoever the fresh analysis likes instead.

The ranking is deliberately market-aware rather than purely production-maximising: an
optimiser that only chases projected points loads up on exactly the players the community
is already high on, which is where you get outbid or forced to overpay.
"""
import pandas as pd

from core.league_rules import SCORING, AUCTION_BUDGET_PER_TEAM

BASE_POSITIONS = ["PG", "SG", "SF", "PF", "C"]
TIER_LABELS = ["Primary", "Fallback", "Value"]

# Market sentiment multipliers — lean toward players the room is not already chasing.
MARKET_WEIGHTS = {"underrated": 1.12, "fairly priced": 1.0, "overhyped": 0.88, "unknown": 0.97}

MIN_GAMES = 60          # the wire cannot repair a broken roster in this league
STOCK_BONUS = 2.5       # steals/blocks pay 3.0 each and are chronically underpriced
DURABILITY_BONUS = 0.08

def _is_unavailable(row):
    """Drops players the analysis flagged as off the board (retirement, no role)."""
    text = f"{row.get('why', '')} {row.get('community_read', '')}".lower()
    return "retire" in text or "dead money" in text

def score_candidates(df, min_games=MIN_GAMES):
    d = df[(df.get("is_rookie") != True) & df["position"].notna()].copy()
    d = d[~d.apply(_is_unavailable, axis=1)]
    d = d[(d["GP"] >= min_games) & (d["target"] > 0) & (d["adj_score"] > 0)]
    d["market_weight"] = d["market_vs_value"].map(MARKET_WEIGHTS).fillna(0.97)
    d["pick_score"] = (
        d["adj_score"] * d["market_weight"]
        + d["stocks_pg"] * STOCK_BONUS
        + (d["GP"] - min_games) * DURABILITY_BONUS
    )
    return d

def build_position_board(df, per_position=3):
    """Three targets per position at descending prices. Tier prices adapt to the data:
    the fallback costs at most ~60% of the primary and the value pick ~35%, so whichever
    one you land, the rest of the roster stays affordable."""
    d = score_candidates(df)
    taken, rows = set(), []

    for pos in BASE_POSITIONS:
        pool = d[d["position"] == pos].sort_values("pick_score", ascending=False)
        pool = pool[~pool["player"].isin(taken)]
        if pool.empty:
            continue

        picks, ceiling = [], None
        for tier in range(per_position):
            if ceiling is None:
                cand = pool
            else:
                cand = pool[pool["target"] <= ceiling]
                if cand.empty:                      # nothing cheaper — take next best
                    cand = pool
            if cand.empty:
                break
            best = cand.iloc[0]
            picks.append((TIER_LABELS[tier] if tier < len(TIER_LABELS) else f"Option {tier+1}", best))
            taken.add(best["player"])
            pool = pool[pool["player"] != best["player"]]
            ceiling = best["target"] * (0.6 if tier == 0 else 0.55)

        for label, p in picks:
            rows.append({
                "Position": pos,
                "Tier": label,
                "Player": p["player"],
                "Team": p["team"],
                "Buy at": p["target"],
                "Walk away": p["walk_away"],
                "Steal under": p["steal"],
                "Proj fpts/g": round(p["adj_score"], 1),
                "Stocks/g": p["stocks_pg"],
                "GP": int(p["GP"]),
                "Market": p["market_vs_value"],
                "Career arc": p["career_arc"],
                "Why": str(p["why"])[:300],
                "In the room": str(p["live_note"])[:220],
            })
    return pd.DataFrame(rows)

def budget_shape(board, budget=AUCTION_BUDGET_PER_TEAM, roster_spots=13):
    """Affordability of each tier across the five base positions.

    Reports only what it can actually measure: the cost of the five base slots plus the
    minimum needed to fill the remaining roster at $1 each. Flex and bench prices depend on
    who is still on the board mid-auction, so they are left as headroom rather than invented.
    """
    rows = []
    remaining_spots = roster_spots - len(BASE_POSITIONS)
    for tier in TIER_LABELS:
        sub = board[board["Tier"] == tier]
        if sub.empty:
            continue
        five = float(sub["Buy at"].sum())
        headroom = budget - five - remaining_spots      # $1 minimum per unfilled slot
        if headroom < 0:
            verdict = "NOT AFFORDABLE — you cannot land every one of these"
        elif headroom < 40:
            verdict = "Affordable but tight; the rest of the roster is $1-4 fills"
        elif headroom < 100:
            verdict = "Comfortable — real money left for flex and bench"
        else:
            verdict = "Underspending; unspent budget is forfeited, so trade up somewhere"
        rows.append({
            "If you land every": tier,
            "Cost of 5 base slots": round(five, 1),
            f"Left for other {remaining_spots} spots": round(budget - five, 1),
            "Headroom above $1 minimums": round(headroom, 1),
            "Verdict": verdict,
        })

    df = pd.DataFrame(rows)
    prim = board[board["Tier"] == "Primary"]["Buy at"].sum()
    note = pd.DataFrame([{
        "If you land every": "READ THIS",
        "Cost of 5 base slots": "",
        f"Left for other {remaining_spots} spots": "",
        "Headroom above $1 minimums": "",
        "Verdict": (
            f"All five Primary targets cost ${prim:.0f} of a ${budget} budget, so you can realistically "
            f"win one or two of them, not all five. Plan on one Primary, two Fallbacks and two Value "
            f"picks across the base positions, then fill flex and bench from whoever is left."
        ),
    }])
    return pd.concat([df, note], ignore_index=True)

def strategy_notes(board):
    stock_stars = board.nlargest(4, "Stocks/g")[["Player", "Stocks/g"]].values.tolist()
    stock_str = ", ".join(f"{n} ({s})" for n, s in stock_stars)
    return pd.DataFrame([
        ("How to use this board",
         "Three options per position, cheapest-last. Bid the Primary up to its walk-away price. "
         "The moment it passes, stop and move to the Fallback. Never chase past a walk-away — "
         "the dollars you save there are what buy the rest of your roster."),
        ("Stocks are the edge",
         f"Steals and blocks pay {SCORING['STL']:.1f} each in this league but are priced on scoring. "
         f"Board leaders: {stock_str}. A player at 2.5 stocks earns 7.5 fpts/g before scoring a point."),
        ("Efficiency is irrelevant",
         "Field goals and free throws are worth zero, attempted or made. Never downgrade a high-volume "
         "inefficient scorer here. Managers carrying category-league instincts will fade exactly the "
         "players you should be buying."),
        ("Durability is strategy, not preference",
         f"With a 45-add season cap and 4 per week across the league, the wire cannot repair a broken "
         f"roster. Every target on this board played {MIN_GAMES}+ games last season."),
        ("Nominate to drain",
         "Open by nominating expensive players you do not want. Rivals commit budget early, and the "
         "mid-priced band where value per dollar peaks gets cheaper for you."),
        ("Do not buy a superstar by default",
         "The most expensive players consume a quarter to a third of the budget for one roster slot. "
         "Check the Draft Plan tab: if two mid-tier targets together project more than one star at the "
         "same price, take the two."),
        ("Late draft",
         "Once rivals hit their $1 maximums they can only win uncontested players. Useful bodies clear "
         "at a dollar late, so do not panic-spend the middle."),
    ], columns=["Principle", "Detail"])
