import os
import requests
from collections import defaultdict
from pathlib import Path
import json


BITRISE_APP_ID = os.environ["BITRISE_APP_ID"]
JENKINS_URL = os.environ.get("JENKINS_URL", "")
JENKINS_USER = os.environ.get("JENKINS_USER", "")
JENKINS_API_TOKEN = os.environ.get("JENKINS_API_TOKEN", "")
JENKINS_JOB_NAME = os.environ.get("JENKINS_JOB_NAME", "create-milestone")

BASE_DIR = Path(__file__).resolve().parent
LAST_TAG_FILE = BASE_DIR / "latest_tags.json"

# Filter by a specific workflow
VALID_WORKFLOWS = {
    "release_promotion_push",        # Firefox
    "release_promotion_push_focus",  # Focus
}

def get_latest_successful_tag():
    url = f"https://api.bitrise.io/v0.1/apps/{BITRISE_APP_ID}/builds?trigger_event_type=tag"
    token = ''
    headers = {
        'accept': 'application/json',
        'Authorization': token
    }
    response = requests.get(url, headers=headers)
    builds = response.json()["data"]
    successful = [
        b for b in builds
        if (b.get("status_text") or "").lower() == "success"
        and b.get("tag")
        and (b.get("triggered_workflow") or "").lower() in VALID_WORKFLOWS
    ]
    if not successful:
        raise Exception("No successful builds with tag found (after filtering).")

    # Group by product (firefox / focus/klar / other)
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for b in successful:
        tag = b["tag"].lower()
        if "firefox" in tag:
            grouped["firefox"].append(b)
        elif "focus" in tag or "klar" in tag:
            grouped["focus/klar"].append(b)
        else:
            grouped["other"].append(b)

    latest_info: Dict[str, Dict[str, Any]] = {}

    CONFIGS_PER_BUILD = 2  # A real build produces 2 Bitrise entries

    for product, lst in grouped.items():
        latest_build = max(lst, key=lambda x: x.get("triggered_at") or "")
        latest_tag = latest_build["tag"]

        same_tag_builds = [b for b in lst if b["tag"] == latest_tag]
        count = len(same_tag_builds)

        if count == 0:
            rc_number = 0
        else:
            # Two workflows run per build
            # 1–2 -> 1, 3–4 -> 2, etc.
            rc_number = (count + CONFIGS_PER_BUILD - 1) // CONFIGS_PER_BUILD

        latest_info[product] = {
            "tag": latest_tag,
            "rc_number": rc_number,
        }

    print(f"Latest successful info detected: {latest_info}")
    return latest_info

def read_last_tags() -> dict:
    """
    Expected (new) format:
      {
        "firefox": {
          "tag": "v145.0-...firefox...",
          "build_slugs": ["slug1", "slug2"]
        },
        ...
      }
    """
    try:
        with open(LAST_TAG_FILE, "r") as f:
            raw = json.load(f)
            print(f"Loaded previous state: {raw}")
    except FileNotFoundError:
        print("No previous tag file found. Creating new one...")
        return {}

    # Normalize any old string-only entries to new dict format
    state: Dict[str, Any] = {}

    for product, value in raw.items():
        if isinstance(value, str):
            # old format: just a tag string
            state[product] = {"tag": value, "rc_number": 0}
        elif isinstance(value, dict):
            state[product] = {
                "tag": value.get("tag"),
                "rc_number": value.get("rc_number", 0),
            }
        else:
            state[product] = {"tag": None, "rc_number": 0}

    return state

def save_last_tags(tags: dict):
    with open(LAST_TAG_FILE, "w") as f:
        json.dump(tags, f, indent=2)
    print(f"Saved tags to {LAST_TAG_FILE}: {tags}")

def extract_version_from_tag(tag: str) -> str:
    """
    Extracts the version from tags like 'firefox-v145.0' -> '145.0'.
    Adjust if your tag format changes.
    """
    if not tag:
        return tag
    # Take last part after '-' and strip leading 'v'
    last_part = tag.split("-")[-1]
    return last_part.lstrip("vV")

def run_create_milestone(product, tag, rc_number: int):
    version = extract_version_from_tag(tag)
    product_name = product.title()

    # Base name: first build for that tag
    release_name = f"Build Validation sign-off - {product_name} RC {version}"

    # For RC2, RC3, ... append "build N"
    if rc_number > 1:
        release_name = f"{release_name} build {rc_number}"

    print(f"Triggering milestone creation for: {release_name}")

    # Validate required Jenkins environment variables
    if not all([JENKINS_URL, JENKINS_USER, JENKINS_API_TOKEN]):
        missing_vars = []
        if not JENKINS_URL:
            missing_vars.append("JENKINS_URL")
        if not JENKINS_USER:
            missing_vars.append("JENKINS_USER")
        if not JENKINS_API_TOKEN:
            missing_vars.append("JENKINS_API_TOKEN")

        error_msg = f"❌ Missing required Jenkins environment variables: {', '.join(missing_vars)}"
        print(error_msg)
        raise ValueError(error_msg)

    # Trigger Jenkins job with parameters
    try:
        jenkins_job_url = f"{JENKINS_URL}/job/{JENKINS_JOB_NAME}/buildWithParameters"

        params = {
            "RELEASE_NAME": release_name,
            "RELEASE_TAG": tag
        }

        # DEBUG: Print values (will be masked by Jenkins)
        print(f"DEBUG: JENKINS_URL = {JENKINS_URL}")
        print(f"DEBUG: JENKINS_JOB_NAME = {JENKINS_JOB_NAME}")
        print(f"DEBUG: JENKINS_USER = {JENKINS_USER}")
        print(f"DEBUG: JENKINS_API_TOKEN length = {len(JENKINS_API_TOKEN) if JENKINS_API_TOKEN else 0}")
        print(f"DEBUG: Full URL = {jenkins_job_url}")

        response = requests.post(
            jenkins_job_url,
            params=params,
            auth=(JENKINS_USER, JENKINS_API_TOKEN),
            timeout=30
        )

        if response.status_code in [200, 201]:
            print(f"✅ Jenkins job triggered successfully for {product}")
            print(f"   Job URL: {JENKINS_URL}/job/{JENKINS_JOB_NAME}")
        else:
            error_msg = f"Failed to trigger Jenkins job for {product}. Status: {response.status_code}"
            print(f"❌ {error_msg}")
            print(f"   Response: {response.text}")
            raise Exception(error_msg)
    except requests.exceptions.RequestException as e:
        error_msg = f"Error triggering Jenkins job for {product}: {str(e)}"
        print(f"❌ {error_msg}")
        raise

def run_handle_new_rc(product, tag, new_build):
    """
    Called when tag is the same, but new builds appear.
    """
    print("")
    print("========================================")
    print(f"New RC detected for {product} / {tag}")
    print(f"New build(s): {new_build}")
    print("========================================")
    print("")

def main():
    print("Checking for new Bitrise tags / RCs...")
    latest_info = get_latest_successful_tag()
    last_state = read_last_tags()

    print("Latest info:", latest_info)
    print("Previous state:", last_state)

    updated_state: Dict[str, Any] = dict(last_state)

    # For each product (firefox, focus/klar, other)
    for product, info in latest_info.items():
        print(latest_info)
        latest_tag = info["tag"]
        latest_rc = info["rc_number"]

        prev = last_state.get(product)
        prev_tag = prev["tag"] if prev else None
        prev_rc = prev["rc_number"] if prev else 0

        # Case 1: tag changed → new version (first RC for that tag)
        if prev_tag != latest_tag:
            print(f"[{product}] New tag detected: {latest_tag} (previous: {prev_tag})")
            # Create milestone for RC1 (or whatever number len(latest_slugs) is)
            run_create_milestone(product, latest_tag, latest_rc)

            updated_state[product] = {
                "tag": latest_tag,
                "rc_number": latest_rc,
            }
            continue

        # Case 2: same tag → check for new RC(s)
        if latest_rc > prev_rc:
            print(f"[{product}] Same tag {latest_tag}, RC increased: {prev_rc} → {latest_rc}")
            run_handle_new_rc(product, latest_tag, latest_rc)
            run_create_milestone(product, latest_tag, latest_rc)
        else:
            print(f"[{product}] No new RC for tag {latest_tag} (rc={latest_rc}).")

        updated_state[product] = {
            "tag": latest_tag,
            "rc_number": latest_rc,
        }

    save_last_tags(updated_state)
    print("✅ All new milestones triggered successfully.")
    print(f"Current {LAST_TAG_FILE} content:")
    print(json.dumps(read_last_tags(), indent=2))


if __name__ == "__main__":
    main()
