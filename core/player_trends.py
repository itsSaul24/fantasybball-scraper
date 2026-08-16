import re
import time
from nba_api.stats.endpoints import LeagueDashPlayerStats
from core.season import current_nba_season

def _normalize_name(name):
    name = name.lower()
    name = re.sub(r"[.']", "", name)
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def get_recent_form(last_n_games=10, season=None):
    """League-wide recent-form vs season-average points, keyed by normalized player name."""
    season = season or current_nba_season()
    try:
        recent_df = LeagueDashPlayerStats(
            season=season, last_n_games=last_n_games, per_mode_detailed="PerGame", timeout=30
        ).get_data_frames()[0]
        time.sleep(1)
        season_df = LeagueDashPlayerStats(
            season=season, last_n_games=0, per_mode_detailed="PerGame", timeout=30
        ).get_data_frames()[0]
    except Exception as e:
        print(f"Warning: Could not fetch player trends: {e}")
        return {}

    season_lookup = {row["PLAYER_ID"]: row["PTS"] for _, row in season_df.iterrows()}

    trends = {}
    for _, row in recent_df.iterrows():
        gp = row["GP"]
        season_pts = season_lookup.get(row["PLAYER_ID"])
        if gp == 0 or season_pts is None:
            continue
        trends[_normalize_name(row["PLAYER_NAME"])] = {
            "recent_pts": round(row["PTS"], 1),
            "season_pts": round(season_pts, 1),
            "trend": round(row["PTS"] - season_pts, 1),
            "games_played_recent": int(gp),
        }
    return trends

def attach_trends(players, trends):
    """Adds a 'recent_trend_text' field to each player dict for use in prompt formatting."""
    for p in players:
        t = trends.get(_normalize_name(p.get("name", "")))
        if not t:
            p["recent_trend_text"] = ""
            continue
        sign = "+" if t["trend"] >= 0 else ""
        flag = " 🔥" if t["trend"] > 3 else " ❄️" if t["trend"] < -3 else ""
        p["recent_trend_text"] = (
            f" | L{t['games_played_recent']}: {t['recent_pts']} pts ({sign}{t['trend']} vs season){flag}"
        )
    return players
