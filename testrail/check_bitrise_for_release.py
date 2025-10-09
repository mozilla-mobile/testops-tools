import os
import requests
import subprocess
from collections import defaultdict
import json

BITRISE_APP_ID = os.environ["BITRISE_APP_ID"]
LAST_TAG_FILE = "latest_tags.json"

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
    
    # Group by product (firefox / focus/klar)
    grouped = defaultdict(list)
    for b in successful:
        tag = b["tag"].lower()
        if "firefox" in tag:
            grouped["firefox"].append(b)
        elif "focus" in tag or "klar" in tag:
            grouped["focus/klar"].append(b)
        else:
            grouped["other"].append(b)

    latest_tags = {}

    # Order by triggered time, newest first
    for product, lst in grouped.items():
        latest = max(lst, key=lambda x: x.get("triggered_at") or "")
        latest_tags[product] = latest["tag"]
    
    print(f"Latest successful tags detected: {latest_tags}")

    return latest_tags

def read_last_tags() -> dict:
    try:
        with open(LAST_TAG_FILE, "r") as f:
            tags = json.load(f)
            print(f"Loaded previous tags: {tags}")
            return tags
    except FileNotFoundError:
        print("No previous tag file found. Creating new one...")
        return {}

def save_last_tags(tags: dict):
    with open(LAST_TAG_FILE, "w") as f:
        json.dump(tags, f, indent=2)
    print(f"Saved tags to {LAST_TAG_FILE}: {tags}")

def run_create_milestone(product, tag):
    release_name = f"{product.title()} {tag}".replace("-", " ")
    print(f"Triggering milestone creation for: {release_name} ({tag})")

    result = subprocess.run([
        "gh", "workflow", "run", "create-milestone.yml",
        "-f", f"release-name={release_name}",
        "-f", f"release-tag={tag}"
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Failed to trigger workflow for {product}: {result.stderr}")
    else:
        print(f"✅ Milestone workflow triggered successfully for {product}")

def main():
    print("Checking for new Bitrise tags...")
    latest_tags = get_latest_successful_tag()
    last_tags = read_last_tags()

    new_tags = {k: v for k, v in latest_tags.items() if last_tags.get(k) != v}

    if not new_tags:
        print("No new tags found.")
        return

    for product, tag in new_tags.items():
        last_tags[product] = tag
    save_last_tags(last_tags)

    for product, tag in new_tags.items():
        print(f"New tag detected for {product}: {tag} (last processed: {last_tags.get(product)})")
        run_create_milestone(product, tag)

    print("✅ All new milestones triggered successfully.")
    print(f"Current {LAST_TAG_FILE} content:")
    print(json.dumps(read_last_tags(), indent=2))

if __name__ == "__main__":
    main()
