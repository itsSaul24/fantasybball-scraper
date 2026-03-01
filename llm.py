import os
import requests
from dotenv import load_dotenv
from datetime import datetime
load_dotenv()

# ─── TOGGLE HERE ───────────────────────────────────────────
LLM_PROVIDER = "gemini"  # "ollama" or "gemini"
OLLAMA_MODEL = "qwen3:8b"
OLLAMA_URL   = "http://localhost:11434/api/generate"
# ───────────────────────────────────────────────────────────

def get_current_week():
    try:
        from espn_data import get_league
        league = get_league()
        return league.currentMatchupPeriod
    except Exception:
        return "Unknown"

def ask_gemini(prompt):
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_KEY"])
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
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
        lines.append(line)
    return "\n\n".join(lines)

def run_analysis(posts, free_agents_text, roster_text):
    posts_text = format_posts_for_prompt(posts)
    today = datetime.now().strftime("%B %d, %Y")
    current_week = get_current_week()

    waiver_prompt = f"""
You are an expert fantasy basketball analyst. Today is {today}, and we are in Week {current_week} of the fantasy season.
This is a POINTS league (not categories) — total fantasy points scored is all that matters.

Analyze the Reddit posts below from r/fantasybball and r/nba and provide waiver wire intelligence.

IMPORTANT RULES:
- ONLY recommend players from the FREE AGENTS LIST below
- Do NOT suggest players who are not on this list
- Prioritize players based on Reddit buzz, breakout potential, role changes, and hot streaks
- Avg fantasy points is provided as CONTEXT only — do NOT simply rank by highest avg points
- A player averaging 20pts who just lost their starting role is WORSE than a player averaging 12pts who just became a starter
- Note how many games each team plays this week if mentioned

{free_agents_text}

REDDIT POSTS FROM TODAY:
{posts_text}

Please provide a concise, actionable digest with these sections:

### 🔥 Top Waiver Wire Adds
List the best available free agents to pick up this week. For each player include:
- Name, team, position
- Avg fantasy points
- Why they are worth adding (role, matchup, injury to starter, hot streak etc.)
- Estimated games this week if known

### 🏥 Injury & News Alerts
Key injuries, returns, and lineup changes from today's posts that affect waiver decisions.
For injured players, include estimated return timeline if mentioned in the posts.

### 📰 Overall Fantasy News Summary
2-3 sentences summarizing the biggest fantasy basketball storylines from today's Reddit posts.
"""

    roster_prompt = f"""
You are an expert fantasy basketball analyst. Today is {today}, and we are in Week {current_week} of the fantasy season.
This is a POINTS league (not categories) — total fantasy points scored is all that matters.
We are likely in or approaching the fantasy playoffs, so roster decisions are critical.

{roster_text}

{free_agents_text}

REDDIT POSTS FROM TODAY:
{posts_text}

Based on all of the above, provide a personalized roster report:

### 🚨 Roster Alerts
Any urgent news about MY players from today's posts. For each flagged player include:
- What happened
- Estimated return timeline if mentioned in Reddit posts
- Recommended action (start, sit, drop, stash on IR)

### ➕ Recommended Pickups
Players from the FREE AGENTS LIST that would improve my team right now.
Only suggest players actually on the free agents list. Explain why each fits my roster.

### 🔄 Suggested Add/Drops
Concrete moves to make:
- DROP: [player] → ADD: [player] with brief reasoning for each swap

### ⚠️ Injury Risk Watch
Any of my current roster players showing injury concern based on today's posts.
"""

    print(f"Running waiver wire analysis via {LLM_PROVIDER} (Week {current_week})...")
    waiver = ask(waiver_prompt)

    print(f"Running roster-specific analysis via {LLM_PROVIDER}...")
    roster = ask(roster_prompt)

    return waiver, roster