"""The ladder model.

1. Ratings   - every team gets a net rating (points better than an average team on a
               neutral floor). It starts at the preseason win total and is pulled toward
               actual game margins with a Bayesian (ridge) fit; recent games count more.
               Margins are first corrected for rest (back-to-backs), so a tired loss
               doesn't drag a rating down as much.
2. Game      - expected margin = rating gap + home court + rest + player availability.
               Margin ~ Normal(expected, SIGMA); SIGMA is re-estimated from this season's
               own prediction errors once enough games are in.
3. Simulate  - the rest of the season is played out N times. Each run also draws each
               team's "true" strength from its uncertainty, so ranges are wide early and
               tighten as evidence piles up. Then play-in and full best-of-7 playoffs
               (2-2-1-1-1 home court) are played game by game for title odds.
4. Confidence- per-team win ranges and seed odds; ladder confidence inside the sims;
               walk-forward and live track records; comparison with betting lines.
"""
from datetime import date

import numpy as np
from scipy.special import ndtr  # standard normal CDF, vectorised

from teams import ABBRS, TEAMS, PRESEASON_WINS, GAMES_PER_TEAM

SIGMA = 12.0        # sd of a game's margin around expectation; updated by estimate_sigma()
SIGMA_PRIOR = 12.0  # "probability sigma": calibrated by log loss in backtest.py
RESID_SD = 14.0     # typical margin error in past seasons (fat-tailed, so > probability sigma)
SIGMA_PRIOR_N = 200 # prior worth this many games when re-estimating sigma
PRIOR_K = 16.0      # preseason prior is worth this many games of evidence
HCA_PRIOR = 2.5     # home-court advantage prior (points)
HCA_K = 150.0       # strength of that prior (lets the season's data move it)
MARGIN_CAP = 20     # blowouts beyond 20 add no extra information to the ratings
HALF_LIFE = 90      # days - older games slowly count less
DRIFT_SD = 1.5      # extra rest-of-season uncertainty (future injuries, trades)
SD_SCALE = 1.0      # scales rating uncertainty; calibrated so 80% win ranges hold ~80%
WINS_PER_POINT = 2.7

# Rest: points added to a team's expected margin by days off before the game.
REST_B2B = -1.5     # second night of a back-to-back
REST_3IN4 = -0.5    # extra if it's also the 3rd game in 4 nights
REST_LONG = 0.3     # 2+ days off

# Travel (fitted on past seasons; 0 = no effect)
REST_B2B_AWAY = 0.0 # extra for the AWAY team on the second night of a back-to-back
TZ_COEF = 0.0       # per hour of time-zone change since the team's previous game
ROAD_COEF = 0.0     # per road game beyond the 2nd in a row (capped at 3)

# Rating engine: "ridge" (weighted regression) or "kalman" (state-space: strength drifts day
# to day, uncertainty comes from the same model). backtest.py picks whichever does better.
METHOD = "ridge"
KF_P0_SD = 4.0      # preseason uncertainty of a team's rating (points)
KF_Q_DAY = 0.06     # daily random drift of true strength (points)
KF_R_SD = 12.5      # single-game margin noise used by the filter
KF_SIM_SCALE = 1.0  # scales simulated uncertainty; calibrated so 80% win ranges hold ~80%

TOTAL_PRIOR = 230.0 # league-average combined points per game (prior)
TOTAL_K = 10.0
MU_K = 30.0

# Tuned values from backtest.py (data/params.json) override the defaults above.
_PARAMS_FILE = __import__("os").path.join(__import__("os").path.dirname(__file__), "data", "params.json")
TUNABLE = ["PRIOR_K", "HALF_LIFE", "HCA_PRIOR", "HCA_K", "MARGIN_CAP", "DRIFT_SD", "REST_B2B",
           "REST_3IN4", "REST_LONG", "TOTAL_K", "SIGMA_PRIOR", "SD_SCALE", "RESID_SD",
           "REST_B2B_AWAY", "TZ_COEF", "ROAD_COEF", "METHOD", "KF_P0_SD", "KF_Q_DAY", "KF_R_SD",
           "KF_SIM_SCALE", "WINS_PER_POINT"]
DEFAULTS = {k: globals()[k] for k in TUNABLE}
if __import__("os").path.exists(_PARAMS_FILE):
    import json as _json
    with open(_PARAMS_FILE) as _f:
        _p = _json.load(_f).get("params", {})
    for _k, _v in _p.items():
        if _k in TUNABLE:
            globals()[_k] = _v
    SIGMA = SIGMA_PRIOR


def set_params(**kw):
    g = globals()
    for k, v in kw.items():
        assert k in TUNABLE, k
        g[k] = v
    g["SIGMA"] = g["SIGMA_PRIOR"]


N = len(ABBRS)
LAST_P = None       # Kalman posterior covariance from the most recent fit()
IDX = {a: i for i, a in enumerate(ABBRS)}
# hours relative to US Eastern (standard time) - for travel
TZ = {**{a: 0 for a in ("ATL", "BOS", "BKN", "CHA", "CLE", "DET", "IND", "MIA", "NY", "ORL", "PHI",
                         "TOR", "WSH")},
      **{a: -1 for a in ("CHI", "DAL", "HOU", "MEM", "MIL", "MIN", "NO", "OKC", "SA")},
      **{a: -2 for a in ("DEN", "UTAH", "PHX")},
      **{a: -3 for a in ("GS", "LAC", "LAL", "POR", "SAC")}}
CONF = np.array([TEAMS[a][1] for a in ABBRS])


def prior_ratings(wins=None):
    wins = wins or PRESEASON_WINS
    w = np.array([wins[a] for a in ABBRS])
    return (w - w.mean()) / WINS_PER_POINT


def _ord(d):
    return date.fromisoformat(d).toordinal()


# ---------------------------------------------------------------- rest / schedule
def rest_adjustments(games):
    """{game_id: (home_pts, away_pts, home_days_off, away_days_off)} from the full schedule.
    Points include rest (back-to-backs, 3-in-4, long rest) and travel (time zones crossed,
    long road trips)."""
    by_team = {a: [] for a in ABBRS}
    for g in games:
        by_team[g["home"]].append((_ord(g["date"]), g["id"], g["home"], True))
        by_team[g["away"]].append((_ord(g["date"]), g["id"], g["home"], False))
    per = {}
    for team, lst in by_team.items():
        lst.sort()
        trip = 0
        for k, (d, gid, venue, home) in enumerate(lst):
            off = d - lst[k - 1][0] - 1 if k else 3
            pts = REST_B2B if off == 0 else (REST_LONG if off >= 2 else 0.0)
            if off == 0 and k >= 2 and d - lst[k - 2][0] <= 3:
                pts += REST_3IN4
            if off == 0 and not home:
                pts += REST_B2B_AWAY
            if k:
                pts += TZ_COEF * abs(TZ[venue] - TZ[lst[k - 1][2]])
            trip = 0 if home else trip + 1
            if not home:
                pts += ROAD_COEF * min(max(trip - 2, 0), 3)
            per[(team, gid)] = (pts, off)
    out = {}
    for g in games:
        hp, ho = per[(g["home"], g["id"])]
        ap, ao = per[(g["away"], g["id"])]
        out[g["id"]] = (hp, ap, ho, ao)
    return out


# ---------------------------------------------------------------- ratings
def _design(games, rest=None):
    """Rows: +1 home, -1 away, HCA column; margin (rest-corrected, capped); totals; day ordinals."""
    G = len(games)
    X = np.zeros((G, N + 1))
    idx = np.arange(G)
    h = np.array([IDX[g["home"]] for g in games], dtype=int)
    a = np.array([IDX[g["away"]] for g in games], dtype=int)
    X[idx, h] = 1.0
    X[idx, a] = -1.0
    X[:, N] = [0.0 if g["neutral"] else 1.0 for g in games]
    ra = np.array([(rest[g["id"]][0] - rest[g["id"]][1]) if rest and g["id"] in rest else 0.0
                   for g in games])
    m = np.array([g["hs"] - g["as"] for g in games], float) - ra
    tot = np.array([g["hs"] + g["as"] for g in games], float)
    t = np.array([_ord(g["date"]) for g in games], float)
    return X, h, a, np.clip(m, -MARGIN_CAP, MARGIN_CAP), tot, t


class Kalman:
    """30-team state-space rating. Each day every team's true strength drifts (random walk,
    sd KF_Q_DAY per day); each game is a noisy observation of the rating gap."""

    def __init__(self, prior, start_ord):
        self.x = np.array(prior, float).copy()
        self.P = np.eye(N) * KF_P0_SD ** 2
        self.t = start_ord

    def advance(self, t):
        if t > self.t:
            self.P += np.eye(N) * (KF_Q_DAY ** 2) * (t - self.t)
            self.t = t

    def predict(self, h, a):
        return self.x[h] - self.x[a], self.P[h, h] + self.P[a, a] - 2 * self.P[h, a]

    def update(self, h, a, y):
        """y = home margin minus home court/rest, capped."""
        mu, var = self.predict(h, a)
        Ph = self.P[:, h] - self.P[:, a]
        k = Ph / (var + KF_R_SD ** 2)
        self.x += k * (y - mu)
        self.P -= np.outer(k, Ph)


def _kf_obs(g, rest):
    ra = (rest[g["id"]][0] - rest[g["id"]][1]) if rest and g["id"] in rest else 0.0
    y = g["hs"] - g["as"] - ra - (0 if g["neutral"] else HCA_PRIOR)
    return float(np.clip(y, -MARGIN_CAP, MARGIN_CAP))


def fit(games_done, asof, rest=None, prior=None, design=None):
    """Ratings from completed games up to `asof`. Returns (ratings, sd, home court)."""
    global LAST_P
    prior = prior_ratings() if prior is None else prior
    if METHOD == "kalman":
        gs = sorted(games_done, key=lambda g: g["date"])
        kf = Kalman(prior, _ord(gs[0]["date"]) if gs else _ord(asof))
        for g in gs:
            kf.advance(_ord(g["date"]))
            kf.update(IDX[g["home"]], IDX[g["away"]], _kf_obs(g, rest))
        kf.advance(_ord(asof))
        LAST_P = kf.P.copy()
        r = kf.x - kf.x.mean()
        return r, np.sqrt(np.diag(kf.P)), HCA_PRIOR
    A = np.zeros((N + 1, N + 1))
    b = np.zeros(N + 1)
    A[:N, :N] += np.eye(N) * PRIOR_K
    b[:N] += prior * PRIOR_K
    A[N, N] += HCA_K
    b[N] += HCA_PRIOR * HCA_K
    eff_n = np.zeros(N)
    if games_done:
        X, h, a, m, _, t = design if design is not None else _design(games_done, rest)
        w = 0.5 ** ((_ord(asof) - t) / HALF_LIFE)
        A += X.T @ (X * w[:, None])
        b += X.T @ (w * m)
        np.add.at(eff_n, h, w)
        np.add.at(eff_n, a, w)
    sol = np.linalg.solve(A, b)
    r = sol[:N] - sol[:N].mean()
    sd = SD_SCALE * SIGMA_PRIOR / np.sqrt(PRIOR_K + eff_n)
    LAST_P = None
    return r, sd, sol[N]


def fit_totals(games_done, asof, design=None):
    """Team 'total' effects: home_pts + away_pts = mu + t_home + t_away."""
    A = np.zeros((N + 1, N + 1))
    b = np.zeros(N + 1)
    A[:N, :N] += np.eye(N) * TOTAL_K
    A[N, N] += MU_K
    b[N] += TOTAL_PRIOR * MU_K
    if games_done:
        X, h, a, _, tot, t = design if design is not None else _design(games_done)
        Z = np.abs(X)
        Z[:, N] = 1.0
        w = 0.5 ** ((_ord(asof) - t) / HALF_LIFE)
        A += Z.T @ (Z * w[:, None])
        b += Z.T @ (w * tot)
    sol = np.linalg.solve(A, b)
    return sol[:N], sol[N]


def exp_margin(r, hca, home, away, neutral=False, adj=0.0):
    return r[IDX[home]] - r[IDX[away]] + (0 if neutral else hca) + adj


def game_var(P, home, away):
    """Rating uncertainty of the gap between two teams (Kalman only; 0 for ridge)."""
    if P is None:
        return 0.0
    h, a = IDX[home], IDX[away]
    return float(P[h, h] + P[a, a] - 2 * P[h, a])


def prob(mu, var=0.0):
    return float(ndtr(mu / np.sqrt(SIGMA ** 2 + var)))


def win_prob(r, hca, home, away, neutral=False, adj=0.0, var=0.0):
    return prob(exp_margin(r, hca, home, away, neutral, adj), var)


def predict_score(r, hca, tot, home, away, neutral=False, adj=0.0):
    """Expected (home_pts, away_pts); the margin matches the win-probability model."""
    t_eff, mu = tot
    margin = exp_margin(r, hca, home, away, neutral, adj)
    total = mu + t_eff[IDX[home]] + t_eff[IDX[away]]
    return (total + margin) / 2, (total - margin) / 2


# ---------------------------------------------------------------- simulation
def _series(rng, true, hca, a, b, a_home):
    """Best-of-7, 2-2-1-1-1. `a_home` (bool array) = a has home court. Returns winner ids.
    Playing all 7 games and taking the majority gives the same winner as stopping at 4."""
    ix = np.arange(len(a))
    d = (true[ix, a] - true[ix, b]) / SIGMA
    p_a_home = ndtr(d + hca / SIGMA)
    p_a_away = ndtr(d - hca / SIGMA)
    n_home_a = np.where(a_home, 4, 3)
    wins_a = rng.binomial(n_home_a, p_a_home) + rng.binomial(7 - n_home_a, p_a_away)
    return np.where(wins_a >= 4, a, b)


def simulate(done, remaining, r, sd, hca, game_adj=None, n_sims=10000, seed=7, chunk=2500,
             random_adj=None, cov=None, asof=None):
    """random_adj: [(game_id, sign, points, p_out)] - questionable/day-to-day players, who
    either sit (full effect) or play in each simulation, instead of a fixed partial effect."""
    """Monte Carlo the rest of the season + play-in + playoffs."""
    rng = np.random.default_rng(seed)
    wins0 = np.zeros(N)
    played = np.zeros(N)
    h2h0 = np.zeros((N, N))          # h2h0[i, j] = wins of i over j
    confw0 = np.zeros(N)
    same_conf = CONF[:, None] == CONF[None, :]
    for g in done:
        h, a = IDX[g["home"]], IDX[g["away"]]
        played[h] += 1
        played[a] += 1
        w, l = (h, a) if g["hs"] > g["as"] else (a, h)
        wins0[w] += 1
        h2h0[w, l] += 1
        if same_conf[h, a]:
            confw0[w] += 1
    H = np.array([IDX[g["home"]] for g in remaining], dtype=int)
    A = np.array([IDX[g["away"]] for g in remaining], dtype=int)
    nh = np.array([0.0 if g["neutral"] else 1.0 for g in remaining])
    adj = np.array([game_adj.get(g["id"], 0.0) if game_adj else 0.0 for g in remaining])
    sched = played.copy()
    np.add.at(sched, H, 1)
    np.add.at(sched, A, 1)
    pad = np.clip(GAMES_PER_TEAM - sched, 0, None).astype(int)  # unscheduled (NBA Cup) games
    G = len(remaining)
    onehot_h = np.zeros((G, N)); onehot_h[np.arange(G), H] = 1
    onehot_a = np.zeros((G, N)); onehot_a[np.arange(G), A] = 1
    tot_sd = np.sqrt(sd ** 2 + DRIFT_SD ** 2)
    kalman = cov is not None
    if kalman:  # strengths drift day by day from the posterior (uncertainty grows with time ahead)
        L = np.linalg.cholesky(cov + np.eye(N) * 1e-9) * KF_SIM_SCALE
        t0 = _ord(asof) if asof else 0
        dayidx = np.array([max(_ord(g["date"]) - t0, 1) for g in remaining], dtype=int) if G else np.zeros(0, int)
        D = int(dayidx.max()) if G else 1
        q = KF_Q_DAY * KF_SIM_SCALE
    cm = np.array([1.0 if same_conf[IDX[g["home"]], IDX[g["away"]]] else 0.0 for g in remaining])
    Mh = np.zeros((G, N * N)); Mh[np.arange(G), H * N + A] = 1   # home beat away
    Ma = np.zeros((G, N * N)); Ma[np.arange(G), A * N + H] = 1
    conf_games = np.zeros(N)
    for g in list(done) + list(remaining):
        h, a = IDX[g["home"]], IDX[g["away"]]
        if same_conf[h, a]:
            conf_games[h] += 1
            conf_games[a] += 1
    tie_mask = same_conf & ~np.eye(N, dtype=bool)
    gpos = {g["id"]: k for k, g in enumerate(remaining)}
    comps = [(gpos[gid], sg * pts, p) for gid, sg, pts, p in (random_adj or []) if gid in gpos]

    out = {k: [] for k in ("wins", "seeds", "playoffs", "r2", "cf", "finals", "title")}
    for start in range(0, n_sims, chunk):
        S = min(chunk, n_sims - start)
        ix = np.arange(S)
        if kalman:
            true0 = r + rng.standard_normal((S, N)) @ L.T
            W = np.cumsum(rng.standard_normal((S, D + 1, N)).astype(np.float32) * q, axis=1)
            true = true0 + W[:, -1, :]                      # end-of-season strength (playoffs)
            sh = true0[:, H] + W[:, dayidx, H] if G else None
            sa = true0[:, A] + W[:, dayidx, A] if G else None
            del W
        else:
            true = r + rng.standard_normal((S, N)) * tot_sd
            sh, sa = (true[:, H], true[:, A]) if G else (None, None)
        if G:
            extra = np.zeros((S, G))
            for gi, eff, pout in comps:
                extra[:, gi] += eff * (rng.random(S) < pout)
            p = ndtr((sh - sa + hca * nh + adj + extra) / SIGMA)
            hw = (rng.random((S, G)) < p).astype(float)
            wins = wins0 + hw @ onehot_h + (1 - hw) @ onehot_a
            h2h = (h2h0.reshape(-1) + hw @ Mh + (1 - hw) @ Ma).reshape(S, N, N)
            confw = confw0 + (hw * cm) @ onehot_h + ((1 - hw) * cm) @ onehot_a
        else:
            wins = np.tile(wins0, (S, 1))
            h2h = np.broadcast_to(h2h0, (S, N, N))
            confw = np.tile(confw0, (S, 1))
        if pad.any():
            wins = wins + rng.binomial(pad, ndtr(true / SIGMA))
        seed_m = np.zeros((S, N), dtype=int)
        po = np.zeros((S, N), dtype=bool)
        r2 = np.zeros((S, N), dtype=bool); cf = np.zeros((S, N), dtype=bool)
        fin = np.zeros((S, N), dtype=bool); title = np.zeros((S, N), dtype=bool)
        # Tiebreakers: record vs the other teams tied on wins (head-to-head), then
        # conference record, then a coin flip.
        eq = (wins[:, :, None] == wins[:, None, :]) & tie_mask[None]
        gw = (h2h * eq).sum(2)
        gg = ((h2h + h2h.transpose(0, 2, 1)) * eq).sum(2)
        grp = np.where(gg > 0, gw / np.maximum(gg, 1), 0.5)
        cpct = confw / np.maximum(conf_games, 1)
        key = wins + 0.1 * grp + 0.01 * cpct + 0.001 * rng.random((S, N))
        champs = {}

        def play(home, away):
            return rng.random(S) < ndtr((true[ix, home] - true[ix, away] + hca) / SIGMA)

        for conf in ("East", "West"):
            cols = np.where(CONF == conf)[0]
            order = cols[np.argsort(-key[:, cols], axis=1)]          # (S, 15) team idx by seed
            seed_m[ix[:, None], order] = np.arange(1, 16)
            po[ix[:, None], order[:, :6]] = True
            s7, s8, s9, s10 = order[:, 6], order[:, 7], order[:, 8], order[:, 9]
            g1 = play(s7, s8)
            w78, l78 = np.where(g1, s7, s8), np.where(g1, s8, s7)
            w910 = np.where(play(s9, s10), s9, s10)
            last = np.where(play(l78, w910), l78, w910)
            po[ix, w78] = True
            po[ix, last] = True
            bracket = [order[:, 0], order[:, 1], order[:, 2], order[:, 3],
                       order[:, 4], order[:, 5], w78, last]          # seeds 1..8
            sn = [np.full(S, k + 1) for k in range(8)]

            def rnd(t1, s1, t2, s2):
                a_home = s1 < s2
                w = _series(rng, true, hca, t1, t2, a_home)
                return w, np.where(w == t1, s1, s2)
            T, Sd = bracket, sn
            a1, sa1 = rnd(T[0], Sd[0], T[7], Sd[7]); a2, sa2 = rnd(T[3], Sd[3], T[4], Sd[4])
            b1, sb1 = rnd(T[2], Sd[2], T[5], Sd[5]); b2, sb2 = rnd(T[1], Sd[1], T[6], Sd[6])
            for t in (a1, a2, b1, b2):
                r2[ix, t] = True
            c1, sc1 = rnd(a1, sa1, a2, sa2); c2, sc2 = rnd(b1, sb1, b2, sb2)
            cf[ix, c1] = True; cf[ix, c2] = True
            ch, _ = rnd(c1, sc1, c2, sc2)
            fin[ix, ch] = True
            champs[conf] = ch
        e, w = champs["East"], champs["West"]
        e_home = key[ix, e] > key[ix, w]
        winner = _series(rng, true, hca, e, w, e_home)
        title[ix, winner] = True
        for k, v in (("wins", wins), ("seeds", seed_m), ("playoffs", po), ("r2", r2),
                     ("cf", cf), ("finals", fin), ("title", title)):
            out[k].append(v)
    res = {k: np.vstack(v) for k, v in out.items()}
    res.update({"wins0": wins0, "played": played, "total_games": sched + pad})
    return res


def summarise(sim, r, sd):
    wins, seeds, po = sim["wins"], sim["seeds"], sim["playoffs"]
    mean_w = wins.mean(0)
    seed_p = np.stack([(seeds == k).mean(0) for k in range(1, 16)], axis=1)  # (N,15)
    proj_seed = np.zeros(N, dtype=int)
    for conf in ("East", "West"):
        cols = np.where(CONF == conf)[0]
        order = cols[np.lexsort((-r[cols], -mean_w[cols]))]
        proj_seed[order] = np.arange(1, 16)
    rd = lambda x: round(float(x), 4)
    teams = []
    for i, a in enumerate(ABBRS):
        teams.append({
            "abbr": a, "name": TEAMS[a][0], "conf": TEAMS[a][1],
            "w": int(sim["wins0"][i]), "l": int(sim["played"][i] - sim["wins0"][i]),
            "games": int(sim["total_games"][i]),
            "proj_w": round(float(mean_w[i]), 1),
            "lo": int(np.percentile(wins[:, i], 10)), "hi": int(np.percentile(wins[:, i], 90)),
            "seed": int(proj_seed[i]),
            "seed_p": [round(float(x), 4) for x in seed_p[i]],
            "p_top6": rd((seeds[:, i] <= 6).mean()),
            "p_playin": rd(((seeds[:, i] >= 7) & (seeds[:, i] <= 10)).mean()),
            "p_playoffs": rd(po[:, i].mean()),
            "p_first": rd((seeds[:, i] == 1).mean()),
            "p_r2": rd(sim["r2"][:, i].mean()), "p_cf": rd(sim["cf"][:, i].mean()),
            "p_finals": rd(sim["finals"][:, i].mean()), "p_title": rd(sim["title"][:, i].mean()),
            "rating": round(float(r[i]), 2), "rating_sd": round(float(sd[i]), 2),
        })
    exact = within1 = field = rho = 0.0
    for conf in ("East", "West"):
        cols = np.where(CONF == conf)[0]
        ps = proj_seed[cols]
        s = seeds[:, cols]
        exact += (s == ps).mean() / 2
        within1 += (np.abs(s - ps) <= 1).mean() / 2
        d2 = ((s - ps) ** 2).sum(1)
        rho += (1 - 6 * d2 / (15 * (15 ** 2 - 1))).mean() / 2
        top8 = cols[np.argsort(-po[:, cols].mean(0))[:8]]
        field += po[:, top8].mean() / 2
    conf = {"exact": round(exact, 4), "within1": round(within1, 4),
            "playoff_field": round(field, 4), "rank_corr": round(rho, 4)}
    return teams, conf


# ---------------------------------------------------------------- evaluation
def walk_forward(done, rest, prior=None):
    """Predict every completed game using only results from earlier days (rest included;
    historical injury reports aren't available, so availability isn't)."""
    by_day = {}
    for g in done:
        by_day.setdefault(g["date"], []).append(g)
    preds, before = [], []
    prior = prior_ratings() if prior is None else prior
    done_sorted = [g for d in sorted(by_day) for g in by_day[d]]
    full = _design(done_sorted, rest) if done_sorted else None
    gp = {t: 0 for t in ABBRS}
    kf = Kalman(prior, _ord(min(by_day))) if METHOD == "kalman" and by_day else None
    for day in sorted(by_day):
        k = len(before)
        des = tuple(x[:k] for x in full) if k else None
        if kf:
            kf.advance(_ord(day))
            r, hca = kf.x - kf.x.mean(), HCA_PRIOR
        else:
            r, _, hca = fit(before, day, rest, prior=prior, design=des)
        tot = fit_totals(before, day, design=des)
        for g in by_day[day]:
            ra = rest[g["id"]][0] - rest[g["id"]][1] if g["id"] in rest else 0.0
            mu = exp_margin(r, hca, g["home"], g["away"], g["neutral"], ra)
            var = kf.predict(IDX[g["home"]], IDX[g["away"]])[1] if kf else 0.0
            p0 = float(ndtr(exp_margin(prior, HCA_PRIOR, g["home"], g["away"], g["neutral"]) / SIGMA_PRIOR))
            ph, pa = predict_score(r, hca, tot, g["home"], g["away"], g["neutral"], ra)
            preds.append({"date": day, "id": g["id"], "home": g["home"], "away": g["away"],
                          "hs": g["hs"], "as": g["as"], "mu": round(mu, 2),
                          "p_prior": round(p0, 4), "home_won": g["hs"] > g["as"],
                          "pred_hs": round(ph), "pred_as": round(pa),
                          "pred_hs_x": round(ph, 2), "pred_as_x": round(pa, 2),
                          "market_p": market_prob(g),
                          "off_h": rest[g["id"]][2] if g["id"] in rest else 1,
                          "off_a": rest[g["id"]][3] if g["id"] in rest else 1,
                          "gn": min(gp[g["home"]], gp[g["away"]]) + 1, "var": round(var, 3)})
        for g in by_day[day]:
            gp[g["home"]] += 1
            gp[g["away"]] += 1
            if kf:
                kf.update(IDX[g["home"]], IDX[g["away"]], _kf_obs(g, rest))
        before.extend(by_day[day])
    for p in preds:  # probabilities use the current SIGMA
        p["p_home"] = round(prob(p["mu"], p["var"]), 4)
    return preds


def estimate_sigma(preds):
    """Scale the calibrated sigma by how noisy this season's margins are vs past seasons
    (shrunk toward 1 with a 200-game prior), so a high-variance season widens the odds."""
    if not preds:
        return SIGMA_PRIOR
    res = np.array([(p["hs"] - p["as"]) - p["mu"] for p in preds])
    n = len(res)
    cur = np.sqrt((SIGMA_PRIOR_N * RESID_SD ** 2 + (res ** 2).sum()) / (SIGMA_PRIOR_N + n))
    return float(SIGMA_PRIOR * cur / RESID_SD)


def market_prob(g):
    """Bookmaker home-win probability from moneylines (vig removed) or the spread."""
    o = g.get("odds") or {}
    if o.get("p_home") is not None:
        return float(o["p_home"])
    mh, ma = o.get("ml_h"), o.get("ml_a")

    def imp(ml):
        return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)
    if mh and ma:
        ph, pa = imp(mh), imp(ma)
        return round(ph / (ph + pa), 4)
    if o.get("spread") is not None:
        return round(float(ndtr(-o["spread"] / SIGMA_PRIOR)), 4)  # spread is home-team line
    return None


def score_block(preds, key_p="p_home"):
    p = np.array([x[key_p] for x in preds])
    y = np.array([1.0 if x["home_won"] else 0.0 for x in preds])
    eps = 1e-6
    return {"n": int(len(p)), "accuracy": round(float(((p >= 0.5) == (y == 1)).mean()), 4),
            "brier": round(float(((p - y) ** 2).mean()), 4),
            "log_loss": round(float(-(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps)).mean()), 4)}


def track_record(preds):
    if not preds:
        return None
    p = np.array([x["p_home"] for x in preds])
    p0 = np.array([x["p_prior"] for x in preds])
    y = np.array([1.0 if x["home_won"] else 0.0 for x in preds])
    correct = ((p >= 0.5) == (y == 1))
    days = sorted({x["date"] for x in preds})
    last7 = set(days[-7:])
    m7 = np.array([x["date"] in last7 for x in preds])
    bins = []
    fav_p = np.maximum(p, 1 - p)
    fav_won = np.where(p >= 0.5, y, 1 - y)
    for lo in (0.5, 0.6, 0.7, 0.8, 0.9):
        sel = (fav_p >= lo) & (fav_p < lo + 0.1 + (1e-9 if lo == 0.9 else 0))
        if sel.any():
            bins.append({"lo": lo, "n": int(sel.sum()), "pred": round(float(fav_p[sel].mean()), 3),
                         "actual": round(float(fav_won[sel].mean()), 3)})
    hs = np.array([x["hs"] for x in preds], float); as_ = np.array([x["as"] for x in preds], float)
    phs = np.array([x["pred_hs_x"] for x in preds]); pas = np.array([x["pred_as_x"] for x in preds])
    team_err = np.concatenate([np.abs(phs - hs), np.abs(pas - as_)])
    scores = {
        "team_mae": round(float(team_err.mean()), 1),
        "margin_mae": round(float(np.abs((phs - pas) - (hs - as_)).mean()), 1),
        "total_mae": round(float(np.abs((phs + pas) - (hs + as_)).mean()), 1),
        "within10": round(float((team_err <= 10).mean()), 4),
        "naive_team_mae": round(float(np.abs(np.concatenate([hs, as_]) - TOTAL_PRIOR / 2).mean()), 1),
    }
    market = None
    mk = [x for x in preds if x.get("market_p") is not None]
    if len(mk) >= 5:
        market = {"model": score_block(mk), "market": score_block(mk, "market_p")}
        dis = [x for x in mk if abs(x["p_home"] - x["market_p"]) >= 0.05]
        if dis:
            # games where model and market disagree by 5+ pts: who was closer?
            mb, kb = score_block(dis), score_block(dis, "market_p")
            sides = [x for x in dis if (x["p_home"] >= 0.5) != (x["market_p"] >= 0.5)]
            model_side = sum((x["p_home"] >= 0.5) == x["home_won"] for x in sides)
            market["disagree"] = {"n": len(dis), "model_brier": mb["brier"], "market_brier": kb["brier"],
                                  "different_pick": len(sides), "model_right": int(model_side)}
    base = score_block(preds)
    return {
        **base, "scores": scores, "market": market,
        "accuracy_7d": round(float(correct[m7].mean()), 4) if m7.any() else None,
        "brier_prior": round(float(((p0 - y) ** 2).mean()), 4),
        "brier_coin": 0.25,
        "calibration": bins,
    }


def segments(preds):
    """Accuracy / Brier / calibration by situation, to find where the model is weak."""
    def seg(name, rows):
        if not rows:
            return None
        p = np.array([x["p_home"] for x in rows])
        y = np.array([1.0 if x["home_won"] else 0.0 for x in rows])
        fav = np.maximum(p, 1 - p)
        fav_won = np.where(p >= 0.5, y, 1 - y)
        return {"segment": name, "n": len(rows), "accuracy": round(float(fav_won.mean()), 4),
                "pred": round(float(fav.mean()), 4), "brier": round(float(((p - y) ** 2).mean()), 4)}
    fp = lambda x: max(x["p_home"], 1 - x["p_home"])
    groups = [
        ("Home favourite", [x for x in preds if x["p_home"] >= 0.5]),
        ("Road favourite", [x for x in preds if x["p_home"] < 0.5]),
        ("Coin flip (50-55%)", [x for x in preds if fp(x) < 0.55]),
        ("Lean (55-65%)", [x for x in preds if 0.55 <= fp(x) < 0.65]),
        ("Solid (65-75%)", [x for x in preds if 0.65 <= fp(x) < 0.75]),
        ("Strong (75%+)", [x for x in preds if fp(x) >= 0.75]),
        ("Team games 1-10", [x for x in preds if x.get("gn", 99) <= 10]),
        ("Team games 11-30", [x for x in preds if 10 < x.get("gn", 99) <= 30]),
        ("Team games 31+", [x for x in preds if x.get("gn", 0) > 30]),
        ("Back-to-back involved", [x for x in preds if x.get("off_h") == 0 or x.get("off_a") == 0]),
        ("Both teams rested", [x for x in preds if x.get("off_h", 1) > 0 and x.get("off_a", 1) > 0]),
    ]
    return [s for s in (seg(n, r) for n, r in groups) if s]
