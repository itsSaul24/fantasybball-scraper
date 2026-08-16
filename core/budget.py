import os
from core.db import get_today_spend

DAILY_BUDGET_USD = float(os.environ.get("DAILY_BUDGET_USD", "2.00"))

# Draft prep is a rare, one-time-per-season deep run — it gets its own, much larger cap
# so the daily digest's tight ceiling doesn't throttle pre-draft analysis.
DRAFT_BUDGET_USD = float(os.environ.get("DRAFT_BUDGET_USD", "10.00"))

# gemini-3.7-flash introductory pricing; thinking tokens bill at the output rate
GEMINI_INPUT_PRICE_PER_1M = 0.75
GEMINI_OUTPUT_PRICE_PER_1M = 3.75

def estimate_cost(prompt_tokens=0, output_tokens=0, thinking_tokens=0):
    input_cost = prompt_tokens / 1_000_000 * GEMINI_INPUT_PRICE_PER_1M
    output_cost = (output_tokens + thinking_tokens) / 1_000_000 * GEMINI_OUTPUT_PRICE_PER_1M
    return round(input_cost + output_cost, 6)

def budget_remaining(run_type="daily_digest"):
    cap = DRAFT_BUDGET_USD if run_type == "draft_prep" else DAILY_BUDGET_USD
    return max(0.0, cap - get_today_spend(run_type=run_type))

def is_budget_exceeded(run_type="daily_digest"):
    cap = DRAFT_BUDGET_USD if run_type == "draft_prep" else DAILY_BUDGET_USD
    return get_today_spend(run_type=run_type) >= cap
