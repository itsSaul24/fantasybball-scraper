import os
from datetime import datetime

import pandas as pd
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

# (column, group, plain-English meaning, how to use it live)
COLUMN_GUIDE = [
    ("rank", "Identity", "Position in the pool, ranked by availability-adjusted value.", "Rough draft order. Not a bid price."),
    ("player", "Identity", "Player name.", ""),
    ("position", "Identity", "Primary ESPN position.", "Check against your unfilled slots."),
    ("eligible", "Identity", "Every roster slot ESPN lets this player fill.", "Multi-slot players add lineup flexibility; worth a small premium."),
    ("team", "Identity", "NBA team for the upcoming season.", ""),
    ("team_changed", "Identity", "TRUE if he changed teams this offseason.", "Last season's stats were produced somewhere else — discount them."),
    ("age", "Identity", "Age.", "Pair with career_arc: decline at 34 differs from decline at 24."),
    ("is_rookie", "Identity", "TRUE for incoming rookies with no NBA stats.", "Valued from community discussion only. Treat as a lottery ticket."),
    ("tier", "Verdict", "anchor / core / value / depth / dart.", "Anchors are roster centerpieces; darts are $1-3 fliers."),
    ("trend", "Verdict", "rising / falling / stable / volatile.", "Direction of travel into this season."),
    ("market_vs_value", "Verdict", "Where community sentiment sits vs actual production.", "'underrated' = bargain candidate. 'overhyped' = let the room overpay."),
    ("steal", "Pricing", "At or below this price, buy immediately.", "If bidding is at or under this, raise your hand."),
    ("target", "Pricing", "Realistic expected price; your plan number.", "Budget with this figure."),
    ("walk_away", "Pricing", "Stop bidding here. One more dollar is an overpay.", "Hard stop. Pivot to your alternative."),
    ("mechanical_value", "Pricing", "Formula price from last season's stats, before any judgement.", "A sanity anchor. Large gaps vs target mean the narrative moved the price."),
    ("community_read", "Analysis", "What Reddit actually says, synthesized across commenters.", "Says 'no meaningful discussion found' when the community is silent."),
    ("why", "Analysis", "The case for the price, reconciling community view with the numbers.", "Read before bidding."),
    ("risk", "Analysis", "The single most likely way this pick fails.", "Your pre-mortem."),
    ("live_note", "Analysis", "Tactical guidance for the auction room.", "When to push, when to fold, who to pivot to."),
    ("trajectory", "Analysis", "Year-over-year change, final-20-game form, and minutes trend.", "Late-season collapse plus falling minutes signals a shrinking role."),
    ("career_arc", "History", "Five-year shape: ascent, plateau, decline, with % of peak.", "Separates a rebound candidate from a fading veteran."),
    ("fp_trend_5y", "History", "Fantasy points per game gained/lost per season (fitted slope).", "Positive = climbing. Check seasons_of_data before trusting it."),
    ("fp_peak", "History", "Best single-season fantasy points per game in the last five.", "The realistic ceiling."),
    ("fp_peak_season", "History", "Which season the peak happened.", "A peak four years ago is a warning."),
    ("pct_of_peak", "History", "Last season as a fraction of peak.", "Below 0.85 means meaningfully off his best."),
    ("fp_consistency", "History", "Standard deviation of fantasy points across five seasons.", "Low = predictable. High = boom/bust."),
    ("seasons_of_data", "History", "How many of the last five seasons have usable data.", "Slope on 2 seasons is fragile — treat with caution."),
    ("avg_gp_5y", "History", "Average games played per season over five years.", "The durability track record behind this year's number."),
    ("steal", "Pricing", "", ""),
    ("fp_per_36", "Rate", "League-scored fantasy points per 36 minutes.", "Role-independent rate. High value + low minutes = breakout candidate."),
    ("stocks_pg", "Rate", "Steals plus blocks per game.", "The single most underpriced stat in this format."),
    ("stock_fpts", "Rate", "Fantasy points from steals and blocks alone (3.0 each).", "Shows how much value is defensive."),
    ("stock_share", "Rate", "Fraction of total production coming from stocks.", "High share = value the wider market systematically misses."),
    ("ast_fpts", "Rate", "Fantasy points from assists (1.5 each).", ""),
    ("reb_fpts", "Rate", "Fantasy points from rebounds (1.2 each).", ""),
    ("tov_drag", "Rate", "Fantasy points lost to turnovers.", "Modest penalty here; do not overweight it."),
    ("custom_score_pg", "Production", "Last season's fantasy points per game under THIS league's scoring.", "The core production number."),
    ("adj_score", "Production", "Fantasy points per game after the availability discount.", "What actually drives the ranking."),
    ("durability", "Production", "Availability multiplier from games played (0.70-1.00).", "Weekly H2H pays nothing for games missed."),
    ("GP", "Production", "Games played last season.", ""),
    ("MIN", "Production", "Minutes per game last season.", "Rising minutes often precede a breakout."),
    ("PTS", "Production", "Points per game.", ""),
    ("REB", "Production", "Rebounds per game.", ""),
    ("AST", "Production", "Assists per game.", ""),
    ("STL", "Production", "Steals per game.", ""),
    ("BLK", "Production", "Blocks per game.", ""),
    ("TOV", "Production", "Turnovers per game.", ""),
    ("yoy_trend", "Production", "Change in fantasy points vs the prior season.", ""),
    ("late_trend", "Production", "Final-20-game form vs full-season average.", "Negative means he finished cold."),
    ("min_trend", "Production", "Change in minutes over the final 20 games.", "The clearest early signal of a role change."),
]

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
GROUP_FILL = PatternFill("solid", fgColor="D9E2F3")

def _autosize(ws, max_width=60):
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        longest = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[letter].width = min(max(longest + 2, 9), max_width)

def _style_header(ws):
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

def _resolve_path(path):
    """Excel holds an exclusive lock on an open workbook. Rather than lose a two-hour run
    to a PermissionError, fall back to a timestamped filename and say so."""
    if not os.path.exists(path):
        return path, False
    try:
        with open(path, "a+b"):
            return path, False
    except PermissionError:
        stem, ext = os.path.splitext(path)
        alt = f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M')}{ext}"
        print(f"  ⚠️  {path} is open in Excel — writing to {alt} instead.")
        return alt, True

def _build_legend(df, strategy=None, budget=None, scarcity_text="", meta=None):
    """One reference sheet: what every column means, then the strategy, budget and run
    notes as labelled sections underneath. Keeping these together avoids a tab per idea."""
    present = list(df.columns)
    rows, seen = [], set()
    rows.append({"Section": "COLUMNS", "Item": "", "Detail": ""})
    for col, _group, meaning, use in COLUMN_GUIDE:
        if col in present and col not in seen and meaning:
            seen.add(col)
            detail = f"{meaning} {('— ' + use) if use else ''}".strip()
            rows.append({"Section": "", "Item": col, "Detail": detail})
    for col in present:
        if col not in seen:
            rows.append({"Section": "", "Item": col, "Detail": ""})

    if strategy is not None and not strategy.empty:
        rows.append({"Section": "", "Item": "", "Detail": ""})
        rows.append({"Section": "STRATEGY", "Item": "", "Detail": ""})
        for _, r in strategy.iterrows():
            rows.append({"Section": "", "Item": r["Principle"], "Detail": r["Detail"]})

    if budget is not None and not budget.empty:
        rows.append({"Section": "", "Item": "", "Detail": ""})
        rows.append({"Section": "BUDGET", "Item": "", "Detail": ""})
        for _, r in budget.iterrows():
            label = r["If you land every"]
            cost = r["Cost of 5 base slots"]
            item = f"All {label}" if label != "READ THIS" else "Bottom line"
            detail = f"{('5 base slots cost $' + str(cost) + '. ') if cost != '' else ''}{r['Verdict']}"
            rows.append({"Section": "", "Item": item, "Detail": detail})

    if scarcity_text:
        rows.append({"Section": "", "Item": "", "Detail": ""})
        rows.append({"Section": "POSITIONAL SUPPLY", "Item": "", "Detail": ""})
        for line in scarcity_text.split("\n")[1:]:
            if line.strip():
                part = line.strip().split(":", 1)
                rows.append({"Section": "", "Item": part[0],
                             "Detail": part[1].strip() if len(part) > 1 else ""})

    if meta:
        rows.append({"Section": "", "Item": "", "Detail": ""})
        rows.append({"Section": "RUN INFO", "Item": "", "Detail": ""})
        for k, v in meta.items():
            rows.append({"Section": "", "Item": str(k), "Detail": str(v)})

    return pd.DataFrame(rows)

def write_draft_workbook(df, path, scarcity_text="", meta=None, board=None,
                         strategy=None, budget=None):
    """Three sheets, in the order you use them: the positional board you draft from,
    the full player pool, and a single reference sheet."""
    present = list(df.columns)
    legend = _build_legend(df, strategy=strategy, budget=budget,
                           scarcity_text=scarcity_text, meta=meta)
    path, _ = _resolve_path(path)

    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        if board is not None and not board.empty:
            board.to_excel(xl, sheet_name="Dream Team", index=False)
        df.to_excel(xl, sheet_name="All Players", index=False)
        legend.to_excel(xl, sheet_name="Legend", index=False)

        for name in xl.book.sheetnames:
            ws = xl.book[name]
            _style_header(ws)
            _autosize(ws)

        if "Dream Team" in xl.book.sheetnames:
            ws = xl.book["Dream Team"]
            for row in ws.iter_rows(min_row=2):
                for c in row:
                    c.alignment = Alignment(vertical="top", wrap_text=True)
            for letter, width in (("A", 10), ("B", 11), ("C", 22), ("M", 55), ("N", 45)):
                ws.column_dimensions[letter].width = width

        # Long prose columns need a fixed width or they blow out the sheet.
        players = xl.book["All Players"]
        for col_name in ("community_read", "why", "risk", "live_note", "trajectory"):
            if col_name in present:
                players.column_dimensions[get_column_letter(present.index(col_name) + 1)].width = 60

        lg = xl.book["Legend"]
        lg.column_dimensions["A"].width = 20
        lg.column_dimensions["B"].width = 24
        lg.column_dimensions["C"].width = 110
        for row in lg.iter_rows(min_row=2):
            row[2].alignment = Alignment(vertical="top", wrap_text=True)
            if row[0].value:                       # section header rows
                for c in row:
                    c.font = Font(bold=True, size=11)
                    c.fill = GROUP_FILL
    return path
