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


def _delta(current: float | None, previous: float | None) -> str:
    """Format the delta between current and previous 28-day rates as ±X.XX%."""
    if current is None or previous is None:
        return "—"
    diff = current - previous
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff * 100:.2f}%"


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


def _narrative_summary(results: dict) -> str:
    """One-line digest of notable changes across all products.

    Flags any metric whose 28-day weighted rate moved more than 10% relative
    to the prior 28-day period (matching the ↑↓ threshold used in the table).
    """
    concerns: list[str] = []
    improvements: list[str] = []

    checks = [
        ("crashrate",  "userPerceivedCrashRate28dUserWeighted",  "crash"),
        ("anrrate",    "userPerceivedAnrRate28dUserWeighted",     "ANR"),
        ("lmkrate",    "userPerceivedLmkRate28dUserWeighted",     "LMK"),
    ]

    for group in PRODUCT_GROUPS:
        for result_key, metric_key, label in checks:
            result = results.get(group[result_key]) or {}
            top_row = _top_version_row(result)
            current = top_row.get(metric_key)
            prior = (result.get("compare_aggregate") or {}).get(metric_key)
            if current is None or prior is None or prior == 0:
                continue
            relative = (current - prior) / prior
            if relative > 0.10:
                concerns.append(f"{group['label']} {label} ↑")
            elif relative < -0.10:
                improvements.append(f"{group['label']} {label} ↓")

    parts = []
    if concerns:
        parts.append("⚠️  " + "  ·  ".join(concerns))
    if improvements:
        parts.append("✅  " + "  ·  ".join(improvements))
    return "  ·  ".join(parts) if parts else "All products stable across crash, ANR, and LMK rates 🟢"


def _top_version_row(result: dict) -> dict:
    """Return the row with the highest (latest) version code."""
    rows = result.get("rows", [])
    if not rows:
        return {}
    return max(rows, key=lambda r: r.get("versionCode", 0))


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
        "> vs. 28d: change in 28-day weighted rate vs. previous 28-day period",
        "",
        "| Product | Top Version | Crash Rate | vs. 28d | ANR Rate | vs. 28d | LMK Rate | vs. 28d | Active Users |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
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

        # Current rates with trend arrows
        crash = _pct(crash_row.get("userPerceivedCrashRate")) + _trend(
            crash_row.get("userPerceivedCrashRate"), crash_row.get("userPerceivedCrashRate28dUserWeighted")
        )
        anr = _pct(anr_row.get("userPerceivedAnrRate")) + _trend(
            anr_row.get("userPerceivedAnrRate"), anr_row.get("userPerceivedAnrRate28dUserWeighted")
        )
        lmk = _pct(lmk_row.get("userPerceivedLmkRate")) + _trend(
            lmk_row.get("userPerceivedLmkRate"), lmk_row.get("userPerceivedLmkRate28dUserWeighted")
        )

        # Deltas vs. previous 28-day period
        crash_compare = crash_result.get("compare_aggregate") or {}
        anr_compare   = anr_result.get("compare_aggregate") or {}
        lmk_compare   = lmk_result.get("compare_aggregate") or {}

        crash_delta = _delta(
            crash_row.get("userPerceivedCrashRate28dUserWeighted"),
            crash_compare.get("userPerceivedCrashRate28dUserWeighted"),
        )
        anr_delta = _delta(
            anr_row.get("userPerceivedAnrRate28dUserWeighted"),
            anr_compare.get("userPerceivedAnrRate28dUserWeighted"),
        )
        lmk_delta = _delta(
            lmk_row.get("userPerceivedLmkRate28dUserWeighted"),
            lmk_compare.get("userPerceivedLmkRate28dUserWeighted"),
        )

        lines.append(f"| {group['label']} | {version} | {crash} | {crash_delta} | {anr} | {anr_delta} | {lmk} | {lmk_delta} | {users} |")

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


def generate_slack_payload(results: dict) -> dict:
    """Build a Slack Block Kit payload (Proposal 3 format) from query results."""
    date_str = next(
        (results[g["crashrate"]]["date"] for g in PRODUCT_GROUPS
         if g["crashrate"] in results and results[g["crashrate"]].get("date")),
        "unknown",
    )

    def _bold_cell(text: str) -> dict:
        return {
            "type": "rich_text",
            "elements": [{"type": "rich_text_section", "elements": [
                {"type": "text", "text": text, "style": {"bold": True}}
            ]}],
        }

    def _raw_cell(text: str) -> dict:
        return {"type": "raw_text", "text": text}

    def _metric_cell(rate, baseline, cmp_baseline) -> dict:
        pct = _pct(rate)
        trend = _trend(rate, baseline)
        delta = _delta(baseline, cmp_baseline)
        return _raw_cell(f"{pct} {trend} ({delta})")

    header_row = [
        _bold_cell("Product"),
        _bold_cell("Version"),
        _bold_cell("Crash (vs. 28d)"),
        _bold_cell("ANR (vs. 28d)"),
        _bold_cell("LMK (vs. 28d)"),
    ]

    rows = [header_row]
    for group in PRODUCT_GROUPS:
        crash_result = results.get(group["crashrate"]) or {}
        anr_result   = results.get(group["anrrate"])   or {}
        lmk_result   = results.get(group["lmkrate"])   or {}

        top_row      = _top_version_row(crash_result)
        version_code = top_row.get("versionCode", "")
        version      = top_row.get("firefoxVersion") or "—"

        anr_row = _find_version_row(anr_result, version_code)
        lmk_row = _find_version_row(lmk_result, version_code)

        crash_cmp = crash_result.get("compare_aggregate") or {}
        anr_cmp   = anr_result.get("compare_aggregate")   or {}
        lmk_cmp   = lmk_result.get("compare_aggregate")   or {}

        rows.append([
            _raw_cell(group["label"]),
            _raw_cell(version),
            _metric_cell(
                top_row.get("userPerceivedCrashRate"),
                top_row.get("userPerceivedCrashRate28dUserWeighted"),
                crash_cmp.get("userPerceivedCrashRate28dUserWeighted"),
            ),
            _metric_cell(
                anr_row.get("userPerceivedAnrRate"),
                anr_row.get("userPerceivedAnrRate28dUserWeighted"),
                anr_cmp.get("userPerceivedAnrRate28dUserWeighted"),
            ),
            _metric_cell(
                lmk_row.get("userPerceivedLmkRate"),
                lmk_row.get("userPerceivedLmkRate28dUserWeighted"),
                lmk_cmp.get("userPerceivedLmkRate28dUserWeighted"),
            ),
        ])

    anomaly_lines = [
        f"• *{g['label']}*: {(results.get(g['anomalies']) or {}).get('row_count')} anomaly/anomalies detected"
        for g in PRODUCT_GROUPS
        if (results.get(g["anomalies"]) or {}).get("row_count", 0) > 0
    ]
    anomaly_text = "\n".join(anomaly_lines) if anomaly_lines else "No anomalies detected."

    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Android Vitals \u2014 {date_str}"},
            },
            {
                "type": "table",
                "rows": rows,
                "column_settings": [
                    {"align": "left"},
                    {"align": "left"},
                    {"align": "right"},
                    {"align": "right"},
                    {"align": "right"},
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Anomalies (last 7 days)*\n{anomaly_text}"},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "\u2191 >10% above 28-day avg  \u00b7  "
                            "\u2193 >10% below  \u00b7  "
                            "\u2192 stable  \u00b7  "
                            f"Data date: {date_str}"
                        ),
                    }
                ],
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "image",
                        "image_url": "https://avatars.slack-edge.com/2025-06-24/9097205871668_a01e2ac8089c067ea5f8_72.png",
                        "alt_text": "TestOps logo",
                    },
                    {
                        "type": "mrkdwn",
                        "text": "Created by Mobile Test Engineering",
                    },
                ],
            },
        ]
    }


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
        if query.get("compare_days"):
            cmd.extend(["--compare-days", str(query["compare_days"])])
        if query.get("sort_by"):
            cmd.extend(["--sort-by", query["sort_by"]])

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
            "compare_aggregate": data.get("compare_aggregate"),
            "rows": [simplify_row(r) for r in raw_rows],
        }
        print(f"  OK ({len(raw_rows)} rows)", file=sys.stderr)

    # Write summary manifest, markdown, and Slack payload
    (output_dir / "summary.json").write_text(json.dumps(results, indent=2))
    (output_dir / "summary.md").write_text(generate_markdown(results))
    (output_dir / "slack_payload.json").write_text(json.dumps(generate_slack_payload(results), indent=2))

    print(json.dumps(results, indent=2))
    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
