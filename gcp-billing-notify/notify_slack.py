import os
import requests
from typing import List, Dict, Callable


def fetch_stmo_results(api_url: str, api_key: str) -> List[Dict]:
    """Fetch results from STMO/Redash API and return rows safely."""
    try:
        response = requests.get(api_url, params={"api_key": api_key}, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(f"STMO API returned HTTP error {response.status_code}: {response.text}") from e
    except requests.Timeout as e:
        raise RuntimeError("STMO API request timed out after 30s") from e
    except requests.RequestException as e:
        raise RuntimeError(f"Unexpected error fetching data from STMO: {e}") from e

    try:
        data = response.json()
    except ValueError as e:
        raise RuntimeError("Failed to decode JSON from STMO API response") from e

    rows = (
        data.get("query_result", {})
            .get("data", {})
            .get("rows", [])
    )

    if not rows:
        raise RuntimeError("No rows returned from STMO query (check query or API key).")

    return rows


def format_monthly_summary(rows: List[Dict]) -> str:
    """Format rows into a monthly billing breakdown with yearly total."""
    lines = ["*Monthly Billing Breakdown*"]
    total_sum = 0.0
    for row in rows:
        month = row.get("month")
        total_cost = row.get("total_cost", 0.0)
        total_sum += total_cost
        lines.append(f"- {month}: ${total_cost:,.2f}")

    lines.append(f"\n*Yearly Total:* ${total_sum:,.2f}")
    return "\n".join(lines)


def format_weekly_summary(rows: List[Dict]) -> str:
    """Format rows into a weekly spend comparison (current vs previous)."""
    if not rows:
        return "_No weekly spend data available._"

    row = rows[0]
    current = row.get("current_week_cost", 0.0)
    previous = row.get("previous_week_cost", 0.0)
    delta = row.get("delta", 0.0)
    pct_change = row.get("pct_change", 0.0)
    trend = row.get("trend", "")

    lines = [
        "*Weekly Billing Trend*",
        f"- Last complete week: ${current:,.2f}",
        f"- Week before that: ${previous:,.2f}",
        f"- Change: {trend} {pct_change:+.2f}% (${delta:+,.2f})",
    ]
    return "\n".join(lines)


def format_daily_summary(rows: List[Dict]) -> str:
    """Format rows into a daily billing breakdown."""
    lines = ["*Daily Billing Breakdown (Past 4 Days)*"]
    for row in rows:
        day = row.get("day")
        daily_cost = row.get("daily_cost", 0.0)
        lines.append(f"- {day}: ${daily_cost:,.2f}")

    return "\n".join(lines)


FORMATTERS: Dict[str, Callable[[List[Dict]], str]] = {
    "monthly": format_monthly_summary,
    "daily": format_daily_summary,
    "weekly": format_weekly_summary,
}


def export_env_vars(summary_text: str, job_status: str = "SUCCESS", job_status_color: str = "#2EB886") -> None:
    """Export environment variables to GITHUB_ENV for Slack template substitution."""
    with open(os.environ["GITHUB_ENV"], "a") as f:
        f.write(f"JOB_STATUS={job_status}\n")
        f.write(f"JOB_STATUS_COLOR={job_status_color}\n")
        f.write("WORKFLOW_NAME=GCP Billing Report\n")
        f.write(f"BRANCH={os.getenv('GITHUB_REF_NAME', 'main')}\n")
        f.write(f"JOB_LOG_URL={os.getenv('GITHUB_SERVER_URL')}/{os.getenv('GITHUB_REPOSITORY')}/actions/runs/{os.getenv('GITHUB_RUN_ID')}\n")
        # Multiline block for summary
        f.write("BILLING_SUMMARY<<EOF\n")
        f.write(summary_text + "\n")
        f.write("EOF\n")


def main():
    api_url = os.getenv("API_URL")
    api_key = os.getenv("API_KEY")
    query_type = os.getenv("QUERY_TYPE", "monthly")  # default to monthly

    rows = fetch_stmo_results(api_url, api_key)

    if query_type not in FORMATTERS:
        raise ValueError(f"Unsupported query type: {query_type}")
    summary_text = FORMATTERS[query_type](rows)

    export_env_vars(summary_text)


if __name__ == "__main__":
    main()
