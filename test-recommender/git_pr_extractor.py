"""
Git-first PR extractor for the release test recommender.

Given a list of commits between two release tags, produce a list of PR records
by parsing commit subjects locally. Falls back to `gh api /commits/<sha>/pulls`
only for commits where no PR number can be extracted from the subject.

Design goals:
  - Zero API calls for standard squash-merged PRs (the ~99% case in firefox-ios).
  - Explicit handling of Mergify backports, reverts, and known bot commits.
  - Orphan commits (no PR reference anywhere) are surfaced, not dropped.
  - Cross-validation samples the git-extracted result against the API to catch
    silent drift if commit conventions change.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional


# =============================================================================
# Data models
# =============================================================================


@dataclass
class GitCommit:
    """A commit as reported by git log (or the compare API)."""
    sha: str
    subject: str
    author_name: str
    # Aspirational: reserved for future author-domain filtering
    # (e.g. distinguishing @mozilla.com contributors from externals).
    # Populated but not read today.
    author_email: str
    additions: int = 0
    deletions: int = 0


@dataclass
class ExtractedPR:
    """A PR resolved from one or more commits."""
    number: int
    title: str
    author: str
    additions: int
    deletions: int
    commits: list[str] = field(default_factory=list)
    is_revert: bool = False
    is_backport: bool = False
    source: str = "git"          # "git" (from subject) or "api" (fallback)


@dataclass
class OrphanCommit:
    """A commit that could not be attributed to any PR."""
    sha: str
    subject: str
    author: str
    additions: int
    deletions: int
    reason: str                   # "bot_version_bump" | "no_pr_reference" | ...


@dataclass
class ExtractionResult:
    prs: list[ExtractedPR]
    orphans: list[OrphanCommit]
    warnings: list[str] = field(default_factory=list)


# =============================================================================
# Patterns
# =============================================================================


# "Refactor FXIOS-NNNNN <description> (#NNNNN)"
# "[TICKET-NNNN] - <description> (#NNNNN)"
# "Bump <package> from X.Y.Z to A.B.C ... (#NNNNN)"
PR_SUFFIX_RE = re.compile(r"\s*\(#(\d+)\)\s*$")

# "Merge pull request #NNNNN from mozilla-mobile/<branch-name>"
PR_MERGE_RE = re.compile(r"^Merge pull request #(\d+)\b")

# "Revert FXIOS-NNNNN <description> ... (#NNNNN)"
REVERT_PREFIX_RE = re.compile(r"^Revert\b", re.IGNORECASE)

# "[vNNN] <description>" — backport marker from Mergify or manual tag
BACKPORT_PREFIX_RE = re.compile(r"^\[(?:v\d+(?:\.\d+)*|backport)\]", re.IGNORECASE)

# Known bot authors whose commits are low-signal by construction.
# Value describes why they're orphans; the report groups by reason.
BOT_AUTHORS: dict[str, str] = {
    "releng-treescript[bot]": "bot_version_bump",
    "dependabot[bot]": "bot_dependency_bump",
    "github-actions[bot]": "bot_automated",
    "mozilla-mobile-l10n-bot": "bot_l10n",
}


# =============================================================================
# Core extraction
# =============================================================================


def strip_pr_suffix(subject: str) -> str:
    """Return the subject without the trailing `(#12345)` suffix."""
    return PR_SUFFIX_RE.sub("", subject).rstrip()


def extract_pr_number(subject: str) -> Optional[int]:
    """Try to find a PR number in the subject via known patterns.

    Priority: merge commit → suffix `(#N)`. Anything not matching yields None.
    Note: a bare `#N` in prose (e.g. "fixes #1234") is intentionally NOT matched
    to avoid false positives on issue references.
    """
    m = PR_MERGE_RE.match(subject)
    if m:
        return int(m.group(1))
    m = PR_SUFFIX_RE.search(subject)
    if m:
        return int(m.group(1))
    return None


def classify_commit(commit: GitCommit) -> tuple[Optional[int], dict]:
    """Return (pr_number, flags) for a single commit.

    flags is a dict with:
        is_revert: bool
        is_backport: bool
        bot_reason: str | None   — if this is a known bot commit
    """
    flags = {
        "is_revert": bool(REVERT_PREFIX_RE.search(commit.subject)),
        "is_backport": bool(BACKPORT_PREFIX_RE.search(commit.subject)),
        "bot_reason": BOT_AUTHORS.get(commit.author_name),
    }
    return extract_pr_number(commit.subject), flags


# =============================================================================
# API fallback (isolated so tests can inject a stub)
# =============================================================================


ApiFetcher = Callable[[str], list[dict]]
"""Callable that takes a repo-relative API path and returns parsed JSON.
Injected to keep the module testable without network I/O."""


def _default_api_fetcher(path: str) -> list[dict]:
    """Real implementation using the `gh` CLI. Raises on failure."""
    out = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"gh api {path} failed: {out.stderr}")
    return json.loads(out.stdout)


def resolve_pr_via_api(sha: str, repo: str, fetcher: ApiFetcher) -> Optional[dict]:
    """Fallback: ask GitHub which PR contains this commit. Returns the first
    matching PR payload, or None. Errors are swallowed to a None — the caller
    treats the commit as orphan and records a warning."""
    try:
        pulls = fetcher(f"repos/{repo}/commits/{sha}/pulls")
    except Exception:
        return None
    if not pulls:
        return None
    return pulls[0]


# =============================================================================
# Main entry
# =============================================================================


def build_prs_from_git(
    commits: list[GitCommit],
    repo: str,
    api_fetcher: Optional[ApiFetcher] = None,
) -> ExtractionResult:
    """Convert a list of git commits into (prs, orphans, warnings).

    Behavior:
      - Commit with a `(#N)` or `Merge pull request #N` subject → grouped by N.
      - Commit by a known bot author → orphan with reason from BOT_AUTHORS.
      - Commit without PR ref → API fallback; if API also silent → orphan.
    """
    fetch = api_fetcher or _default_api_fetcher

    pr_map: dict[int, ExtractedPR] = {}
    orphans: list[OrphanCommit] = []
    warnings: list[str] = []

    for commit in commits:
        pr_num, flags = classify_commit(commit)

        if pr_num is not None:
            pr = pr_map.get(pr_num)
            if pr is None:
                title = strip_pr_suffix(commit.subject)
                pr = ExtractedPR(
                    number=pr_num,
                    title=title,
                    author=commit.author_name,
                    additions=0,
                    deletions=0,
                    is_revert=flags["is_revert"],
                    is_backport=flags["is_backport"],
                    source="git",
                )
                pr_map[pr_num] = pr
            pr.commits.append(commit.sha)
            pr.additions += commit.additions
            pr.deletions += commit.deletions
            continue

        if flags["bot_reason"]:
            orphans.append(OrphanCommit(
                sha=commit.sha, subject=commit.subject,
                author=commit.author_name,
                additions=commit.additions, deletions=commit.deletions,
                reason=flags["bot_reason"],
            ))
            continue

        # No PR number and not a known bot → try API fallback
        pr_payload = resolve_pr_via_api(commit.sha, repo, fetch)
        if pr_payload:
            pr_num = pr_payload["number"]
            pr = pr_map.get(pr_num)
            if pr is None:
                pr = ExtractedPR(
                    number=pr_num,
                    title=pr_payload.get("title", commit.subject),
                    author=(pr_payload.get("user") or {}).get("login", commit.author_name),
                    additions=0, deletions=0,
                    is_revert=flags["is_revert"],
                    is_backport=flags["is_backport"],
                    source="api",
                )
                pr_map[pr_num] = pr
            pr.commits.append(commit.sha)
            pr.additions += commit.additions
            pr.deletions += commit.deletions
            warnings.append(
                f"Commit {commit.sha[:8]} required API fallback (no #N in subject: {commit.subject[:80]!r})"
            )
        else:
            orphans.append(OrphanCommit(
                sha=commit.sha, subject=commit.subject,
                author=commit.author_name,
                additions=commit.additions, deletions=commit.deletions,
                reason="no_pr_reference",
            ))

    prs = sorted(pr_map.values(), key=lambda p: p.number)
    return ExtractionResult(prs=prs, orphans=orphans, warnings=warnings)


# =============================================================================
# Cross-validation
# =============================================================================


def cross_validate_sample(
    result: ExtractionResult,
    commits: list[GitCommit],
    repo: str,
    api_fetcher: Optional[ApiFetcher] = None,
    sample_size: int = 5,
    rng: Optional[random.Random] = None,
) -> list[str]:
    """Pick N random git-sourced commits, verify their PR mapping against the
    API. Returns a list of mismatch warnings (empty = clean)."""
    fetch = api_fetcher or _default_api_fetcher
    rng = rng or random.Random(0)

    git_sourced_commits = [
        (c, pr) for c in commits
        for pr in result.prs
        if c.sha in pr.commits and pr.source == "git"
    ]
    if not git_sourced_commits:
        return []

    sample = rng.sample(
        git_sourced_commits, min(sample_size, len(git_sourced_commits)),
    )

    mismatches: list[str] = []
    for commit, git_pr in sample:
        api_pr = resolve_pr_via_api(commit.sha, repo, fetch)
        if not api_pr:
            mismatches.append(
                f"Commit {commit.sha[:8]}: git said PR #{git_pr.number}, API returned no PR"
            )
            continue
        if api_pr["number"] != git_pr.number:
            mismatches.append(
                f"Commit {commit.sha[:8]}: git said PR #{git_pr.number}, API says PR #{api_pr['number']}"
            )
    return mismatches
