"""Live auction-draft tracker.

Polls ESPN for completed auction picks, then rewrites two files after every sale:

  draft_live.xlsx  - for you: Teams / Picks / Board / My Targets
  draft_state.md   - for the model (Claude): a compact, self-describing snapshot that
                     already contains budgets, max bids, inflation, positional holes,
                     which of your targets are still alive and a ranked nomination shortlist.

Run:   python draft_tracker.py --watch          (poll every 5s during the draft)
       python draft_tracker.py                  (one snapshot)
       python draft_tracker.py --mock 40        (simulate 40 sales from the plan, no ESPN picks needed)

Valuations come from draft_plan.csv (+ the Dream Team sheet of draft_plan.xlsx), which
draft_prep.py writes. Nothing here calls an LLM; judgement is done by reading draft_state.md.
"""
import os
import sys
import json
import time
import random
import difflib
import unicodedata
from datetime import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import requests
import pandas as pd
from dotenv import load_dotenv
load_dotenv()

from core.season import current_espn_year

PLAN_CSV = "draft_plan.csv"
PLAN_XLSX = "draft_plan.xlsx"
LIVE_XLSX = "draft_live.xlsx"
STATE_MD = "draft_state.md"
PLAYER_MAP = "draft_player_map.json"

LEAGUE_ID = os.environ.get("ESPN_LEAGUE_ID", "2031909429")
MY_TEAM_ID = int(os.environ.get("MY_TEAM_ID", "10"))
BUDGET = 200
ROSTER_SPOTS = 13
BASE = (f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/"
        f"{current_espn_year()}/segments/0/leagues/{LEAGUE_ID}")

POS_ID = {1: "PG", 2: "SG", 3: "SF", 4: "PF", 5: "C"}   # ESPN defaultPositionId
POSITIONS = ["PG", "SG", "SF", "PF", "C"]


# ───────────────────────── ESPN access ─────────────────────────
def _cookies():
    return {"espn_s2": os.environ["ESPN_S2"], "SWID": os.environ["ESPN_SWID"]}

def _get(params, headers=None, url=BASE):
    r = requests.get(url, params=params, cookies=_cookies(), headers=headers or {}, timeout=20)
    r.raise_for_status()
    return r.json()

def norm(name):
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    for junk in (".", ",", "'", "-"):
        s = s.replace(junk, " ")
    parts = [p for p in s.split() if p not in ("jr", "sr", "ii", "iii", "iv")]
    return " ".join(parts)

def load_player_map():
    """ESPN playerId -> (name, position). Cached: the pool does not change during a draft."""
    if os.path.exists(PLAYER_MAP):
        with open(PLAYER_MAP, encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}
    flt = {"players": {"limit": 1500, "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "STANDARD"}}}
    data = _get({"view": "players_wl"}, headers={"X-Fantasy-Filter": json.dumps(flt)})
    out = {}
    for p in data.get("players", []):
        info = p.get("player", p)
        out[int(info["id"])] = [info.get("fullName", ""), POS_ID.get(info.get("defaultPositionId"), "")]
    with open(PLAYER_MAP, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out

def fetch_league_state():
    data = _get([("view", "mTeam"), ("view", "mDraftDetail"), ("view", "mSettings")])
    teams = {}
    for t in data["teams"]:
        teams[t["id"]] = {
            "id": t["id"],
            "abbrev": t.get("abbrev", str(t["id"])),
            "name": t.get("name") or f"{t.get('location','')} {t.get('nickname','')}".strip(),
        }
    picks = data.get("draftDetail", {}).get("picks", [])
    return teams, picks, data.get("draftDetail", {})


# ───────────────────────── plan data ─────────────────────────
def load_plan():
    df = pd.read_csv(PLAN_CSV)
    df["key"] = df["player"].map(norm)
    for c in ("steal", "target", "walk_away", "mechanical_value", "rank"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def load_dream_team():
    try:
        d = pd.read_excel(PLAN_XLSX, sheet_name="Dream Team")
    except Exception:
        return pd.DataFrame()
    d["key"] = d["Player"].map(norm)
    return d

def match_plan(name, keys):
    k = norm(name)
    if k in keys:
        return k
    close = difflib.get_close_matches(k, list(keys), n=1, cutoff=0.88)
    return close[0] if close else None


# ───────────────────────── core computation ─────────────────────────
def build_state(teams, raw_picks, plan, dream, pmap, mock_sales=None):
    keys = set(plan["key"])
    sold = []
    for p in raw_picks:
        if mock_sales is not None:
            break
        if p.get("playerId", -1) in (-1, None) or p.get("teamId", -1) in (-1, None):
            continue
        name, pos = pmap.get(int(p["playerId"]), (f"id{p['playerId']}", ""))
        sold.append({"n": len(sold) + 1, "player": name, "pos": pos, "team_id": p["teamId"],
                     "price": p.get("bidAmount", 0), "nominator": p.get("nominatingTeamId")})
    if mock_sales is not None:
        sold = mock_sales

    for s in sold:
        k = match_plan(s["player"], keys)
        s["key"] = k
        row = plan[plan["key"] == k].iloc[0] if k else None
        s["target"] = float(row["target"]) if row is not None and pd.notna(row["target"]) else None
        s["pos"] = (row["position"] if row is not None else s["pos"]) or s["pos"]
        s["delta"] = (s["price"] - s["target"]) if s["target"] is not None else None

    sold_keys = {s["key"] for s in sold if s["key"]}
    tstate = {}
    for tid, t in teams.items():
        mine = [s for s in sold if s["team_id"] == tid]
        spent = sum(s["price"] for s in mine)
        open_spots = ROSTER_SPOTS - len(mine)
        left = BUDGET - spent
        max_bid = max(0, left - max(open_spots - 1, 0)) if open_spots > 0 else 0
        pos_ct = {p: sum(1 for s in mine if s["pos"] == p) for p in POSITIONS}
        tstate[tid] = {**t, "spent": spent, "left": left, "open": open_spots, "max_bid": max_bid,
                       "players": mine, "pos": pos_ct,
                       "needs": [p for p in POSITIONS if pos_ct[p] == 0],
                       "per_open": (left / open_spots) if open_spots else 0}

    avail = plan[~plan["key"].isin(sold_keys)].copy()
    open_total = sum(t["open"] for t in tstate.values())
    money_left = sum(t["left"] for t in tstate.values())
    # Inflation: dollars still in the room vs. the sheet's value of the best players that will
    # fill the remaining spots. >1 = the room has more money than the sheet says players are worth.
    top_value = avail.sort_values("target", ascending=False).head(open_total)["target"].sum()
    inflation = (money_left - open_total) / max(top_value - open_total, 1)  # $1 floor per spot
    paid = sum(s["price"] for s in sold if s["target"] is not None)
    worth = sum(s["target"] for s in sold if s["target"] is not None)
    realized = (paid / worth) if worth else None

    # next nominator: the pick slot after the sales we have seen
    next_nom = None
    if mock_sales is None and len(raw_picks) > len(sold):
        next_nom = raw_picks[len(sold)].get("nominatingTeamId")

    return dict(sold=sold, teams=tstate, avail=avail, inflation=inflation, realized=realized,
                money_left=money_left, open_total=open_total, next_nom=next_nom, dream=dream,
                sold_keys=sold_keys)


def shortlist(st):
    """Ranked nomination ideas for the user's turn. Heuristic, meant to be judged by the model."""
    me = st["teams"][MY_TEAM_ID]
    my_targets = set(st["dream"]["key"]) if len(st["dream"]) else set()
    rows = []
    for _, r in st["avail"].head(120).iterrows():
        tgt = r["target"]
        if pd.isna(tgt) or tgt < 3:
            continue
        price_guess = tgt * st["inflation"]
        pos = r["position"]
        buyers = [t for t in st["teams"].values()
                  if t["id"] != MY_TEAM_ID and t["max_bid"] >= price_guess and t["open"] > 0]
        needy = [t for t in buyers if pos in t["needs"]]
        rows.append({
            "player": r["player"], "pos": pos, "target": tgt,
            "walk_away": r.get("walk_away"), "est_price": round(price_guess, 1),
            "buyers": len(buyers), "needy_buyers": len(needy),
            "mine": r["key"] in my_targets,
        })
    return pd.DataFrame(rows)


# ───────────────────────── outputs ─────────────────────────
def write_md(st, plan, path=STATE_MD, mock=False):
    me = st["teams"][MY_TEAM_ID]
    L = []
    L.append(f"# LIVE DRAFT STATE — {datetime.now():%Y-%m-%d %H:%M:%S}" + ("  (MOCK DATA)" if mock else ""))
    L.append("")
    L.append("## How to read this (for the model)")
    L.append("- League: 10 teams, H2H points, salary-cap auction, $200 each, 13 roster spots, $1 min bid.")
    L.append("- `target` = fair price in $ per our valuation sheet; `steal` = bargain price; `walk_away` = stop bidding above this.")
    L.append("- `max bid` = money left - (open spots - 1). Teams at $1 max can only win uncontested players.")
    L.append("- `inflation` = (money left - open spots) / (sheet value of the best players that will fill the open spots, above $1). >1.0 means the room is richer than the sheet, so expect prices above `target`; <1.0 means bargains are coming.")
    L.append("- `est price` = target x inflation. `buyers` = other teams whose max bid covers est price; `needy` = of those, teams with zero players at that position.")
    L.append("- Position counts use ESPN primary position. Leftover money is worthless after the draft, and prices paid become keeper costs (+$12) next season.")
    L.append("")
    L.append(f"## Progress: {len(st['sold'])}/130 sold · ${st['money_left']} left in room · {st['open_total']} spots open")
    infl = st["inflation"]
    L.append(f"- Inflation: **{infl:.2f}** · prices realized so far vs sheet: " +
             (f"**{st['realized']:.2f}x**" if st["realized"] else "n/a"))
    if st["next_nom"]:
        nm = st["teams"].get(st["next_nom"], {}).get("abbrev", st["next_nom"])
        L.append(f"- Next to nominate: **{nm}**" + ("  ← YOU" if st["next_nom"] == MY_TEAM_ID else ""))
    L.append("")
    L.append("## Teams (sorted by max bid)")
    L.append("| team | left | open | max bid | $/open | owns (PG/SG/SF/PF/C) | needs |")
    L.append("|---|---|---|---|---|---|---|")
    for t in sorted(st["teams"].values(), key=lambda t: -t["max_bid"]):
        tag = " **(ME)**" if t["id"] == MY_TEAM_ID else ""
        own = "/".join(str(t["pos"][p]) for p in POSITIONS)
        L.append(f"| {t['abbrev']}{tag} | ${t['left']} | {t['open']} | ${t['max_bid']} | {t['per_open']:.1f} | {own} | {','.join(t['needs']) or '-'} |")
    L.append("")
    L.append("## Last 12 sales")
    L.append("| # | player | pos | team | paid | target | vs target |")
    L.append("|---|---|---|---|---|---|---|")
    for s in st["sold"][-12:]:
        ab = st["teams"][s["team_id"]]["abbrev"]
        d = f"{s['delta']:+.0f}" if s["delta"] is not None else "?"
        tg = f"{s['target']:.0f}" if s["target"] is not None else "?"
        L.append(f"| {s['n']} | {s['player']} | {s['pos']} | {ab} | ${s['price']} | {tg} | {d} |")
    L.append("")
    L.append(f"## My team (budget ${me['left']}, max bid ${me['max_bid']}, {me['open']} open spots)")
    for s in me["players"]:
        L.append(f"- {s['player']} ({s['pos']}) ${s['price']}")
    if not me["players"]:
        L.append("- (nobody yet)")
    L.append(f"- Still need: {', '.join(me['needs']) or 'all positions covered'}")
    L.append("")
    L.append("## My Dream Team targets — still available")
    L.append("| pos | tier | player | buy at | walk away | steal under | est price now |")
    L.append("|---|---|---|---|---|---|---|")
    d = st["dream"]
    if len(d):
        alive = d[~d["key"].isin(st["sold_keys"])]
        for _, r in alive.iterrows():
            est = float(r["Buy at"]) * infl
            L.append(f"| {r['Position']} | {r['Tier']} | {r['Player']} | ${r['Buy at']:.0f} | ${r['Walk away']:.0f} | ${r['Steal under']:.0f} | ${est:.0f} |")
        gone = d[d["key"].isin(st["sold_keys"])]
        if len(gone):
            L.append("")
            L.append("Gone: " + ", ".join(gone["Player"]))
    L.append("")
    sl = shortlist(st)
    L.append("## Nomination shortlist (best available by value; model should choose using the rules in the plan)")
    L.append("`mine`=on my Dream Team (don't nominate unless I want to set the price early).")
    L.append("| player | pos | target | est price | buyers | needy | mine |")
    L.append("|---|---|---|---|---|---|---|")
    for _, r in sl.sort_values(["needy_buyers", "target"], ascending=False).head(18).iterrows():
        L.append(f"| {r['player']} | {r['pos']} | ${r['target']:.0f} | ${r['est_price']:.0f} | {r['buyers']} | {r['needy_buyers']} | {'Y' if r['mine'] else ''} |")
    L.append("")
    L.append("## Best remaining values (top 25 available by sheet target)")
    L.append("| player | pos | team | target | walk away | tier |")
    L.append("|---|---|---|---|---|---|")
    for _, r in st["avail"].sort_values("target", ascending=False).head(25).iterrows():
        L.append(f"| {r['player']} | {r['position']} | {r.get('team','')} | ${r['target']:.0f} | ${r['walk_away']:.0f} | {r.get('tier','')} |")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    os.replace(tmp, path)


def write_xlsx(st, plan, path=LIVE_XLSX):
    teams = pd.DataFrame([{
        "team": t["abbrev"], "name": t["name"], "spent": t["spent"], "left": t["left"],
        "open_spots": t["open"], "max_bid": t["max_bid"], "avg_per_open": round(t["per_open"], 1),
        **{p: t["pos"][p] for p in POSITIONS}, "needs": ",".join(t["needs"]),
    } for t in st["teams"].values()]).sort_values("max_bid", ascending=False)
    picks = pd.DataFrame([{
        "#": s["n"], "player": s["player"], "pos": s["pos"],
        "team": st["teams"][s["team_id"]]["abbrev"], "paid": s["price"],
        "target": s["target"], "vs_target": s["delta"],
    } for s in st["sold"]])
    board = plan.copy()
    sold_map = {s["key"]: s for s in st["sold"] if s["key"]}
    board["status"] = board["key"].map(lambda k: "SOLD" if k in sold_map else "available")
    board["sold_to"] = board["key"].map(lambda k: st["teams"][sold_map[k]["team_id"]]["abbrev"] if k in sold_map else "")
    board["sold_for"] = board["key"].map(lambda k: sold_map[k]["price"] if k in sold_map else None)
    board["est_price_now"] = (board["target"] * st["inflation"]).round(1)
    cols = [c for c in ["rank", "player", "position", "eligible", "team", "tier", "steal", "target",
                        "walk_away", "est_price_now", "status", "sold_to", "sold_for",
                        "market_vs_value", "trend", "risk", "why"] if c in board.columns]
    board = board[cols]
    d = st["dream"]
    mine = d.drop(columns=["key"]).copy() if len(d) else pd.DataFrame()
    if len(mine):
        mine["status"] = d["key"].map(lambda k: "SOLD" if k in st["sold_keys"] else "available")
        mine["est_price_now"] = (d["Buy at"] * st["inflation"]).round(1)
    tmp = path + ".tmp.xlsx"
    with pd.ExcelWriter(tmp, engine="openpyxl") as xw:
        teams.to_excel(xw, sheet_name="Teams", index=False)
        picks.to_excel(xw, sheet_name="Picks", index=False)
        board.to_excel(xw, sheet_name="Board", index=False)
        if len(mine):
            mine.to_excel(xw, sheet_name="My Targets", index=False)
    os.replace(tmp, path)


def snapshot(plan, dream, pmap, mock=None):
    teams, raw, _ = fetch_league_state()
    mock_sales = None
    if mock:
        rng = random.Random(7)
        ids = list(teams)
        pool = plan.sort_values("rank").head(mock)
        mock_sales, left, cnt = [], {i: BUDGET for i in ids}, {i: 0 for i in ids}
        for i, (_, r) in enumerate(pool.sample(frac=1, random_state=3).iterrows(), 1):
            ok = [t for t in ids if cnt[t] < ROSTER_SPOTS - 3]
            tid = rng.choice(ok)
            cap = left[tid] - (ROSTER_SPOTS - cnt[tid] - 1)
            price = max(1, min(cap, int(round(r["target"] * rng.uniform(0.7, 1.4)))))
            left[tid] -= price; cnt[tid] += 1
            mock_sales.append({"n": i, "player": r["player"], "pos": r["position"],
                               "team_id": tid, "price": price, "nominator": None})
    st = build_state(teams, raw, plan, dream, pmap, mock_sales)
    write_md(st, plan, mock=bool(mock))
    try:
        write_xlsx(st, plan)
    except PermissionError:
        print("  (draft_live.xlsx is open in Excel — skipped this refresh; state.md still updated)")
    return st


def main():
    args = sys.argv[1:]
    mock = int(args[args.index("--mock") + 1]) if "--mock" in args else None
    plan, dream = load_plan(), load_dream_team()
    pmap = {} if mock else load_player_map()
    if not mock and not pmap:
        raise SystemExit("could not load ESPN player map")
    if "--watch" not in args:
        st = snapshot(plan, dream, pmap, mock)
        print(f"{len(st['sold'])} sold · inflation {st['inflation']:.2f} → {STATE_MD}, {LIVE_XLSX}")
        return
    last = -1
    print("Watching ESPN draft... Ctrl+C to stop")
    while True:
        try:
            teams, raw, _ = fetch_league_state()
            n = sum(1 for p in raw if p.get("playerId", -1) not in (-1, None) and p.get("teamId", -1) not in (-1, None))
            if n != last:
                st = snapshot(plan, dream, pmap)
                print(f"[{datetime.now():%H:%M:%S}] {n} sold · inflation {st['inflation']:.2f} · updated")
                last = n
        except Exception as e:
            print(f"[{datetime.now():%H:%M:%S}] poll error: {e}")
        time.sleep(5)

if __name__ == "__main__":
    main()
