# 🏀 Fantasy BBall Daily Digest

Scrapes r/fantasybball and r/nba daily, analyzes with Gemini Flash, and emails you a personalized fantasy basketball digest with waiver wire recommendations and roster-specific alerts.

## Setup

```bash
pip install -r requirements.txt
```

Make sure your `.env` file has:
```
GEMINI_KEY=your_gemini_key
GMAIL_ADDRESS=your@gmail.com
GMAIL_APP_PASSWORD=your_app_password
```

## Run

```bash
python main.py
```

## Automate (run daily at 8am)

Add to crontab (`crontab -e`):
```
0 8 * * * cd /path/to/fantasybball-scraper && python main.py
```

## Files

- `main.py` — orchestrates everything
- `scraper.py` — fetches Reddit posts (no API key needed)
- `llm.py` — sends posts to Gemini Flash for analysis
- `emailer.py` — sends HTML email digest
- `roster.py` — your current fantasy roster (update weekly)
