import os
from pathlib import Path
import requests
import yaml
from typing import List, Set


USE_GITHUB_COMPARE = True  # Toggle this
RULES_FILE = "rules.yml"
OWNER = "mozilla-mobile"
REPO = "firefox-ios"

# Hardcoded for local testing
BASE_TAG = "firefox-v147.3"
HEAD_TAG = "firefox-v147.4"

IGNORED_DIRECTORIES = [
    ".github/workflows/",
    "taskcluster/",
    ".github/workflows",
]

IGNORED_FILENAMES = [
    ".swiftlint.yml",
    "README.md",
    "bitrise.yml",
    "version.txt",
]

IGNORED_EXACT_PATHS = [
    "firefox-ios/Client.xcodeproj/project.pbxproj",
    "firefox-ios/Client/Configuration/version.xcconfig",
    "taskcluster/requirements.txt",
]

IGNORED_EXTENSIONS = [
    ".strings",
    ".stringsdict",
]

def is_ignored_path(path: str) -> bool:
    p = path.lower()

    # Ignore test directories
    if "/tests/" in p or p.startswith("tests/"):
        return True
    if "/uitests/" in p or p.startswith("uitests/"):
        return True

    # Ignore specific directories
    for d in IGNORED_DIRECTORIES:
        if p.startswith(d) or f"/{d}" in p:
            return True

    # Ignore exact file paths
    for exact in IGNORED_EXACT_PATHS:
        if p == exact.lower():
            return True

    # Ignore specific filenames
    if Path(p).name in [f.lower() for f in IGNORED_FILENAMES]:
        return True

    # Ignore specific extensions
    if any(p.endswith(ext) for ext in IGNORED_EXTENSIONS):
        return True
    return False


# -------------------------------
# Load rules from YAML
# -------------------------------

def load_rules(filename: str):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    rules_path = os.path.join(script_dir, filename)

    with open(rules_path, "r") as f:
        config = yaml.safe_load(f)

    return config.get("rules", [])


# -------------------------------
# Map files to components
# -------------------------------

def map_files_to_components(files: List[str], rules) -> (Set[str], List[str]):
    impacted_components = set()
    unmatched_files = []

    for file_path in files:
        matched = False

        for rule in rules:
            prefix = rule["prefix"]
            components = rule["components"]

            if file_path.startswith(prefix):
                impacted_components.update(components)
                matched = True

        if not matched:
            unmatched_files.append(file_path)

    return impacted_components, unmatched_files


# -------------------------------
# Get changed files from GitHub
# -------------------------------

def get_changed_files(owner, repo, base, head):
    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{base}...{head}"
    headers = {"Accept": "application/vnd.github+json"}

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()

    all_files = [f["filename"] for f in data.get("files", [])]

    # Apply ignore filtering here
    filtered_files = [
        f for f in all_files if not is_ignored_path(f)
    ]

    print(f"\nTotal changed files (raw): {len(all_files)}")
    print(f"After filtering ignored paths: {len(filtered_files)}")

    return filtered_files

def get_impacted_components(base_tag: str, head_tag: str) -> list[str]:
    rules = load_rules(RULES_FILE)
    changed_files = get_changed_files(OWNER, REPO, base_tag, head_tag) 
    #filtered_files = [f for f in changed_files if not is_ignored_path(f)]
    components, unmatched = map_files_to_components(changed_files, rules)
    print(f"Unmatched files: {len(unmatched)}")
    return sorted(components)

# Debug
if __name__ == "__main__":
    components = get_impacted_components(BASE_TAG, HEAD_TAG)
    print("\nImpacted Components:")
    for c in components:
        print("-", c)
