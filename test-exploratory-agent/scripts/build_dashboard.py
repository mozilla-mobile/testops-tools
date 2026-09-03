"""
scripts/build_dashboard.py

Generates a single self-contained interactive HTML dashboard from all past
sessions in reports/. No server, no dependencies to view — open the output
file in any browser (needs internet only for Chart.js CDN).

Run:
    python scripts/build_dashboard.py
    python scripts/build_dashboard.py --reports-dir reports --output reports/dashboard.html
"""

import argparse
import glob
import json
import os
from datetime import datetime
from statistics import mean


# ── Data aggregation ───────────────────────────────────────────────────────────

def load_sessions(reports_dir: str) -> list[dict]:
    files = sorted(glob.glob(os.path.join(reports_dir, "session_*.json")))
    out = []
    for path in files:
        try:
            with open(path) as f:
                data = json.load(f)
            data["_path"] = path
            out.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return out


_SEVERITY_ORDER = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}


def _top_severity(bugs: list[dict]) -> str:
    if not bugs:
        return ""
    return max(bugs, key=lambda b: _SEVERITY_ORDER.get(b.get("severity", ""), 0)).get("severity", "")


def _session_date(session_id: str) -> str:
    """session_id format: YYYYMMDD_HHMMSS → 'YYYY-MM-DD'."""
    if len(session_id) < 8:
        return session_id
    y, m, d = session_id[:4], session_id[4:6], session_id[6:8]
    return f"{y}-{m}-{d}"


def _usage(session: dict) -> dict:
    """Session's usage block. Falls back to the pre-refactor 'cost' key."""
    return session.get("usage") or session.get("cost") or {}


def _tokens(session: dict) -> int:
    u = _usage(session)
    return (u.get("total_tokens")
            or (u.get("total_input_tokens", 0) + u.get("total_output_tokens", 0)))


def build_data(sessions: list[dict]) -> dict:
    """Reshape session JSONs into the flat structure consumed by the dashboard JS."""

    sessions_out = []
    bugs_out     = []
    for s in sessions:
        sid    = s.get("session_id", "")
        date   = _session_date(sid)
        tokens = _tokens(s)
        bugs   = s.get("bugs", []) or []
        sessions_out.append({
            "session_id":   sid,
            "date":         date,
            "objective":    (s.get("objective") or "")[:120],
            "steps":        s.get("total_steps", 0),
            "tokens":       tokens,
            "bugs_count":   len(bugs),
            "top_severity": _top_severity(bugs),
        })
        for b in bugs:
            bugs_out.append({
                "title":         b.get("title", ""),
                "severity":      b.get("severity", ""),
                "session_id":    sid,
                "session_date":  date,
                "step_index":    b.get("step_index", 0),
            })

    # By model aggregation
    by_model: dict[str, dict] = {}
    for s in sessions:
        for m, d in _usage(s).get("by_model", {}).items():
            row = by_model.setdefault(m, {"model": m, "calls": 0, "in_tokens": 0, "out_tokens": 0})
            row["calls"]      += d.get("calls",         0)
            row["in_tokens"]  += d.get("input_tokens",  0)
            row["out_tokens"] += d.get("output_tokens", 0)
    by_model_list = sorted(by_model.values(),
                           key=lambda r: -(r["in_tokens"] + r["out_tokens"]))

    # By purpose aggregation (only sessions with the TrackedClient refactor)
    by_purpose: dict[str, dict] = {}
    for s in sessions:
        for p, d in _usage(s).get("by_purpose", {}).items():
            row = by_purpose.setdefault(p, {"purpose": p, "calls": 0, "in_tokens": 0, "out_tokens": 0})
            row["calls"]      += d.get("calls",         0)
            row["in_tokens"]  += d.get("input_tokens",  0)
            row["out_tokens"] += d.get("output_tokens", 0)
    by_purpose_list = sorted(by_purpose.values(),
                             key=lambda r: -(r["in_tokens"] + r["out_tokens"]))

    # By objective aggregation
    by_obj_dict: dict[str, list] = {}
    for s in sessions:
        obj_key = (s.get("objective") or "unknown").strip().lower()[:80]
        by_obj_dict.setdefault(obj_key, []).append(s)
    by_objective = []
    for obj, ss in by_obj_dict.items():
        tokens = [_tokens(x) for x in ss]
        bugs   = sum(x.get("bugs_found", 0) for x in ss)
        steps  = sum(x.get("total_steps", 0) for x in ss)
        by_objective.append({
            "objective":    obj[:80],
            "runs":         len(ss),
            "avg_tokens":   int(mean(tokens)) if tokens else 0,
            "total_tokens": sum(tokens),
            "total_bugs":   bugs,
            "total_steps":  steps,
            "bugs_per_run": round(bugs / len(ss), 2) if ss else 0,
        })
    by_objective.sort(key=lambda r: -r["avg_tokens"])

    # Totals
    dates = [s["date"] for s in sessions_out if s["date"]]
    totals = {
        "sessions":   len(sessions),
        "tokens":     sum(_tokens(s) for s in sessions),
        "bugs":       sum(s.get("bugs_found", 0) for s in sessions),
        "date_range": f"{min(dates)} to {max(dates)}" if dates else "no data",
    }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "totals":       totals,
        "sessions":     sessions_out,
        "bugs":         bugs_out,
        "by_model":     by_model_list,
        "by_purpose":   by_purpose_list,
        "by_objective": by_objective,
    }


# ── HTML template ──────────────────────────────────────────────────────────────
# Uses a __DATA_JSON__ placeholder replaced at build time. Avoids f-string
# escaping headaches (no need to double { and } in CSS/JS).

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Appium Explorer Agent — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       max-width: 1400px; margin: 0 auto; padding: 2rem;
       color: #1f2937; background: #f9fafb; line-height: 1.5; }
h1 { font-size: 1.75rem; margin: 0 0 0.25rem; }
h2 { font-size: 1.25rem; margin: 2rem 0 1rem; color: #374151; }
h3 { font-size: 1rem; margin: 1.5rem 0 0.5rem; color: #4b5563; }
.subtle { color: #6b7280; font-size: 0.875rem; }

.stat-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin: 1rem 0 2rem; }
.card { background: white; padding: 1.25rem; border-radius: 0.5rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.big-num { font-size: 2rem; font-weight: 600; color: #111827; }
.stat-label { font-size: 0.875rem; color: #6b7280; margin-top: 0.25rem; }

.chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 2rem; }
.chart-box { background: white; padding: 1rem; border-radius: 0.5rem;
             box-shadow: 0 1px 3px rgba(0,0,0,0.05); }

table { width: 100%; border-collapse: collapse; background: white;
        border-radius: 0.5rem; overflow: hidden;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05); font-size: 0.9rem; }
th, td { padding: 0.65rem 0.75rem; text-align: left; border-bottom: 1px solid #e5e7eb; }
th { background: #f3f4f6; font-weight: 600; font-size: 0.85rem;
     cursor: pointer; user-select: none; }
th:hover { background: #e5e7eb; }
th[data-sort]::after { content: " ↕"; opacity: 0.3; font-size: 0.8em; }
th.sort-asc::after  { content: " ↑"; opacity: 1; }
th.sort-desc::after { content: " ↓"; opacity: 1; }
tr:hover td { background: #f9fafb; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }

.sev { display: inline-block; padding: 0.125rem 0.5rem; border-radius: 9999px;
       font-size: 0.75rem; font-weight: 500; }
.sev-Critical { background: #fee2e2; color: #991b1b; }
.sev-High     { background: #fed7aa; color: #9a3412; }
.sev-Medium   { background: #fef3c7; color: #92400e; }
.sev-Low      { background: #dbeafe; color: #1e40af; }

.filter-row { margin: 0 0 0.5rem; display: flex; gap: 0.5rem; align-items: center; }
select { padding: 0.4rem 0.6rem; border: 1px solid #d1d5db; border-radius: 0.375rem;
         background: white; font-size: 0.9rem; }

details { background: white; border-radius: 0.5rem; padding: 0.5rem 1rem; margin-top: 2rem;
          box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
summary { font-weight: 600; cursor: pointer; padding: 0.5rem; font-size: 1.1rem; color: #374151; }
details[open] summary { border-bottom: 1px solid #e5e7eb; margin-bottom: 1rem; }

.footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #e5e7eb;
          color: #9ca3af; font-size: 0.8rem; text-align: center; }

@media (max-width: 768px) {
  .stat-cards, .chart-row { grid-template-columns: 1fr; }
  body { padding: 1rem; }
}
</style>
</head>
<body>

<header>
  <h1>Appium Explorer Agent — Dashboard</h1>
  <div class="subtle" id="date-range"></div>
</header>

<div class="stat-cards">
  <div class="card"><div class="big-num" id="stat-sessions">–</div><div class="stat-label">Sessions</div></div>
  <div class="card"><div class="big-num" id="stat-tokens">–</div>  <div class="stat-label">Total tokens</div></div>
  <div class="card"><div class="big-num" id="stat-bugs">–</div>    <div class="stat-label">Bugs found</div></div>
  <div class="card"><div class="big-num" id="stat-perbug">–</div>  <div class="stat-label">Tokens per bug</div></div>
</div>
<div class="subtle" style="margin: -1rem 0 2rem;">
  For $ cost see the
  <a href="https://console.anthropic.com/settings/usage" target="_blank">Anthropic console</a>
  — this dashboard tracks tokens only.
</div>

<section class="chart-row">
  <div class="chart-box"><canvas id="cost-chart"></canvas></div>
  <div class="chart-box"><canvas id="bugs-chart"></canvas></div>
</section>

<h2>Recent sessions</h2>
<table id="sessions-table">
  <thead>
    <tr>
      <th data-sort="date">Date</th>
      <th data-sort="objective">Objective</th>
      <th data-sort="steps" class="num">Steps</th>
      <th data-sort="tokens" class="num">Tokens</th>
      <th data-sort="bugs_count" class="num">Bugs</th>
      <th data-sort="top_severity">Top severity</th>
    </tr>
  </thead>
  <tbody></tbody>
</table>

<h2>Bugs found</h2>
<div class="filter-row">
  <label for="sev-filter">Filter by severity:</label>
  <select id="sev-filter">
    <option value="">All</option>
    <option>Critical</option>
    <option>High</option>
    <option>Medium</option>
    <option>Low</option>
  </select>
  <span class="subtle" id="bugs-count"></span>
</div>
<table id="bugs-table">
  <thead>
    <tr>
      <th data-sort="severity">Severity</th>
      <th data-sort="title">Title</th>
      <th data-sort="session_date">Session date</th>
      <th data-sort="session_id">Session ID</th>
    </tr>
  </thead>
  <tbody></tbody>
</table>

<details>
  <summary>Technical detail (engineering)</summary>

  <h3>By model</h3>
  <table id="model-table">
    <thead>
      <tr>
        <th data-sort="model">Model</th>
        <th data-sort="calls" class="num">Calls</th>
        <th data-sort="in_tokens" class="num">Input tokens</th>
        <th data-sort="out_tokens" class="num">Output tokens</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>

  <h3>By purpose</h3>
  <table id="purpose-table">
    <thead>
      <tr>
        <th data-sort="purpose">Purpose</th>
        <th data-sort="calls" class="num">Calls</th>
        <th data-sort="in_tokens" class="num">Input tokens</th>
        <th data-sort="out_tokens" class="num">Output tokens</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>

  <h3>By objective (ROI view)</h3>
  <table id="objective-table">
    <thead>
      <tr>
        <th data-sort="objective">Objective</th>
        <th data-sort="runs" class="num">Runs</th>
        <th data-sort="avg_tokens" class="num">Avg tokens</th>
        <th data-sort="total_tokens" class="num">Total tokens</th>
        <th data-sort="total_bugs" class="num">Total bugs</th>
        <th data-sort="bugs_per_run" class="num">Bugs/run</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>
</details>

<div class="footer" id="footer"></div>

<script>
const DATA = __DATA_JSON__;

// ── Helpers ──────────────────────────────────────────────────────────────────
function el(tag, attrs = {}, text = "") {
  const e = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));
  if (text !== "") e.textContent = text;
  return e;
}

function num(v) {
  if (typeof v !== "number") return v;
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function fmtTokens(v) {
  return (v || 0).toLocaleString();
}

// ── Table rendering + sorting ────────────────────────────────────────────────
function renderTable(tableId, rows, columns) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  tbody.innerHTML = "";
  rows.forEach(row => {
    const tr = el("tr");
    // Store row data on the tr for filter/sort access
    Object.entries(row).forEach(([k, v]) => tr.dataset[k] = v ?? "");
    columns.forEach(col => {
      const td = el("td");
      if (col.class) td.className = col.class;
      if (col.render) {
        const rendered = col.render(row);
        if (rendered instanceof Node) td.appendChild(rendered);
        else td.textContent = String(rendered);  // safe fallback — never parse as HTML
      } else {
        td.textContent = row[col.key] ?? "";
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function attachSort(tableId) {
  const table = document.getElementById(tableId);
  table.querySelectorAll("th[data-sort]").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      const currentKey = table.dataset.sortKey;
      const currentDir = table.dataset.sortDir;
      const dir = (currentKey === key && currentDir === "asc") ? "desc" : "asc";

      const tbody = table.tBodies[0];
      const rows = Array.from(tbody.querySelectorAll("tr"));
      rows.sort((a, b) => {
        const av = a.dataset[key] ?? "";
        const bv = b.dataset[key] ?? "";
        const an = parseFloat(av), bn = parseFloat(bv);
        if (!isNaN(an) && !isNaN(bn)) return dir === "asc" ? an - bn : bn - an;
        return dir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      });
      rows.forEach(r => tbody.appendChild(r));

      table.dataset.sortKey = key;
      table.dataset.sortDir = dir;
      table.querySelectorAll("th").forEach(h => h.classList.remove("sort-asc", "sort-desc"));
      th.classList.add("sort-" + dir);
    });
  });
}

// ── Header + stats ───────────────────────────────────────────────────────────
document.getElementById("stat-sessions").textContent = DATA.totals.sessions;
document.getElementById("stat-tokens").textContent   = fmtTokens(DATA.totals.tokens);
document.getElementById("stat-bugs").textContent     = DATA.totals.bugs;
document.getElementById("stat-perbug").textContent   =
  DATA.totals.bugs > 0
    ? fmtTokens(Math.round(DATA.totals.tokens / DATA.totals.bugs))
    : "–";
document.getElementById("date-range").textContent =
  `${DATA.totals.date_range}   ·   generated ${DATA.generated_at}`;

// ── Sessions table ───────────────────────────────────────────────────────────
function sevBadge(sev) {
  if (!sev) return document.createTextNode("");
  const span = document.createElement("span");
  span.className = "sev sev-" + sev;
  span.textContent = sev;
  return span;
}

function sessionLink(sessionId, text) {
  const a = document.createElement("a");
  a.href = "session_" + sessionId + ".json";
  a.textContent = text;
  return a;
}

renderTable("sessions-table", DATA.sessions, [
  { key: "date",         render: r => sessionLink(r.session_id, r.date) },
  { key: "objective" },
  { key: "steps",        class: "num" },
  { key: "tokens",       class: "num", render: r => fmtTokens(r.tokens) },
  { key: "bugs_count",   class: "num" },
  { key: "top_severity", render: r => sevBadge(r.top_severity) },
]);
attachSort("sessions-table");

// ── Bugs table ───────────────────────────────────────────────────────────────
renderTable("bugs-table", DATA.bugs, [
  { key: "severity",     render: r => sevBadge(r.severity) },
  { key: "title" },
  { key: "session_date" },
  { key: "session_id",   render: r => sessionLink(r.session_id, r.session_id) },
]);
attachSort("bugs-table");
document.getElementById("bugs-count").textContent = `(${DATA.bugs.length} total)`;

document.getElementById("sev-filter").addEventListener("change", e => {
  const target = e.target.value;
  let shown = 0;
  document.querySelectorAll("#bugs-table tbody tr").forEach(row => {
    const match = !target || row.dataset.severity === target;
    row.style.display = match ? "" : "none";
    if (match) shown++;
  });
  document.getElementById("bugs-count").textContent =
    target ? `(${shown} of ${DATA.bugs.length})` : `(${DATA.bugs.length} total)`;
});

// ── Technical tables ─────────────────────────────────────────────────────────
renderTable("model-table", DATA.by_model, [
  { key: "model" },
  { key: "calls",      class: "num" },
  { key: "in_tokens",  class: "num", render: r => fmtTokens(r.in_tokens) },
  { key: "out_tokens", class: "num", render: r => fmtTokens(r.out_tokens) },
]);
attachSort("model-table");

renderTable("purpose-table", DATA.by_purpose, [
  { key: "purpose" },
  { key: "calls",      class: "num" },
  { key: "in_tokens",  class: "num", render: r => fmtTokens(r.in_tokens) },
  { key: "out_tokens", class: "num", render: r => fmtTokens(r.out_tokens) },
]);
attachSort("purpose-table");

renderTable("objective-table", DATA.by_objective, [
  { key: "objective" },
  { key: "runs",         class: "num" },
  { key: "avg_tokens",   class: "num", render: r => fmtTokens(r.avg_tokens) },
  { key: "total_tokens", class: "num", render: r => fmtTokens(r.total_tokens) },
  { key: "total_bugs",   class: "num" },
  { key: "bugs_per_run", class: "num" },
]);
attachSort("objective-table");

// ── Charts ───────────────────────────────────────────────────────────────────
const chronological = [...DATA.sessions].sort((a, b) => a.session_id.localeCompare(b.session_id));

new Chart(document.getElementById("cost-chart"), {
  type: "line",
  data: {
    labels: chronological.map(s => s.date),
    datasets: [{
      label: "Tokens per session",
      data:  chronological.map(s => s.tokens),
      borderColor: "#3b82f6",
      backgroundColor: "rgba(59,130,246,0.15)",
      fill: true,
      tension: 0.2,
    }],
  },
  options: {
    responsive: true,
    plugins: { title: { display: true, text: "Tokens per session over time" } },
    scales: { y: { beginAtZero: true, ticks: { callback: v => v.toLocaleString() } } },
  },
});

new Chart(document.getElementById("bugs-chart"), {
  type: "bar",
  data: {
    labels: chronological.map(s => s.date),
    datasets: [{
      label: "Bugs found per session",
      data:  chronological.map(s => s.bugs_count),
      backgroundColor: "#f97316",
    }],
  },
  options: {
    responsive: true,
    plugins: { title: { display: true, text: "Bugs found per session over time" } },
    scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
  },
});

// ── Footer ───────────────────────────────────────────────────────────────────
document.getElementById("footer").textContent =
  `Generated from ${DATA.totals.sessions} session files · ` +
  `Regenerate with: python scripts/build_dashboard.py`;
</script>
</body>
</html>
"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reports-dir", default="reports",
                        help="Directory containing session_*.json files (default: reports)")
    parser.add_argument("--output", default="reports/dashboard.html",
                        help="Output HTML path (default: reports/dashboard.html)")
    args = parser.parse_args()

    sessions = load_sessions(args.reports_dir)
    if not sessions:
        print(f"No sessions found in {args.reports_dir}/. Nothing to render.")
        return

    data = build_data(sessions)
    # Defense against </script> injection in any user-supplied string:
    data_json = json.dumps(data).replace("</", "<\\/")

    html = HTML_TEMPLATE.replace("__DATA_JSON__", data_json)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        f.write(html)

    print(f"[dashboard] Generated {args.output}")
    print(f"[dashboard] {data['totals']['sessions']} sessions · "
          f"{data['totals']['tokens']:,} tokens · "
          f"{data['totals']['bugs']} bugs · "
          f"{len(data['bugs'])} bug entries")
    print(f"[dashboard] Open in browser:  file://{os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
