# src/run_queries.py
"""Execute queries from a TOML manifest."""
import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

PRODUCT_GROUPS = [
    {
        "label": "Firefox Release",
        "crashrate": "firefox-release-crashrate",
        "anrrate":   "firefox-release-anrrate",
        "lmkrate":   "firefox-release-lmkrate",
        "anomalies": "firefox-release-anomalies",
    },
    {
        "label": "Firefox Beta",
        "crashrate": "firefox-beta-crashrate",
        "anrrate":   "firefox-beta-anrrate",
        "lmkrate":   "firefox-beta-lmkrate",
        "anomalies": "firefox-beta-anomalies",
    },
    {
        "label": "Firefox Nightly",
        "crashrate": "firefox-nightly-crashrate",
        "anrrate":   "firefox-nightly-anrrate",
        "lmkrate":   "firefox-nightly-lmkrate",
        "anomalies": "firefox-nightly-anomalies",
    },
    {
        "label": "Firefox Focus",
        "crashrate": "focus-crashrate",
        "anrrate":   "focus-anrrate",
        "lmkrate":   "focus-lmkrate",
        "anomalies": "focus-anomalies",
    },
]


def simplify_row(row: dict) -> dict:
    """Extract a compact representation of a row for the summary."""
    result = {}
    if "firefoxVersion" in row:
        result["firefoxVersion"] = row["firefoxVersion"]
    if "cpuArch" in row:
        result["cpuArch"] = row["cpuArch"]

    for d in row.get("dimensions", []):
        result[d["dimension"]] = d.get("stringValue", d.get("int64Value", ""))

    for m in row.get("metrics", []):
        if "decimalValue" in m:
            result[m["metric"]] = float(m["decimalValue"]["value"])

    return result


def _pct(value: float | None) -> str:
    return f"{value * 100:.2f}%" if value is not None else "—"


def _fmt_users(value: float | None) -> str:
    return f"{int(value):,}" if value is not None else "—"


def _trend(current: float | None, baseline: float | None) -> str:
    """Return a trend arrow comparing current rate to its 28-day baseline.

    ↑ = more than 10% above baseline (elevated, warrants attention)
    ↓ = more than 10% below baseline (improving)
    → = within 10% of baseline (stable)
    """
    if current is None or baseline is None or baseline == 0:
        return ""
    delta = (current - baseline) / baseline
    if delta > 0.10:
        return " ↑"
    if delta < -0.10:
        return " ↓"
    return " →"


def _top_version_row(result: dict) -> dict:
    """Return the row with the most active users."""
    rows = result.get("rows", [])
    if not rows:
        return {}
    return max(rows, key=lambda r: r.get("distinctUsers", 0))


def _find_version_row(result: dict, version_code: str) -> dict:
    """Find a row matching a specific version code, or fall back to the top row."""
    for row in result.get("rows", []):
        if row.get("versionCode") == version_code:
            return row
    # Version code not found (e.g. different user sets for LMK) — use top row
    return _top_version_row(result)


def generate_markdown(results: dict) -> str:
    # Determine data date from the first successful crashrate result
    date_str = next(
        (results[g["crashrate"]]["date"] for g in PRODUCT_GROUPS
         if g["crashrate"] in results and results[g["crashrate"]].get("date")),
        "unknown",
    )

    lines = [
        f"## Android Vitals — {date_str}",
        "",
        "> Rates for the top version (by active users) for the most recent available day.",
        "> Trend: ↑ >10% above 28-day avg · ↓ >10% below · → stable",
        "",
        "| Product | Top Version | Crash Rate | ANR Rate | LMK Rate | Active Users |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for group in PRODUCT_GROUPS:
        crash_result = results.get(group["crashrate"]) or {}
        anr_result   = results.get(group["anrrate"])   or {}
        lmk_result   = results.get(group["lmkrate"])   or {}

        # Find the top version from crashrate (largest user base)
        top_row = _top_version_row(crash_result)
        version_code = top_row.get("versionCode", "")
        version = top_row.get("firefoxVersion") or "—"
        users = _fmt_users(top_row.get("distinctUsers"))

        # Pull the same version's metrics from each metric set
        crash_row = top_row  # already from crashrate
        anr_row   = _find_version_row(anr_result, version_code)
        lmk_row   = _find_version_row(lmk_result, version_code)

        crash = _pct(crash_row.get("userPerceivedCrashRate")) + _trend(
            crash_row.get("userPerceivedCrashRate"), crash_row.get("userPerceivedCrashRate28dUserWeighted")
        )
        anr = _pct(anr_row.get("userPerceivedAnrRate")) + _trend(
            anr_row.get("userPerceivedAnrRate"), anr_row.get("userPerceivedAnrRate28dUserWeighted")
        )
        lmk = _pct(lmk_row.get("userPerceivedLmkRate")) + _trend(
            lmk_row.get("userPerceivedLmkRate"), lmk_row.get("userPerceivedLmkRate28dUserWeighted")
        )

        lines.append(f"| {group['label']} | {version} | {crash} | {anr} | {lmk} | {users} |")

    lines += ["", "### Anomalies (last 7 days)", ""]

    any_anomalies = False
    for group in PRODUCT_GROUPS:
        count = (results.get(group["anomalies"]) or {}).get("row_count", 0)
        if count:
            any_anomalies = True
            noun = "anomaly" if count == 1 else "anomalies"
            lines.append(f"- **{group['label']}**: {count} {noun} detected")

    if not any_anomalies:
        lines.append("No anomalies detected.")

    lines += ["", f"*Data date: {date_str} · Generated by play-developer-reporting*"]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="queries.toml")
    parser.add_argument("--output-dir", default="/tmp/vitals-output")
    args = parser.parse_args()

    manifest = tomllib.load(Path(args.manifest).open("rb"))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    any_failed = False
    for query in manifest["queries"]:
        name = query["name"]
        cmd = ["uv", "run", "python", "src/fetch_metrics.py",
               "--package", query["package"],
               "--output-format", "json"]

        if query.get("anomalies"):
            cmd.append("--anomalies")
        else:
            cmd.extend(["--metric-set", query["metric_set"]])

        if query.get("days"):
            cmd.extend(["--days", str(query["days"])])
        if query.get("top"):
            cmd.extend(["--top", str(query["top"])])
        if query.get("resolve_versions"):
            cmd.append("--resolve-versions")
        if query.get("min_users"):
            cmd.extend(["--min-users", str(query["min_users"])])

        print(f"Running: {name}", file=sys.stderr)
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"  FAILED: {result.stderr}", file=sys.stderr)
            results[name] = {"error": result.stderr}
            any_failed = True
            continue

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            print("  FAILED: invalid JSON", file=sys.stderr)
            results[name] = {"error": "invalid JSON output"}
            any_failed = True
            continue

        # Write individual result
        (output_dir / f"{name}.json").write_text(
            json.dumps(data, indent=2)
        )

        # Extract date from first row
        raw_rows = data.get("rows", data.get("anomalies", []))
        first_row = raw_rows[0] if raw_rows else {}
        start_time = first_row.get("startTime", {})
        date_str = ""
        if start_time:
            date_str = f"{start_time.get('year', '')}-{start_time.get('month', 0):02d}-{start_time.get('day', 0):02d}"

        results[name] = {
            "status": "ok",
            "date": date_str,
            "package": query["package"],
            "metric_set": query.get("metric_set", "anomalies"),
            "row_count": len(raw_rows),
            "aggregate": data.get("aggregate"),
            "rows": [simplify_row(r) for r in raw_rows],
        }
        print(f"  OK ({len(raw_rows)} rows)", file=sys.stderr)

    # Write summary manifest and markdown
    (output_dir / "summary.json").write_text(json.dumps(results, indent=2))
    (output_dir / "summary.md").write_text(generate_markdown(results))

    print(json.dumps(results, indent=2))
    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()