import time
import numpy as np
import pandas as pd
from nba_api.stats.endpoints import LeagueDashPlayerStats

from core.league_rules import custom_fantasy_score
from core.season import last_completed_season

HISTORY_SEASONS = 5
MIN_GP_FOR_SEASON = 10   # a handful of games is noise, not a season

def _season_back(season_str, n):
    start = int(season_str.split("-")[0]) - n
    return f"{start}-{str(start + 1)[2:]}"

def get_multiyear_history(seasons=HISTORY_SEASONS):
    """League-scored fantasy points per game for each of the last N seasons.

    One API call per season, joined on player id — cheap, and it turns a single-season
    snapshot into a career arc: who is climbing, who peaked two years ago, and who is
    simply erratic."""
    latest = last_completed_season()
    frames = {}
    for i in range(seasons):
        season = _season_back(latest, i)
        try:
            df = LeagueDashPlayerStats(
                season=season, per_mode_detailed="PerGame", timeout=30
            ).get_data_frames()[0]
        except Exception as e:
            print(f"  Warning: could not fetch {season}: {e}")
            continue
        df = df[df["GP"] >= MIN_GP_FOR_SEASON].copy()
        df["fp"] = df.apply(
            lambda r: custom_fantasy_score(
                r["PTS"], r["REB"], r["AST"], r["STL"], r["BLK"], r["TOV"], r["FG3M"]
            ),
            axis=1,
        )
        frames[season] = df.set_index("PLAYER_ID")[["fp", "GP", "MIN"]]
        print(f"  {season}: {len(df)} qualifying players")
        time.sleep(1)
    return frames

def _slope(values):
    """Fantasy points per season, fitted by least squares — the direction of a career."""
    pairs = [(i, v) for i, v in enumerate(values) if v == v]
    if len(pairs) < 2:
        return float("nan")
    xs, ys = zip(*pairs)
    return float(np.polyfit(xs, ys, 1)[0])

def attach_history(df, frames):
    """Adds per-season fantasy point columns plus derived career-arc metrics."""
    df = df.copy()
    seasons = sorted(frames.keys())            # oldest -> newest
    for season in seasons:
        col = f"fp_{season.replace('-', '_')}"
        df[col] = df["PLAYER_ID"].map(frames[season]["fp"]).round(1)
        gp_col = f"gp_{season.replace('-', '_')}"
        df[gp_col] = df["PLAYER_ID"].map(frames[season]["GP"])

    fp_cols = [f"fp_{s.replace('-', '_')}" for s in seasons]
    gp_cols = [f"gp_{s.replace('-', '_')}" for s in seasons]
    hist = df[fp_cols]

    df["seasons_of_data"] = hist.notna().sum(axis=1)
    df["fp_peak"] = hist.max(axis=1).round(1)
    df["fp_peak_season"] = hist.idxmax(axis=1).map(
        lambda c: c.replace("fp_", "").replace("_", "-") if isinstance(c, str) else ""
    )
    df["fp_trend_5y"] = hist.apply(lambda r: _slope(list(r)), axis=1).round(2)
    df["fp_consistency"] = hist.std(axis=1).round(2)   # lower = more predictable
    latest_col = fp_cols[-1]
    df["pct_of_peak"] = (df[latest_col] / df["fp_peak"].replace(0, np.nan)).round(3)
    df["avg_gp_5y"] = df[gp_cols].mean(axis=1).round(1)

    df["career_arc"] = [
        _describe_arc(t, p, n) for t, p, n in
        zip(df["fp_trend_5y"], df["pct_of_peak"], df["seasons_of_data"])
    ]
    return df

def _describe_arc(trend, pct_peak, n_seasons):
    if n_seasons < 2 or trend != trend:
        return "insufficient history"
    if trend >= 3:
        label = "steep ascent"
    elif trend >= 1:
        label = "improving"
    elif trend > -1:
        label = "plateau"
    elif trend > -3:
        label = "declining"
    else:
        label = "steep decline"
    if pct_peak == pct_peak and pct_peak < 0.85:
        label += f" ({pct_peak:.0%} of peak)"
    return label

def add_rate_metrics(df):
    """Per-minute and defensive-share metrics derived from data already in hand — free to
    compute and directly decision-relevant in a format that pays 3.0 per stock."""
    df = df.copy()
    minutes = df["MIN"].replace(0, np.nan)
    df["fp_per_36"] = (df["custom_score_pg"] / minutes * 36).round(1)
    df["stocks_pg"] = (df["STL"] + df["BLK"]).round(2)
    df["stock_fpts"] = (df["stocks_pg"] * 3.0).round(1)
    df["stock_share"] = (df["stock_fpts"] / df["custom_score_pg"].replace(0, np.nan)).round(3)
    df["ast_fpts"] = (df["AST"] * 1.5).round(1)
    df["reb_fpts"] = (df["REB"] * 1.2).round(1)
    df["tov_drag"] = (df["TOV"] * -1.0).round(1)
    return df
