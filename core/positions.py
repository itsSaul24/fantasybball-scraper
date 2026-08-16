import unicodedata
from core.espn_data import get_league
from core.league_rules import NUM_TEAMS

# Starting slots per team from the rulebook: PG SG SF PF C G F UTIL UTIL.
# G and F are flex, so demand at a base position exceeds its dedicated slot count.
STARTERS_PER_TEAM = {"PG": 1, "SG": 1, "SF": 1, "PF": 1, "C": 1}
FLEX_SLOTS = {"G": ("PG", "SG"), "F": ("SF", "PF")}

def _norm(name):
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    return name.lower().replace(".", "").replace("'", "").strip()

def get_position_map(league=None):
    """{normalized player name: (position, eligible_slots)} for everyone in the league
    universe. ESPN is the right source here: its eligibility is what actually governs
    which roster slot a player can fill on draft night."""
    league = league or get_league()
    mapping = {}
    try:
        pool = list(league.free_agents(size=1000))
        for team in league.teams:
            pool.extend(team.roster)
    except Exception as e:
        print(f"  Warning: could not load ESPN positions: {e}")
        return {}

    for p in pool:
        slots = [s for s in getattr(p, "eligibleSlots", []) if s not in ("BE", "IR", "UT")]
        mapping[_norm(p.name)] = (getattr(p, "position", ""), slots)
    return mapping

def attach_positions(df, position_map):
    df = df.copy()
    df["position"] = [position_map.get(_norm(n), ("", []))[0] for n in df["PLAYER_NAME"]]
    df["eligible"] = ["/".join(position_map.get(_norm(n), ("", []))[1]) for n in df["PLAYER_NAME"]]
    return df

def positional_scarcity(df, top_n=182):
    """How deep each position runs among the players who will actually be rostered.

    Auction strategy is positional: if only nine centers clear replacement level and
    fourteen teams each need one, centers command a premium and waiting is punished.
    Returns {position: {...}} summarizing supply, demand and value concentration."""
    pool = df.head(top_n)
    demand = dict(STARTERS_PER_TEAM)
    report = {}
    for pos, need_per_team in demand.items():
        # Flex slots (G/F) add demand on top of the dedicated slot.
        flex_extra = sum(0.5 for _, bases in FLEX_SLOTS.items() if pos in bases)
        total_demand = round((need_per_team + flex_extra) * NUM_TEAMS)
        at_pos = pool[pool["position"] == pos]
        starters = at_pos.head(total_demand)
        report[pos] = {
            "supply_in_pool": len(at_pos),
            "demand": total_demand,
            "median_value_of_starters": round(float(starters["mechanical_value"].median()), 1) if len(starters) else 0.0,
            "value_cliff": round(
                float(starters["mechanical_value"].min() - at_pos["mechanical_value"].median()), 1
            ) if len(starters) else 0.0,
            "scarcity_ratio": round(total_demand / max(len(at_pos), 1), 2),
        }
    return report

def format_scarcity_for_prompt(report):
    lines = ["POSITIONAL SCARCITY (supply of startable players vs league-wide demand):"]
    for pos, r in sorted(report.items(), key=lambda kv: -kv[1]["scarcity_ratio"]):
        tightness = "TIGHT" if r["scarcity_ratio"] >= 0.9 else "adequate" if r["scarcity_ratio"] >= 0.6 else "deep"
        lines.append(
            f"  {pos}: {r['supply_in_pool']} rosterable vs {r['demand']} needed league-wide "
            f"({tightness}); median starter value ${r['median_value_of_starters']}"
        )
    return "\n".join(lines)
