"""Betting lines from The Odds API (optional, free tier).

Set a GitHub secret ODDS_API_KEY (free key from https://the-odds-api.com). Each run uses
3 credits (moneyline + spread + total, US books); two runs a day is ~180 of the 500 free
monthly credits. Without a key this module does nothing and the model falls back to any
lines ESPN includes.

Lines are stored per game in data/odds.json and refreshed every run until tip-off, so the
stored line for a finished game is the last one seen before it started (close to the
closing line). The consensus is the median across bookmakers, with the vig removed.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from statistics import median

import requests

from teams import TEAMS

URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
STORE = os.path.join(os.path.dirname(__file__), "data", "odds.json")
NAME_TO_ABBR = {v[0]: k for k, v in TEAMS.items()}
NAME_TO_ABBR.update({"Los Angeles Clippers": "LAC", "LA Lakers": "LAL"})


def _implied(price):
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def fetch(api_key):
    r = requests.get(URL, params={"apiKey": api_key, "regions": "us", "markets": "h2h,spreads,totals",
                                  "oddsFormat": "american"}, timeout=25)
    r.raise_for_status()
    out = []
    for ev in r.json():
        h, a = NAME_TO_ABBR.get(ev["home_team"]), NAME_TO_ABBR.get(ev["away_team"])
        if not h or not a:
            continue
        start = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        us_date = (start - timedelta(hours=5)).date().isoformat()
        probs, spreads, totals = [], [], []
        for bk in ev.get("bookmakers", []):
            for m in bk.get("markets", []):
                oc = {o["name"]: o for o in m.get("outcomes", [])}
                if m["key"] == "h2h" and ev["home_team"] in oc and ev["away_team"] in oc:
                    ph, pa = _implied(oc[ev["home_team"]]["price"]), _implied(oc[ev["away_team"]]["price"])
                    probs.append(ph / (ph + pa))
                elif m["key"] == "spreads" and ev["home_team"] in oc:
                    spreads.append(float(oc[ev["home_team"]]["point"]))
                elif m["key"] == "totals" and "Over" in oc:
                    totals.append(float(oc["Over"]["point"]))
        if not probs:
            continue
        sp = median(spreads) if spreads else None
        out.append({"date": us_date, "home": h, "away": a, "start": ev["commence_time"],
                    "p_home": round(median(probs), 4), "spread": sp,
                    "total": median(totals) if totals else None, "books": len(ev.get("bookmakers", [])),
                    "details": (f"{h} {sp:+.1f}" if sp is not None and sp != 0 else (f"{h} PK" if sp == 0 else None))})
    return out


def update_and_attach(games, api_key=None):
    """Refresh stored lines (if a key is set) and attach them to `games` as g['odds']."""
    store = {}
    if os.path.exists(STORE):
        with open(STORE) as f:
            store = json.load(f)
    if api_key:
        now = datetime.now(timezone.utc)
        key = {(g["date"], g["home"], g["away"]): g for g in games}
        for o in fetch(api_key):
            g = key.get((o["date"], o["home"], o["away"]))
            if not g or g["done"]:
                continue
            if datetime.fromisoformat(o["start"].replace("Z", "+00:00")) <= now:
                continue  # game started: keep the last pre-game line
            store[g["id"]] = {**o, "provider": "consensus", "fetched": now.isoformat(timespec="minutes")}
        os.makedirs(os.path.dirname(STORE), exist_ok=True)
        with open(STORE, "w") as f:
            json.dump(store, f, separators=(",", ":"))
    for g in games:
        if g["id"] in store:
            g["odds"] = store[g["id"]]
    return len(store)
