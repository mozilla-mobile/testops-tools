"""Tests for android/budget.py."""

from __future__ import annotations

import unittest

from android import budget as bd


def signal(**kw) -> bd.BuildSignal:
    return bd.BuildSignal(**kw)


class TestDetectTier(unittest.TestCase):
    def test_no_app_code_and_quiet_engine_is_silent(self):
        """The final-beta-to-RC shape: the RC is a straight copy."""
        self.assertEqual(
            bd.detect_tier(signal(app_product_files=0, engine_is_material=False)),
            "silent")

    def test_no_app_code_but_material_engine(self):
        """40% of measured ranges touch no product code; when the engine moved
        they still need a real budget."""
        self.assertEqual(
            bd.detect_tier(signal(app_product_files=0, engine_is_material=True)),
            "engine_only")

    def test_tier_boundaries(self):
        for n, tier in [(1, "light"), (3, "light"), (4, "moderate"),
                        (10, "moderate"), (11, "heavy"), (21, "heavy")]:
            self.assertEqual(bd.detect_tier(signal(app_product_files=n)), tier, n)


class TestBumps(unittest.TestCase):
    def test_no_bumps(self):
        bump, reasons = bd.compute_bumps(signal())
        self.assertEqual((bump, reasons), (0, []))

    def test_each_bump_fires_independently(self):
        bump, reasons = bd.compute_bumps(signal(
            nimbus_changed=True, has_backout=True, notable_collections=2,
            dependency_changed=True, source_strings_changed=True))
        self.assertEqual(bump, bd.BUMP_NIMBUS + bd.BUMP_BACKOUT
                         + bd.BUMP_REMOTE_SETTINGS + bd.BUMP_DEPENDENCY
                         + bd.BUMP_SOURCE_STRINGS)
        self.assertEqual(len(reasons), 5)

    def test_reasons_are_human_readable(self):
        _, reasons = bd.compute_bumps(signal(nimbus_changed=True))
        self.assertIn("Nimbus", reasons[0])


class TestComputeBudget(unittest.TestCase):
    def test_silent_range_gets_a_smoke_floor_not_zero(self):
        d = bd.compute_budget(signal(app_product_files=0, engine_is_material=False))
        self.assertEqual((d.final_lo, d.final_hi), bd.BASE_RANGES["silent"])
        self.assertGreater(d.final_lo, 0)

    def test_bumps_raise_only_the_ceiling(self):
        base = bd.compute_budget(signal(app_product_files=5))
        bumped = bd.compute_budget(signal(app_product_files=5, nimbus_changed=True))
        self.assertEqual(base.final_lo, bumped.final_lo)
        self.assertEqual(bumped.final_hi, base.final_hi + bd.BUMP_NIMBUS)

    def test_exact_matches_raise_the_floor(self):
        """Cases linked from a changed instrumented test are known affected,
        so the budget cannot come in under that count."""
        d = bd.compute_budget(signal(app_product_files=0,
                                     engine_is_material=False,
                                     exact_match_cases=15))
        self.assertEqual(d.final_lo, 15)
        self.assertIn("floor raised", d.floor_reason)

    def test_exact_matches_below_the_base_floor_change_nothing(self):
        d = bd.compute_budget(signal(app_product_files=2, exact_match_cases=2))
        self.assertEqual(d.tier, "light")
        self.assertEqual(d.final_lo, bd.BASE_RANGES["light"][0])
        self.assertEqual(d.floor_reason, "")

    def test_ceiling_never_falls_below_the_floor(self):
        d = bd.compute_budget(signal(app_product_files=0,
                                     engine_is_material=False,
                                     exact_match_cases=43))
        self.assertGreaterEqual(d.final_hi, d.final_lo)

    def test_absolute_clamps(self):
        d = bd.compute_budget(signal(
            app_product_files=50, exact_match_cases=999,
            nimbus_changed=True, has_backout=True, notable_collections=9,
            dependency_changed=True, source_strings_changed=True))
        self.assertLessEqual(d.final_hi, bd.ABSOLUTE_CEILING)
        self.assertLessEqual(d.final_lo, bd.ABSOLUTE_CEILING)

    def test_summary_line_is_auditable(self):
        d = bd.compute_budget(signal(app_product_files=0,
                                     engine_is_material=True,
                                     nimbus_changed=True))
        line = d.summary_line()
        self.assertIn("Test budget:", line)
        self.assertIn("engine_only", line)
        self.assertIn("Nimbus", line)

    def test_android_budgets_stay_well_under_the_ios_scale(self):
        """iOS majors run 100-160; no Android beta shape should reach that."""
        worst = bd.compute_budget(signal(
            app_product_files=21, nimbus_changed=True, has_backout=True,
            notable_collections=5, dependency_changed=True,
            source_strings_changed=True))
        self.assertLess(worst.final_hi, 100)


class TestFromExtraction(unittest.TestCase):
    class _File:
        def __init__(self, category):
            self.category = category

    class _Commit:
        def __init__(self, backout=False):
            self.is_backout = backout

    class _Bug:
        def __init__(self, commits):
            self.commits = commits

    class _Result:
        def __init__(self, categories, bugs=()):
            self._c = categories
            self.bugs = list(bugs)

        def counts_by_category(self):
            return self._c

    class _Risk:
        def __init__(self, material, collections=()):
            self.is_material = material
            self.notable_collections = list(collections)

    def test_reads_categories_and_backouts(self):
        r = self._Result(
            {"code": 3, "nimbus": 1, "dependency": 1, "source_strings": 1},
            [self._Bug([self._Commit(backout=True)])])
        s = bd.from_extraction(r, self._Risk(True, ["main/top-sites"]), 7)
        self.assertEqual(s.app_product_files, 3)
        self.assertTrue(s.nimbus_changed)
        self.assertTrue(s.dependency_changed)
        self.assertTrue(s.source_strings_changed)
        self.assertTrue(s.has_backout)
        self.assertTrue(s.engine_is_material)
        self.assertEqual(s.notable_collections, 1)
        self.assertEqual(s.exact_match_cases, 7)

    def test_works_without_a_risk_object(self):
        s = bd.from_extraction(self._Result({"code": 1}))
        self.assertFalse(s.engine_is_material)
        self.assertEqual(s.notable_collections, 0)


if __name__ == "__main__":
    unittest.main()
