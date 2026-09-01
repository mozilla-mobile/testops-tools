"""
Tests for git_pr_extractor.

Fixtures use real commit subjects from mozilla-mobile/firefox-ios, mostly from
the v151.2 → v151.3 and v150.0 → v151.0 ranges. See the file header of each
group for provenance.
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

# Make the module importable when running `python3 -m unittest` from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from git_pr_extractor import (
    BOT_AUTHORS,
    ExtractedPR,
    GitCommit,
    OrphanCommit,
    build_prs_from_git,
    classify_commit,
    cross_validate_sample,
    extract_pr_number,
    strip_pr_suffix,
)


REPO = "mozilla-mobile/firefox-ios"


# =============================================================================
# Real fixtures from firefox-ios
# =============================================================================


REAL_SUBJECTS = {
    # Standard squash (author | subject) — from v151.2...v151.3
    "squash_bugfix": (
        "Cyndi Chin",
        "Bugfix FXIOS-15833 [Quick Answers] clear key between environments (#33979)",
    ),
    "squash_refactor": (
        "Alexander Bangu",
        "Refactor FXIOS-15780 Reader mode Add custom readermode scheme (#33846)",
    ),
    "squash_add": (
        "Issam Mani",
        "Add FXIOS-15920 [WC] M3 logic for knockout phase (#34028)",
    ),
    # Non-FXIOS prefix (MTE ticket format)
    "squash_mte_prefix": (
        "dragosb01",
        "[MTE-5326] - fix for jump back in failures on iPad (#33983)",
    ),
    # Dependabot bump — bot author + standard suffix
    "dependabot_bump": (
        "dependabot[bot]",
        "Bump urllib3 from 2.6.3 to 2.7.0 in /firefox-ios/firefox-ios-tests/Tests/SyncIntegrationTests (#33982)",
    ),
    # l10n import — github-actions bot
    "l10n_import": (
        "github-actions[bot]",
        "Localize FOCUS [Strings] Import l10n from 05-25-2026 (#34002)",
    ),
    # Revert — starts with "Revert"
    "revert": (
        "Yoana Rios",
        "Revert FXIOS-15916 address bar fixes Bugfix for FXIOS-15917 frozen address bar  (#34020)",
    ),
    # Bot version bump — NO (#N) suffix, orphan
    "bot_version_bump_orphan": (
        "releng-treescript[bot]",
        "Automatic version bump CLOSED TREE NO BUG a=release",
    ),
    # Synthetic — merge commit style (not seen in firefox-ios but supported)
    "merge_commit": (
        "octocat",
        "Merge pull request #12345 from mozilla-mobile/some-branch",
    ),
    # Synthetic — backport prefix
    "backport_v151": (
        "Mergify bot",
        "[v151] Refactor FXIOS-15780 Reader mode Add custom readermode scheme (#33846)",
    ),
    # Synthetic — no PR ref, not a known bot → API fallback candidate
    "direct_push_no_pr": (
        "some_dev",
        "Emergency hotfix on release branch",
    ),
}


def make_commit(key: str, sha: str = None, adds: int = 10, dels: int = 5) -> GitCommit:
    author, subject = REAL_SUBJECTS[key]
    return GitCommit(
        sha=sha or f"sha_{key}",
        subject=subject,
        author_name=author,
        author_email=f"{author.replace(' ', '.').lower()}@example.com",
        additions=adds,
        deletions=dels,
    )


# =============================================================================
# extract_pr_number
# =============================================================================


class ExtractPRNumberTests(unittest.TestCase):
    def test_squash_suffix_standard(self):
        self.assertEqual(extract_pr_number(REAL_SUBJECTS["squash_bugfix"][1]), 33979)

    def test_squash_suffix_with_brackets_prefix(self):
        self.assertEqual(extract_pr_number(REAL_SUBJECTS["squash_mte_prefix"][1]), 33983)

    def test_merge_commit_style(self):
        self.assertEqual(extract_pr_number(REAL_SUBJECTS["merge_commit"][1]), 12345)

    def test_backport_prefix_still_extracts(self):
        self.assertEqual(extract_pr_number(REAL_SUBJECTS["backport_v151"][1]), 33846)

    def test_revert_still_extracts(self):
        self.assertEqual(extract_pr_number(REAL_SUBJECTS["revert"][1]), 34020)

    def test_no_pr_ref_returns_none(self):
        self.assertIsNone(extract_pr_number(REAL_SUBJECTS["bot_version_bump_orphan"][1]))
        self.assertIsNone(extract_pr_number(REAL_SUBJECTS["direct_push_no_pr"][1]))

    def test_issue_reference_in_prose_not_matched(self):
        # Guard against false positives: "#1234" in the middle should not be picked up
        self.assertIsNone(extract_pr_number("Bugfix — fixes #1234 in the widget"))

    def test_empty_subject(self):
        self.assertIsNone(extract_pr_number(""))


# =============================================================================
# strip_pr_suffix
# =============================================================================


class StripPRSuffixTests(unittest.TestCase):
    def test_strips_trailing_suffix(self):
        self.assertEqual(
            strip_pr_suffix("Bugfix FXIOS-15833 [Quick Answers] clear key (#33979)"),
            "Bugfix FXIOS-15833 [Quick Answers] clear key",
        )

    def test_no_suffix_unchanged(self):
        self.assertEqual(
            strip_pr_suffix("Automatic version bump"),
            "Automatic version bump",
        )


# =============================================================================
# classify_commit
# =============================================================================


class ClassifyCommitTests(unittest.TestCase):
    def test_normal_squash(self):
        pr, flags = classify_commit(make_commit("squash_bugfix"))
        self.assertEqual(pr, 33979)
        self.assertFalse(flags["is_revert"])
        self.assertFalse(flags["is_backport"])
        self.assertIsNone(flags["bot_reason"])

    def test_revert_flag(self):
        pr, flags = classify_commit(make_commit("revert"))
        self.assertEqual(pr, 34020)
        self.assertTrue(flags["is_revert"])

    def test_backport_flag(self):
        pr, flags = classify_commit(make_commit("backport_v151"))
        self.assertEqual(pr, 33846)
        self.assertTrue(flags["is_backport"])

    def test_bot_dependabot(self):
        pr, flags = classify_commit(make_commit("dependabot_bump"))
        # Dependabot squash-merges have (#N) too — classifier still finds it.
        # The bot flag is separate; downstream decides how to treat it.
        self.assertEqual(pr, 33982)
        self.assertEqual(flags["bot_reason"], "bot_dependency_bump")

    def test_bot_version_bump_no_pr(self):
        pr, flags = classify_commit(make_commit("bot_version_bump_orphan"))
        self.assertIsNone(pr)
        self.assertEqual(flags["bot_reason"], "bot_version_bump")


# =============================================================================
# build_prs_from_git — end-to-end, no API
# =============================================================================


class BuildPRsWithoutAPITests(unittest.TestCase):
    """Cases where API fallback is never invoked."""

    def test_single_squash_commit(self):
        commits = [make_commit("squash_refactor", sha="abc123", adds=100, dels=20)]
        result = build_prs_from_git(commits, REPO, api_fetcher=_never_called_fetcher)

        self.assertEqual(len(result.prs), 1)
        pr = result.prs[0]
        self.assertEqual(pr.number, 33846)
        self.assertEqual(pr.title, "Refactor FXIOS-15780 Reader mode Add custom readermode scheme")
        self.assertEqual(pr.author, "Alexander Bangu")
        self.assertEqual(pr.additions, 100)
        self.assertEqual(pr.deletions, 20)
        self.assertEqual(pr.source, "git")
        self.assertEqual(result.orphans, [])
        self.assertEqual(result.warnings, [])

    def test_multiple_commits_same_pr_aggregate_loc(self):
        # Two commits belonging to the same PR number aggregate additions/deletions
        commits = [
            make_commit("squash_add", sha="a1", adds=50, dels=10),
            make_commit("squash_add", sha="a2", adds=30, dels=5),
        ]
        result = build_prs_from_git(commits, REPO, api_fetcher=_never_called_fetcher)
        self.assertEqual(len(result.prs), 1)
        self.assertEqual(result.prs[0].additions, 80)
        self.assertEqual(result.prs[0].deletions, 15)
        self.assertEqual(result.prs[0].commits, ["a1", "a2"])

    def test_revert_and_backport_flags_preserved(self):
        commits = [
            make_commit("revert"),
            make_commit("backport_v151"),
        ]
        result = build_prs_from_git(commits, REPO, api_fetcher=_never_called_fetcher)
        by_num = {pr.number: pr for pr in result.prs}
        self.assertTrue(by_num[34020].is_revert)
        self.assertTrue(by_num[33846].is_backport)

    def test_bot_version_bump_becomes_orphan(self):
        commits = [make_commit("bot_version_bump_orphan")]
        result = build_prs_from_git(commits, REPO, api_fetcher=_never_called_fetcher)
        self.assertEqual(result.prs, [])
        self.assertEqual(len(result.orphans), 1)
        self.assertEqual(result.orphans[0].reason, "bot_version_bump")

    def test_mixed_realistic_batch(self):
        commits = [
            make_commit("squash_bugfix"),
            make_commit("squash_refactor"),
            make_commit("dependabot_bump"),
            make_commit("l10n_import"),
            make_commit("bot_version_bump_orphan"),
            make_commit("revert"),
            make_commit("backport_v151"),
        ]
        result = build_prs_from_git(commits, REPO, api_fetcher=_never_called_fetcher)

        # 5 real PRs (bot_version_bump has no PR → orphan; the rest all have (#N)).
        # Note: backport_v151 and squash_refactor share PR #33846, so they merge into one.
        pr_numbers = sorted(pr.number for pr in result.prs)
        self.assertEqual(pr_numbers, [33846, 33979, 33982, 34002, 34020])
        self.assertEqual(len(result.orphans), 1)
        self.assertEqual(result.warnings, [])


# =============================================================================
# build_prs_from_git — API fallback path
# =============================================================================


class BuildPRsWithAPIFallbackTests(unittest.TestCase):
    def test_direct_push_falls_back_to_api_and_resolves(self):
        commits = [make_commit("direct_push_no_pr", sha="def456", adds=15, dels=3)]

        def fetcher(path):
            self.assertEqual(path, "repos/mozilla-mobile/firefox-ios/commits/def456/pulls")
            return [{"number": 99999, "title": "Emergency hotfix (proper)", "user": {"login": "emergency_dev"}}]

        result = build_prs_from_git(commits, REPO, api_fetcher=fetcher)
        self.assertEqual(len(result.prs), 1)
        self.assertEqual(result.prs[0].number, 99999)
        self.assertEqual(result.prs[0].source, "api")
        self.assertEqual(result.prs[0].author, "emergency_dev")
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("required API fallback", result.warnings[0])

    def test_direct_push_api_returns_nothing_becomes_orphan(self):
        commits = [make_commit("direct_push_no_pr", sha="ghi789")]

        def fetcher(path):
            return []

        result = build_prs_from_git(commits, REPO, api_fetcher=fetcher)
        self.assertEqual(result.prs, [])
        self.assertEqual(len(result.orphans), 1)
        self.assertEqual(result.orphans[0].reason, "no_pr_reference")

    def test_api_failure_treated_as_orphan(self):
        commits = [make_commit("direct_push_no_pr", sha="jkl012")]

        def fetcher(path):
            raise RuntimeError("simulated network failure")

        result = build_prs_from_git(commits, REPO, api_fetcher=fetcher)
        self.assertEqual(result.prs, [])
        self.assertEqual(result.orphans[0].reason, "no_pr_reference")


# =============================================================================
# cross_validate_sample
# =============================================================================


class CrossValidateSampleTests(unittest.TestCase):
    def test_all_match_no_warnings(self):
        commits = [
            make_commit("squash_bugfix", sha="sha1"),
            make_commit("squash_refactor", sha="sha2"),
        ]
        result = build_prs_from_git(commits, REPO, api_fetcher=_never_called_fetcher)

        # API returns matching numbers → no mismatches
        def fetcher(path):
            if "sha1" in path:
                return [{"number": 33979}]
            if "sha2" in path:
                return [{"number": 33846}]
            return []

        mismatches = cross_validate_sample(
            result, commits, REPO, api_fetcher=fetcher, sample_size=2,
            rng=random.Random(42),
        )
        self.assertEqual(mismatches, [])

    def test_detects_mismatch(self):
        commits = [make_commit("squash_bugfix", sha="sha1")]
        result = build_prs_from_git(commits, REPO, api_fetcher=_never_called_fetcher)

        def fetcher(path):
            return [{"number": 99999}]   # wrong on purpose

        mismatches = cross_validate_sample(
            result, commits, REPO, api_fetcher=fetcher, sample_size=5,
            rng=random.Random(42),
        )
        self.assertEqual(len(mismatches), 1)
        self.assertIn("git said PR #33979", mismatches[0])
        self.assertIn("API says PR #99999", mismatches[0])

    def test_empty_result_returns_empty(self):
        result = build_prs_from_git([], REPO, api_fetcher=_never_called_fetcher)
        self.assertEqual(cross_validate_sample(result, [], REPO, api_fetcher=_never_called_fetcher), [])


# =============================================================================
# Helpers
# =============================================================================


def _never_called_fetcher(path):
    raise AssertionError(f"API fallback should NOT have been called for path: {path}")


if __name__ == "__main__":
    unittest.main()
