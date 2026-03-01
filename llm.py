import os
from dotenv import load_dotenv
load_dotenv()

from google import genai
from roster import MY_ROSTER

def format_posts_for_prompt(posts):
    lines = []
    for p in posts:
        line = f"[{p['flair'] or 'General'}] {p['title']} (score: {p['score']})"
        if p["body"]:
            line += f"\n  {p['body']}"
        lines.append(line)
    return "\n\n".join(lines)

def run_analysis(posts):
    client = genai.Client(api_key=os.environ["GEMINI_KEY"])
    posts_text = format_posts_for_prompt(posts)
    roster_str = ", ".join(MY_ROSTER)

    waiver_prompt = f"""
You are an expert fantasy basketball analyst. Analyze these Reddit posts from r/fantasybball and r/nba and produce a daily digest.

POSTS:
{posts_text}

Please provide:
1. **Top Waiver Wire Adds** - Players being heavily discussed as pickups (with reasoning)
2. **Injury & News Alerts** - Any notable player injuries, returns, or lineup changes
3. **Players to Sell High** - Anyone with inflated value right now
4. **Players to Buy Low** - Undervalued players worth targeting
5. **Overall Sentiment Summary** - 2-3 sentences on the day's biggest fantasy storylines

Be concise and actionable. Focus on players likely available on waivers (not stars).
"""

    roster_prompt = f"""
You are an expert fantasy basketball analyst.

My current roster: {roster_str}

Here are today's Reddit posts from r/fantasybball and r/nba:
{posts_text}

Based on this, please provide:
1. **Roster Alerts** - Any news about MY players I need to act on immediately
2. **Targeted Waiver Adds** - Specific adds that fill gaps or upgrade my roster
3. **Suggested Add/Drops** - Concrete recommendations (who to drop, who to add)
4. **Injury Risk Watch** - Any of my players showing injury concern

Be direct and specific. My league is ESPN standard categories.
"""

    print("Running waiver wire analysis...")
    waiver_response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=waiver_prompt
    )

    print("Running roster-specific analysis...")
    roster_response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=roster_prompt
    )

    return waiver_response.text, roster_response.text