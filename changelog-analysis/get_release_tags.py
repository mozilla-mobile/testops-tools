import os
import requests
from typing import List, Tuple

BITRISE_APP_ID = os.environ.get("BITRISE_APP_ID", "6c06d3a40422d10f")
BITRISE_TOKEN = os.environ["BITRISE_TOKEN"]

VALID_WORKFLOWS = {
    "release_promotion_push",       # Firefox
    "release_promotion_push_focus", # Focus
}

TAG_PREFIX = "firefox-v"


def _get_firefox_tags_from_bitrise() -> List[str]:
    """Return all unique firefox-v* tags from successful Bitrise release builds, newest-version first."""
    url = f"https://api.bitrise.io/v0.1/apps/{BITRISE_APP_ID}/builds?trigger_event_type=tag&limit=50"
    headers = {"accept": "application/json", "Authorization": BITRISE_TOKEN}

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    builds = response.json().get("data", [])

    tags = {
        b["tag"]
        for b in builds
        if (b.get("status_text") or "").lower() == "success"
        and b.get("tag", "").lower().startswith(TAG_PREFIX)
        and (b.get("triggered_workflow") or "").lower() in VALID_WORKFLOWS
    }

    def version_key(tag: str) -> tuple:
        try:
            return tuple(int(p) for p in tag.removeprefix(TAG_PREFIX).split("."))
        except ValueError:
            return (0,)

    return sorted(tags, key=version_key, reverse=True)


def get_tags() -> Tuple[str, str]:
    """Return (base_tag, head_tag) — the two latest firefox-v* tags from Bitrise."""
    tags = _get_firefox_tags_from_bitrise()

    if len(tags) < 2:
        raise RuntimeError(
            f"Need at least 2 firefox-v* tags from Bitrise, found {len(tags)}: {tags}"
        )

    head_tag, base_tag = tags[0], tags[1]
    print(f"Tags from Bitrise: {base_tag} → {head_tag}")
    return base_tag, head_tag


if __name__ == "__main__":
    base, head = get_tags()
    print(f"Base: {base}")
    print(f"Head: {head}")
