"""Renders the self-contained dashboard (docs/index.html) from the model output."""
import json

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NBA Ladder Model</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<style>
:root{
  color-scheme:light;
  --bg:#f6f5f2; --surface:#fcfcfb; --surface-2:#f0efeb; --line:#e3e1db;
  --text:#0b0b0b; --text-2:#52514e; --muted:#8a8984;
  --accent:#2a78d6; --accent-soft:#86b6ef; --series-2:#eb6834;
  --good:#1a7f37; --bad:#c62f2e;
  --seq-0:#f0efeb; --seq-1:#cde2fb; --seq-2:#9ec5f4; --seq-3:#5598e7; --seq-4:#256abf; --seq-5:#104281;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --bg:#121211; --surface:#1a1a19; --surface-2:#232321; --line:#2f2f2c;
    --text:#f0efec; --text-2:#c3c2b7; --muted:#8d8c85;
    --accent:#3987e5; --accent-soft:#1c5cab; --series-2:#d95926;
    --good:#4cb86a; --bad:#e66767;
    --seq-0:#232321; --seq-1:#104281; --seq-2:#184f95; --seq-3:#256abf; --seq-4:#3987e5; --seq-5:#86b6ef;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#121211; --surface:#1a1a19; --surface-2:#232321; --line:#2f2f2c;
  --text:#f0efec; --text-2:#c3c2b7; --muted:#8d8c85;
  --accent:#3987e5; --accent-soft:#1c5cab; --series-2:#d95926;
  --good:#4cb86a; --bad:#e66767;
  --seq-0:#232321; --seq-1:#104281; --seq-2:#184f95; --seq-3:#256abf; --seq-4:#3987e5; --seq-5:#86b6ef;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:26px;letter-spacing:-.02em;margin:0 0 4px}
h2{font-size:16px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--text-2);margin:0}
.note{color:var(--muted);font-size:12.5px;margin:2px 0 14px}
.num{font-family:"JetBrains Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
section{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px;margin-top:16px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-top:20px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.kpi .lab{color:var(--text-2);font-size:12.5px}
.kpi .val{font-size:30px;font-weight:700;letter-spacing:-.02em;margin-top:2px}
.kpi .foot{color:var(--muted);font-size:12px;margin-top:2px}
.up{color:var(--good)} .down{color:var(--bad)}
.movers{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.mover{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--surface-2)}
.mover b{font-size:14px}
.mover .d{float:right;font-weight:600}
.mover .why{color:var(--text-2);font-size:12.5px;margin-top:4px}
.tabs{display:flex;gap:6px;margin:6px 0 12px}
.tabs button{font:inherit;border:1px solid var(--line);background:var(--surface-2);color:var(--text-2);padding:6px 14px;border-radius:999px;cursor:pointer}
.tabs button[aria-selected="true"]{background:var(--text);color:var(--surface);border-color:var(--text)}
.tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;min-width:860px}
th{font-weight:500;color:var(--muted);font-size:12px;text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:7px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
tr.cut td{border-bottom:2px dashed var(--muted)}
td.r,th.r{text-align:right}
.seed{font-weight:700;width:28px}
.team b{font-weight:600}
.team span{color:var(--muted);font-size:12px;margin-left:6px}
.strip{display:flex;gap:2px}
.strip i{width:11px;height:18px;border-radius:2px;display:block}
.range{width:170px}
.chart{width:100%;height:auto;display:block}
.legend{display:flex;gap:16px;font-size:12.5px;color:var(--text-2);margin:4px 0 8px;flex-wrap:wrap}
.legend span::before{content:"";display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle;background:var(--c)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid2>*{min-width:0}
@media (max-width:820px){.grid2{grid-template-columns:1fr}}
.games{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px}
.game{display:flex;justify-content:space-between;align-items:center;border:1px solid var(--line);border-radius:10px;padding:8px 12px;background:var(--surface-2);font-size:13px}
.ok{color:var(--good);font-weight:600} .miss{color:var(--bad);font-weight:600}
.sgames{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
.sg{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--surface-2);font-size:13.5px}
.sg .row{display:flex;align-items:center;gap:8px;padding:2px 0}
.sg .row .ab{width:46px;font-weight:600}
.sg .row .pt{font-family:"JetBrains Mono",ui-monospace,monospace;font-weight:600;font-size:16px;min-width:34px;text-align:right}
.sg .row .pr{margin-left:auto;color:var(--muted);font-size:12px}
.sg .row.win .ab,.sg .row.win .pt{color:var(--text)} .sg .row:not(.win) .ab,.sg .row:not(.win) .pt{color:var(--text-2);font-weight:500}
.sg .bar{height:4px;border-radius:2px;background:var(--line);margin:6px 0 2px;overflow:hidden;display:flex;gap:2px}
.sg .bar i{display:block;height:100%;border-radius:2px}
.sg .foot{color:var(--muted);font-size:12px;margin-top:4px;display:flex;justify-content:space-between}
a{color:var(--accent)}
.tag{display:inline-block;font-size:10.5px;font-weight:600;padding:1px 5px;border-radius:4px;margin-left:4px;background:var(--surface);border:1px solid var(--line);color:var(--text-2)}
.tag.inj{color:var(--bad);border-color:currentColor}
.hbar{display:flex;align-items:center;gap:8px}
.hbar i{display:block;height:8px;border-radius:0 4px 4px 0;background:var(--accent);min-width:2px}
#tip{position:fixed;pointer-events:none;background:var(--text);color:var(--surface);padding:6px 9px;border-radius:8px;font-size:12px;opacity:0;transition:opacity .1s;z-index:9;max-width:240px}
details{margin-top:4px} summary{cursor:pointer;color:var(--text-2)}
.method p,.method li{color:var(--text-2);font-size:13.5px}
</style>
</head>
<body>
<div class="wrap">
  <h1>NBA Ladder Model</h1>
  <p class="sub" id="sub"></p>
  <div class="kpis" id="kpis"></div>

  <section>
    <h2>What changed since the last game day</h2>
    <p class="note" id="moversNote"></p>
    <div class="movers" id="movers"></div>
  </section>

  <section>
    <h2>Projected ladder</h2>
    <p class="note">Ordered by projected wins. Bar = 80% range of final wins (10th–90th percentile), dot = average. Seed odds run 1 → 15, darker = likelier. Dashed line = play-in cutoff.</p>
    <div class="tabs" role="tablist" id="tabs"></div>
    <div class="tablewrap"><table id="ladder"></table></div>
  </section>

  <div class="grid2">
    <section>
      <h2>Playoff &amp; title odds</h2>
      <p class="note">From the same simulations: play-in, then every best-of-7 series game by game (2-2-1-1-1 home court).</p>
      <div class="tablewrap"><table id="title" style="min-width:420px"></table></div>
    </section>
    <section>
      <h2>Injury impact</h2>
      <p class="note">Players on the ESPN injury report, valued from their box-score impact and how much they've played. "Effect" = points taken off the team's rating while they're out.</p>
      <div class="tablewrap"><table id="inj" style="min-width:420px"></table></div>
    </section>
  </div>

  <section>
    <h2>Confidence over time</h2>
    <p class="note">Ladder confidence = share of teams expected to finish within one seed of where the model has them. Pick accuracy = share of games the model's favourite has won (cumulative).</p>
    <div class="legend"><span style="--c:var(--accent)">Ladder confidence</span><span style="--c:var(--series-2)">Pick accuracy</span></div>
    <svg class="chart" id="trend" viewBox="0 0 900 260" role="img" aria-label="Confidence over time"></svg>
  </section>

  <div class="grid2">
    <section>
      <h2>Track record</h2>
      <p class="note">Every game is predicted using only results from before that day, then scored. Lower Brier = better.</p>
      <div id="record"></div>
      <svg class="chart" id="calib" viewBox="0 0 420 240" role="img" aria-label="Calibration"></svg>
    </section>
    <section>
      <h2 id="lastTitle">Latest results vs the model</h2>
      <p class="note">Predicted score (made before tip-off) vs what happened. ✓/✗ = did the model's pick win.</p>
      <div class="sgames" id="lastGames"></div>
    </section>
  </div>

  <section>
    <h2>Score predictions</h2>
    <p class="note">Predicted final score and win chance for every game in the next 7 game days, using today's ratings. <a href="predictions.csv" download>Download every remaining game (CSV)</a></p>
    <div class="tabs" role="tablist" id="dayTabs" style="flex-wrap:wrap"></div>
    <div class="sgames" id="nextGames"></div>
  </section>

  <section>
    <h2>Backtest on past seasons</h2>
    <p class="note" id="btNote"></p>
    <div class="kpis" id="btKpis" style="margin-top:8px"></div>
    <div class="grid2" style="margin-top:4px">
      <div><h2 style="font-size:14px;margin-top:14px">Are the 80% win ranges honest?</h2>
        <p class="note">Projections made at points through the held-out season, checked against how it actually finished.</p>
        <div class="tablewrap"><table id="btCov" style="min-width:420px"></table></div></div>
      <div><h2 style="font-size:14px;margin-top:14px">Where the model is strong and weak</h2>
        <p class="note">Favourite's win rate vs what the model predicted, by situation. <span id="segSrc"></span></p>
        <div class="tabs" id="segTabs"></div>
        <div class="tablewrap"><table id="segTbl" style="min-width:420px"></table></div></div>
    </div>
  </section>

  <section class="method">
    <h2>How the model works</h2>
    <details><summary>Show method</summary>
    <ul>
      <li><b>Team ratings.</b> Each team has a net rating (points better than average). It starts from the preseason sportsbook win total and is updated after every game with a Bayesian fit on game margins (home-court adjusted, blowouts capped at 20, older games slowly weighted down). The preseason prior is worth ~16 games, so by mid-season results dominate.</li>
      <li><b>Rest.</b> Second night of a back-to-back, 3 games in 4 nights and 2+ days off each shift the expected margin; the sizes were fitted on past seasons (<span id="restVals"></span>). Past margins are rest-corrected before rating teams.</li>
      <li><b>Tuning.</b> Every setting (how much the preseason line is trusted, how fast old games fade, blowout cap, home court, rest, the probability spread and the uncertainty in the ranges) was chosen on 2023-24 and 2024-25, then checked on 2025-26, which was never used for tuning. Settings are only adopted if they beat the defaults on that held-out season.</li>
      <li><b>Player availability.</b> Each player's value comes from his box-score Game Score per 36 minutes (blended with last season early on) and his minutes. Players on the injury report reduce the team's rating for the games they're expected to miss (Out = full, Doubtful 80%, Questionable 50%, Day-to-day 35%), scaled by how much of the season they've played, since the rating already reflects games they missed.</li>
      <li><b>Simulation.</b> The remaining schedule is played out __SIMS__ times. In each run, every team's true strength is drawn from its rating uncertainty plus an allowance for future injuries/trades, so ranges are wide early and narrow as the season goes on. Single-game spread (sigma, now __SIGMA__ pts) and home court (now __HCA__ pts) are re-estimated from this season's results.</li>
      <li><b>Ladder.</b> Seeds 1–15 per conference (ties broken at random — real NBA tiebreakers aren't modelled), then the play-in (7v8, 9v10, loser vs winner), then every playoff series best-of-7 game by game with 2-2-1-1-1 home court, for round-by-round and title odds.</li>
      <li><b>Scores.</b> The predicted margin comes from the ratings (so the predicted winner always matches the favourite). The predicted total comes from a second fit of how many combined points each team's games produce, starting from a 230-point league average. Score = (total ± margin) ÷ 2.</li>
      <li><b>Confidence.</b> Per-team 80% win ranges; ladder confidence measured inside the simulations; and an honest out-of-sample track record on games already played.</li>
      <li><b>Track records.</b> Walk-forward: every past game predicted using only earlier results (rest included; old injury reports aren't archived). Live: the exact prediction made before tip-off, frozen and scored afterwards. Both are compared with the betting market when ESPN publishes lines.</li>
      <li>Data: ESPN public scoreboard, injury report and player stats. Updated daily by GitHub Actions.</li>
    </ul>
    </details>
  </section>
</div>
<div id="tip"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const pct = (x, d=0) => x == null ? '–' : (x*100).toFixed(d) + '%';
const sgn = (x, d=1) => (x > 0 ? '+' : x < 0 ? '−' : '±') + Math.abs(x).toFixed(d);
const NAME = Object.fromEntries(D.teams.map(t => [t.abbr, t.name]));
const fmtDay = s => new Date(s + 'T12:00:00Z').toLocaleDateString('en-AU', {weekday:'short', day:'numeric', month:'short', timeZone:'UTC'});
const tip = $('tip');
function showTip(e, html){ tip.innerHTML = html; tip.style.opacity = 1;
  const x = Math.min(e.clientX + 14, innerWidth - 250); tip.style.left = x + 'px'; tip.style.top = (e.clientY + 14) + 'px'; }
function hideTip(){ tip.style.opacity = 0; }

// Header + KPIs
const upd = new Date(D.generated_at).toLocaleString('en-AU', {timeZone:'Australia/Melbourne', dateStyle:'medium', timeStyle:'short'});
$('sub').textContent = `2026–27 regular season · results through ${fmtDay(D.through)} (US) · ${D.games_played} of 1230 games played · updated ${upd} Melbourne time`;
const c = D.confidence, cp = D.confidence_prev, R = D.record;
const dc = c.within1 - cp.within1;
const kpis = [
  {lab:'Ladder confidence', val:pct(c.within1), foot:`teams expected within ±1 seed · <span class="${dc>=0?'up':'down'}">${dc>=0?'▲':'▼'} ${Math.abs(dc*100).toFixed(1)} pts</span> since last game day`},
  {lab:'Exact seed hit rate', val:pct(c.exact), foot:`expected share of teams in exactly their projected seed`},
  {lab:'Playoff field confidence', val:pct(c.playoff_field), foot:'chance the projected 16 playoff teams actually make it (avg)'},
  R ? {lab:'Game picks correct', val:pct(R.accuracy, 1), foot:`${R.n} games · last 7 game days ${pct(R.accuracy_7d)}`}
    : {lab:'Game picks correct', val:'–', foot:'no games played yet'},
  R ? {lab:'Brier score', val:R.brier.toFixed(3), foot:`coin flip 0.250 · preseason-only model ${R.brier_prior.toFixed(3)}`} : null,
  (() => { const f = [...D.teams].sort((a,b) => b.p_title - a.p_title)[0]; return {lab:'Title favourite', val:f.abbr + ' ' + pct(f.p_title), foot:`${f.name} · finals ${pct(f.p_finals)}`}; })(),
].filter(Boolean);
$('kpis').innerHTML = kpis.map(k => `<div class="kpi"><div class="lab">${k.lab}</div><div class="val num">${k.val}</div><div class="foot">${k.foot}</div></div>`).join('');

// Movers
const movers = [...D.teams].sort((a,b) => Math.abs(b.d_proj_w) - Math.abs(a.d_proj_w)).slice(0, 8);
$('moversNote').textContent = `Change in projected wins from ${fmtDay(D.previous)} to ${fmtDay(D.through)}, and the result that drove it.`;
$('movers').innerHTML = movers.map(t => {
  const why = t.latest.length ? t.latest.map(g => `${g.won ? 'Beat' : 'Lost to'} ${g.opp} ${g.score} ${g.home ? '(home)' : '(away)'} — had ${pct(g.pregame)} pre-game`).join('<br>')
                              : 'Didn\'t play — moved on other results';
  const cls = t.d_proj_w > 0 ? 'up' : t.d_proj_w < 0 ? 'down' : '';
  return `<div class="mover"><b>${t.name}</b><span class="d num ${cls}">${sgn(t.d_proj_w)} W</span>
    <div class="why">${why}</div><div class="why">Playoffs ${pct(t.p_playoffs)} (${sgn(t.d_playoffs*100,0)} pts) · seed ${t.seed}${t.d_seed ? ` (${t.d_seed>0?'▲':'▼'}${Math.abs(t.d_seed)})` : ''}</div></div>`;
}).join('');

// Ladder table
const css = getComputedStyle(document.documentElement);
const seqVar = p => p < .02 ? 'var(--seq-0)' : p < .08 ? 'var(--seq-1)' : p < .18 ? 'var(--seq-2)' : p < .32 ? 'var(--seq-3)' : p < .5 ? 'var(--seq-4)' : 'var(--seq-5)';
function rangeSvg(t){
  const W = 170, x = v => 4 + (v / 82) * (W - 8);
  return `<svg width="${W}" height="18" viewBox="0 0 ${W} 18" aria-hidden="true">
    <line x1="${x(0)}" x2="${x(82)}" y1="9" y2="9" stroke="var(--line)" stroke-width="2" stroke-linecap="round"/>
    <line x1="${x(41)}" x2="${x(41)}" y1="4" y2="14" stroke="var(--line)" stroke-width="1"/>
    <rect x="${x(t.lo)}" y="5" width="${Math.max(4, x(t.hi) - x(t.lo))}" height="8" rx="4" fill="var(--accent-soft)"/>
    <circle cx="${x(t.proj_w)}" cy="9" r="4.5" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/></svg>`;
}
let conf = 'East';
function drawLadder(){
  const rows = D.teams.filter(t => t.conf === conf).sort((a,b) => a.seed - b.seed);
  $('ladder').innerHTML = `<thead><tr><th>#</th><th>Team</th><th class="r">Now</th><th class="r">Proj W–L</th><th>80% win range</th>
    <th class="r">Playoffs</th><th class="r">Top 6</th><th class="r">Play-in</th><th class="r">Title</th><th>Seed odds 1 → 15</th><th class="r">Δ W</th></tr></thead><tbody>` +
  rows.map(t => `<tr class="${t.seed === 6 || t.seed === 10 ? 'cut' : ''}">
    <td class="seed num">${t.seed}</td>
    <td class="team"><b>${t.name}</b><span>${t.abbr}</span>${t.avail_now < -0.5 ? `<span class="tag inj" data-tip="Injuries cost ${Math.abs(t.avail_now).toFixed(1)} pts of rating right now">INJ ${t.avail_now.toFixed(1)}</span>` : ''}</td>
    <td class="r num">${t.w}–${t.l}</td>
    <td class="r num"><b>${t.proj_w.toFixed(1)}</b>–${(t.games - t.proj_w).toFixed(1)}</td>
    <td class="range" data-tip="${t.name}: ${t.lo}–${t.hi} wins (80% range), avg ${t.proj_w.toFixed(1)}">${rangeSvg(t)}</td>
    <td class="r num">${pct(t.p_playoffs)}</td><td class="r num">${pct(t.p_top6)}</td><td class="r num">${pct(t.p_playin)}</td><td class="r num" data-tip="2nd round ${pct(t.p_r2)} · conf finals ${pct(t.p_cf)} · finals ${pct(t.p_finals)}">${t.p_title < .005 && t.p_title > 0 ? '<1%' : pct(t.p_title)}</td>
    <td><div class="strip">${t.seed_p.map((p,i) => `<i style="background:${seqVar(p)}" data-tip="${t.abbr} · seed ${i+1}: ${pct(p,1)}"></i>`).join('')}</div></td>
    <td class="r num ${t.d_proj_w>0?'up':t.d_proj_w<0?'down':''}">${sgn(t.d_proj_w)}</td></tr>`).join('') + '</tbody>';
}
$('tabs').innerHTML = ['East','West'].map(c => `<button role="tab" aria-selected="${c===conf}" data-c="${c}">${c}ern Conference</button>`).join('');
$('tabs').addEventListener('click', e => { const b = e.target.closest('button'); if(!b) return; conf = b.dataset.c;
  [...$('tabs').children].forEach(x => x.setAttribute('aria-selected', x.dataset.c === conf)); drawLadder(); });
drawLadder();
document.addEventListener('mousemove', e => { const el = e.target.closest('[data-tip]'); if (el) showTip(e, el.dataset.tip); else if (!e.target.closest('#trend,#calib')) hideTip(); });

// Trend chart
(function(){
  const H = D.history, svg = $('trend'), W = 900, Ht = 260, m = {l:44, r:16, t:12, b:30};
  const n = H.length, x = i => m.l + (n <= 1 ? 0 : i / (n - 1)) * (W - m.l - m.r), y = v => m.t + (1 - v) * (Ht - m.t - m.b);
  let s = '';
  for (const v of [0, .25, .5, .75, 1]) s += `<line x1="${m.l}" x2="${W-m.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)" stroke-width="1"/><text x="${m.l-8}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="var(--muted)">${v*100}%</text>`;
  const step = Math.max(1, Math.ceil(n / 8));
  H.forEach((h, i) => { if (i % step === 0 || i === n-1) s += `<text x="${x(i)}" y="${Ht-8}" text-anchor="${i===n-1&&n>1?'end':i===0?'start':'middle'}" font-size="11" fill="var(--muted)">${i===0?'Preseason':fmtDay(h.date)}</text>`; });
  const path = (key) => { let d = '', pen = false; H.forEach((h,i) => { const v = h[key]; if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + x(i) + ' ' + y(v); pen = true; }); return d; };
  s += `<path d="${path('within1')}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>`;
  s += `<path d="${path('accuracy')}" fill="none" stroke="var(--series-2)" stroke-width="2" stroke-linejoin="round"/>`;
  const last = H[n-1];
  s += `<circle cx="${x(n-1)}" cy="${y(last.within1)}" r="4" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/>`;
  if (last.accuracy != null) s += `<circle cx="${x(n-1)}" cy="${y(last.accuracy)}" r="4" fill="var(--series-2)" stroke="var(--surface)" stroke-width="2"/>`;
  s += `<line id="xh" y1="${m.t}" y2="${Ht-m.b}" stroke="var(--muted)" stroke-width="1" opacity="0"/><rect x="${m.l}" y="0" width="${W-m.l-m.r}" height="${Ht}" fill="transparent" id="hit"/>`;
  svg.innerHTML = s;
  const xh = svg.querySelector('#xh');
  svg.querySelector('#hit').addEventListener('mousemove', e => {
    const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) / r.width * W;
    const i = Math.max(0, Math.min(n-1, Math.round((px - m.l) / ((W - m.l - m.r) / Math.max(1, n-1)))));
    xh.setAttribute('x1', x(i)); xh.setAttribute('x2', x(i)); xh.setAttribute('opacity', .6);
    const h = H[i];
    showTip(e, `<b>${i===0?'Preseason':fmtDay(h.date)}</b> · ${h.games} games<br>Ladder confidence ${pct(h.within1,1)}<br>Exact seed ${pct(h.exact,1)}<br>Pick accuracy ${pct(h.accuracy,1)}`);
  });
  svg.querySelector('#hit').addEventListener('mouseleave', () => { xh.setAttribute('opacity', 0); hideTip(); });
})();

// Track record + calibration
(function(){
  if (!R) { $('record').innerHTML = '<p class="note">Appears after the first game day.</p>'; return; }
  $('record').innerHTML = `<div class="legend" style="gap:22px">
    <div><div class="note" style="margin:0">Games</div><b class="num">${R.n}</b></div>
    <div><div class="note" style="margin:0">Correct</div><b class="num">${pct(R.accuracy,1)}</b></div>
    <div><div class="note" style="margin:0">Brier</div><b class="num">${R.brier.toFixed(3)}</b></div>
    <div><div class="note" style="margin:0">Log loss</div><b class="num">${R.log_loss.toFixed(3)}</b></div></div>
    <div class="legend" style="gap:22px;margin-top:10px">
    <div><div class="note" style="margin:0">Avg miss per team score</div><b class="num">${R.scores.team_mae} pts</b></div>
    <div><div class="note" style="margin:0">Avg miss on margin</div><b class="num">${R.scores.margin_mae} pts</b></div>
    <div><div class="note" style="margin:0">Avg miss on total</div><b class="num">${R.scores.total_mae} pts</b></div>
    <div><div class="note" style="margin:0">Scores within 10</div><b class="num">${pct(R.scores.within10)}</b></div></div>
    ${D.live_record ? `<div class="legend" style="gap:22px;margin-top:10px">
      <div><div class="note" style="margin:0">Live picks (made pre-tip, with injuries)</div><b class="num">${pct(D.live_record.accuracy,1)} of ${D.live_record.n}</b></div>
      <div><div class="note" style="margin:0">Live Brier</div><b class="num">${D.live_record.brier.toFixed(3)}</b></div></div>` : ''}
    ${(D.live_record && D.live_record.market) || R.market ? (() => { const M = (D.live_record && D.live_record.market) || R.market;
      return `<p class="note"><b>vs the betting market</b> (${M.model.n} games with a line): model Brier ${M.model.brier.toFixed(3)} vs market ${M.market.brier.toFixed(3)} · picks ${pct(M.model.accuracy)} vs ${pct(M.market.accuracy)}. ${M.model.brier < M.market.brier ? 'The model is beating the market so far.' : 'The market is ahead so far — normal; beating it is hard.'}
      ${M.disagree ? `<br>Where they disagree by 5+ pts (${M.disagree.n} games): model Brier ${M.disagree.model_brier.toFixed(3)} vs market ${M.disagree.market_brier.toFixed(3)}; when they picked different winners the model was right ${M.disagree.model_right} of ${M.disagree.different_pick}.` : ''}</p>`; })() : '<p class="note">Betting-market comparison appears once ESPN publishes lines for enough games.</p>'}
    <p class="note">Score predictions vs a naive "every team scores ${(230/2).toFixed(0)}" guess: ${R.scores.naive_team_mae} pts avg miss.</p>
    <p class="note">Calibration: when the model gives its favourite X%, how often do they win? Dots on the diagonal = well calibrated. Dot size = number of games.</p>`;
  const svg = $('calib'), W = 420, H = 240, m = {l:44, r:12, t:10, b:30};
  const x = v => m.l + (v - .5) / .5 * (W - m.l - m.r), y = v => m.t + (1 - v) * (H - m.t - m.b);
  let s = '';
  for (const v of [0, .25, .5, .75, 1]) s += `<line x1="${m.l}" x2="${W-m.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${m.l-8}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="var(--muted)">${v*100}%</text>`;
  for (const v of [.5, .6, .7, .8, .9, 1]) s += `<text x="${x(v)}" y="${H-10}" text-anchor="middle" font-size="11" fill="var(--muted)">${v*100}%</text>`;
  s += `<line x1="${x(.5)}" y1="${y(.5)}" x2="${x(1)}" y2="${y(1)}" stroke="var(--muted)" stroke-dasharray="4 4"/>`;
  const maxN = Math.max(...R.calibration.map(b => b.n));
  R.calibration.forEach(b => { const r = 4 + 8 * Math.sqrt(b.n / maxN);
    s += `<circle cx="${x(b.pred)}" cy="${y(b.actual)}" r="${r}" fill="var(--accent)" stroke="var(--surface)" stroke-width="2" data-tip="Model said ${pct(b.pred,0)} → favourites won ${pct(b.actual,0)} (${b.n} games)"/>`; });
  svg.innerHTML = s;
})();

// Backtest
(function(){
  const B = D.backtest;
  const rv = B && B.tuned ? B.tuned : null;
  if (rv) $('restVals').textContent = `back-to-back ${rv.REST_B2B}, extra for 3-in-4 ${rv.REST_3IN4}, 2+ days off +${rv.REST_LONG} pts`;
  if (!B) { $('btNote').textContent = 'Run backtest.py to generate.'; return; }
  const t = B.test_tuned, d0 = B.test_default, po = B.preseason_only_test;
  $('btNote').textContent = `Tuned on ${B.train.join(' + ')}, tested on ${B.test} (${t.n} games the tuning never saw). Using: ${B.adopted} settings.`;
  $('btKpis').innerHTML = [
    {lab:`${B.test} picks correct`, val:pct(t.accuracy,1), foot:`untuned model ${pct(d0.accuracy,1)} · preseason lines only ${pct(po.accuracy,1)}`},
    {lab:`${B.test} Brier score`, val:t.brier.toFixed(3), foot:`untuned ${d0.brier.toFixed(3)} · preseason lines only ${po.brier.toFixed(3)} · coin flip 0.250`},
    {lab:`${B.test} log loss`, val:t.log_loss.toFixed(3), foot:`untuned ${d0.log_loss.toFixed(3)}`},
    {lab:'Avg miss on margin', val:t.margin_mae.toFixed(1) + ' pts', foot:`untuned ${d0.margin_mae.toFixed(1)} pts`},
  ].map(k => `<div class="kpi"><div class="lab">${k.lab}</div><div class="val num" style="font-size:24px">${k.val}</div><div class="foot">${k.foot}</div></div>`).join('');
  $('btCov').innerHTML = `<thead><tr><th>Projected at</th><th class="r">Inside 80% range</th><th class="r">±1 seed: expected</th><th class="r">actual</th><th class="r">Avg win error</th></tr></thead><tbody>` +
    B.coverage_test.map(c => `<tr><td>${c.checkpoint}</td><td class="r num">${pct(c.coverage80)}</td><td class="r num">${pct(c.pred_within1)}</td><td class="r num">${pct(c.real_within1)}</td><td class="r num">${c.mean_abs_win_err.toFixed(1)}</td></tr>`).join('') + '</tbody>';
  const sets = {'This season': D.segments || [], [B.test + ' backtest']: B.segments_test || []};
  let cur = (D.segments || []).length && D.games_played >= 300 ? 'This season' : B.test + ' backtest';
  function draw(){
    [...$('segTabs').children].forEach(b => b.setAttribute('aria-selected', b.dataset.k === cur));
    $('segSrc').textContent = cur === 'This season' && D.games_played < 300 ? 'Small sample so far — treat as noisy.' : '';
    $('segTbl').innerHTML = `<thead><tr><th>Situation</th><th class="r">Games</th><th class="r">Predicted</th><th class="r">Actual</th><th class="r">Brier</th></tr></thead><tbody>` +
      sets[cur].map(r => { const gap = r.accuracy - r.pred;
        return `<tr><td>${r.segment}</td><td class="r num">${r.n}</td><td class="r num">${pct(r.pred)}</td><td class="r num ${Math.abs(gap) >= .04 && r.n >= 50 ? (gap > 0 ? 'up' : 'down') : ''}">${pct(r.accuracy)}</td><td class="r num">${r.brier.toFixed(3)}</td></tr>`; }).join('') + '</tbody>';
  }
  $('segTabs').innerHTML = Object.keys(sets).map(k => `<button role="tab" data-k="${k}">${k}</button>`).join('');
  $('segTabs').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { cur = b.dataset.k; draw(); } });
  draw();
})();
// Playoff & title odds table
(function(){
  const top = [...D.teams].sort((a,b) => b.p_title - a.p_title).slice(0, 12), mx = top[0].p_title || 1;
  $('title').innerHTML = `<thead><tr><th>Team</th><th class="r">Playoffs</th><th class="r">2nd rd</th><th class="r">Conf F</th><th class="r">Finals</th><th>Title</th></tr></thead><tbody>` +
    top.map(t => `<tr><td class="team"><b>${t.abbr}</b><span>${t.conf}</span></td><td class="r num">${pct(t.p_playoffs)}</td><td class="r num">${pct(t.p_r2)}</td>
      <td class="r num">${pct(t.p_cf)}</td><td class="r num">${pct(t.p_finals)}</td>
      <td><div class="hbar"><i style="width:${Math.round(90 * t.p_title / mx)}px"></i><span class="num">${pct(t.p_title,1)}</span></div></td></tr>`).join('') + '</tbody>';
  const A = D.absences || [];
  $('inj').innerHTML = A.length ? `<thead><tr><th>Team</th><th>Player</th><th>Status</th><th>Until</th><th class="r">Effect</th></tr></thead><tbody>` +
    A.slice(0, 15).map(a => `<tr><td><b>${a.team}</b></td><td data-tip="Full-strength impact ${a.impact.toFixed(1)} pts · played ${pct(a.share)} of team games · ${a.detail}">${a.name}</td>
      <td>${a.status}</td><td class="num">${fmtDay(a.until)}</td><td class="r num down">−${a.effect.toFixed(1)}</td></tr>`).join('') + '</tbody>'
    : '<tbody><tr><td class="note">No significant absences on the current report.</td></tr></tbody>';
})();
// Injuries per team on a date
function injOf(team, d){
  const rows = (D.absences || []).filter(a => a.team === team && D.today <= d && d < a.until);
  if (!rows.length) return null;
  return {pts: Math.min(10, rows.reduce((s, a) => s + a.effect, 0)), names: rows.map(a => `${a.name} (${a.status})`).join(', ')};
}
// Latest results + score predictions
function card(g, done){
  const homeFav = g.p_home >= .5, ph = g.p_home, pa = 1 - g.p_home;
  const rows = [[g.away, g.pred_as, g.as, pa, !homeFav, g.b2b_away, injOf(g.away, g.date)],
                [g.home, g.pred_hs, g.hs, ph, homeFav, g.b2b_home, injOf(g.home, g.date)]];
  const body = rows.map(([ab, pred, act, p, fav, b2b, inj]) => {
    const win = done ? (act === Math.max(g.hs, g.as)) : fav;
    const tags = done ? '' : (b2b ? '<span class="tag" data-tip="Second night of a back-to-back">B2B</span>' : '') +
      (fav && g.disagree ? `<span class="tag" style="color:var(--series-2);border-color:currentColor" data-tip="Model ${pct(p)} vs market ${pct(ab===g.home?g.market_p:1-g.market_p)} — 5+ pt disagreement">≠ mkt</span>` : '') +
      (inj && inj.pts > 0.3 ? `<span class="tag inj" data-tip="Out/limited: ${inj.names}">−${inj.pts.toFixed(1)}</span>` : '');
    return `<div class="row ${win?'win':''}"><span class="ab">${ab}</span>
      ${done ? `<span class="pt">${act}</span><span class="pr">pred ${pred}</span>` : `<span class="pt">${pred}</span>${tags}<span class="pr">${pct(p)}</span>`}</div>`;
  }).join('');
  const bar = `<div class="bar"><i style="width:${pa*100}%;background:${homeFav?'var(--accent-soft)':'var(--accent)'}"></i><i style="flex:1;background:${homeFav?'var(--accent)':'var(--accent-soft)'}"></i></div>`;
  let foot;
  if (done) {
    const ok = (g.p_home >= .5) === g.home_won;
    const miss = (Math.abs(g.pred_hs - g.hs) + Math.abs(g.pred_as - g.as)) / 2;
    foot = `<span class="${ok?'ok':'miss'}">${ok?'✓':'✗'} picked ${homeFav?g.home:g.away} (${pct(Math.max(ph,pa))})</span><span>off by ${miss.toFixed(1)}/team</span>`;
  } else {
    const m = Math.abs(g.pred_hs - g.pred_as), tot = g.pred_hs + g.pred_as;
    foot = `<span>${homeFav?g.home:g.away} by ${m || '<1'}</span><span>total ${tot}</span>`;
    if (g.line || g.market_p != null) foot += `</div><div class="foot"><span>Line: ${g.line || '–'}${g.ou ? ' · O/U ' + g.ou : ''}</span><span>${g.market_p != null ? 'market ' + pct(homeFav ? g.market_p : 1 - g.market_p) : ''}</span>`;
  }
  return `<div class="sg">${body}${done ? '' : bar}<div class="foot">${foot}</div></div>`;
}
$('lastTitle').textContent = `Results on ${fmtDay(D.through)} vs the model`;
$('lastGames').innerHTML = D.latest_games.map(g => card(g, true)).join('') || '<p class="note">No games yet.</p>';
const days = [...new Set(D.next_games.map(g => g.date))];
let day = days[0];
function drawDay(){
  [...$('dayTabs').children].forEach(b => b.setAttribute('aria-selected', b.dataset.d === day));
  $('nextGames').innerHTML = D.next_games.filter(g => g.date === day).map(g => card(g, false)).join('') || '<p class="note">Regular season complete.</p>';
}
$('dayTabs').innerHTML = days.map(d => `<button role="tab" data-d="${d}">${fmtDay(d)}</button>`).join('');
$('dayTabs').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { day = b.dataset.d; drawDay(); } });
drawDay();
</script>
</body>
</html>
"""


def render(out):
    data = json.dumps(out, separators=(",", ":")).replace("</", "<\\/")
    return (TEMPLATE.replace("__DATA__", data).replace("__SIMS__", f"{out['n_sims']:,}")
            .replace("__SIGMA__", f"{out['sigma']:.1f}").replace("__HCA__", f"{out['hca']:.1f}"))
