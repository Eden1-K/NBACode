"""Daily update: fetch results + injuries, refit, simulate, write docs/.

    python run.py                  # normal run (fetches from ESPN)
    python run.py --offline        # reuse data/games.json, skip all fetching
    python run.py --no-injuries    # skip the injury/player-value step
    python run.py --sims 20000     # more simulations for the headline numbers
"""
import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone

from scipy.special import ndtr

import model
from teams import SEASON_START, ABBRS

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
DATA = os.path.join(HERE, "data")
LIVE_LOG = os.path.join(DATA, "live_log.json")
SEASON_YEAR = 2027  # ESPN labels 2026-27 as 2027


def split(games, through):
    """Games completed on/before `through`, and everything else (as it stood then)."""
    done = [g for g in games if g["done"] and g["date"] <= through]
    rem = [g for g in games if not (g["done"] and g["date"] <= through)]
    return done, rem


def snapshot(done, remaining, asof, n_sims, rest, game_adj, seed=11, random_adj=None):
    r, sd, hca = model.fit(done, asof, rest)
    P = model.LAST_P
    sim = model.simulate(done, remaining, r, sd, hca, game_adj=game_adj, n_sims=n_sims, seed=seed,
                         random_adj=random_adj, cov=P, asof=asof)
    teams, conf = model.summarise(sim, r, sd)
    return teams, conf, (r, hca, P)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-injuries", action="store_true")
    ap.add_argument("--games", help="path to a games JSON list (testing)")
    ap.add_argument("--injuries-file", help="JSON {injuries, values} (testing)")
    ap.add_argument("--today", help="override today's US date (testing)")
    ap.add_argument("--sims", type=int, default=10000)
    ap.add_argument("--hist-sims", type=int, default=1500)
    args = ap.parse_args()
    testing = bool(args.games)

    if args.games:
        with open(args.games) as f:
            games = json.load(f)
        fetched_at = None
    else:
        import espn
        games, fetched_at = espn.load_games(refresh=not args.offline)
    if not testing:
        import odds
        try:
            n_lines = odds.update_and_attach(games, None if args.offline else os.environ.get("ODDS_API_KEY"))
            print(f"Betting lines on file: {n_lines}")
        except Exception as e:
            print(f"Odds step skipped: {e}")

    today = args.today or (datetime.now(timezone.utc) - timedelta(hours=5)).date().isoformat()
    done_all = [g for g in games if g["done"]]
    days = sorted({g["date"] for g in done_all})
    preseason = (date.fromisoformat(SEASON_START) - timedelta(days=1)).isoformat()
    latest = days[-1] if days else preseason
    prev = days[-2] if len(days) >= 2 else preseason

    # 1. Rest / back-to-backs for every game on the schedule
    rest = model.rest_adjustments(games)
    rest_diff = {gid: v[0] - v[1] for gid, v in rest.items()}

    # 2. Walk-forward track record, then calibrate SIGMA on its residuals
    preds = model.walk_forward(done_all, rest)
    model.SIGMA = model.estimate_sigma(preds)
    for p in preds:
        p["p_home"] = round(model.prob(p["mu"], p.get("var", 0.0)), 4)
    record = model.track_record(preds)
    latest_games = [p for p in preds if p["date"] == latest]

    # 3. Player availability (injury report x player value)
    team_games = {a: 0 for a in ABBRS}
    for g in done_all:
        team_games[g["home"]] += 1
        team_games[g["away"]] += 1
    absences, avail = [], (lambda team, d: 0.0)
    if not args.no_injuries and not args.offline:
        import availability
        try:
            if args.injuries_file:
                with open(args.injuries_file) as f:
                    blob = json.load(f)
                inj, vals = blob["injuries"], blob["values"]
            elif not testing:
                inj, vals = availability.fetch_injuries(), availability.player_values(SEASON_YEAR)
            else:
                inj, vals = [], {}
            absences, avail = availability.build(inj, vals, team_games, today)
        except Exception as e:  # never let a flaky injury feed stop the update
            print(f"Availability step skipped: {e}")

    def avail_diff(g):
        return avail(g["home"], g["date"]) - avail(g["away"], g["date"])
    game_adj = {g["id"]: rest_diff.get(g["id"], 0.0) + avail_diff(g) for g in games if not g["done"]}
    # For the simulations: certain absences are fixed, questionable players are coin flips
    sim_adj, random_adj = dict(game_adj), []
    if hasattr(avail, "parts"):
        for g in games:
            if g["done"]:
                continue
            ch, mh = avail.parts(g["home"], g["date"])
            ca, ma = avail.parts(g["away"], g["date"])
            sim_adj[g["id"]] = rest_diff.get(g["id"], 0.0) + ch - ca
            random_adj += [(g["id"], 1, pts, p) for pts, p in mh] + [(g["id"], -1, pts, p) for pts, p in ma]

    # 4. Headline projection + the one before it (same seed + same injury list, so the
    #    difference is what the latest results changed)
    d_now, rem_now = split(games, latest)
    teams, conf, (r_now, hca_now, P_now) = snapshot(d_now, rem_now, latest, args.sims, rest, sim_adj,
                                             random_adj=random_adj)
    tot_now = model.fit_totals(d_now, latest)
    d_prev, rem_prev = split(games, prev)
    adj_prev = {g["id"]: sim_adj.get(g["id"], rest_diff.get(g["id"], 0.0)) for g in rem_prev}
    teams_prev, conf_prev, _ = snapshot(d_prev, rem_prev, prev, args.sims, rest, adj_prev,
                                        random_adj=random_adj)

    prev_by = {t["abbr"]: t for t in teams_prev}
    for t in teams:
        p = prev_by[t["abbr"]]
        t["d_proj_w"] = round(t["proj_w"] - p["proj_w"], 1)
        t["d_playoffs"] = round(t["p_playoffs"] - p["p_playoffs"], 4)
        t["d_seed"] = p["seed"] - t["seed"]  # positive = moved up the ladder
        t["avail_now"] = round(avail(t["abbr"], today), 2)
        res = []
        for g in latest_games:
            if t["abbr"] in (g["home"], g["away"]):
                home = g["home"] == t["abbr"]
                pw = g["p_home"] if home else 1 - g["p_home"]
                score = f'{g["hs"]}-{g["as"]}' if home else f'{g["as"]}-{g["hs"]}'
                res.append({"won": g["home_won"] == home, "opp": g["away"] if home else g["home"],
                            "home": home, "score": score, "pregame": round(pw, 3)})
        t["latest"] = res

    # 5. History of the projection (one snapshot per game day; rest only - past injury
    #    reports aren't archived)
    history = []
    for d in [preseason] + days:
        dd, rr = split(games, d)
        if d == latest:
            tt, cc = teams, conf
        elif d == prev:
            tt, cc = teams_prev, conf_prev
        else:
            tt, cc, _ = snapshot(dd, rr, d, args.hist_sims, rest,
                                 {g["id"]: rest_diff.get(g["id"], 0.0) for g in rr}, seed=5)
        upto = [p for p in preds if p["date"] <= d]
        acc = (sum((p["p_home"] >= 0.5) == p["home_won"] for p in upto) / len(upto)) if upto else None
        history.append({"date": d, "games": len(dd), "within1": cc["within1"], "exact": cc["exact"],
                        "rank_corr": cc["rank_corr"],
                        "accuracy": round(acc, 4) if acc is not None else None,
                        "proj": {t["abbr"]: t["proj_w"] for t in tt}})

    # 6. Game predictions (next 7 game days on the page, every game in the CSV)
    upcoming = sorted([g for g in games if not g["done"]], key=lambda g: (g["date"], g["id"]))

    def game_pred(g):
        ra, aa = rest_diff.get(g["id"], 0.0), avail_diff(g)
        adj = ra + aa
        ph, pa = model.predict_score(r_now, hca_now, tot_now, g["home"], g["away"], g["neutral"], adj)
        rs = rest.get(g["id"], (0, 0, 1, 1))
        o = g.get("odds") or {}
        return {"id": g["id"], "date": g["date"], "home": g["home"], "away": g["away"],
                "p_home": round(model.win_prob(r_now, hca_now, g["home"], g["away"], g["neutral"], adj,
                                    model.game_var(P_now, g["home"], g["away"])), 3),
                "pred_hs": round(ph), "pred_as": round(pa), "rest_adj": round(ra, 2),
                "avail_adj": round(aa, 2), "b2b_home": rs[2] == 0, "b2b_away": rs[3] == 0,
                "market_p": model.market_prob(g), "line": o.get("details"), "ou": o.get("total"),
                "disagree": (model.market_prob(g) is not None and abs(
                    model.win_prob(r_now, hca_now, g["home"], g["away"], g["neutral"], adj,
                                    model.game_var(P_now, g["home"], g["away"])) - model.market_prob(g)) >= 0.05)}
    next_days = sorted({g["date"] for g in upcoming})[:7]
    nxt = [game_pred(g) for g in upcoming if g["date"] in next_days]
    csv_rows = ["date,away,home,pred_away,pred_home,home_win_prob,rest_adj,injury_adj"]
    for g in upcoming:
        q = game_pred(g)
        csv_rows.append(f'{q["date"]},{q["away"]},{q["home"]},{q["pred_as"]},{q["pred_hs"]},'
                        f'{q["p_home"]},{q["rest_adj"]},{q["avail_adj"]}')

    # 7. Live log: freeze the last pre-game prediction for imminent games, score finished ones
    live = {}
    if os.path.exists(LIVE_LOG):
        with open(LIVE_LOG) as f:
            live = json.load(f)
    if not testing:
        horizon = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
        for q in nxt:
            if q["date"] <= horizon:
                live[q["id"]] = {**q, "logged_at": datetime.now(timezone.utc).isoformat(timespec="minutes")}
        os.makedirs(DATA, exist_ok=True)
        with open(LIVE_LOG, "w") as f:
            json.dump(live, f, separators=(",", ":"))
    by_id = {g["id"]: g for g in done_all}
    live_scored = []
    for gid, q in live.items():
        g = by_id.get(gid)
        if g:
            live_scored.append({**q, "hs": g["hs"], "as": g["as"], "home_won": g["hs"] > g["as"],
                                "pred_hs_x": q["pred_hs"], "pred_as_x": q["pred_as"],
                                "p_prior": q["p_home"], "market_p": q.get("market_p")})
    live_record = model.track_record(live_scored) if live_scored else None

    backtest = None
    bt_path = os.path.join(DATA, "backtest.json")
    if os.path.exists(bt_path):
        with open(bt_path) as f:
            bt = json.load(f)
        backtest = {k: bt.get(k) for k in ("train", "test", "adopted", "test_default", "test_tuned",
                                           "preseason_only_test", "coverage_test", "segments_test", "candidates",
                                           "tuned", "generated_at")}
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fetched_at": fetched_at, "today": today,
        "through": latest, "previous": prev,
        "games_played": len(d_now), "games_left": 1230 - len(d_now),
        "n_sims": args.sims, "hca": round(float(hca_now), 2), "sigma": round(model.SIGMA, 2),
        "confidence": conf, "confidence_prev": conf_prev,
        "record": record, "live_record": live_record, "backtest": backtest,
        "segments": model.segments(preds) if preds else [],
        "teams": teams, "absences": absences[:40],
        "latest_games": latest_games, "next_games": nxt, "history": history,
    }
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "predictions.csv"), "w") as f:
        f.write("\n".join(csv_rows) + "\n")
    with open(os.path.join(DOCS, "data.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    import dashboard
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(dashboard.render(out))
    print(f"Through {latest}: {len(d_now)} games. Ladder confidence {conf['within1']:.1%}. "
          f"Sigma {model.SIGMA:.2f}, HCA {hca_now:.2f}. Absences used: {len(absences)}. "
          + (f"Picks {record['accuracy']:.1%} of {record['n']}." if record else ""))


if __name__ == "__main__":
    main()
