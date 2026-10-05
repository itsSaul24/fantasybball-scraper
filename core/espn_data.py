import os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from espn_api.basketball import League
from core.season import current_espn_year

EXCLUDE_STATUSES = {"OUT", "IR", "SUSPENSION", "INJURED_RESERVE"}

def get_league():
    return League(
        league_id=int(os.environ["ESPN_LEAGUE_ID"]),
        year=current_espn_year(),
        espn_s2=os.environ["ESPN_S2"],
        swid=os.environ["ESPN_SWID"]
    )

# ESPN basketball stat and lineup-slot ids, as they appear in league settings.
_SCORED_STATS = {0: "PTS", 17: "FG3M", 6: "REB", 3: "AST", 2: "STL", 1: "BLK", 11: "TOV"}
_ZEROED_STATS = {13: "FGM", 14: "FGA", 15: "FTM", 16: "FTA"}
_EXPECTED_SLOTS = {"0": ("PG", 1), "1": ("SG", 1), "2": ("SF", 1), "3": ("PF", 1), "4": ("C", 1),
                   "5": ("G", 1), "6": ("F", 1), "11": ("UTIL", 2), "12": ("BE", 4), "13": ("IR", 2)}

def settings_drift(league=None):
    """Compares the live ESPN league against the rules this pipeline prices on. A mismatch
    means draft-night scoring differs from what the sheet assumes, so every price drifts.
    Returns (mismatches, draft_date): mismatches is a list of plain-English strings, empty
    when aligned; draft_date is the scheduled draft time as ESPN has it, for reference."""
    from core.league_rules import SCORING, NUM_TEAMS, ROSTER_SPOTS, AUCTION_BUDGET_PER_TEAM
    league = league or get_league()
    s = league.espn_request.league_get(params={"view": "mSettings"})["settings"]
    issues = []

    teams = s.get("size") or len(league.teams)
    if teams != NUM_TEAMS:
        issues.append(f"Teams: ESPN has {teams}, rules say {NUM_TEAMS}")

    points = {i["statId"]: i["points"] for i in s.get("scoringSettings", {}).get("scoringItems", [])}
    for stat_id, key in _SCORED_STATS.items():
        live, want = points.get(stat_id, 0.0), SCORING[key]
        if abs(live - want) > 1e-6:
            issues.append(f"Scoring {key}: ESPN {live:+g}, rules {want:+g}")
    for stat_id, key in _ZEROED_STATS.items():
        if abs(points.get(stat_id, 0.0)) > 1e-6:
            issues.append(f"Scoring {key}: ESPN {points[stat_id]:+g}, rules 0 (shooting must be zeroed)")

    slots = s.get("rosterSettings", {}).get("lineupSlotCounts", {})
    for slot_id, (name, want) in _EXPECTED_SLOTS.items():
        live = slots.get(slot_id, 0)
        if live != want:
            issues.append(f"Roster {name}: ESPN {live}, rules {want}")
    for slot_id, live in slots.items():
        if live and slot_id not in _EXPECTED_SLOTS:
            issues.append(f"Roster slot id {slot_id}: ESPN has {live}, rules have none")

    draft = s.get("draftSettings", {})
    if draft.get("type") != "AUCTION":
        issues.append(f"Draft type: ESPN {draft.get('type')}, rules AUCTION")
    if draft.get("auctionBudget") not in (None, AUCTION_BUDGET_PER_TEAM):
        issues.append(f"Auction budget: ESPN ${draft.get('auctionBudget')}, rules ${AUCTION_BUDGET_PER_TEAM}")
    when = (datetime.fromtimestamp(draft["date"] / 1000).strftime("%a %b %d %I:%M %p")
            if draft.get("date") else "not set")
    return issues, when

def get_free_agents(top=50, league=None):
    if league is None:
        league = get_league()
    free_agents = league.free_agents(size=200)
    players = []
    for p in free_agents:
        if p.injuryStatus in EXCLUDE_STATUSES:
            continue
        players.append({
            "name": p.name,
            "position": p.position,
            "pro_team": p.proTeam,
            "avg_points": p.avg_points,
            "total_points": p.total_points,
            "injured": p.injured,
            "injury_status": p.injuryStatus,
            "games_this_week": 0,
            "game_days": "N/A",
        })
        if len(players) >= top:
            break
    players.sort(key=lambda x: x["avg_points"], reverse=True)
    return players

def get_my_team(league=None):
    if league is None:
        league = get_league()
    my_team = next((t for t in league.teams if t.team_id == 10), None)
    if not my_team:
        return []
    players = []
    for p in my_team.roster:
        players.append({
            "name": p.name,
            "position": p.position,
            "pro_team": p.proTeam,
            "avg_points": p.avg_points,
            "injured": p.injured,
            "injury_status": p.injuryStatus,
            "games_this_week": 0,
            "game_days": "N/A",
        })
    return players

def get_recent_activity(league=None, size=25):
    if league is None:
        league = get_league()
    try:
        activities = league.recent_activity(size=size)
    except Exception as e:
        print(f"Warning: Could not fetch league activity: {e}")
        return []

    events = []
    for act in activities:
        when = datetime.fromtimestamp(act.date / 1000)
        for team, action, player, position in act.actions:
            team_name = getattr(team, "team_name", str(team)) if team else "Unknown"
            events.append({
                "date": when,
                "team": team_name,
                "action": action,
                "player": player,
            })
    return events

def format_activity_for_prompt(activity):
    if not activity:
        return "LEAGUE TRANSACTIONS: No recent activity (league may not have drafted yet)."
    lines = ["RECENT LEAGUE TRANSACTIONS (who your leaguemates are adding/dropping):"]
    for e in activity:
        lines.append(f"  - {e['date'].strftime('%b %d')}: {e['team']} {e['action']} {e['player']}")
    return "\n".join(lines)

def format_free_agents_for_prompt(free_agents):
    lines = ["AVAILABLE FREE AGENTS (active players only, sorted by avg fantasy points):"]
    for p in free_agents:
        status = f" [{p['injury_status']}]" if p['injury_status'] not in ("ACTIVE", "NORMAL", "", None) else ""
        games = f" | {p['games_this_week']} games this week ({p['game_days']})" if p['games_this_week'] > 0 else " | 0 games this week"
        trend = p.get("recent_trend_text", "")
        lines.append(f"  - {p['name']} ({p['position']}, {p['pro_team']}) — {p['avg_points']} avg pts{games}{trend}{status}")
    return "\n".join(lines)

def format_roster_for_prompt(roster):
    lines = ["MY CURRENT ROSTER:"]
    for p in roster:
        injury = f" [{p['injury_status']}]" if p['injured'] else ""
        games = f" | {p['games_this_week']} games this week ({p['game_days']})" if p['games_this_week'] > 0 else " | 0 games this week"
        trend = p.get("recent_trend_text", "")
        lines.append(f"  - {p['name']} ({p['position']}, {p['pro_team']}) — {p['avg_points']} avg pts{games}{trend}{injury}")
    return "\n".join(lines)