import json
import time
import unicodedata
from collections import Counter

from core.llm import ask_gemini, last_token_usage
from core.budget import estimate_cost, DRAFT_BUDGET_USD
from core.db import get_today_spend
from core.league_rules import MIN_BID, AUCTION_BUDGET_PER_TEAM
from core.draft_valuation import describe_trend

# Draft prep runs once a season against a large budget — buy the deeper reasoning.
DRAFT_THINKING_LEVEL = "high"

def _normalize(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower().strip()

def match_player_context(players_df, posts, max_snippets=3, max_chars_per_snippet=350):
    """Matches scraped Reddit posts/comments to players by name, returns {player_id: [snippets]}."""
    normalized_posts = []
    for p in posts:
        parts = [p["title"], p.get("body", "")] + p.get("comments", [])
        raw = " ".join(t for t in parts if t)
        normalized_posts.append((_normalize(raw), raw))

    last_name_counts = Counter(_normalize(n.split()[-1]) for n in players_df["PLAYER_NAME"])
    first_name_counts = Counter(_normalize(n.split()[0]) for n in players_df["PLAYER_NAME"])

    context = {}
    for _, row in players_df.iterrows():
        parts = row["PLAYER_NAME"].split()
        full_norm = _normalize(row["PLAYER_NAME"])
        first_norm, last_norm = _normalize(parts[0]), _normalize(parts[-1])
        unique_last = last_name_counts[last_norm] == 1
        unique_first = first_name_counts[first_norm] == 1
        snippets = []
        for norm_text, raw_text in normalized_posts:
            if (
                full_norm in norm_text
                or (unique_last and last_norm in norm_text)
                or (unique_first and first_norm in norm_text)
            ):
                snippets.append(raw_text[:max_chars_per_snippet])
                if len(snippets) >= max_snippets:
                    break
        context[row["PLAYER_ID"]] = snippets
    return context

def merge_context(keyword_context, semantic_context, max_snippets=5):
    """Unions keyword-matched and semantically-matched snippets per player, deduped."""
    merged = {}
    all_ids = set(keyword_context) | set(semantic_context)
    for pid in all_ids:
        combined = []
        for snippet in keyword_context.get(pid, []) + semantic_context.get(pid, []):
            if snippet not in combined:
                combined.append(snippet)
            if len(combined) >= max_snippets:
                break
        merged[pid] = combined
    return merged

def _build_batch_prompt(batch_df, context_map, scarcity_text=""):
    lines = []
    for _, row in batch_df.iterrows():
        ctx = context_map.get(row["PLAYER_ID"], [])
        ctx_text = "\n      * ".join(ctx) if ctx else "(none found)"
        team_note = (
            f", MOVED {row['last_season_team']} -> {row['current_team']} this offseason"
            if row["team_changed"] else ""
        )
        pos = row.get("position") or "?"
        eligible = row.get("eligible") or ""
        elig_note = f" [eligible: {eligible}]" if eligible else ""
        lines.append(
            f"""- {row['PLAYER_NAME']} ({pos}, {row['current_team']}{team_note}), age {row['AGE']:.0f}{elig_note}
    Last season per-game: {row['PTS']:.1f}p / {row['REB']:.1f}r / {row['AST']:.1f}a / """
            f"""{row['STL']:.1f}s / {row['BLK']:.1f}b / {row['TOV']:.1f}to / {row['FG3M']:.1f} 3pm """
            f"""in {int(row['GP'])} GP, {row['MIN']:.1f} mpg
    League-scored value: {row['custom_score_pg']:.1f} fpts/g """
            f"""(availability-adjusted {row['adj_score']:.1f}, durability {row['durability']:.2f})
    TRAJECTORY: {describe_trend(row)}
    Mechanical auction value: ${row['mechanical_value']:.1f}
    Reddit discussion (each snippet prefixed with its publish date):
      * {ctx_text}"""
        )
    players_block = "\n\n".join(lines)
    scarcity_block = f"\n{scarcity_text}\n" if scarcity_text else ""

    return f"""You are a sharp fantasy basketball auction analyst preparing a bidding sheet a
manager will have OPEN IN FRONT OF THEM during a live auction. Every word you write should
help them decide, in ten seconds, whether the current bid is a bargain or a trap.

LEAGUE: 14 teams, $200 budget each, 13 roster spots, one head-to-head matchup per week.
SCORING: PTS 1.0, REB 1.2, AST 1.5, STL 3.0, BLK 3.0, TOV -1.0, made 3s +0.5 bonus.
Field goals and free throws (attempted AND made) are worth ZERO. Two consequences you must
reason from: (a) inefficient high-volume shooters are not punished at all, so chuckers are
underrated here; (b) steals and blocks at 3.0 are enormous — a 2.0 stocks/game player earns
6 fpts/g from that alone, which is worth more than 5 rebounds.
MARKET CONTEXT: $2,800 total across 182 rostered players (~$15 avg). Elite players go
$50-70; the back half of every roster is $1-3 filler. Money spent early is committed, not
saved — every dollar over market on a star is a dollar missing from your middle class.
ROSTER SLOTS: PG, SG, SF, PF, C, G(PG/SG), F(SF/PF), UTIL x2, plus 4 bench and 2 IR.
{scarcity_block}

For each player you get: last season's per-game production, a TRAJECTORY line (year-over-year
change, late-season form over the final 20 games, and minutes trend), a mechanical auction
value computed by value-over-replacement on this league's exact scoring, and real Reddit
discussion about him.

HOW TO REASON — READ THE ROOM FIRST:
- THE REDDIT DISCUSSION IS YOUR PRIMARY INPUT. The mechanical value is backward-looking
  arithmetic on last season's box scores; it cannot see a trade, a role change, a rookie
  arriving, a coach's rotation plan, or where the market has already moved. The community
  can. When the discussion and the mechanical value disagree, the discussion usually knows
  something the arithmetic does not — follow it, and say what it knows.
- Treat the mechanical value as a sanity anchor, not an answer: it tells you roughly what
  last season's production was worth, and keeps you from drifting into fantasy.
- SYNTHESIZE ACROSS COMMENTS rather than quoting one. Look for the consensus, the dissent,
  and the intensity: several independent people fading the same player is a real signal;
  one loud contrarian is not. Note when the community is split — split opinion means a wide
  gap between your steal and walk_away prices.
- MARKET AWARENESS IS EDGE. If the discussion shows a player is a popular breakout pick,
  expect his auction price to be bid ABOVE his mechanical value, and set walk_away where
  the hype stops being worth it. If the community has soured on someone whose production is
  intact, that is where bargains live — set an aggressive steal price and say why.
- TRAJECTORY IS OFTEN THE BURIED LEDE. A player whose final-20-game line collapsed while his
  minutes fell is being phased out; one who finished hot with rising minutes is being handed
  a role. Use it to corroborate or challenge what the community claims.
- Weigh age against trajectory: a 34-year-old trending down is a different asset than a
  23-year-old trending down.
- AVAILABILITY IS VALUE. The availability-adjusted score already discounts players who
  missed time, because weekly head-to-head pays nothing for games not played. A high
  per-game rate on 35 games is a luxury, not a foundation — price it accordingly.
- POSITIONAL SCARCITY CHANGES PRICE. A tight position means waiting gets punished and a
  modest premium is rational; a deep position means the same production will be available
  later for less, so bid conservatively and pivot.
- READ THE DATES. Every Reddit snippet is prefixed with its publish date. Posts from the
  current offseason describe the rosters you are drafting; anything from last season's
  in-season months may describe a team the player has since left, an injury long since
  resolved, or a role that no longer exists. Weight recent discussion far more heavily, and
  never state a player is currently injured based on a dated in-season post.
- Do not invent facts or manufacture a narrative. If the retrieved discussion is generic,
  off-topic, or absent for a player, say plainly that the read is stats-driven and lean on
  the trajectory instead.

PLAYERS:
{players_block}

Return ONLY a JSON array, one object per player above, in exactly this shape:
[{{"name": "Full Player Name",
   "tier": "one of: anchor | core | value | depth | dart",
   "trend": "rising | falling | stable | volatile",
   "community_read": "what the Reddit discussion actually says about him, synthesized across commenters — the consensus, any notable dissent, and whether the market is high or low on him. Write 'no meaningful discussion found' if the retrieved chunks say nothing useful about him. Never fabricate.",
   "market_vs_value": "one of: overhyped | fairly priced | underrated | unknown — where community sentiment sits relative to his actual production",
   "walk_away": 46.0,
   "target": 38.0,
   "steal": 30.0,
   "why": "2-3 sentences of real analysis. Lead with the single most decision-relevant fact, and reconcile what the community says with what the trajectory shows. No filler adjectives.",
   "risk": "the specific thing most likely to make this pick fail, in one short clause",
   "live_note": "one tactical sentence for the auction room: when to push, when to let him go, who to pivot to"}}]

PRICE DEFINITIONS — be decisive, these drive real money:
- walk_away: the price where you STOP bidding. One more dollar and you have overpaid.
- target: what you realistically expect to pay; your plan price.
- steal: at or below this, buy immediately without thinking.
Require steal < target < walk_away, each between ${MIN_BID} and ${AUCTION_BUDGET_PER_TEAM}.
Anchor these to the mechanical value and the market context above; deviate beyond roughly
+/-30% only when trajectory or discussion gives a concrete reason, and name that reason in
"why". No text outside the JSON array."""

def _parse_batch_response(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())

TEXT_FIELDS = {
    "tier": "unrated",
    "trend": "unknown",
    "community_read": "",
    "market_vs_value": "unknown",
    "why": "",
    "risk": "",
    "live_note": "",
}

def _coerce_prices(r, mechanical):
    """Keeps the LLM's prices usable: numeric, ordered steal < target < walk_away, and
    inside the league's legal bid range."""
    def num(key, default):
        try:
            return max(MIN_BID, min(float(r.get(key, default)), AUCTION_BUDGET_PER_TEAM))
        except (TypeError, ValueError):
            return default
    walk = num("walk_away", mechanical)
    target = num("target", mechanical * 0.85)
    steal = num("steal", mechanical * 0.7)
    target = min(target, walk)
    steal = min(steal, target)
    return round(walk, 1), round(target, 1), round(steal, 1)

def refine_valuations(players_df, context_map, top_n=250, batch_size=10, max_batches=None,
                      budget_cap=None, run_type="draft_prep", scarcity_text=""):
    """LLM-refines the top_n players (by mechanical value) in batches. Players outside
    top_n keep a mechanical-only fallback range. Returns (df_with_bids, total_cost_usd)."""
    cap = budget_cap if budget_cap is not None else DRAFT_BUDGET_USD
    df = players_df.copy()
    df["walk_away"] = df["mechanical_value"]
    df["target"] = (df["mechanical_value"] * 0.85).round(1).clip(lower=MIN_BID)
    df["steal"] = (df["mechanical_value"] * 0.7).round(1).clip(lower=MIN_BID)
    for field, default in TEXT_FIELDS.items():
        df[field] = default
    df["why"] = "Below LLM-refinement cutoff — mechanical value from last-season stats only."

    refine_pool = df.head(top_n)
    batches = [refine_pool.iloc[i:i + batch_size] for i in range(0, len(refine_pool), batch_size)]
    if max_batches:
        batches = batches[:max_batches]

    name_to_idx = {_normalize(row["PLAYER_NAME"]): idx for idx, row in df.iterrows()}
    spent_before = get_today_spend(run_type=run_type)
    total_cost = 0.0
    refined = 0

    for b_num, batch in enumerate(batches):
        if spent_before + total_cost >= cap:
            print(f"  Budget cap ${cap:.2f} reached after {b_num} batches — stopping early.")
            break
        try:
            response_text = ask_gemini(
                _build_batch_prompt(batch, context_map, scarcity_text),
                thinking_level=DRAFT_THINKING_LEVEL,
            )
            total_cost += estimate_cost(
                last_token_usage.get("prompt_tokens", 0),
                last_token_usage.get("output_tokens", 0),
                last_token_usage.get("thinking_tokens", 0),
            )
            for r in _parse_batch_response(response_text):
                idx = name_to_idx.get(_normalize(r.get("name", "")))
                if idx is None:
                    continue
                walk, target, steal = _coerce_prices(r, df.at[idx, "mechanical_value"])
                df.at[idx, "walk_away"], df.at[idx, "target"], df.at[idx, "steal"] = walk, target, steal
                for field in TEXT_FIELDS:
                    if r.get(field):
                        df.at[idx, field] = str(r[field]).strip()
                refined += 1
            print(f"  Batch {b_num + 1}/{len(batches)} done ({refined} players refined, ${total_cost:.3f})")
        except Exception as e:
            print(f"  Batch {b_num + 1} failed ({e}) — keeping mechanical values for this batch.")
        time.sleep(1)

    return df, total_cost
