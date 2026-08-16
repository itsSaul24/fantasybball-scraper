import time
import pandas as pd
from nba_api.stats.endpoints import LeagueDashPlayerStats, CommonAllPlayers
from core.league_rules import custom_fantasy_score, TOTAL_LEAGUE_BUDGET, TOTAL_ROSTERED, MIN_BID
from core.season import last_completed_season, current_nba_season

MIN_GAMES_PLAYED = 15
LATE_SEASON_GAMES = 20
MIN_LATE_GP = 8          # below this the late-season split is too noisy to trust
MIN_PRIOR_GP = 20        # below this the year-over-year comparison is too noisy to trust

def _season_before(season_str):
    start = int(season_str.split("-")[0]) - 1
    return f"{start}-{str(start + 1)[2:]}"

def _score_row(r):
    return custom_fantasy_score(r["PTS"], r["REB"], r["AST"], r["STL"], r["BLK"], r["TOV"], r["FG3M"])

def get_player_pool():
    """Last-completed-season production plus trajectory signals: year-over-year change,
    late-season form, minutes trend, and age. All scored under this league's rules."""
    season = last_completed_season()
    prior_season = _season_before(season)

    stats = LeagueDashPlayerStats(season=season, per_mode_detailed="PerGame", timeout=30).get_data_frames()[0]
    time.sleep(1)
    late = LeagueDashPlayerStats(
        season=season, per_mode_detailed="PerGame", last_n_games=LATE_SEASON_GAMES, timeout=30
    ).get_data_frames()[0]
    time.sleep(1)
    prior = LeagueDashPlayerStats(season=prior_season, per_mode_detailed="PerGame", timeout=30).get_data_frames()[0]
    time.sleep(1)
    current = CommonAllPlayers(
        is_only_current_season=1, season=current_nba_season(), timeout=30
    ).get_data_frames()[0]

    current_team = dict(zip(current["PERSON_ID"], current["TEAM_ABBREVIATION"]))
    active_ids = set(current["PERSON_ID"])

    stats = stats[(stats["GP"] >= MIN_GAMES_PLAYED) & (stats["PLAYER_ID"].isin(active_ids))].copy()
    stats["custom_score_pg"] = stats.apply(_score_row, axis=1)

    # Late-season form — captures role/usage changes heading into the offseason.
    late = late[late["GP"] >= MIN_LATE_GP].copy()
    late["late_score"] = late.apply(_score_row, axis=1)
    late_score = dict(zip(late["PLAYER_ID"], late["late_score"]))
    late_min = dict(zip(late["PLAYER_ID"], late["MIN"]))

    # Prior season — year-over-year trajectory.
    prior = prior[prior["GP"] >= MIN_PRIOR_GP].copy()
    prior["prior_score"] = prior.apply(_score_row, axis=1)
    prior_score = dict(zip(prior["PLAYER_ID"], prior["prior_score"]))
    prior_min = dict(zip(prior["PLAYER_ID"], prior["MIN"]))

    stats["late_score"] = stats["PLAYER_ID"].map(late_score)
    stats["late_min"] = stats["PLAYER_ID"].map(late_min)
    stats["prior_score"] = stats["PLAYER_ID"].map(prior_score)
    stats["prior_min"] = stats["PLAYER_ID"].map(prior_min)

    stats["late_trend"] = (stats["late_score"] - stats["custom_score_pg"]).round(1)
    stats["yoy_trend"] = (stats["custom_score_pg"] - stats["prior_score"]).round(1)
    stats["min_trend"] = (stats["late_min"] - stats["MIN"]).round(1)

    stats["current_team"] = stats["PLAYER_ID"].map(current_team)
    stats["team_changed"] = stats["current_team"] != stats["TEAM_ABBREVIATION"]

    cols = [
        "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "current_team", "team_changed", "AGE",
        "GP", "MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV", "FG3M",
        "custom_score_pg", "late_score", "late_trend", "prior_score", "yoy_trend", "min_trend",
    ]
    return stats[cols].rename(columns={"TEAM_ABBREVIATION": "last_season_team"}).sort_values(
        "custom_score_pg", ascending=False
    ).reset_index(drop=True)

def get_rookie_pool(stats_pool, position_map=None):
    """Incoming rookies have no NBA box score, so the stats-driven pool drops them
    entirely — yet in a 14-team league they get drafted and Reddit discusses them heavily.
    Returns them as a separate, explicitly stats-less track valued from discussion only."""
    current = CommonAllPlayers(
        is_only_current_season=1, season=current_nba_season(), timeout=30
    ).get_data_frames()[0]

    known = set(stats_pool["PLAYER_ID"])
    rookies = current[
        (~current["PERSON_ID"].isin(known))
        & (current["FROM_YEAR"].astype(str) >= str(int(current_nba_season().split("-")[0])))
    ].copy()
    if rookies.empty:
        return rookies

    out = pd.DataFrame({
        "PLAYER_ID": rookies["PERSON_ID"],
        "PLAYER_NAME": rookies["DISPLAY_FIRST_LAST"],
        "last_season_team": "",
        "current_team": rookies["TEAM_ABBREVIATION"],
        "team_changed": False,
        "AGE": float("nan"),
        "GP": 0, "MIN": 0.0, "PTS": 0.0, "REB": 0.0, "AST": 0.0,
        "STL": 0.0, "BLK": 0.0, "TOV": 0.0, "FG3M": 0.0,
        "custom_score_pg": 0.0, "late_score": float("nan"), "late_trend": float("nan"),
        "prior_score": float("nan"), "yoy_trend": float("nan"), "min_trend": float("nan"),
        "is_rookie": True,
    })
    return out.reset_index(drop=True)

def describe_trend(row):
    """Compact human/LLM-readable trajectory summary for one player."""
    parts = []
    if row["yoy_trend"] == row["yoy_trend"]:  # not NaN
        direction = "up" if row["yoy_trend"] > 0 else "down"
        parts.append(
            f"YoY {direction} {abs(row['yoy_trend']):.1f} fpts/g "
            f"({row['prior_score']:.1f} -> {row['custom_score_pg']:.1f})"
        )
    else:
        parts.append("no prior-season baseline (rookie or limited sample)")

    if row["late_score"] == row["late_score"]:
        direction = "finished hot" if row["late_trend"] > 1.5 else "faded late" if row["late_trend"] < -1.5 else "steady late"
        parts.append(f"{direction} (last {LATE_SEASON_GAMES}: {row['late_score']:.1f}, {row['late_trend']:+.1f})")
        if row["min_trend"] == row["min_trend"] and abs(row["min_trend"]) >= 2:
            parts.append(f"minutes {row['min_trend']:+.1f}/g late")
    return "; ".join(parts)

FULL_SEASON_GAMES = 82
DURABILITY_FLOOR = 0.70   # even a heavily injured star retains real value when healthy

def durability_factor(gp):
    """Weekly head-to-head pays you nothing for games not played. Pure per-game rate
    treats a 36-game star and a 78-game one as equals; they are not. Availability is
    discounted toward a floor rather than linearly, since last season's games missed
    only partly predicts next season's."""
    played_share = min(gp / FULL_SEASON_GAMES, 1.0)
    return round(DURABILITY_FLOOR + (1 - DURABILITY_FLOOR) * played_share, 3)

def compute_auction_values(df, total_rostered=TOTAL_ROSTERED, total_budget=TOTAL_LEAGUE_BUDGET):
    """Value-over-replacement-player $1-$200 auction dollar allocation, adjusted for
    availability."""
    df = df.copy()
    df["durability"] = df["GP"].apply(durability_factor)
    df["adj_score"] = df["custom_score_pg"] * df["durability"]
    df = df.sort_values("adj_score", ascending=False).reset_index(drop=True)

    if len(df) >= total_rostered:
        replacement_score = df.iloc[total_rostered - 1]["adj_score"]
    else:
        replacement_score = df["adj_score"].min()

    df["surplus"] = (df["adj_score"] - replacement_score).clip(lower=0)
    total_surplus = df["surplus"].sum()
    spendable = total_budget - total_rostered * MIN_BID

    def alloc(surplus):
        if surplus <= 0 or total_surplus <= 0:
            return float(MIN_BID)
        return round(MIN_BID + (surplus / total_surplus) * spendable, 1)

    df["mechanical_value"] = df["surplus"].apply(alloc)
    return df
