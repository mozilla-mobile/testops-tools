import os
import requests
import subprocess

BITRISE_APP_ID = os.environ["BITRISE_APP_ID"]
LAST_TAG_FILE = "last_tag.txt"

def get_latest_successful_tag():
    url = f"https://api.bitrise.io/v0.1/apps/{BITRISE_APP_ID}/builds?trigger_event_type=tag"
    token = ''
    headers = {'accept': 'application/json',
                               'Authorization': token}
    response = requests.get(url, headers=headers)
    builds = response.json()["data"]

    successful = [b for b in builds if b["status_text"] == "success" and b.get("tag")]
    if not successful:
        raise Exception("No successful builds with tag found")

    # Order by triggered time, newest first
    latest = sorted(successful, key=lambda b: b["triggered_at"], reverse=True)[0]
    return latest["tag"]

def read_last_tag():
    if os.path.exists(LAST_TAG_FILE):
        with open(LAST_TAG_FILE) as f:
            return f.read().strip()
    return ""

def save_last_tag(tag):
    with open(LAST_TAG_FILE, "w") as f:
        f.write(tag)

def run_create_milestone(tag):
    release_name = tag.replace("-", " ").title()
    print(f"Triggering milestone creation for: {release_name} ({tag})")

    result = subprocess.run([
        "gh", "workflow", "run", "create-milestone.yml",
        "-f", f"release-name={release_name}",
        "-f", f"release-tag={tag}"
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print("Failed to trigger workflow:")
        print(result.stderr)
        exit(1)

    print("Milestone workflow triggered successfully.")

def main():
    latest_tag = get_latest_successful_tag()
    last_tag = read_last_tag()

    if latest_tag != last_tag:
        print(f"New tag detected: {latest_tag} (last processed: {last_tag})")
        run_create_milestone(latest_tag)
        save_last_tag(latest_tag)
    else:
        print("No new tag found.")

if __name__ == "__main__":
    main()
