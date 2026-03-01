import time
from datetime import datetime, timedelta
from nba_api.stats.endpoints import ScheduleLeagueV2

NBA_TO_ESPN = {
    "Hawks": "ATL", "Celtics": "BOS", "Nets": "BKN", "Hornets": "CHA",
    "Bulls": "CHI", "Cavaliers": "CLE", "Mavericks": "DAL", "Nuggets": "DEN",
    "Pistons": "DET", "Warriors": "GSW", "Rockets": "HOU", "Pacers": "IND",
    "Clippers": "LAC", "Lakers": "LAL", "Grizzlies": "MEM", "Heat": "MIA",
    "Bucks": "MIL", "Timberwolves": "MIN", "Pelicans": "NOP", "Knicks": "NYK",
    "Thunder": "OKC", "Magic": "ORL", "76ers": "PHL", "Suns": "PHX",
    "Trail Blazers": "POR", "Kings": "SAC", "Spurs": "SAS", "Raptors": "TOR",
    "Jazz": "UTA", "Wizards": "WAS",
}

def parse_game_date(raw):
    """Try multiple date formats."""
    raw = str(raw).strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except:
            continue
    return None

def get_week_dates():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.date(), sunday.date()

def get_team_games_this_week():
    monday, sunday = get_week_dates()
    print(f"  Fetching schedule for week: {monday} to {sunday}")

    try:
        schedule = ScheduleLeagueV2(season="2025-26", league_id="00")
        time.sleep(1)
        df = schedule.get_data_frames()[0]
    except Exception as e:
        print(f"Warning: Could not fetch NBA schedule: {e}")
        return {}

    team_games = {}

    for _, row in df.iterrows():
        game_date = parse_game_date(row["gameDate"])
        if not game_date:
            continue
        if not (monday <= game_date <= sunday):
            continue

        day_abbr = game_date.strftime("%a")

        for col in ["homeTeam_teamName", "awayTeam_teamName"]:
            team_name = row.get(col, "")
            espn_abbr = NBA_TO_ESPN.get(team_name)
            if espn_abbr:
                if espn_abbr not in team_games:
                    team_games[espn_abbr] = []
                team_games[espn_abbr].append(day_abbr)

    return team_games

def attach_schedule(players, team_games):
    for p in players:
        team = p.get("pro_team", "")
        games = team_games.get(team, [])
        p["games_this_week"] = len(games)
        p["game_days"] = ", ".join(games) if games else "N/A"
    return players