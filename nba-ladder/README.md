# NBA Ladder Model (2026-27)

A live model of the NBA ladder. After every game day it pulls results from ESPN,
re-rates every team, simulates the rest of the season 10,000 times and publishes a
dashboard with:

- **Projected ladder** for each conference: projected W–L, 80% win range, seed odds 1–15,
  top-6 / play-in / playoff chances
- **Confidence**: ladder confidence (share of teams expected within ±1 seed), exact-seed
  hit rate and playoff-field confidence, tracked over the season
- **Track record**: every game predicted walk-forward (only earlier results used), scored
  for accuracy, Brier score and calibration, vs a coin flip and the preseason-only model
- **Score predictions** for every game: the next 7 game days on the dashboard, every remaining
  game in `docs/predictions.csv`, and predicted-vs-actual scores tracked for accuracy
- **Player availability**: ESPN injury report x each player's value (box-score Game Score per 36,
  minutes, share of games played) adjusts the team's rating for the games he misses
- **Rest**: back-to-backs and 3-in-4s cost points; 2+ days off helps a little
- **Playoff & title odds**: play-in plus every best-of-7 series simulated game by game (2-2-1-1-1)
- **Live track record**: the exact pre-tip prediction is frozen in `data/live_log.json` and scored
  afterwards; compared with betting lines whenever ESPN publishes them
- **Self-calibrating**: the game-to-game spread (sigma) and home court are re-estimated from this
  season's results
- **Backtested and tuned on past seasons**: every setting was fitted on 2023-24 + 2024-25 and
  checked on 2025-26 (never used for tuning); includes 80%-range honesty checks and a
  strengths/weaknesses breakdown by situation
- **Betting market**: optional free Odds API key for consensus lines; the dashboard flags games
  where the model and market disagree by 5+ points and tracks who was right
- **Questionable players** sit or play at random in each simulation (by their injury status)
- **What changed** since the last game day, and the result that drove each move

## Files
| File | What it does |
|---|---|
| `teams.py` | Teams, conferences and preseason win totals (the starting prior) |
| `espn.py` | Fetches schedule + results from ESPN, caches them in `data/games.json` |
| `model.py` | Ratings, rest, simulation (incl. playoffs), confidence and track-record maths |
| `backtest.py` | Walk-forward backtest + tuning on `data/history.json` → `data/params.json`, `data/backtest.json` |
| `odds.py` | Optional betting lines from The Odds API (`ODDS_API_KEY`) |
| `availability.py` | Injury report + player values → per-game team adjustments |
| `run.py` | Daily pipeline → `docs/data.json` + `docs/index.html` |
| `dashboard.py` | The dashboard page template |
| `.github/workflows/update.yml` | Runs it automatically twice a day |

## One-time setup (GitHub)
0. Move `update.yml` into a `.github/workflows/` folder (create it) — GitHub only runs workflows from there.
1. Create a new repo on GitHub (e.g. `nba-ladder`) and push this folder to it:
   ```
   git init && git add . && git commit -m "NBA ladder model"
   git branch -M main
   git remote add origin https://github.com/<your-username>/nba-ladder.git
   git push -u origin main
   ```
2. Repo **Settings → Pages**: Source = *Deploy from a branch*, Branch = `main`, folder = `/docs`.
3. Repo **Actions** tab → *Update NBA ladder* → **Run workflow** to do the first run now.
4. (Optional, recommended) Betting lines: get a free key at https://the-odds-api.com, then repo
   **Settings → Secrets and variables → Actions → New repository secret**, name `ODDS_API_KEY`.
   Uses ~180 of the 500 free monthly credits.
5. Your dashboard lives at `https://<your-username>.github.io/nba-ladder/`.

After that it updates itself at about 6:23 pm and 12:23 am Melbourne time (daylight saving)
every day.

## Run locally
```
pip install -r requirements.txt
python run.py            # fetch + update
python run.py --offline  # re-run on cached data
```
Then open `docs/index.html`.

## Re-tuning
`python backtest.py` re-tunes on the past seasons in `data/history.json` and only adopts new
settings if they beat the defaults on the held-out season. Settings live in `data/params.json`.

## Tuning knobs (`model.py`)
`REST_B2B` / `REST_3IN4` / `REST_LONG` (rest effects), `TOTAL_PRIOR` / `TOTAL_K` (league scoring level and how fast team scoring profiles adapt), `PRIOR_K` (how much the preseason line is trusted, in games), `HALF_LIFE` (how fast old
games fade), `DRIFT_SD` (injury/trade allowance), `MARGIN_CAP` (blowout cap).

## Limitations
- Real NBA tiebreakers aren't modelled (ties are broken at random).
- Injury impact uses a box-score value (no on/off or lineup data), so defensive specialists are
  undervalued. Past injury reports aren't archived, so the walk-forward record excludes injuries
  (the live record includes them).
- Travel distance and time zones aren't modelled (small effect).
- Betting-line comparison depends on ESPN including odds in its feed.
- Until the NBA Cup knockout games are scheduled (early Dec), each team's 2 unscheduled
  games are simulated against an average opponent.
