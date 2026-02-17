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


def format_weekly_summary(rows: List[Dict]) -> tuple[str, str]:
    """Format rows into an ALERT/NO ALERT weekly budget status.
    Returns (summary_text, billing_color) tuple.
    """
    if not rows:
        return "_No weekly spend data available._", "#2EB886"

    row = rows[0]
    current          = row.get("current_week_cost", 0.0)
    weekly_budget    = row.get("weekly_budget", 0.0)
    over_weekly      = row.get("over_weekly_budget", False)
    ytd_actual       = row.get("ytd_actual", 0.0)
    ytd_budget       = row.get("ytd_budget", 0.0)
    over_ytd         = row.get("over_ytd_budget", False)

    weekly_emoji  = "🔴" if over_weekly else "✅"
    weekly_status = "OVER BUDGET" if over_weekly else "WITHIN BUDGET"
    ytd_emoji     = "🔴" if over_ytd else "✅"
    ytd_status    = "OVER BUDGET" if over_ytd else "WITHIN BUDGET"

    lines = [
        "*Weekly Billing Status*",
        f"- Previous week {weekly_emoji} *{weekly_status}*: budget ${weekly_budget:,.2f}, actual ${current:,.2f}",
        f"- YTD {ytd_emoji} *{ytd_status}*: budget ${ytd_budget:,.2f}, actual ${ytd_actual:,.2f}",
    ]

    task_delta_query_url = os.getenv("TASK_DELTA_QUERY_URL")
    if task_delta_query_url:
        lines.append(f"\n<{task_delta_query_url}|View CI Task Volume Changes>")

    # Red if either metric is over budget, green if both within budget
    billing_color = "#ff0000" if (over_weekly or over_ytd) else "#36a64f"

    return "\n".join(lines), billing_color


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
        f.write("WORKFLOW_NAME=Mobile Infra Billing: GCP\n")
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

    result = FORMATTERS[query_type](rows)

    # Weekly formatter returns (text, billing_color) tuple
    if isinstance(result, tuple):
        summary_text, billing_color = result
        export_env_vars(summary_text, job_status_color=billing_color)
    else:
        export_env_vars(result)


if __name__ == "__main__":
    main()
