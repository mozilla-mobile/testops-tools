"""
scripts/analyze_costs.py

Aggregates token usage and outcome data across all past sessions in reports/.
One-shot analysis — no ongoing infra, just answers questions like:
  - Which objectives use the most tokens?
  - What's the tokens/bug ratio?
  - Are we getting more efficient over time?

USD cost is not aggregated here — see the Anthropic console for that.
    https://console.anthropic.com/settings/usage

Run:
    python scripts/analyze_costs.py
    python scripts/analyze_costs.py --reports-dir /path/to/reports
"""

import argparse
import glob
import json
import os
from collections import defaultdict
from statistics import mean


def load_sessions(reports_dir: str) -> list[dict]:
    files = sorted(glob.glob(os.path.join(reports_dir, "session_*.json")))
    sessions = []
    for path in files:
        try:
            with open(path) as f:
                data = json.load(f)
            data["_path"] = path
            sessions.append(data)
        except (json.JSONDecodeError, OSError):
            print(f"[skipped] Could not parse {path}")
    return sessions


def _usage(session: dict) -> dict:
    """Return the session's usage block. Falls back to the pre-refactor 'cost'
    key for sessions recorded before the token-only migration."""
    return session.get("usage") or session.get("cost") or {}


def _tokens(session: dict) -> int:
    u = _usage(session)
    return (u.get("total_tokens")
            or (u.get("total_input_tokens", 0) + u.get("total_output_tokens", 0)))


def print_totals(sessions: list[dict]):
    total_tokens = sum(_tokens(s) for s in sessions)
    total_steps  = sum(s.get("total_steps", 0) for s in sessions)
    total_bugs   = sum(s.get("bugs_found",  0) for s in sessions)
    with_usage   = [s for s in sessions if _tokens(s) > 0]

    print(f"\n# Usage Analysis — {len(sessions)} sessions ({len(with_usage)} with token data)")
    print(f"  Total tokens:   {total_tokens:,}")
    print(f"  Total steps:    {total_steps:,}")
    print(f"  Total bugs:     {total_bugs}")
    if total_bugs > 0:
        print(f"  Tokens/bug:     {total_tokens // total_bugs:,}")
    if total_steps > 0:
        print(f"  Tokens/step:    {total_tokens // total_steps:,}")
    if with_usage:
        avg_tokens = mean(_tokens(s) for s in with_usage)
        print(f"  Avg tokens/session (of those with data): {int(avg_tokens):,}")
    print(f"\n  For $ cost:     https://console.anthropic.com/settings/usage")


def print_by_model(sessions: list[dict]):
    by_model: dict[str, dict] = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0})
    for s in sessions:
        for model, data in _usage(s).get("by_model", {}).items():
            by_model[model]["calls"] += data.get("calls",         0)
            by_model[model]["in"]    += data.get("input_tokens",  0)
            by_model[model]["out"]   += data.get("output_tokens", 0)

    if not by_model:
        return
    print(f"\n## By model (aggregated across all sessions)")
    for model, d in sorted(by_model.items(), key=lambda x: -(x[1]["in"] + x[1]["out"])):
        print(f"  {model:<25} {d['calls']:>5} calls  {d['in']:>10,} in  {d['out']:>8,} out")


def print_by_purpose(sessions: list[dict]):
    by_purpose: dict[str, dict] = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0})
    for s in sessions:
        for purpose, data in _usage(s).get("by_purpose", {}).items():
            by_purpose[purpose]["calls"] += data.get("calls",         0)
            by_purpose[purpose]["in"]    += data.get("input_tokens",  0)
            by_purpose[purpose]["out"]   += data.get("output_tokens", 0)

    if not by_purpose:
        return
    print(f"\n## By purpose (only sessions with the TrackedClient refactor)")
    for purpose, d in sorted(by_purpose.items(), key=lambda x: -(x[1]["in"] + x[1]["out"])):
        print(f"  {purpose:<20} {d['calls']:>5} calls  {d['in']:>10,} in  {d['out']:>8,} out")


def print_by_objective(sessions: list[dict]):
    """
    Groups sessions by normalized objective (lowercase, trimmed, first 60 chars).
    Same objective phrased differently won't group perfectly — that's a known limitation.
    """
    groups: dict[str, list] = defaultdict(list)
    for s in sessions:
        obj = (s.get("objective") or "unknown").strip().lower()[:60]
        groups[obj].append(s)

    print(f"\n## By objective ({len(groups)} unique)")
    rows = []
    for obj, ss in groups.items():
        tokens = [_tokens(s) for s in ss]
        bugs   = sum(s.get("bugs_found",  0) for s in ss)
        steps  = sum(s.get("total_steps", 0) for s in ss)
        rows.append({
            "objective":    obj,
            "runs":         len(ss),
            "mean_tokens":  mean(tokens) if tokens else 0,
            "total_bugs":   bugs,
            "total_steps":  steps,
        })

    for row in sorted(rows, key=lambda r: -r["mean_tokens"]):
        bugs_per_run = row["total_bugs"] / row["runs"] if row["runs"] else 0
        print(f"  [{row['runs']:>2}× runs] {int(row['mean_tokens']):>9,} tokens avg  "
              f"{row['total_bugs']:>2} bugs ({bugs_per_run:.1f}/run)  "
              f"{row['total_steps']:>4} steps  "
              f"— {row['objective'][:50]}")


def print_outliers(sessions: list[dict], top_n: int = 3):
    with_usage = [s for s in sessions if _tokens(s) > 0]
    if not with_usage:
        return
    print(f"\n## Heaviest sessions (top {top_n} by token count)")
    for s in sorted(with_usage, key=lambda x: -_tokens(x))[:top_n]:
        obj   = (s.get("objective") or "")[:60]
        steps = s.get("total_steps", 0)
        bugs  = s.get("bugs_found",  0)
        print(f"  {_tokens(s):>10,} tokens  {steps:>3} steps  {bugs} bugs  '{obj}'")


def print_temporal_trend(sessions: list[dict], window: int = 10):
    with_usage = [s for s in sessions if _tokens(s) > 0]
    if len(with_usage) < 2:
        return
    print(f"\n## Last {min(window, len(with_usage))} sessions chronologically")
    for s in with_usage[-window:]:
        session_id = s.get("session_id", "?")
        obj        = (s.get("objective") or "")[:40]
        print(f"  {session_id}  {_tokens(s):>10,} tokens  '{obj}'")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reports-dir", default="reports",
                        help="Directory containing session_*.json files (default: reports)")
    args = parser.parse_args()

    sessions = load_sessions(args.reports_dir)
    if not sessions:
        print(f"No sessions found in {args.reports_dir}/")
        return

    print_totals(sessions)
    print_by_model(sessions)
    print_by_purpose(sessions)
    print_by_objective(sessions)
    print_outliers(sessions)
    print_temporal_trend(sessions)


if __name__ == "__main__":
    main()
