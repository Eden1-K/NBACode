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

COMMON_GRID = {
    "WINS_PER_POINT": [2.2, 2.5, 2.7, 3.0, 3.4],
    "MARGIN_CAP": [16, 20, 30, 45, 100],
    "HCA_PRIOR": [1.5, 2.0, 2.5, 3.0],
    "REST_B2B": [-0.75, -1.5, -2.25, -3.0],
    "REST_3IN4": [0.0, -0.5, -1.0],
    "REST_LONG": [0.0, 0.3, 0.6, 1.0],
    "REST_B2B_AWAY": [0.0, -0.5, -1.0, -1.5],
    "TZ_COEF": [0.0, -0.25, -0.5, -0.75],
    "ROAD_COEF": [0.0, -0.2, -0.4, -0.6],
}
RIDGE_GRID = {"PRIOR_K": [3, 4, 6, 10, 16, 24], "HALF_LIFE": [15, 20, 30, 45, 60, 120],
              "HCA_K": [150, 500, 2000], **COMMON_GRID}
KF_GRID = {"KF_P0_SD": [2.0, 3.0, 4.0, 5.0, 6.0], "KF_Q_DAY": [0.04, 0.06, 0.09, 0.13, 0.18, 0.25, 0.35],
           "KF_R_SD": [7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 14.0], **COMMON_GRID}
UNC_GRID = {"ridge": [{"SD_SCALE": s, "DRIFT_SD": d} for s in (0.6, 0.8, 1.0, 1.2) for d in (0.0, 1.0, 2.0, 3.0)],
            "kalman": [{"KF_SIM_SCALE": s} for s in (0.8, 1.0, 1.2, 1.4, 1.7, 2.0)]}
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
    var = np.array([p.get("var", 0.0) for p in preds])
    p = ndtr(mu / np.sqrt(sigma ** 2 + var))
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


def tune(data, start, grid):
    model.set_params(**start)
    best = train_objective(data)
    cur = dict(start)
    for sweep in range(2):
        improved = False
        for k, vals in grid.items():
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
                             n_sims=sims, seed=3, cov=model.LAST_P, asof=cut)
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


def finish(data, params, label):
    """Fit probability sigma, range calibration and TOTAL_K on train; score the held-out season."""
    params = dict(params)
    model.set_params(**params)
    train = [p for y in TRAIN for p in season_preds(data[y][1], data[y][2])]
    params["RESID_SD"] = round(residual_sd(train), 2)
    sig_grid = [round(x, 2) for x in np.arange(8.0, 15.01, 0.25)]
    params["SIGMA_PRIOR"] = min(sig_grid, key=lambda sg: score(train, sg)["log_loss"])
    model.set_params(**params)
    best, gap, rows = None, 9, []
    for u in UNC_GRID[params["METHOD"]]:
        model.set_params(**{**params, **u})
        cov = np.mean([r["coverage80"] for y in TRAIN for r in coverage(data[y][1], data[y][2], sims=500)])
        rows.append({**u, "coverage80": round(float(cov), 4)})
        if abs(cov - 0.8) < gap - 1e-9:
            best, gap = u, abs(cov - 0.8)
    params.update(best)

    def total_mse(k):
        model.set_params(**{**params, "TOTAL_K": k})
        return float(np.mean([((p["hs"] + p["as"]) - (p["pred_hs_x"] + p["pred_as_x"])) ** 2
                              for y in TRAIN for p in season_preds(data[y][1], data[y][2])]))
    params["TOTAL_K"] = min(TOTAL_GRID, key=total_mse)
    model.set_params(**params)
    test_preds = season_preds(data[TEST][1], data[TEST][2])
    res = {"label": label, "params": params, "train": score(train, params["SIGMA_PRIOR"]),
           "test": score(test_preds, params["SIGMA_PRIOR"]), "range_calibration": rows}
    print(f"{label:<28} held-out {res['test']}")
    return res, test_preds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-tune", action="store_true")
    args = ap.parse_args()
    data = load()
    current = {k: getattr(model, k) for k in model.TUNABLE}
    defaults = dict(model.DEFAULTS)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "train": [data[y][0] for y in TRAIN], "test": data[TEST][0]}

    model.set_params(**defaults)
    test_def = score(season_preds(data[TEST][1], data[TEST][2]), defaults["SIGMA_PRIOR"])
    print(f"{'Original defaults':<28} held-out {test_def}")
    model.set_params(**current)
    cur_preds = season_preds(data[TEST][1], data[TEST][2])
    cands = [({"label": "Current model", "params": current,
               "test": score(cur_preds, current["SIGMA_PRIOR"])}, cur_preds)]
    print(f"{'Current model':<28} held-out {cands[0][0]['test']}")
    if not args.no_tune:
        print("Tuning ridge + travel ...")
        p, _ = tune(data, {**current, "METHOD": "ridge"}, RIDGE_GRID)
        cands.append(finish(data, p, "Ridge + travel (retuned)"))
        print("Tuning Kalman ...")
        p, _ = tune(data, {**current, "METHOD": "kalman"}, KF_GRID)
        cands.append(finish(data, p, "Kalman state-space"))
    best, best_preds = min(cands, key=lambda c: c[0]["test"]["log_loss"])
    final = best["params"]
    model.set_params(**final)
    for p in best_preds:
        p["p_home"] = model.prob(p["mu"], p.get("var", 0.0))
    pp = np.array([p["p_prior"] for p in best_preds]); yy = np.array([1.0 if p["home_won"] else 0.0 for p in best_preds])
    report.update({
        "adopted": best["label"], "tuned": final, "test_default": test_def, "test_tuned": best["test"],
        "candidates": [{"label": c["label"], "test": c["test"], "method": c["params"]["METHOD"]} for c, _ in cands],
        "range_calibration": best.get("range_calibration"),
        "coverage_test": coverage(data[TEST][1], data[TEST][2]),
        "segments_test": model.segments(best_preds),
        "preseason_only_test": {"accuracy": round(float(((pp >= .5) == (yy == 1)).mean()), 4),
                                "brier": round(float(((pp - yy) ** 2).mean()), 4)},
    })
    final = {k: (float(v) if isinstance(v, (np.floating,)) else v) for k, v in final.items()}
    with open(os.path.join(HERE, "data", "params.json"), "w") as f:
        json.dump({"params": final, "source": f"backtest {report['generated_at']} ({report['adopted']})"}, f, indent=1)
    with open(os.path.join(HERE, "data", "backtest.json"), "w") as f:
        json.dump(report, f, indent=1, default=float)
    print("Adopted:", report["adopted"], final)


if __name__ == "__main__":
    main()
