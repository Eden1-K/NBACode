"""Backtest and tune the model on past seasons (data/history.json).

    python backtest.py            # tune on 2023-24 + 2024-25, test on held-out 2025-26
    python backtest.py --no-tune  # just report the current settings

Rules that keep improvements honest:
  * strictly walk-forward - every game is predicted using only earlier games
  * settings are chosen on the TRAIN seasons only; 2025-26 is never used for tuning
  * tuned settings are adopted only if they beat the defaults on the held-out season
    (lower log loss) - otherwise the defaults stay
Writes data/params.json (settings the live model uses) and data/backtest.json (report).
"""
import argparse
import json
import os
from datetime import datetime, timezone

import numpy as np
from scipy.special import ndtr

import model

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "data", "history.json")
TRAIN, TEST = ["2024", "2025"], "2026"

GRID = {
    "PRIOR_K": [2, 3, 4, 6, 10, 16, 24],
    "HALF_LIFE": [10, 15, 20, 30, 45, 60, 120, 100000],
    "MARGIN_CAP": [12, 16, 20, 30, 45, 100],
    "HCA_PRIOR": [1.5, 2.0, 2.5, 3.0],
    "HCA_K": [50, 150, 500, 2000],
    "REST_B2B": [0.0, -0.75, -1.5, -2.25, -3.0],
    "REST_3IN4": [0.0, -0.5, -1.0],
    "REST_LONG": [0.0, 0.3, 0.6, 1.0],
}
UNC_GRID = [(s, d) for s in (0.6, 0.8, 1.0, 1.2, 1.4) for d in (0.0, 1.0, 2.0)]
TOTAL_GRID = [3, 5, 10, 20, 40]


def load():
    with open(HIST) as f:
        h = json.load(f)["seasons"]
    out = {}
    for y, s in h.items():
        if s.get("preseason_wins"):
            out[y] = (s["label"], s["games"], model.prior_ratings(s["preseason_wins"]))
    return out


def season_preds(games, prior):
    rest = model.rest_adjustments(games)
    return model.walk_forward(games, rest, prior=prior)


def residual_sd(preds):
    return float(np.sqrt(np.mean([((p["hs"] - p["as"]) - p["mu"]) ** 2 for p in preds])))


def score(preds, sigma):
    mu = np.array([p["mu"] for p in preds])
    y = np.array([1.0 if p["home_won"] else 0.0 for p in preds])
    act = np.array([p["hs"] - p["as"] for p in preds], float)
    p = ndtr(mu / sigma)
    eps = 1e-9
    return {"n": len(preds),
            "accuracy": round(float(((p >= 0.5) == (y == 1)).mean()), 4),
            "brier": round(float(((p - y) ** 2).mean()), 4),
            "log_loss": round(float(-(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps)).mean()), 4),
            "margin_mae": round(float(np.abs(act - mu).mean()), 2),
            "margin_rmse": round(float(np.sqrt(((act - mu) ** 2).mean())), 2)}


def train_objective(data):
    """Mean squared margin error over the train seasons (log loss follows it once sigma is fit)."""
    se, n = 0.0, 0
    for y in TRAIN:
        _, games, prior = data[y]
        for p in season_preds(games, prior):
            se += ((p["hs"] - p["as"]) - p["mu"]) ** 2
            n += 1
    return se / n


def tune(data, start):
    model.set_params(**start)
    best = train_objective(data)
    cur = dict(start)
    for sweep in range(2):
        improved = False
        for k, vals in GRID.items():
            for v in vals:
                if v == cur[k]:
                    continue
                trial = {**cur, k: v}
                model.set_params(**trial)
                obj = train_objective(data)
                if obj < best - 1e-4:
                    best, cur, improved = obj, trial, True
            model.set_params(**cur)
            print(f"  sweep {sweep + 1} {k:<10} -> {cur[k]}  (train MSE {best:.2f})")
        if not improved:
            break
    model.set_params(**cur)
    return cur, best


def coverage(games, prior, sims=1500, fracs=(0.2, 0.4, 0.6, 0.8)):
    """At checkpoints in the season, project the rest and check how often each team's final
    wins land inside its 80% range, and how the ladder confidence compares with reality."""
    rest = model.rest_adjustments(games)
    rest_diff = {gid: v[0] - v[1] for gid, v in rest.items()}
    days = sorted({g["date"] for g in games})
    final_w = {a: 0 for a in model.ABBRS}
    for g in games:
        final_w[g["home"] if g["hs"] > g["as"] else g["away"]] += 1
    # realised final seeds (ties broken by rating at season end - close enough for a check)
    rows = []
    for f in fracs:
        cut = days[int(len(days) * f) - 1]
        done = [g for g in games if g["date"] <= cut]
        rem = [g for g in games if g["date"] > cut]
        r, sd, hca = model.fit(done, cut, rest, prior=prior)
        sim = model.simulate(done, rem, r, sd, hca, game_adj={g["id"]: rest_diff[g["id"]] for g in rem},
                             n_sims=sims, seed=3)
        teams, conf = model.summarise(sim, r, sd)
        inside = [t["lo"] <= final_w[t["abbr"]] <= t["hi"] for t in teams]
        realised_within1 = 0.0
        for c in ("East", "West"):
            ct = [t for t in teams if t["conf"] == c]
            order = sorted(ct, key=lambda t: (-final_w[t["abbr"]], -t["rating"]))
            real_seed = {t["abbr"]: i + 1 for i, t in enumerate(order)}
            realised_within1 += np.mean([abs(real_seed[t["abbr"]] - t["seed"]) <= 1 for t in ct]) / 2
        rows.append({"checkpoint": f"{int(f * 100)}% of season", "date": cut,
                     "coverage80": round(float(np.mean(inside)), 4),
                     "pred_within1": conf["within1"], "real_within1": round(float(realised_within1), 4),
                     "mean_abs_win_err": round(float(np.mean([abs(t["proj_w"] - final_w[t["abbr"]]) for t in teams])), 2)})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-tune", action="store_true")
    args = ap.parse_args()
    data = load()
    defaults = dict(model.DEFAULTS)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "train": [data[y][0] for y in TRAIN], "test": data[TEST][0]}

    # ---- defaults on train + test
    model.set_params(**defaults)
    train_def = [p for y in TRAIN for p in season_preds(data[y][1], data[y][2])]
    sig_def = defaults["SIGMA_PRIOR"]
    test_def_preds = season_preds(data[TEST][1], data[TEST][2])
    test_def = score(test_def_preds, sig_def)
    print("Default settings - held-out", data[TEST][0], test_def)

    # ---- tune on train seasons only
    if args.no_tune:
        tuned = dict(defaults)
    else:
        print("Tuning on", [data[y][0] for y in TRAIN])
        tuned, _ = tune(data, defaults)
    model.set_params(**tuned)
    train_tuned = [p for y in TRAIN for p in season_preds(data[y][1], data[y][2])]
    tuned["RESID_SD"] = round(residual_sd(train_tuned), 2)
    # probability sigma: the value that minimises log loss on the train seasons
    sig_grid = [round(x, 2) for x in np.arange(10.0, 15.01, 0.25)]
    tuned["SIGMA_PRIOR"] = min(sig_grid, key=lambda sg: score(train_tuned, sg)["log_loss"])
    model.set_params(**tuned)
    print("Probability sigma ->", tuned["SIGMA_PRIOR"], "(margin residual sd", tuned["RESID_SD"], ")")

    # uncertainty (rating sd scale + rest-of-season drift) so 80% ranges hold ~80% on train seasons
    best, best_gap, drift_rows = (tuned["SD_SCALE"], tuned["DRIFT_SD"]), 9, []
    for sc, d in UNC_GRID:
        model.set_params(**{**tuned, "SD_SCALE": sc, "DRIFT_SD": d})
        cov = np.mean([r["coverage80"] for y in TRAIN for r in coverage(data[y][1], data[y][2], sims=600)])
        drift_rows.append({"sd_scale": sc, "drift_sd": d, "coverage80": round(float(cov), 4)})
        if abs(cov - 0.8) < best_gap - 1e-9:
            best, best_gap = (sc, d), abs(cov - 0.8)
    tuned["SD_SCALE"], tuned["DRIFT_SD"] = best
    # scoring-environment prior strength for score predictions (total points error on train)
    def total_mse(k):
        model.set_params(**{**tuned, "TOTAL_K": k})
        e = [((p["hs"] + p["as"]) - (p["pred_hs_x"] + p["pred_as_x"])) ** 2
             for y in TRAIN for p in season_preds(data[y][1], data[y][2])]
        return float(np.mean(e))
    tuned["TOTAL_K"] = min(TOTAL_GRID, key=total_mse)
    model.set_params(**tuned)
    print("Uncertainty calibration ->", best, "| TOTAL_K ->", tuned["TOTAL_K"])

    test_tuned_preds = season_preds(data[TEST][1], data[TEST][2])
    test_tuned = score(test_tuned_preds, tuned["SIGMA_PRIOR"])
    print("Tuned settings  - held-out", data[TEST][0], test_tuned)

    adopt = test_tuned["log_loss"] <= test_def["log_loss"]
    final = tuned if adopt else defaults
    model.set_params(**final)
    final_preds = test_tuned_preds if adopt else test_def_preds
    for p in final_preds:
        p["p_home"] = float(ndtr(p["mu"] / final["SIGMA_PRIOR"]))
    report.update({
        "adopted": "tuned" if adopt else "defaults",
        "defaults": defaults, "tuned": tuned,
        "test_default": test_def, "test_tuned": test_tuned,
        "train_default": score(train_def, sig_def),
        "train_tuned": score(train_tuned, tuned["SIGMA_PRIOR"]),
        "drift_calibration": drift_rows,
        "coverage_test": coverage(data[TEST][1], data[TEST][2]),
        "segments_test": model.segments(final_preds),
    })
    # Market-prior-only baseline on the test season (how much do results add to the preseason line?)
    pp = np.array([p["p_prior"] for p in final_preds]); yy = np.array([1.0 if p["home_won"] else 0.0 for p in final_preds])
    report["preseason_only_test"] = {"accuracy": round(float(((pp >= .5) == (yy == 1)).mean()), 4),
                                     "brier": round(float(((pp - yy) ** 2).mean()), 4)}
    with open(os.path.join(HERE, "data", "params.json"), "w") as f:
        json.dump({"params": final, "source": f"backtest {report['generated_at']} ({report['adopted']})"}, f, indent=1)
    with open(os.path.join(HERE, "data", "backtest.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("Adopted:", report["adopted"], final)


if __name__ == "__main__":
    main()
