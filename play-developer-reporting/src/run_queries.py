# src/run_queries.py
"""Execute queries from a TOML manifest."""
import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path


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

    # Write summary manifest
    (output_dir / "summary.json").write_text(
        json.dumps(results, indent=2)
    )
    print(json.dumps(results, indent=2))
    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()