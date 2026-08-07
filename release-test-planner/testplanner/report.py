# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Stage 7: render the self-contained HTML dashboard.

One file, no dependencies, no server. The payload is embedded as JSON so the
report can be attached to a release ticket and still work.
"""

from __future__ import annotations

import json

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fenix Release Test Plan</title>
<style>
:root {
  color-scheme: light;
  --surface-1: #fcfcfb;
  --plane: #f9f9f7;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --baseline: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6;
  --series-2: #eb6834;
  --good: #0ca30c;
  --warning: #fab219;
  --critical: #d03b3b;
  --success-text: #006300;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --surface-1: #1a1a19;
    --plane: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --baseline: #383835;
    --border: rgba(255,255,255,0.10);
    --series-1: #3987e5;
    --series-2: #d95926;
    --success-text: #0ca30c;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1: #1a1a19;
  --plane: #0d0d0d;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --muted: #898781;
  --grid: #2c2c2a;
  --baseline: #383835;
  --border: rgba(255,255,255,0.10);
  --series-1: #3987e5;
  --series-2: #d95926;
  --success-text: #0ca30c;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 32px 28px 80px;
  background: var(--plane);
  color: var(--text-primary);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 1180px; margin: 0 auto; }

header { display: flex; justify-content: space-between; align-items: flex-start;
  gap: 24px; margin-bottom: 28px; flex-wrap: wrap; }
h1 { font-size: 22px; margin: 0 0 6px; letter-spacing: -0.01em; }
.sub { color: var(--text-secondary); font-size: 13px; }
.sub code { background: var(--surface-1); border: 1px solid var(--border);
  padding: 1px 6px; border-radius: 4px; font-size: 12px; }

button.theme { background: var(--surface-1); color: var(--text-secondary);
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 13px;
  cursor: pointer; font-size: 13px; font-family: inherit; }
button.theme:hover { color: var(--text-primary); }

section { background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 12px; padding: 22px 24px; margin-bottom: 20px; }
h2 { font-size: 15px; margin: 0 0 4px; letter-spacing: -0.005em; }
.note { color: var(--text-secondary); font-size: 12.5px; margin: 0 0 18px;
  max-width: 78ch; }

/* KPI row */
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px,1fr));
  gap: 1px; background: var(--border); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden; margin-bottom: 20px; }
.kpi { background: var(--surface-1); padding: 18px 20px; }
.kpi .label { font-size: 11.5px; color: var(--muted); text-transform: uppercase;
  letter-spacing: 0.055em; margin-bottom: 8px; }
.kpi .value { font-size: 30px; line-height: 1.1; font-weight: 600;
  letter-spacing: -0.02em; }
.kpi .value.sm { font-size: 22px; }
.kpi .foot { font-size: 12px; color: var(--text-secondary); margin-top: 6px; }
.hero .value { font-size: 42px; }

/* chart */
.legend { display: flex; gap: 20px; margin-bottom: 16px; font-size: 12.5px;
  color: var(--text-secondary); flex-wrap: wrap; }
.legend span { display: inline-flex; align-items: center; gap: 7px; }
.swatch { width: 11px; height: 11px; border-radius: 3px; display: inline-block; }

.bars { display: flex; flex-direction: column; gap: 9px; }
.bar-row { display: grid; grid-template-columns: 210px 1fr 84px; gap: 14px;
  align-items: center; }
.bar-name { font-size: 12.5px; color: var(--text-secondary); text-align: right;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.track { height: 20px; display: flex; background: transparent; }
.seg { height: 100%; }
.seg.removed { background: var(--series-1); border-radius: 4px 0 0 4px; }
.seg.residual { background: var(--series-2); border-radius: 0 4px 4px 0;
  margin-left: 2px; }
.seg.removed.full { border-radius: 4px; }
.seg.residual.full { border-radius: 4px; margin-left: 0; }
.bar-val { font-size: 12.5px; color: var(--text-secondary);
  font-variant-numeric: tabular-nums; }
.bar-row:hover .bar-name, .bar-row:hover .bar-val { color: var(--text-primary); }

/* tables */
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; font-size: 11.5px; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--muted); font-weight: 600;
  padding: 0 10px 9px; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
td { padding: 9px 10px; border-bottom: 1px solid var(--grid);
  vertical-align: top; }
tbody tr:hover { background: var(--plane); }
td.feat { font-weight: 500; }
.dim { color: var(--text-secondary); font-size: 12px; }

.badge { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px;
  font-weight: 600; white-space: nowrap; }
.badge .dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.badge.good .dot { background: var(--good); }
.badge.warning .dot { background: var(--warning); }
.badge.critical .dot { background: var(--critical); }

.meter { display: inline-flex; gap: 2px; vertical-align: middle;
  margin-right: 7px; }
.meter i { width: 5px; height: 11px; border-radius: 1px;
  background: var(--grid); display: block; }
.meter i.on { background: var(--series-1); }

h3 { font-size: 13.5px; margin: 0 0 6px; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 26px;
  margin-bottom: 20px; }
.split .note { margin-bottom: 0; }
@media (max-width: 820px) { .split { grid-template-columns: 1fr; } }

.cmp { display: flex; flex-direction: column; gap: 9px; margin-bottom: 22px; }
.cmp-row { display: grid; grid-template-columns: 150px 1fr 128px; gap: 14px;
  align-items: center; }
.cmp-bar { height: 20px; background: var(--series-1); border-radius: 4px; }
.cmp-bar.muted { background: var(--baseline); }

.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px,1fr));
  gap: 14px; margin-bottom: 6px; }
.card { border: 1px solid var(--border); border-radius: 10px; padding: 15px 16px; }
.card .hd { display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 10px; gap: 8px; }
.card .big { font-size: 25px; font-weight: 600; letter-spacing: -0.02em; }
.card .cap { font-size: 11.5px; color: var(--muted); text-transform: uppercase;
  letter-spacing: 0.05em; }
.card p { font-size: 12px; color: var(--text-secondary); margin: 8px 0 0; }
.check { font-size: 11.5px; font-weight: 600; display: inline-flex;
  align-items: center; gap: 5px; }
.check .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--good); }

.src { display: inline-block; font-size: 10.5px; font-weight: 600;
  letter-spacing: 0.04em; text-transform: uppercase; padding: 1px 6px;
  border-radius: 4px; border: 1px solid var(--border); color: var(--text-secondary); }
.src.parsed { border-color: var(--good); color: var(--success-text); }

.warn { border: 1px solid var(--critical); border-left-width: 4px;
  border-radius: 10px; padding: 14px 16px; margin-bottom: 20px;
  background: var(--surface-1); }
.warn .hd { font-weight: 700; font-size: 13.5px; margin-bottom: 6px;
  display: flex; align-items: center; gap: 7px; }
.warn .hd .dot { width: 9px; height: 9px; border-radius: 50%;
  background: var(--critical); flex: none; }
.warn p { font-size: 12.5px; color: var(--text-secondary); margin: 0 0 6px; }
.warn pre { margin-top: 8px; }

.mtx { font-size: 12px; }
.mtx td { padding: 6px 9px; }
.mtx td.cfg { font-variant-numeric: tabular-nums; color: var(--muted); }

details { border-top: 1px solid var(--grid); padding: 11px 0 3px; }
details:first-of-type { border-top: none; }
summary { cursor: pointer; font-size: 13px; font-weight: 500; }
summary::marker { color: var(--muted); }
details .body { padding: 10px 0 6px 18px; font-size: 12.5px;
  color: var(--text-secondary); }
pre { background: var(--plane); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; overflow-x: auto; font-size: 12px;
  margin: 8px 0 0; }
.tag { display: inline-block; background: var(--plane); border: 1px solid var(--border);
  border-radius: 5px; padding: 1px 7px; font-size: 11px; color: var(--text-secondary);
  margin-right: 5px; font-variant-numeric: tabular-nums; }
.empty { color: var(--text-secondary); font-size: 13px; font-style: italic; }
.toggle-tbl { background: none; border: none; color: var(--series-1);
  font: inherit; font-size: 12.5px; cursor: pointer; padding: 0; margin-top: 14px; }
</style>
</head>
<body>
<div class="wrap">

<header>
  <div>
    <h1>Fenix Release Test Plan</h1>
    <div class="sub" id="meta"></div>
  </div>
  <button class="theme" id="themeBtn">Toggle theme</button>
</header>

<div id="warnings"></div>

<div class="kpis" id="kpis"></div>

<section>
  <h2>Where the risk goes</h2>
  <p class="note">Each bar is one feature's <strong>inherent risk</strong>
  (Severity x Occurrence x 10, the risk if we shipped with no testing at all).
  The blue portion is what the planned automated tests remove; the orange
  portion survives the run and is what a release decision actually rides on.</p>
  <div class="legend">
    <span><i class="swatch" style="background:var(--series-1)"></i>
      Risk removed by planned automation</span>
    <span><i class="swatch" style="background:var(--series-2)"></i>
      Residual risk after the run</span>
  </div>
  <div class="bars" id="chart"></div>
  <button class="toggle-tbl" id="tblBtn">Show as table</button>
  <div id="chartTable" hidden></div>
</section>

<section>
  <h2>FMEA risk register</h2>
  <p class="note">RPN = Severity x Occurrence x Detection (IEC 60812). Detection
  is inverted coverage: 10 means a defect would almost certainly escape to
  release, 2 means our automation would very likely catch it. Thresholds follow
  conventional AIAG practice - 200+ demands action, 100+ demands review.</p>
  <table id="fmea"></table>
</section>

<section>
  <h2>Recommended test run</h2>
  <p class="note" id="planNote"></p>
  <table id="plan"></table>
</section>

<section>
  <h2>Generated-test candidate space</h2>
  <p class="note">The efficiency framework does not only hold hand-written
  tests. Factories under <code>generation/</code> synthesise cases from the
  page-object model, and they scale combinatorially. This is the catalogue the
  planner filters - risk is what turns it into a run list.</p>
  <table id="factories"></table>
  <div id="factoryNote"></div>
</section>

<section id="testrailSection" style="display:none">
  <h2>TestRail case set &mdash; an assumed denominator</h2>
  <p class="note">The factory space above is <em>derived</em>: it is computed by
  enumerating what the page-object model can reach. The TestRail case set is
  <em>assumed</em> &mdash; someone decided each case was worth writing, which
  makes it a statement of intent about what a release needs, but not a complete
  map of the app. It answers "how much of the plan we wrote down is automated",
  never "how much of the app is covered". The join is exact rather than
  heuristic: both codebases already carry the case id above each test.</p>
  <table id="testrailTotals"></table>
  <div id="testrailNote"></div>
  <table id="testrailPerFeature"></table>
</section>

<section>
  <h2>Combinatorial matrix</h2>
  <p class="note">A test is not one thing - it is a test run in a configuration.
  Every feature multiplies out against devices, API levels and product state,
  and the full cross product is unaffordable. Two standard reductions, and the
  gap between them is the whole argument for picking the right one:</p>

  <div class="split">
    <div>
      <h3>Orthogonal array</h3>
      <p class="note">Every pair of levels appears <em>exactly</em> the same
      number of times. That balance is what lets you attribute an effect to a
      factor - it is a design for <strong>analysis</strong>, from Taguchi's
      design of experiments. Balance costs runs, and strength-2 arrays only
      exist for particular level structures.</p>
    </div>
    <div>
      <h3>Covering array</h3>
      <p class="note">Every pair appears <em>at least</em> once. Dropping
      balance makes it markedly smaller and lets it take any mix of level
      counts. It is a design for <strong>detection</strong> - generated here
      with IPOG, the algorithm behind NIST's ACTS, and the form used for
      large-scale combinatorial test selection.</p>
    </div>
  </div>

  <div id="matrixCompare"></div>
  <div id="matrixDesigns"></div>

  <h3 style="margin-top:26px">Allocation by risk band</h3>
  <p class="note">How much matrix a feature earns is a function of its FMEA
  band. Spending 3-way coverage everywhere is how a matrix becomes
  unaffordable; spending a single config on an action-required feature is how a
  release ships broken.</p>
  <table id="matrixAlloc"></table>

  <h3 style="margin-top:26px">The review-band matrix, in full</h3>
  <p class="note">This is the artifact a test lead would actually review - the
  pairwise configurations every review-band feature runs against.</p>
  <div id="matrixTable"></div>
</section>

<section>
  <h2>Coverage gaps - manual testing required</h2>
  <p class="note">Risk that survives running every automated test we own. This
  is the scope that has to be covered by hand, or accepted explicitly.</p>
  <div id="gaps"></div>
</section>

<section>
  <h2>Open questions for an agent</h2>
  <p class="note">The pipeline is deterministic and stops where judgement
  starts. These are the calls it will not make on its own. Answer them into a
  JSON file and re-run with <code>--answers</code> to fold them back in.</p>
  <div id="tasks"></div>
</section>

</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
/* Data source, in priority order:
   1. report.json sitting next to this file - so `testplanner serve` gives a
      plain browser refresh instead of regenerating the HTML.
   2. the copy embedded below - so the file still works from file:// and can be
      dropped onto a static host on its own.
   Never both, and the header says which one won. */
const EMBEDDED = JSON.parse(document.getElementById('payload').textContent);
let D = EMBEDDED;
let SOURCE = 'snapshot';

async function boot() {
  // Paint the embedded copy first. Under `serve --live` the fetch below kicks
  // off a full pipeline re-run server-side, which takes seconds - without this
  // the page would sit blank until it finished.
  render();
  try {
    const res = await fetch('report.json?t=' + Date.now(), { cache: 'no-store' });
    if (res.ok) {
      D = await res.json();
      SOURCE = 'live';
      render();
    }
  } catch (e) {
    /* file:// or no sibling report.json - the embedded copy is correct. */
  }
}

function render() {
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct = n => (n * 100).toFixed(1) + '%';

const BANDS = {
  'action-required': ['critical', 'Action required'],
  'review':          ['warning',  'Review'],
  'acceptable':      ['good',     'Acceptable'],
};
const badge = b => {
  const [cls, label] = BANDS[b] || ['good', b];
  return `<span class="badge ${cls}"><i class="dot"></i>${label}</span>`;
};
const TIERS = ['none','disabled-only','thin','moderate','good','deep'];
const meter = tier => {
  const n = TIERS.indexOf(tier) + 1;
  let s = '<span class="meter" role="img" aria-label="coverage ' + esc(tier) + '">';
  for (let i = 0; i < 6; i++) s += `<i class="${i < n ? 'on' : ''}"></i>`;
  return s + '</span>';
};

/* meta */
document.getElementById('meta').innerHTML =
  `range <code>${esc(D.meta.range)}</code> &middot; ` +
  `${D.changes.commit_count} commits &middot; ${D.changes.file_count} files &middot; ` +
  `${D.changes.total_churn.toLocaleString()} lines churned &middot; ` +
  `${D.risk.totals.features_touched} features touched` +
  (SOURCE === 'live'
    ? ` &middot; <span class="src parsed">live</span> reading report.json`
    : ` &middot; <span class="src">snapshot</span> embedded copy`);

/* warnings - these travel with the file, so a report generated against the
   wrong tree says so wherever it ends up */
document.getElementById('warnings').innerHTML = D.meta.tree_mismatch_tip
  ? `<div class="warn">
      <div class="hd"><i class="dot"></i>These numbers are not trustworthy</div>
      <p>The checkout used to generate this report does not contain the code
      being analysed &mdash; range tip <code>${esc(D.meta.tree_mismatch_tip)}</code>
      is not an ancestor of its <code>HEAD</code>. Churn was scored against a
      different revision's tests, so coverage and confidence are wrong, and
      usually overstated.</p>
      <p>Regenerate from a worktree of the branch being analysed:</p>
      <pre>git worktree add --no-checkout ../firefox-beta origin/beta
cd ../firefox-beta &amp;&amp; git sparse-checkout set mobile/android/fenix &amp;&amp; git checkout
./plan.py analyze --repo ../firefox-beta --range "${esc(D.meta.range)}"</pre>
    </div>`
  : '';

/* KPIs */
const P = D.plan.totals, R = D.risk.totals;
document.getElementById('kpis').innerHTML = [
  `<div class="kpi hero"><div class="label">Release confidence</div>
    <div class="value">${pct(P.release_confidence)}</div>
    <div class="foot">of inherent risk removed by the planned run</div></div>`,
  `<div class="kpi"><div class="label">Residual RPN</div>
    <div class="value">${P.residual_rpn.toLocaleString()}</div>
    <div class="foot">of ${P.inherent_rpn.toLocaleString()} inherent</div></div>`,
  `<div class="kpi"><div class="label">Action required</div>
    <div class="value">${R.action_required}</div>
    <div class="foot">features with RPN &ge; 200</div></div>`,
  `<div class="kpi"><div class="label">Coverage gaps</div>
    <div class="value">${P.features_with_gaps}</div>
    <div class="foot">need manual testing</div></div>`,
  `<div class="kpi"><div class="label">Planned run</div>
    <div class="value sm">${D.plan.estimated_hours} h</div>
    <div class="foot">${D.plan.selected_count} tests &middot; ${D.plan.redundant_count} skipped as redundant</div></div>`,
  `<div class="kpi"><div class="label">Across the matrix</div>
    <div class="value sm">${D.matrix.totals.est_hours} h</div>
    <div class="foot">${D.matrix.totals.executions} executions &middot; ${D.matrix.totals.matrix_multiplier}&times; the single-config run</div></div>`,
].join('');

/* chart */
const rows = D.plan.per_feature.filter(r => r.baseline_rpn > 0).slice(0, 18);
const max = Math.max(...rows.map(r => r.baseline_rpn), 1);
document.getElementById('chart').innerHTML = rows.map(r => {
  const removedW = (r.rpn_removed / max) * 100;
  const residW = (r.residual_rpn / max) * 100;
  const noneRemoved = r.rpn_removed === 0, noneResid = r.residual_rpn === 0;
  const tip = `${r.name}: inherent ${r.baseline_rpn}, removed ${r.rpn_removed}, `
    + `residual ${r.residual_rpn} (S${r.severity} x O${r.occurrence}), `
    + `${r.planned_tests} tests planned`;
  return `<div class="bar-row" title="${esc(tip)}">
    <div class="bar-name">${esc(r.name)}</div>
    <div class="track">
      ${noneRemoved ? '' : `<div class="seg removed ${noneResid ? 'full' : ''}" style="width:${removedW}%"></div>`}
      ${noneResid ? '' : `<div class="seg residual ${noneRemoved ? 'full' : ''}" style="width:${residW}%"></div>`}
    </div>
    <div class="bar-val">${r.residual_rpn} left</div>
  </div>`;
}).join('');

document.getElementById('chartTable').innerHTML =
  '<table><thead><tr><th>Feature</th><th class="num">Inherent</th>' +
  '<th class="num">Removed</th><th class="num">Residual</th></tr></thead><tbody>' +
  rows.map(r => `<tr><td>${esc(r.name)}</td><td class="num">${r.baseline_rpn}</td>
    <td class="num">${r.rpn_removed}</td><td class="num">${r.residual_rpn}</td></tr>`).join('') +
  '</tbody></table>';

document.getElementById('tblBtn').onclick = e => {
  const t = document.getElementById('chartTable');
  t.hidden = !t.hidden;
  e.target.textContent = t.hidden ? 'Show as table' : 'Hide table';
};

/* FMEA */
document.getElementById('fmea').innerHTML =
  `<thead><tr>
    <th>Feature</th><th class="num">S</th><th class="num">O</th><th class="num">D</th>
    <th class="num">RPN</th><th>Band</th><th>Coverage</th>
    <th class="num" title="Directly bound tests. '+n off' are disabled; '+n inc' only pass through the feature and are not counted as coverage.">Tests</th>
    <th class="num">Churn</th><th class="num">CRAP</th>
  </tr></thead><tbody>` +
  D.risk.rows.map(r => `<tr>
    <td class="feat">${esc(r.name)}
      <div class="dim">${esc(r.occurrence_basis)}${r.backout_touched ? ' &middot; touched by a backout' : ''}</div></td>
    <td class="num">${r.severity}</td>
    <td class="num">${r.occurrence}</td>
    <td class="num">${r.detection}</td>
    <td class="num"><strong>${r.rpn}</strong></td>
    <td>${badge(r.band)}</td>
    <td>${meter(r.coverage_tier)}<span class="dim">${esc(r.coverage_tier)}</span></td>
    <td class="num">${r.direct_count}${r.disabled_count ? ` <span class="dim">+${r.disabled_count} off</span>` : ''}${r.incidental_count ? ` <span class="dim">+${r.incidental_count} inc</span>` : ''}</td>
    <td class="num">${r.churned_lines.toLocaleString()}</td>
    <td class="num">${r.crap_score}</td>
  </tr>`).join('') + '</tbody>';

/* plan */
document.getElementById('planNote').innerHTML =
  `Greedy budgeted selection: tests ordered by RPN removed per device-minute. ` +
  `<strong>${D.plan.selected_count}</strong> tests, ~<strong>${D.plan.estimated_minutes} min</strong>` +
  (D.plan.budget_minutes ? ` against a ${D.plan.budget_minutes} min budget` : ' (unbudgeted)') +
  `. ${D.plan.redundant_count} further bound tests were skipped because they ` +
  `removed no additional risk.`;

document.getElementById('plan').innerHTML =
  `<thead><tr><th>Test</th><th>Suite</th><th>Covers</th>
   <th class="num">RPN removed</th><th class="num">Min</th></tr></thead><tbody>` +
  D.plan.selected.slice(0, 60).map(t => `<tr>
    <td class="feat">${esc(t.name)}
      <div class="dim">${esc(t.class_name)}${t.is_smoke ? ' &middot; smoke' : ''}${t.testrail_id ? ' &middot; C' + esc(t.testrail_id) : ''}</div></td>
    <td class="dim">${esc(t.suite)}</td>
    <td class="dim">${t.covers_features.map(f => `<span class="tag">${esc(f)}</span>`).join('')}</td>
    <td class="num">${t.rpn_removed}</td>
    <td class="num">${t.cost_minutes}</td>
  </tr>`).join('') + '</tbody>';

/* factories */
const F = D.factories;
if (!F.factories.length) {
  /* A platform with no factory framework. Not a gap to fill with an estimate:
     the candidate space is what gives coverage a derived denominator, so
     inventing one here would fabricate the number the model rests on. */
  document.getElementById('factories').innerHTML =
    `<thead><tr><th>Generated-test candidate space</th></tr></thead><tbody><tr>
      <td class="dim">Not available on ${esc(D.meta.platform_label || D.meta.platform || 'this platform')}.
      ${esc(F.reason || '')}</td></tr></tbody>`;
  document.getElementById('factoryNote').innerHTML =
    `<p class="note">Coverage below is reported as counts, and as a ratio only
     against the TestRail case set when one was supplied - an assumed
     denominator, not a derived one.</p>`;
} else {
document.getElementById('factories').innerHTML =
  `<thead><tr><th>Factory</th><th>Unit of generation</th>
   <th class="num">Candidates</th><th>Basis</th></tr></thead><tbody>` +
  F.factories.map(f => `<tr>
    <td class="feat">${esc(f.name)} <span class="src ${f.source === 'parsed' ? 'parsed' : ''}">${esc(f.source)}</span></td>
    <td class="dim">${esc(f.unit)}</td>
    <td class="num"><strong>${f.candidates.toLocaleString()}</strong></td>
    <td class="dim">${esc(f.basis)}</td>
  </tr>`).join('') +
  `<tr><td class="feat">Total candidate space</td><td></td>
   <td class="num"><strong>${F.total_candidates.toLocaleString()}</strong></td>
   <td class="dim">before any risk filtering</td></tr></tbody>`;

const beh = F.factories.find(f => f.id === 'behavior');
document.getElementById('factoryNote').innerHTML = `
  <details><summary>Why the behavior factory looks small today</summary>
    <div class="body">
      <p>${esc(beh.note || '')}</p>
      <p>Parsed from the tree: <strong>${F.capabilities.length}</strong> capabilities
      (covering ${F.capability_features.map(x => `<span class="tag">${esc(x)}</span>`).join('')}),
      <strong>${F.templates.length}</strong> templates, and
      <strong>${F.context_profiles.EXHAUSTIVE_PREVIEW}</strong> exhaustive context variants
      from <code>BehaviorContextMatrix.kt</code>.</p>
      <p>Context profiles already defined:
      ${Object.entries(F.context_profiles).map(([k, v]) => `<span class="tag">${esc(k)} = ${v}</span>`).join('')}</p>
      <p>Projected at ${beh.projection.assumed_entities} entities (one CRUD entity per
      catalogued feature, <em>stubbed</em>): <strong>${beh.projection.candidates.toLocaleString()}</strong>
      candidates - which would make it the largest factory of the four.</p>
    </div></details>`;
}

/* TestRail: an assumed denominator, shown only when an export was supplied */
const TR = D.testrail;
if (TR) {
  const t = TR.totals;
  document.getElementById('testrailSection').style.display = '';
  document.getElementById('testrailTotals').innerHTML =
    `<thead><tr><th>Cases in export</th><th class="num">Automated</th>
     <th class="num">Manual only</th><th class="num">Automated by a skipped test</th>
     <th class="num">Automated share</th></tr></thead><tbody><tr>
      <td class="feat">${t.cases.toLocaleString()}</td>
      <td class="num">${t.automated.toLocaleString()}</td>
      <td class="num">${t.manual_only.toLocaleString()}</td>
      <td class="num">${t.skipped_automation.toLocaleString()}</td>
      <td class="num"><strong>${pct(t.automated_ratio)}</strong></td>
     </tr></tbody>`;
  document.getElementById('testrailPerFeature').innerHTML =
    `<thead><tr><th>Feature</th><th class="num">Cases</th><th class="num">Automated</th>
     <th class="num">Skipped</th><th class="num">Manual</th><th class="num">Automated</th>
     </tr></thead><tbody>` +
    TR.per_feature.filter(e => e.cases).map(e => `<tr>
      <td class="feat">${esc(e.feature)}</td>
      <td class="num">${e.cases}</td>
      <td class="num">${e.automated}</td>
      <td class="num">${e.skipped_automation || ''}</td>
      <td class="num">${e.manual_only}</td>
      <td class="num">${e.automated_ratio == null ? '-' : pct(e.automated_ratio)}</td>
    </tr>`).join('') + '</tbody>';
  document.getElementById('testrailNote').innerHTML =
    `<p class="note">${esc(TR.denominator_note)}</p>
     <p class="note">${t.skipped_automation.toLocaleString()} case(s) are claimed by
     an automated test that no test plan runs, so they fall back to manual.
     ${t.tests_without_case_id.toLocaleString()} automated test(s) carry no case id and
     cannot be counted either way. ${t.unmatched_ids.toLocaleString()} id(s) referenced by
     tests are absent from this export.</p>`;
}

/* matrix */
const M = D.matrix;
const rev = M.designs['review'];
const cmp = [
  ['Full factorial', rev.full_factorial, true],
  ['Orthogonal array', rev.orthogonal_alternative ? rev.orthogonal_alternative.runs : 0, false],
  ['Covering array (2-way)', rev.config_count, false],
].filter(r => r[1] > 0);
const cmax = Math.max(...cmp.map(r => r[1]));
document.getElementById('matrixCompare').innerHTML =
  '<div class="cmp">' + cmp.map(([label, val, muted]) => `
    <div class="cmp-row" title="${esc(label)}: ${val} configurations">
      <div class="bar-name">${esc(label)}</div>
      <div><div class="cmp-bar ${muted ? 'muted' : ''}" style="width:${(val / cmax) * 100}%"></div></div>
      <div class="bar-val">${val} configs</div>
    </div>`).join('') + '</div>' +
  (rev.orthogonal_alternative && !rev.orthogonal_alternative.balanced
    ? `<p class="note">${rev.orthogonal_alternative.notes.map(esc).join(' ')}</p>` : '');

document.getElementById('matrixDesigns').innerHTML = '<div class="cards">' +
  ['action-required', 'review', 'acceptable'].map(b => {
    const g = M.designs[b];
    if (!g) return '';
    const v = g.verification;
    return `<div class="card">
      <div class="hd">${badge(b)}<span class="cap">${g.strength === 0 ? 'baseline' : g.strength + '-way'}</span></div>
      <div class="big">${g.config_count} <span class="cap">configs</span></div>
      <p>${g.factors.length} factors, ${g.full_factorial} full cross product
      (&minus;${(g.reduction * 100).toFixed(0)}%).</p>
      ${v ? `<p class="check"><i class="dot"></i>all ${v.tuples_required} ${g.strength}-way tuples verified covered</p>` : ''}
      <p>${esc(g.rationale)}</p>
    </div>`;
  }).join('') + '</div>';

document.getElementById('matrixAlloc').innerHTML =
  `<thead><tr><th>Feature</th><th>Band</th><th class="num">Strength</th>
   <th class="num">Configs</th><th class="num">Tests</th>
   <th class="num">Executions</th><th class="num">Device min</th></tr></thead><tbody>` +
  M.per_feature.map(e => `<tr>
    <td class="feat">${esc(e.name)}${e.planned_tests === 0 ? '<div class="dim">no automation - this matrix is the manual scope</div>' : ''}</td>
    <td>${badge(e.band)}</td>
    <td class="num">${e.strength === 0 ? 'base' : e.strength + '-way'}</td>
    <td class="num">${e.config_count}</td>
    <td class="num">${e.planned_tests}</td>
    <td class="num"><strong>${e.executions}</strong></td>
    <td class="num">${e.est_minutes}</td>
  </tr>`).join('') +
  `<tr><td class="feat">Total</td><td></td><td></td><td></td><td></td>
   <td class="num"><strong>${M.totals.executions}</strong></td>
   <td class="num"><strong>${M.totals.est_minutes}</strong></td></tr></tbody>`;

const mf = rev.factors.map(f => f.name);
document.getElementById('matrixTable').innerHTML =
  '<table class="mtx"><thead><tr><th class="num">#</th>' +
  mf.map(n => `<th>${esc(n)}</th>`).join('') + '</tr></thead><tbody>' +
  rev.configs.map((c, i) => `<tr><td class="cfg">${i + 1}</td>` +
    mf.map(n => `<td>${esc(c[n])}</td>`).join('') + '</tr>').join('') +
  '</tbody></table>';

/* gaps */
document.getElementById('gaps').innerHTML = D.plan.gaps.length
  ? D.plan.gaps.map(g => `<details>
      <summary>${esc(g.name)} &mdash; residual RPN ${g.residual_rpn}</summary>
      <div class="body">
        <p><strong>Why it is a gap:</strong> ${esc(g.reason)}</p>
        <p><strong>Why it matters:</strong> ${esc(g.severity_rationale)}</p>
        <p>${(g.iso25010 || []).map(a => `<span class="tag">${esc(a)}</span>`).join('')}</p>
        <p class="dim">S${g.severity} x O${g.occurrence} &middot;
          ${g.planned_tests} automated test(s) planned &middot;
          ${g.churned_lines.toLocaleString()} lines churned</p>
      </div></details>`).join('')
  : '<p class="empty">No coverage gaps. Every touched feature is adequately covered.</p>';

/* agent tasks */
const byType = {};
D.agent_tasks.tasks.forEach(t => (byType[t.type] ||= []).push(t));
document.getElementById('tasks').innerHTML = Object.entries(byType).map(([type, ts]) =>
  `<details>
    <summary>${esc(type)} <span class="dim">(${ts.length})</span></summary>
    <div class="body">
      <p>${esc(ts[0].why_this_needs_judgement)}</p>
      <pre>${esc(JSON.stringify(ts.slice(0, 6), null, 2))}</pre>
      ${ts.length > 6 ? `<p class="dim">+ ${ts.length - 6} more in agent-tasks.json</p>` : ''}
    </div></details>`).join('') ||
  '<p class="empty">No open questions.</p>';
}

boot();

/* theme */
document.getElementById('themeBtn').onclick = () => {
  const cur = document.documentElement.getAttribute('data-theme');
  const dark = cur ? cur === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
};
</script>
</body>
</html>
"""


def render(payload: dict, out_path: str) -> str:
    blob = json.dumps(payload).replace("</", "<\\/")
    html = TEMPLATE.replace("__PAYLOAD__", blob)
    with open(out_path, "w") as fh:
        fh.write(html)
    return out_path
