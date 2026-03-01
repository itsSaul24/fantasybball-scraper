import os
import requests
from dotenv import load_dotenv
from datetime import datetime
load_dotenv()

# ─── TOGGLE HERE ───────────────────────────────────────────
LLM_PROVIDER = "gemini"  # "ollama" or "gemini"
OLLAMA_MODEL = "qwen3:8b"
OLLAMA_URL   = "http://localhost:11434/api/generate"
MAX_PROMPT_CHARS = 100_000
# ───────────────────────────────────────────────────────────

last_token_usage = {
    "prompt_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
}

def get_current_week():
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from espn_data import get_league
        league = get_league()
        return league.currentMatchupPeriod
    except Exception as e:
        print(f"  Warning: Could not get current week: {e}")
        return "Unknown"

def ask_gemini(prompt):
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_KEY"])
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        last_token_usage["prompt_tokens"] = getattr(response.usage_metadata, "prompt_token_count", 0)
        last_token_usage["output_tokens"] = getattr(response.usage_metadata, "candidates_token_count", 0)
        last_token_usage["total_tokens"] = getattr(response.usage_metadata, "total_token_count", 0)
    return response.text

def ask_ollama(prompt):
    res = requests.post(OLLAMA_URL, json={
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }, timeout=180)
    return res.json()["response"]

def ask(prompt):
    if LLM_PROVIDER == "ollama":
        return ask_ollama(prompt)
    else:
        return ask_gemini(prompt)

def format_posts_for_prompt(posts):
    lines = []
    for p in posts:
        line = f"[{p['flair'] or 'General'}] {p['title']} (score: {p['score']})"
        if p["body"]:
            line += f"\n  {p['body']}"
        comments = p.get("comments", [])
        if comments:
            line += "\n  Top comments:"
            for c in comments:
                line += f"\n    > {c}"
        lines.append(line)
    return "\n\n".join(lines)

def truncate_to_limit(posts_text, free_agents_text, roster_text, matchup_text=""):
    static_chars = len(free_agents_text) + len(roster_text) + len(matchup_text)
    available_for_posts = MAX_PROMPT_CHARS - static_chars
    if len(posts_text) > available_for_posts:
        print(f"  ⚠️ Truncating posts: {len(posts_text):,} → {available_for_posts:,} chars")
        posts_text = posts_text[:available_for_posts]
    total = static_chars + len(posts_text)
    print(f"  Total prompt chars: {total:,} / {MAX_PROMPT_CHARS:,}")
    return posts_text

def run_analysis(posts, free_agents_text, roster_text, matchup_text=""):
    posts_text = format_posts_for_prompt(posts)
    today = datetime.now().strftime("%B %d, %Y")
    current_week = get_current_week()
    next_week = current_week + 1 if isinstance(current_week, int) else "Unknown"

    posts_text = truncate_to_limit(posts_text, free_agents_text, roster_text, matchup_text)

    prompt = f"""
You are an expert fantasy basketball analyst. Today is {today}, Week {current_week} of the fantasy season.
This is a POINTS league — total fantasy points is all that matters, not categories.
We are in or approaching the fantasy playoffs so every decision is critical.

You have been given:
1. My current roster with avg points and weekly schedule
2. Available free agents with avg points and weekly schedule
3. Current matchup details including live scores, my lineup, and my opponent's full roster
4. Today's Reddit posts from r/fantasybball and r/nba (including top comments)

KEY RULES:
- Use Reddit posts and comments as your PRIMARY source of insight
- Avg fantasy points is CONTEXT only — trending players beat high-avg players who lost minutes
- Weekly game count is CRITICAL — a player with 4 games often outscores a better player with 2 games
- ONLY recommend free agent adds from the FREE AGENTS LIST
- PAY ATTENTION TO THE TIMING NOTE in the matchup section — if it's Sunday, recommend for NEXT WEEK only
- Be specific, direct, and actionable

---

{matchup_text}

---

{roster_text}

---

{free_agents_text}

---

REDDIT POSTS FROM TODAY (including top comments):
{posts_text}

---

Produce a daily digest with EXACTLY these sections in this order:

### 🏆 Matchup Analysis
Analyze my current matchup vs {'{opponent}'}. Include:
- Current standing (leading/trailing by X pts)
- Projected final margin
- Key players driving the score on both sides
- What I need to win or protect my lead
- Any opponent players who are injured or underperforming that I should exploit
- Specific recommendations based on today being {today} ({datetime.now().strftime('%A')})

### 🔥 Top Waiver Wire Adds
Best free agents to add based on Reddit buzz, role changes, injuries to starters, or hot streaks.
Make it clear if the recommendation is for THIS WEEK (Week {current_week}) or NEXT WEEK (Week {next_week}).
For each player:
- Name (Position, TEAM) — avg pts
- Why add: [specific reason]
- Week {current_week} Games: [number]
Only include players from the FREE AGENTS LIST. Prioritize 4-game weeks.

### 🏥 Injury & News Alerts
Key injuries and news from today's posts affecting waiver decisions.
For each: player name, what happened, return timeline if mentioned, fantasy impact.

### 📰 Overall Fantasy News Summary
2-3 sentences on the biggest fantasy basketball storylines from today's Reddit posts.

### 🚨 Roster Alerts
Urgent news about MY current roster players.
For each flagged player:
- What happened
- Estimated return timeline (from Reddit posts if mentioned)
- Recommended action: START / SIT / DROP / STASH ON IR

### ➕ Recommended Pickups
Players from the FREE AGENTS LIST that improve my team.
For each: name, avg pts, games this week, why they fit my roster specifically.
Clarify if pickup is for current matchup or next week.

### 🔄 Suggested Add/Drops
Concrete moves:
DROP: [player] → ADD: [player]
Reasoning: [specific reason — injury, schedule, role change, matchup context]

### ⚠️ Injury Risk Watch
My roster players with active injury concern. What to watch for.
"""

    print(f"Running full analysis via {LLM_PROVIDER} (Week {current_week})...")
    result = ask(prompt)

    if LLM_PROVIDER == "gemini" and last_token_usage["total_tokens"] > 0:
        print(f"  Tokens — Input: {last_token_usage['prompt_tokens']:,} | Output: {last_token_usage['output_tokens']:,} | Total: {last_token_usage['total_tokens']:,}")

    # Split into waiver and roster sections for email
    waiver_headers = ["### 🏆", "### 🔥", "### 🏥", "### 📰"]
    roster_headers = ["### 🚨", "### ➕", "### 🔄", "### ⚠️"]

    lines = result.split("\n")
    current_section = "waiver"
    waiver_lines = []
    roster_lines = []

    for line in lines:
        if any(h in line for h in roster_headers):
            current_section = "roster"
        elif any(h in line for h in waiver_headers):
            current_section = "waiver"
        if current_section == "waiver":
            waiver_lines.append(line)
        else:
            roster_lines.append(line)

    return "\n".join(waiver_lines), "\n".join(roster_lines)