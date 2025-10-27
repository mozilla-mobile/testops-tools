# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import re
import sys
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import requests


@dataclass
class PlayStoreDataPaths:
    """
    Data paths for extracting information from Google Play Store's nested JSON structure.
    These represent the array indices where specific data can be found in the AF_initDataCallback data.
    """

    # Base path to the app data
    BASE = [1, 2]

    # App information paths (relative to BASE)
    NAME = [0, 0]
    DEVELOPER = [37, 0]
    RATING = [51, 0, 0]
    RATING_COUNT = [51, 2, 0]
    DOWNLOADS = [13, 0]
    VERSION = [140, 0, 0, 0]
    CATEGORY = [79, 0, 0, 0]
    DESCRIPTION = [72, 0, 1]
    LAST_UPDATED = [145, 0, 0]
    LAUNCH_DATE = [10, 0]


def safe_nested_get(data: List, path: List[int], default: Any = None) -> Any:
    """Safely navigate nested list structures using a path of indices."""
    current = data
    try:
        for index in path:
            if not isinstance(current, list) or index >= len(current):
                return default
            current = current[index]
        return current
    except (IndexError, TypeError, KeyError):
        return default


def find_json_end(json_string: str) -> str:
    """Find where a JSON string actually ends by counting brackets and braces."""
    brace_count = 0
    bracket_count = 0

    for i, char in enumerate(json_string):
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
        elif char == "[":
            bracket_count += 1
        elif char == "]":
            bracket_count -= 1

        if brace_count == 0 and bracket_count == 0 and i > 0:
            return json_string[: i + 1]

    return json_string


def extract_json_from_html(html: str, package_id: str) -> Optional[List]:
    """Extract the JSON data from the Play Store HTML page."""
    pattern = r"AF_initDataCallback\(\{key:\s*'ds:5'.*?data:(.*?), sideChannel:"
    match = re.search(pattern, html, re.DOTALL)

    if not match:
        print(f"❌ Could not find AF_initDataCallback data for package: {package_id}")
        return None

    json_string = find_json_end(match.group(1).strip())

    try:
        return json.loads(json_string)
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode error: {e}")
        return None


def parse_app_data(json_data: List, package_id: str) -> Optional[Dict[str, Any]]:
    """Parse the extracted JSON data into a structured dictionary."""
    paths = PlayStoreDataPaths()

    base_data = safe_nested_get(json_data, paths.BASE)
    if base_data is None:
        print(f"❌ Could not find base data structure for package: {package_id}")
        return None

    app_info = {
        "package_id": package_id,
        "name": safe_nested_get(base_data, paths.NAME, "Unknown"),
        "developer": safe_nested_get(base_data, paths.DEVELOPER, "Unknown"),
        "rating": safe_nested_get(base_data, paths.RATING),
        "rating_count": safe_nested_get(base_data, paths.RATING_COUNT),
        "version": safe_nested_get(base_data, paths.VERSION, "Unknown"),
        "downloads": safe_nested_get(base_data, paths.DOWNLOADS, "Unknown"),
        "category": safe_nested_get(base_data, paths.CATEGORY, "Unknown"),
        "last_updated": safe_nested_get(base_data, paths.LAST_UPDATED, "Unknown"),
    }

    if app_info["name"] == "Unknown" or app_info["rating"] is None:
        print(f"⚠️  Warning: Missing critical data for package: {package_id}")
        return None

    return app_info


def get_app_rating(package_id: str, timeout: int = 15) -> Optional[Dict[str, Any]]:
    """Fetch app rating and other metadata from Google Play Store."""
    playstore_url = f"https://play.google.com/store/apps/details?id={package_id}"

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux i686; rv:144.0) Gecko/20100101 Firefox/144.0",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        response = requests.get(playstore_url, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ Error fetching Play Store page: {e}")
        return None

    json_data = extract_json_from_html(response.text, package_id)
    if json_data is None:
        return None

    return parse_app_data(json_data, package_id)


def load_previous_state(filepath: str) -> Optional[Dict[str, Any]]:
    """Load previous rating state from file."""
    try:
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                return json.load(f)
        return None
    except Exception as e:
        print(f"⚠️  Error loading previous state: {e}")
        return None


def save_current_state(filepath: str, data: Dict[str, Any]) -> None:
    """Save current rating state to file."""
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        print(f"✅ Saved current state to {filepath}")
    except Exception as e:
        print(f"❌ Error saving state: {e}")


def set_github_output(name: str, value: str) -> None:
    """Set GitHub Actions output variable."""
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"{name}={value}\n")
    else:
        print(f"Output: {name}={value}")


def main():
    package_id = os.getenv("PACKAGE_ID")
    package_name = os.getenv("PACKAGE_NAME", package_id)
    state_file = os.getenv("STATE_FILE", f"rating-state-{package_id}.json")

    if not package_id:
        print("❌ PACKAGE_ID environment variable not set")
        sys.exit(1)

    print(f"Checking rating for: {package_name}")
    print(f"Package ID: {package_id}")
    print(f"Run ID: {os.getenv('GITHUB_RUN_ID', 'local')}")
    print("=" * 70)

    # Get current rating from Play Store
    current_data = get_app_rating(package_id)
    if not current_data or current_data.get("rating") is None:
        print("❌ Failed to fetch current rating")
        sys.exit(1)

    current_rating = float(current_data["rating"])
    print(
        f"✅ Current rating: {current_rating} ⭐ ({current_data['rating_count']} ratings)"
    )
    print(f"   App: {current_data['name']}")
    print(f"   Version: {current_data['version']}")
    print(f"   Downloads: {current_data['downloads']}")

    # Load previous state
    previous_data = load_previous_state(state_file)

    rating_dropped = False
    old_rating = current_rating

    if previous_data and previous_data.get("rating"):
        previous_rating = float(previous_data["rating"])
        old_rating = previous_rating
        print(f"📊 Previous rating: {previous_rating} ⭐")

        # Check if rating dropped
        if current_rating < previous_rating:
            rating_drop = previous_rating - current_rating
            print(f"📉 RATING DROPPED by {rating_drop:.1f}!")
            rating_dropped = True
        elif current_rating > previous_rating:
            rating_increase = current_rating - previous_rating
            print(f"📈 Rating increased by {rating_increase:.1f} (no notification)")
        else:
            print(f"➡️  Rating unchanged {current_rating} ⭐")
    else:
        print("📝 First time checking - storing initial rating")

    # Save current state
    save_current_state(state_file, current_data)

    # Set GitHub Actions outputs
    set_github_output("rating_dropped", "true" if rating_dropped else "false")
    set_github_output("app_name", current_data["name"])
    set_github_output("old_rating", str(old_rating))
    set_github_output("new_rating", str(current_rating))
    set_github_output("rating_count", str(current_data["rating_count"]))
    set_github_output("version", current_data["version"])
    set_github_output("downloads", current_data["downloads"])

    print("=" * 70)
    if rating_dropped:
        print("🚨 Will send Slack notification")
    else:
        print("✅ No notification needed")


if __name__ == "__main__":
    main()
