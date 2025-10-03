import os
import requests


def main():
    api_url = os.getenv("API_URL")
    api_key = os.getenv("API_KEY")

    # Call the STMO API
    response = requests.get(api_url, params={"api_key": api_key})
    response.raise_for_status()
    data = response.json()

    rows = data["query_result"]["data"]["rows"]

    # Build monthly breakdown
    lines = ["*Monthly Billing Breakdown*"]
    total_sum = 0.0
    for row in rows:
        month = row.get("month")
        total_cost = row.get("total_cost", 0.0)
        total_sum += total_cost
        lines.append(f"- {month}: ${total_cost:,.2f}")

    # Add yearly total at the end
    lines.append(f"\n*Yearly Total:* ${total_sum:,.2f}")

    summary_text = "\n".join(lines)

    # Derive status color (always success unless you add logic)
    job_status = "SUCCESS"
    job_status_color = "#2EB886"  # green stripe

    # Export env vars for Slack templating
    with open(os.environ["GITHUB_ENV"], "a") as f:
        f.write(f"JOB_STATUS={job_status}\n")
        f.write(f"JOB_STATUS_COLOR={job_status_color}\n")
        f.write("WORKFLOW_NAME=GCP Billing Report\n")
        f.write(f"BRANCH={os.getenv('GITHUB_REF_NAME', 'main')}\n")
        f.write(f"JOB_LOG_URL={os.getenv('GITHUB_SERVER_URL')}/{os.getenv('GITHUB_REPOSITORY')}/actions/runs/{os.getenv('GITHUB_RUN_ID')}\n")
        # Escape newlines for Slack templating
        f.write("BILLING_SUMMARY<<EOF\n")
        f.write(summary_text + "\n")
        f.write("EOF\n")


if __name__ == "__main__":
    main()
