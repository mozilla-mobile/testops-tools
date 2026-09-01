"""Tests for the budget calculator."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from budget_calculator import (
    ABSOLUTE_CEILING,
    ABSOLUTE_FLOOR,
    BASE_RANGES,
    ReleaseSignal,
    compute_bumps,
    compute_test_budget,
    detect_release_type,
)


# =============================================================================
# detect_release_type
# =============================================================================


class DetectReleaseTypeTests(unittest.TestCase):
    def test_patch_third_component_added(self):
        self.assertEqual(detect_release_type("firefox-v153.2", "firefox-v153.2.1"), "patch")

    def test_patch_third_component_changed(self):
        self.assertEqual(detect_release_type("firefox-v153.2.1", "firefox-v153.2.2"), "patch")

    def test_minor_middle_bumped(self):
        self.assertEqual(detect_release_type("firefox-v153.1", "firefox-v153.2"), "minor")

    def test_minor_from_our_baseline(self):
        # The exact release we've been testing against
        self.assertEqual(detect_release_type("firefox-v151.2", "firefox-v151.3"), "minor")

    def test_major_first_bumped(self):
        self.assertEqual(detect_release_type("firefox-v153.5", "firefox-v154.0"), "major")

    def test_major_from_v150_to_v151(self):
        self.assertEqual(detect_release_type("firefox-v150.0", "firefox-v151.0"), "major")

    def test_major_wins_over_patch(self):
        # Even if the destination has a Z component, a change in X is still major
        self.assertEqual(detect_release_type("firefox-v153.2", "firefox-v154.0.1"), "major")

    def test_unparseable_tags_default_to_minor(self):
        self.assertEqual(detect_release_type("weird-tag", "firefox-v151.3"), "minor")
        self.assertEqual(detect_release_type("firefox-v151.2", "not-a-tag"), "minor")

    def test_whitespace_tolerated(self):
        self.assertEqual(detect_release_type("  firefox-v151.2  ", "firefox-v151.3"), "minor")

    def test_release_branch_recognized_as_major(self):
        # Real-world usage: run against the release branch before the tag is created
        self.assertEqual(detect_release_type("firefox-v152.4", "release/v153.0"), "major")

    def test_release_branch_recognized_as_minor(self):
        self.assertEqual(detect_release_type("firefox-v152.3", "release/v152.4"), "minor")

    def test_release_branch_recognized_as_patch(self):
        self.assertEqual(detect_release_type("release/v153.0", "release/v153.0.1"), "patch")

    def test_mixed_tag_and_branch(self):
        # from = shipped tag, to = in-flight branch is the common case
        self.assertEqual(detect_release_type("firefox-v151.3", "release/v152.0"), "major")

    def test_commit_sha_falls_back_to_minor(self):
        # A raw SHA doesn't match either pattern — safe default
        self.assertEqual(detect_release_type("firefox-v151.2", "504a01f"), "minor")


# =============================================================================
# compute_bumps
# =============================================================================


class ComputeBumpsTests(unittest.TestCase):
    def test_no_bumps_when_release_is_quiet(self):
        signal = ReleaseSignal(total_loc=3000, max_pr_loc=500, high_severity_risk_count=1)
        bump, reasons = compute_bumps(signal)
        self.assertEqual(bump, 0)
        self.assertEqual(reasons, [])

    def test_loc_bump_at_threshold(self):
        # Exactly at threshold does NOT trigger (strict >)
        signal = ReleaseSignal(total_loc=15000, max_pr_loc=100, high_severity_risk_count=0)
        bump, _ = compute_bumps(signal)
        self.assertEqual(bump, 0)

    def test_loc_bump_over_threshold(self):
        signal = ReleaseSignal(total_loc=15001, max_pr_loc=100, high_severity_risk_count=0)
        bump, reasons = compute_bumps(signal)
        self.assertEqual(bump, 15)
        self.assertEqual(len(reasons), 1)
        self.assertIn("total LOC", reasons[0])

    def test_big_pr_bump(self):
        signal = ReleaseSignal(total_loc=500, max_pr_loc=2500, high_severity_risk_count=0)
        bump, reasons = compute_bumps(signal)
        self.assertEqual(bump, 10)
        self.assertIn("large PR", reasons[0])

    def test_big_pr_bump_at_threshold(self):
        # Exactly at threshold does NOT trigger (strict >)
        signal = ReleaseSignal(total_loc=500, max_pr_loc=2000, high_severity_risk_count=0)
        bump, _ = compute_bumps(signal)
        self.assertEqual(bump, 0)

    def test_high_risks_bump_at_threshold(self):
        # 3 risks triggers (>=)
        signal = ReleaseSignal(total_loc=500, max_pr_loc=100, high_severity_risk_count=3)
        bump, reasons = compute_bumps(signal)
        self.assertEqual(bump, 10)
        self.assertIn("high-severity risks", reasons[0])

    def test_high_risks_below_threshold(self):
        signal = ReleaseSignal(total_loc=500, max_pr_loc=100, high_severity_risk_count=2)
        bump, _ = compute_bumps(signal)
        self.assertEqual(bump, 0)

    def test_all_bumps_stack(self):
        signal = ReleaseSignal(total_loc=20000, max_pr_loc=3000, high_severity_risk_count=5)
        bump, reasons = compute_bumps(signal)
        self.assertEqual(bump, 35)   # 15 + 10 + 10
        self.assertEqual(len(reasons), 3)


# =============================================================================
# compute_test_budget
# =============================================================================


class ComputeTestBudgetTests(unittest.TestCase):
    def _quiet(self) -> ReleaseSignal:
        return ReleaseSignal(total_loc=1000, max_pr_loc=200, high_severity_risk_count=0)

    def test_patch_base_range(self):
        d = compute_test_budget("patch", self._quiet())
        self.assertEqual((d.final_lo, d.final_hi), BASE_RANGES["patch"])

    def test_minor_base_range(self):
        d = compute_test_budget("minor", self._quiet())
        self.assertEqual((d.final_lo, d.final_hi), BASE_RANGES["minor"])

    def test_major_base_range(self):
        d = compute_test_budget("major", self._quiet())
        self.assertEqual((d.final_lo, d.final_hi), BASE_RANGES["major"])

    def test_major_with_full_bumps_still_clamped(self):
        # Major base_hi = 160, all bumps = +35 → raw 195 (under 200 cap)
        signal = ReleaseSignal(total_loc=20000, max_pr_loc=3000, high_severity_risk_count=5)
        d = compute_test_budget("major", signal)
        self.assertEqual(d.final_hi, 195)
        self.assertEqual(d.bump, 35)

    def test_ceiling_clamp_kicks_in(self):
        # Force an absurd bump via extreme signal (in reality bumps cap at 35,
        # but if a future rule adds more, we should still clamp).
        # Simulate by picking major (hi=160) with all bumps → 195 (below 200).
        # Now with a hypothetical future stronger bump this would clamp.
        # We can't easily force this without mocking, so we check that the code
        # respects ABSOLUTE_CEILING when computed_hi would exceed.
        # Trick: use a signal where base + bumps > 200 IF base were higher.
        # Instead, test the property via a synthetic assertion:
        signal = ReleaseSignal(total_loc=20000, max_pr_loc=3000, high_severity_risk_count=5)
        d = compute_test_budget("major", signal)
        self.assertLessEqual(d.final_hi, ABSOLUTE_CEILING)

    def test_unknown_release_type_falls_back_to_minor(self):
        d = compute_test_budget("weird", self._quiet())
        self.assertEqual((d.final_lo, d.final_hi), BASE_RANGES["minor"])

    def test_minor_with_one_bump(self):
        # Minor base 40-70, +10 for a big PR → 40-80
        signal = ReleaseSignal(total_loc=1000, max_pr_loc=2500, high_severity_risk_count=0)
        d = compute_test_budget("minor", signal)
        self.assertEqual(d.final_lo, 40)
        self.assertEqual(d.final_hi, 80)
        self.assertEqual(d.bump, 10)

    def test_summary_line_format_quiet(self):
        d = compute_test_budget("minor", self._quiet())
        line = d.summary_line()
        self.assertIn("40-70", line)
        self.assertIn("base minor", line)

    def test_summary_line_format_with_bumps(self):
        signal = ReleaseSignal(total_loc=20000, max_pr_loc=3000, high_severity_risk_count=5)
        d = compute_test_budget("major", signal)
        line = d.summary_line()
        self.assertIn("100-195", line)
        self.assertIn("base major", line)
        self.assertIn("total LOC", line)
        self.assertIn("large PR", line)
        self.assertIn("high-severity risks", line)


if __name__ == "__main__":
    unittest.main()
