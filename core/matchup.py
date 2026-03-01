import os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

def get_matchup_context(league, my_team_id=10):
    """Fetch current matchup data and format for LLM prompt."""
    try:
        my_team = next(t for t in league.teams if t.team_id == my_team_id)
        box_scores = league.box_scores(matchup_period=league.currentMatchupPeriod)

        my_box = None
        for box in box_scores:
            is_home = box.home_team and box.home_team.team_id == my_team_id
            is_away = box.away_team and box.away_team.team_id == my_team_id
            if is_home or is_away:
                my_box = box
                is_my_home = is_home
                break

        if not my_box:
            return None, None

        my_score = my_box.home_score if is_my_home else my_box.away_score
        my_projected = my_box.home_projected if is_my_home else my_box.away_projected
        opp_team = my_box.away_team if is_my_home else my_box.home_team
        opp_score = my_box.away_score if is_my_home else my_box.home_score
        opp_projected = my_box.away_projected if is_my_home else my_box.home_projected
        my_lineup = my_box.home_lineup if is_my_home else my_box.away_lineup
        opp_lineup = my_box.away_lineup if is_my_home else my_box.home_lineup

        diff = my_score - opp_score
        leading = "LEADING" if diff > 0 else "TRAILING" if diff < 0 else "TIED"

        # ESPN returns -1 when projection is unavailable
        my_projected = my_projected if my_projected > 0 else None
        opp_projected = opp_projected if opp_projected > 0 else None

        # Determine matchup timing context
        today = datetime.now()
        day_of_week = today.weekday()  # 0=Mon, 6=Sun
        day_name = today.strftime("%A")

        if day_of_week == 6:  # Sunday
            timing = "END_OF_WEEK"
            timing_note = "Today is Sunday — this matchup ends tonight. Focus on NEXT WEEK's pickups, not this week."
        elif day_of_week >= 4:  # Fri/Sat
            timing = "LATE_WEEK"
            timing_note = "Late in the matchup week. Consider both finishing strong this week AND planning next week's adds."
        elif day_of_week <= 1:  # Mon/Tue
            timing = "EARLY_WEEK"
            timing_note = "Early in the matchup week. In-week pickups are highly relevant. Also consider next week."
        else:  # Wed/Thu
            timing = "MID_WEEK"
            timing_note = "Mid-week. Balance between winning this matchup and planning ahead for next week."

        # Format my lineup
        my_lineup_lines = []
        for p in my_lineup:
            pts = getattr(p, 'points', 0) or 0
            my_lineup_lines.append(f"  {p.name} — {pts:.1f} pts this week")

        # Format opponent lineup
        opp_lineup_lines = []
        for p in opp_lineup:
            pts = getattr(p, 'points', 0) or 0
            opp_lineup_lines.append(f"  {p.name} — {pts:.1f} pts this week")

        # Format opponent roster
        opp_roster_lines = []
        for p in opp_team.roster:
            injury = f" [{p.injuryStatus}]" if p.injuryStatus not in ("ACTIVE", "NORMAL") else ""
            opp_roster_lines.append(f"  {p.name} ({p.position}, {p.proTeam}) — {p.avg_points} avg{injury}")

        proj_my = f"{my_projected:.1f} pts" if my_projected else "N/A"
        proj_opp = f"{opp_projected:.1f} pts" if opp_projected else "N/A"
        proj_margin = f"{my_projected - opp_projected:+.1f} pts" if my_projected and opp_projected else "N/A"

        matchup_text = f"""CURRENT MATCHUP — Week {league.currentMatchupPeriod} ({day_name})
⚠️ TIMING NOTE: {timing_note}

My Team: {my_team.team_name}
  Current Score: {my_score:.1f} pts
  Projected Score: {proj_my}

Opponent: {opp_team.team_name}
  Current Score: {opp_score:.1f} pts
  Projected Score: {proj_opp}

Status: {leading} by {abs(diff):.1f} pts
Projected margin: {proj_margin}

MY ACTIVE LINEUP THIS WEEK:
{chr(10).join(my_lineup_lines)}

OPPONENT ACTIVE LINEUP THIS WEEK:
{chr(10).join(opp_lineup_lines)}

OPPONENT FULL ROSTER:
{chr(10).join(opp_roster_lines)}"""

        return matchup_text, {
            "my_score": my_score,
            "opp_score": opp_score,
            "my_projected": my_projected,
            "opp_projected": opp_projected,
            "opp_team_name": opp_team.team_name,
            "diff": diff,
            "leading": leading,
            "timing": timing,
            "day_name": day_name,
        }

    except Exception as e:
        import traceback
        print(f"Warning: Could not fetch matchup data: {e}")
        traceback.print_exc()
        return None, None


def format_matchup_for_log(info):
    if not info:
        return "Matchup data unavailable"
    proj_my = f"{info['my_projected']:.1f}" if info['my_projected'] else "N/A"
    proj_opp = f"{info['opp_projected']:.1f}" if info['opp_projected'] else "N/A"
    return (
        f"{info['leading']} by {abs(info['diff']):.1f} pts vs {info['opp_team_name']} "
        f"({info['my_score']:.1f} - {info['opp_score']:.1f}) | "
        f"Projected: {proj_my} - {proj_opp}"
    )