from datetime import datetime

def current_nba_season(today=None):
    """nba_api-style season string, e.g. '2026-27'. Rolls over Aug 1 (offseason, before training camps)."""
    today = today or datetime.now()
    start_year = today.year if today.month >= 8 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"

def current_espn_year(today=None):
    """espn_api's `year` param — the season's ending year."""
    start_year = int(current_nba_season(today).split("-")[0])
    return start_year + 1

def last_completed_season(today=None):
    """nba_api-style season string for the most recently finished season, e.g. '2025-26'."""
    start_year = int(current_nba_season(today).split("-")[0]) - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"
