import os
from dotenv import load_dotenv
load_dotenv()

from espn_api.basketball import League

EXCLUDE_STATUSES = {"OUT", "IR", "SUSPENSION", "INJURED_RESERVE"}

def get_league():
    return League(
        league_id=int(os.environ["ESPN_LEAGUE_ID"]),
        year=2026,
        espn_s2=os.environ["ESPN_S2"],
        swid=os.environ["ESPN_SWID"]
    )

def get_free_agents(top=50):
    league = get_league()
    # Fetch a large pool so we have enough after filtering OUT players
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
        })
        if len(players) >= top:
            break
    players.sort(key=lambda x: x["avg_points"], reverse=True)
    return players

def get_my_team():
    league = get_league()
    my_team = None
    for team in league.teams:
        if team.team_id == 10:
            my_team = team
            break
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
        })
    return players

def format_free_agents_for_prompt(free_agents):
    lines = ["AVAILABLE FREE AGENTS (active players only, sorted by avg fantasy points):"]
    for p in free_agents:
        status = f" [{p['injury_status']}]" if p['injury_status'] not in ("ACTIVE", "NORMAL", "") else ""
        lines.append(f"  - {p['name']} ({p['position']}, {p['pro_team']}) — {p['avg_points']} avg pts{status}")
    return "\n".join(lines)

def format_roster_for_prompt(roster):
    lines = ["MY CURRENT ROSTER:"]
    for p in roster:
        injury = f" [{p['injury_status']}]" if p['injured'] else ""
        lines.append(f"  - {p['name']} ({p['position']}, {p['pro_team']}) — {p['avg_points']} avg pts{injury}")
    return "\n".join(lines)