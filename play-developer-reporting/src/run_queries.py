# src/run_queries.py
"""Execute queries from a TOML manifest."""
import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


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
        results[name] = {
            "status": "ok",
            "row_count": len(data.get("rows", data.get("anomalies", []))),
            "aggregate": data.get("aggregate"),
        }
        print(f"  OK ({results[name]['row_count']} rows)", file=sys.stderr)

    # Write summary manifest
    (output_dir / "summary.json").write_text(
        json.dumps(results, indent=2)
    )
    print(json.dumps(results, indent=2))
    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()