"""Player availability: who is out, how much they matter, and the per-game team adjustment.

Data (ESPN, free):
  * injury report   - status (Out / Day-To-Day / Questionable / Doubtful) and return date
  * player averages - this season and last season, for a box-score value estimate

Player value: Hollinger Game Score per 36 minutes (rebounds weighted 0.4 since ESPN
doesn't split offensive/defensive boards), blended with last season early on.
Impact (points of team net rating lost when he sits) =
    0.5 x (GameScore/36 - 8 replacement level) x (minutes per game / 48), capped at 8.
That puts an MVP-level player around 6-7 points and a bench player near 0.

Because a team's rating is learned from games, a player who has already missed most of
them is partly "baked in". So the adjustment is scaled by the share of the team's games
he actually played this season.
"""
import re
import time
from datetime import date, timedelta

import requests

from teams import TEAMS

INJ_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
STATS_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/byathlete"
HEADERS = {"User-Agent": "nba-ladder-model/1.0 (personal project)"}

REPLACEMENT = 8.0
SCALE = 0.5
MAX_PLAYER = 8.0
MAX_TEAM = 8.0
DECAY = 0.8   # diminishing returns: 2nd-biggest absence counts 80%, 3rd 64%, ... (minutes get absorbed)
LAST_SEASON_WEIGHT_MIN = 500  # last season's minutes count like this many minutes this season

# status -> (weight, days it applies when no return date is given)
STATUS = {
    "out": (1.0, 7), "suspension": (1.0, 7), "doubtful": (0.8, 2),
    "questionable": (0.5, 2), "day-to-day": (0.35, 2), "probable": (0.1, 1),
}


def _get(url, params=None):
    for i in range(4):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(2 * (i + 1))
    return None


def fetch_injuries():
    j = _get(INJ_URL)
    out = []
    if not j:
        return out
    for team in j.get("injuries", []):
        for inj in team.get("injuries", []):
            a = inj.get("athlete") or {}
            abbr = (a.get("team") or {}).get("abbreviation")
            pid = a.get("id")
            if not pid:
                for l in a.get("links", []):
                    m = re.search(r"/id/(\d+)", l.get("href", ""))
                    if m:
                        pid = m.group(1)
                        break
            out.append({
                "id": str(pid) if pid else None, "name": a.get("displayName"), "team": abbr,
                "status": (inj.get("status") or "").strip(),
                "return": ((inj.get("details") or {}).get("returnDate")),
                "detail": " ".join(filter(None, [(inj.get("details") or {}).get("type"),
                                                  (inj.get("details") or {}).get("detail")])),
            })
    return out


def _season_stats(season):
    """{player_id: dict(name, team, gp, mpg, gmsc36)} for one ESPN season year."""
    res, page = {}, 1
    while True:
        j = _get(STATS_URL, {"region": "us", "lang": "en", "contentorigin": "espn",
                             "isqualified": "false", "page": page, "limit": 200,
                             "season": season, "seasontype": 2})
        if not j or not j.get("athletes"):
            break
        names = {c["name"]: c.get("names", []) for c in j.get("categories", [])}
        for a in j["athletes"]:
            v = {}
            for c in a.get("categories", []):
                vals = c.get("values") or c.get("totals") or []
                for k, x in zip(names.get(c["name"], []), vals):
                    try:
                        v[k] = float(x)
                    except (TypeError, ValueError):
                        v[k] = 0.0
            gp, mpg = v.get("gamesPlayed", 0), v.get("avgMinutes", 0)
            if gp <= 0 or mpg <= 0:
                continue
            gmsc = (v.get("avgPoints", 0) + 0.4 * v.get("avgFieldGoalsMade", 0)
                    - 0.7 * v.get("avgFieldGoalsAttempted", 0)
                    - 0.4 * (v.get("avgFreeThrowsAttempted", 0) - v.get("avgFreeThrowsMade", 0))
                    + 0.4 * v.get("avgRebounds", 0) + v.get("avgSteals", 0)
                    + 0.7 * v.get("avgAssists", 0) + 0.7 * v.get("avgBlocks", 0)
                    - 0.4 * v.get("avgFouls", 0) - v.get("avgTurnovers", 0))
            ath = a["athlete"]
            res[str(ath["id"])] = {"name": ath.get("displayName"), "team": ath.get("teamShortName"),
                                   "gp": gp, "mpg": mpg, "gmsc36": gmsc / mpg * 36}
        pag = j.get("pagination") or {}
        if page >= int(pag.get("pages") or 1):
            break
        page += 1
        time.sleep(0.25)
    return res


def player_values(season_year):
    """Blend this season with last season, weighted by minutes."""
    cur, last = _season_stats(season_year), _season_stats(season_year - 1)
    vals = {}
    for pid in set(cur) | set(last):
        c, l = cur.get(pid), last.get(pid)
        cm = c["gp"] * c["mpg"] if c else 0.0
        lm = LAST_SEASON_WEIGHT_MIN if l else 0.0
        g36 = ((c["gmsc36"] * cm if c else 0) + (l["gmsc36"] * lm if l else 0)) / max(cm + lm, 1e-9)
        mpg = c["mpg"] if c and c["gp"] >= 3 else (l["mpg"] if l else c["mpg"])
        vals[pid] = {"name": (c or l)["name"], "team": (c or l)["team"],
                     "gp": c["gp"] if c else 0, "mpg": round(mpg, 1), "gmsc36": round(g36, 1),
                     "impact": round(min(MAX_PLAYER, max(0.0, SCALE * (g36 - REPLACEMENT) * mpg / 48)), 2)}
    return vals


def build(injuries, values, team_games, today):
    """Return (list of absences with their effect, function adj(team, date_iso) -> points)."""
    by_name = {v["name"]: k for k, v in values.items()}
    rows = []
    for inj in injuries:
        team = inj.get("team")
        if team not in TEAMS:
            continue
        pid = inj.get("id") if inj.get("id") in values else by_name.get(inj.get("name"))
        v = values.get(pid)
        if not v or v["impact"] <= 0:
            continue
        key = inj["status"].lower()
        weight, days = next((STATUS[k] for k in STATUS if k in key), (0.0, 0))
        if weight == 0:
            continue
        tg = team_games.get(team, 0)
        share = min(1.0, v["gp"] / tg) if tg else 0.5
        if v["gp"] == 0:
            share = 0.0  # hasn't played yet: his absence is already in the team's results / preseason line
        until = inj.get("return")
        until = until[:10] if until else (date.fromisoformat(today) + timedelta(days=days)).isoformat()
        eff = round(v["impact"] * weight * share, 2)
        if eff < 0.05:
            continue
        rows.append({"team": team, "name": v["name"], "status": inj["status"], "until": until,
                     "impact": v["impact"], "weight": weight, "share": round(share, 2), "effect": eff,
                     "detail": inj.get("detail") or ""})
    rows.sort(key=lambda r: -r["effect"])

    def active(team, d):
        return [r for r in rows if r["team"] == team and today <= d < r["until"]]

    def combine(effects):
        """Biggest absence counts fully, each next one a bit less; capped."""
        return min(MAX_TEAM, sum(e * DECAY ** k for k, e in enumerate(sorted(effects, reverse=True))))

    def adj(team, d):
        """Expected points lost (used for game predictions)."""
        return -combine([r["effect"] for r in active(team, d)])

    def parts(team, d):
        """(certain points lost, [(full points, chance he sits)]) - for the simulations."""
        act = sorted(active(team, d), key=lambda r: -r["impact"] * r["share"])
        certain = -combine([r["effect"] for r in act if r["weight"] >= 1])
        maybe = [(-round(r["impact"] * r["share"] * DECAY ** k, 2), r["weight"])
                 for k, r in enumerate(act) if r["weight"] < 1]
        return certain, maybe
    adj.parts = parts
    return rows, adj
