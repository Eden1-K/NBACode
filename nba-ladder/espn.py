"""Pull the 2026-27 regular-season schedule and results from ESPN's public scoreboard API.

Games are cached in data/games.json. Days whose games are all final and more than
two days old are never re-fetched, so a daily run makes only a handful of requests.
"""
import json
import os
import time
from datetime import date, datetime, timedelta, timezone

import requests

from teams import TEAMS, SEASON_START, SEASON_END

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
CACHE = os.path.join(os.path.dirname(__file__), "data", "games.json")
HEADERS = {"User-Agent": "nba-ladder-model/1.0 (personal project)"}


def _get(params, tries=4):
    for i in range(tries):
        try:
            r = requests.get(BASE, params=params, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"ESPN request failed: {params}")


def _parse_day(day, payload):
    """day = 'YYYYMMDD' (US date). Returns list of normalised game dicts."""
    out = []
    for e in payload.get("events", []):
        season = e.get("season") or {}
        if season.get("type") != 2:          # regular season only
            continue
        comp = e["competitions"][0]
        home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
        away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
        h, a = home["team"]["abbreviation"], away["team"]["abbreviation"]
        if h not in TEAMS or a not in TEAMS:  # TBD placeholders (NBA Cup knockouts)
            continue
        notes = " | ".join(n.get("headline", "") for n in comp.get("notes", []))
        if "Championship" in notes:           # NBA Cup final doesn't count in the standings
            continue
        odds = None
        for o in comp.get("odds") or []:
            def ml(side):
                v = (o.get(side) or {}).get("moneyLine")
                try:
                    return float(v) if v not in (None, "", "OFF") else None
                except (TypeError, ValueError):
                    return None
            spread = o.get("spread")
            try:
                spread = float(spread) if spread is not None else None
            except (TypeError, ValueError):
                spread = None
            odds = {"ml_h": ml("homeTeamOdds"), "ml_a": ml("awayTeamOdds"), "spread": spread,
                    "total": o.get("overUnder"), "details": o.get("details"),
                    "provider": (o.get("provider") or {}).get("name")}
            break
        st = e["status"]["type"]
        done = bool(st.get("completed"))
        out.append({
            "id": e["id"],
            "date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
            "home": h, "away": a,
            "hs": int(home["score"]) if done else None,
            "as": int(away["score"]) if done else None,
            "done": done,
            "neutral": bool(comp.get("neutralSite")),
            "note": notes,
            "odds": odds,
        })
    return out


def season_days():
    """All game days in the regular season, from ESPN's calendar."""
    payload = _get({"dates": SEASON_START.replace("-", "")})
    cal = payload["leagues"][0].get("calendar", [])
    days = sorted({c[:10].replace("-", "") for c in cal})
    lo, hi = SEASON_START.replace("-", ""), SEASON_END.replace("-", "")
    days = [d for d in days if lo <= d <= hi]
    if not days:  # fall back to every date in range
        d0 = datetime.strptime(lo, "%Y%m%d").date()
        d1 = datetime.strptime(hi, "%Y%m%d").date()
        days = [(d0 + timedelta(n)).strftime("%Y%m%d") for n in range((d1 - d0).days + 1)]
    return days


def load_games(refresh=True):
    cache = {"days": {}}
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            cache = json.load(f)
    if refresh:
        today_us = (datetime.now(timezone.utc) - timedelta(hours=5)).date()
        recent = (today_us - timedelta(days=2)).strftime("%Y%m%d")
        for day in season_days():
            games = cache["days"].get(day)
            settled = games is not None and all(g["done"] for g in games) and day < recent
            if settled:
                continue
            fresh = _parse_day(day, _get({"dates": day, "limit": 100}))
            old = {g["id"]: g for g in (games or [])}
            for g in fresh:  # keep the pre-game line if ESPN drops it after the game
                if not g.get("odds") and old.get(g["id"], {}).get("odds"):
                    g["odds"] = old[g["id"]]["odds"]
            cache["days"][day] = fresh
            time.sleep(0.25)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        cache["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with open(CACHE, "w") as f:
            json.dump(cache, f, separators=(",", ":"))
    by_id = {}  # a postponed game re-listed on a later day: the later listing wins
    for day in sorted(cache["days"]):
        for g in cache["days"][day]:
            if g["id"] in by_id and by_id[g["id"]]["done"] and not g["done"]:
                continue
            by_id[g["id"]] = g
    games = sorted(by_id.values(), key=lambda g: (g["date"], g["id"]))
    return games, cache.get("fetched_at")
