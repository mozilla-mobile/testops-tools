import os
from pathlib import Path
import requests
import yaml
from typing import List, Set, Tuple

RULES_FILE = "rules.yml"
OWNER = "mozilla-mobile"
REPO = "firefox-ios"
TAG_PREFIX = "firefox-v"

IGNORED_DIRECTORIES = [
    ".github/workflows/",
    "taskcluster/",
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


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def get_all_release_tags(owner: str, repo: str, prefix: str = TAG_PREFIX) -> List[str]:
    """Return all release tags matching prefix, sorted by version descending."""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/matching-refs/tags/{prefix}"
    all_tags = []

    while url:
        response = requests.get(url, headers=_github_headers())
        response.raise_for_status()
        all_tags.extend(ref["ref"].removeprefix("refs/tags/") for ref in response.json())

        url = None
        for part in response.headers.get("Link", "").split(","):
            if 'rel="next"' in part:
                url = part[part.index("<") + 1: part.index(">")]
                break

    def version_key(tag: str) -> tuple:
        try:
            return tuple(int(p) for p in tag.removeprefix(prefix).split("."))
        except ValueError:
            return (0,)

    all_tags.sort(key=version_key, reverse=True)
    return all_tags


def get_base_tag(head_tag: str, owner: str = OWNER, repo: str = REPO,
                 prefix: str = TAG_PREFIX) -> str:
    """Return the latest released tag with a lower version than head_tag."""
    tags = get_all_release_tags(owner, repo, prefix)

    def version_tuple(tag: str) -> tuple:
        try:
            return tuple(int(p) for p in tag.removeprefix(prefix).split("."))
        except ValueError:
            return (0,)

    head_version = version_tuple(head_tag)

    for tag in tags:  # already sorted descending
        if version_tuple(tag) < head_version:
            return tag

    raise ValueError(f"No released tag before '{head_tag}' found in {owner}/{repo}")


def is_ignored_path(path: str) -> bool:
    p = path.lower()

    if "/tests/" in p or p.startswith("tests/"):
        return True
    if "/uitests/" in p or p.startswith("uitests/"):
        return True

    for d in IGNORED_DIRECTORIES:
        if p.startswith(d) or f"/{d}" in p:
            return True

    for exact in IGNORED_EXACT_PATHS:
        if p == exact.lower():
            return True

    if Path(p).name in [f.lower() for f in IGNORED_FILENAMES]:
        return True

    if any(p.endswith(ext) for ext in IGNORED_EXTENSIONS):
        return True

    return False


def load_rules(filename: str):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(script_dir, filename)) as f:
        return yaml.safe_load(f).get("rules", [])


def map_files_to_components(files: List[str], rules) -> Tuple[Set[str], List[str]]:
    impacted: Set[str] = set()
    unmatched: List[str] = []

    for file_path in files:
        matched = False
        for rule in rules:
            if file_path.startswith(rule["prefix"]):
                impacted.update(rule["components"])
                matched = True
        if not matched:
            unmatched.append(file_path)

    return impacted, unmatched


def _release_branch(tag: str) -> str:
    # firefox-v150.2 -> release/v150.2
    version = tag.rsplit("-v", 1)[-1]
    return f"release/v{version}"


def get_changed_files(owner: str, repo: str, base: str, head: str) -> List[str]:
    base_ref = _release_branch(base)
    head_ref = _release_branch(head)
    commit_shas = []
    page = 1
    while True:
        response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/compare/{base_ref}...{head_ref}",
            headers=_github_headers(),
            params={"per_page": 100, "page": page},
        )
        response.raise_for_status()
        commits = response.json().get("commits", [])
        commit_shas.extend(c["sha"] for c in commits)
        if len(commits) < 100:
            break
        page += 1

    all_files: Set[str] = set()
    for sha in commit_shas:
        response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}",
            headers=_github_headers(),
        )
        response.raise_for_status()
        all_files.update(f["filename"] for f in response.json().get("files", []))

    filtered = [f for f in sorted(all_files) if not is_ignored_path(f)]
    print(f"Total changed files (raw): {len(all_files)}")
    print(f"After filtering ignored paths: {len(filtered)}")
    return filtered


def get_impacted_components(base_tag: str, head_tag: str,
                             owner: str = OWNER, repo: str = REPO) -> List[str]:
    rules = load_rules(RULES_FILE)
    changed_files = get_changed_files(owner, repo, base_tag, head_tag)
    components, unmatched = map_files_to_components(changed_files, rules)
    print(f"Unmatched files: {len(unmatched)}")
    return sorted(components)
