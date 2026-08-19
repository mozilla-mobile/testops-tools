#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for effnext's other-branch advisory check.

Why this exists: the check shipped broken twice in one session, both times FAILING SILENTLY and reporting a
clean "no other branch has this" — first because `git grep -E` was handed a `\\b`/`\\s` pattern it cannot
parse, then because `subprocess` was not imported and the resulting NameError was swallowed by a bare
`except`. A check that cannot distinguish "nothing found" from "nothing ran" is worse than no check, so the
surfacing behaviour is tested, not just the happy path.

    python -m unittest discover -s tae-conversion/tests -p '*tests.py'
"""

import os
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(TESTS_DIR), "tools")
sys.path.insert(0, TOOLS)

import effnext  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


class OtherBranchCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _git(self.tmp, "init", "-q", "-b", "main")
        _git(self.tmp, "config", "user.email", "t@example.com")
        _git(self.tmp, "config", "user.name", "t")
        os.makedirs(os.path.join(self.tmp, effnext.EFF_TESTS), exist_ok=True)
        base = os.path.join(self.tmp, effnext.EFF_TESTS, "Base.kt")
        with open(base, "w") as fh:
            fh.write("class Base { fun alreadyLandedTest() {} }\n")
        _git(self.tmp, "add", "-A")
        _git(self.tmp, "commit", "-qm", "base")
        # an unlanded conversion on another branch, absent from main
        _git(self.tmp, "checkout", "-q", "-b", "feature")
        with open(os.path.join(self.tmp, effnext.EFF_TESTS, "New.kt"), "w") as fh:
            fh.write("class New { fun pendingReviewTest() {} }\n")
        _git(self.tmp, "add", "-A")
        _git(self.tmp, "commit", "-qm", "pending")
        _git(self.tmp, "checkout", "-q", "main")
        # a backup branch carrying REJECTED work, which must never be reported
        _git(self.tmp, "checkout", "-q", "-b", "backup/rejected")
        with open(os.path.join(self.tmp, effnext.EFF_TESTS, "Dropped.kt"), "w") as fh:
            fh.write("class Dropped { fun rejectedFakerTest() {} }\n")
        _git(self.tmp, "add", "-A")
        _git(self.tmp, "commit", "-qm", "dropped")
        _git(self.tmp, "checkout", "-q", "main")

    def test_finds_unlanded_conversion_on_another_branch(self):
        hits = effnext.converted_on_other_branches(self.tmp, {"pendingReviewTest"})
        self.assertEqual(hits, {"pendingReviewTest": ["feature"]})

    def test_backup_branches_are_ignored(self):
        # Dropped/abandoned work lives on backup/*; reporting it would push genuinely outstanding tests out of
        # the pool (the two faker conversions are the real-world case).
        self.assertEqual(effnext.converted_on_other_branches(self.tmp, {"rejectedFakerTest"}), {})

    def test_absent_method_is_not_reported(self):
        self.assertEqual(effnext.converted_on_other_branches(self.tmp, {"neverWrittenTest"}), {})

    def test_no_methods_asked_about_is_cheap_and_empty(self):
        self.assertEqual(effnext.converted_on_other_branches(self.tmp, set()), {})

    def test_non_repo_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(effnext.converted_on_other_branches(d, {"anyTest"}), {})

    def test_failure_to_list_branches_is_surfaced_not_swallowed(self):
        real = effnext.subprocess.run

        def boom(*a, **k):
            if a and a[0][:2] == ["git", "for-each-ref"]:
                raise OSError("git unavailable")
            return real(*a, **k)

        effnext.subprocess.run = boom
        try:
            hits = effnext.converted_on_other_branches(self.tmp, {"pendingReviewTest"})
        finally:
            effnext.subprocess.run = real
        self.assertIn("__unchecked__", hits)

    def test_per_ref_failure_is_surfaced_not_swallowed(self):
        real = effnext.subprocess.run

        def boom(*a, **k):
            if a and a[0][:2] == ["git", "grep"]:
                raise subprocess.TimeoutExpired(cmd="git grep", timeout=1)
            return real(*a, **k)

        effnext.subprocess.run = boom
        try:
            hits = effnext.converted_on_other_branches(self.tmp, {"pendingReviewTest"})
        finally:
            effnext.subprocess.run = real
        self.assertIn("__unchecked__", hits)
        self.assertNotIn("pendingReviewTest", hits)


if __name__ == "__main__":
    unittest.main()
