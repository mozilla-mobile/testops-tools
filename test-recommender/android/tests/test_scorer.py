"""Tests for android/scorer.py."""

from __future__ import annotations

import unittest

from android import scorer as sc
from android import testrail_index as ti


FENIX = "mobile/android/fenix/app/src/main/java/org/mozilla/fenix"


def case(case_id="1", automation="Unsuitable", priority="High"):
    return ti.TestCase(
        case_id=str(case_id), title=f"case {case_id}",
        section_hierarchy="Bookmarks", priority=priority,
        automation=automation, automation_coverage="None",
        case_type="Functional", labels="",
    )


def mapping(*sections):
    return {"sections": list(sections)}


def section(name, modules=(), test_count=1):
    return {
        "name": name, "test_count": test_count,
        "modules": [{"path": p, "confidence": "high", "weight": w}
                    for p, w in modules],
    }


class TestModuleMatches(unittest.TestCase):
    def test_exact(self):
        self.assertTrue(sc._module_matches(f"{FENIX}/bookmarks",
                                           f"{FENIX}/bookmarks"))

    def test_changed_file_under_mapped_module(self):
        self.assertTrue(sc._module_matches(
            f"{FENIX}/settings", f"{FENIX}/settings/logins/X.kt"))

    def test_mapped_module_under_changed_path(self):
        self.assertTrue(sc._module_matches(
            f"{FENIX}/settings/trustpanel", f"{FENIX}/settings"))

    def test_sibling_prefix_does_not_match(self):
        self.assertFalse(sc._module_matches(
            f"{FENIX}/book", f"{FENIX}/bookmarks/X.kt"))


class TestBuildContext(unittest.TestCase):
    def test_touched_section_records_best_weight(self):
        m = mapping(section("Bookmarks", [(f"{FENIX}/bookmarks", 18)]))
        ctx = sc.build_context(m, [f"{FENIX}/bookmarks/X.kt"])
        self.assertEqual(ctx.touched_sections["Bookmarks"], 18)

    def test_untouched_section_absent(self):
        m = mapping(section("Bookmarks", [(f"{FENIX}/bookmarks", 18)]))
        ctx = sc.build_context(m, [f"{FENIX}/home/X.kt"])
        self.assertEqual(ctx.touched_sections, {})

    def test_nimbus_blast_radius_follows_feature_ids(self):
        """A coarse prefix match over Homescreen|Onboarding|Search|Menus put a
        third of the catalogue in the radius; the feature IDs are narrower."""
        m = mapping(section("Homescreen"), section("Downloads"),
                    section("Menus > Settings menu > General > Homepage"))
        ctx = sc.build_context(m, [], nimbus_features=["homescreen"])
        self.assertIn("Homescreen", ctx.nimbus_sections)
        self.assertNotIn("Downloads", ctx.nimbus_sections)

    def test_generic_tokens_do_not_widen_the_radius(self):
        """`homepage-opening-screen-default` matched `Set as default browser`
        and `Splash-screen` before generic tokens were filtered."""
        m = mapping(section("Menus > Settings menu > General > Set as default browser"),
                    section("Splash-screen"),
                    section("Search > Default search code"),
                    section("Menus > Settings menu > General > Homepage"))
        ctx = sc.build_context(
            m, [], nimbus_features=["homepage-opening-screen-default"])
        self.assertEqual(
            ctx.nimbus_sections,
            {"Menus > Settings menu > General > Homepage"})

    def test_engine_hints_match_by_section_prefix(self):
        m = mapping(section("Browsing > Normal browsing"), section("Downloads"))
        ctx = sc.build_context(m, [], engine_hints=["Browsing"])
        self.assertEqual(ctx.engine_hint_sections, {"Browsing > Normal browsing"})

    def test_no_signal_yields_an_empty_context(self):
        ctx = sc.build_context(mapping(section("Bookmarks")), [])
        self.assertFalse(ctx.touched_sections)
        self.assertFalse(ctx.nimbus_sections)
        self.assertFalse(ctx.engine_hint_sections)


class TestScoreCase(unittest.TestCase):
    def test_exact_match_dominates(self):
        ctx = sc.ScoringContext(exact_match_cases={"1"})
        s = sc.score_case(case("1"), "Bookmarks", ctx)
        self.assertGreaterEqual(s.score, sc.SCORE_EXACT_MATCH)
        self.assertIn("instrumented test", s.reasons[0])

    def test_automated_case_is_penalised(self):
        # Needs a connection first, or the gate zeroes both.
        ctx = sc.ScoringContext(touched_sections={"B": 0})
        auto = sc.score_case(case("1", automation="Completed"), "B", ctx)
        manual = sc.score_case(case("2", automation="Unsuitable"), "B", ctx)
        self.assertLess(auto.score, manual.score)
        self.assertEqual(manual.score - auto.score,
                         sc.SCORE_MANUAL_ONLY - sc.SCORE_AUTOMATED)

    def test_exact_match_rescues_an_automated_case(self):
        """CI coverage is a reason to deprioritise, not to hide a case whose
        own test just changed."""
        ctx = sc.ScoringContext(exact_match_cases={"1"})
        s = sc.score_case(case("1", automation="Completed"), "B", ctx)
        self.assertGreater(s.score, 0)

    def test_module_weight_scales_the_bonus(self):
        strong = sc.ScoringContext(touched_sections={"B": 20}, max_weight=20)
        weak = sc.ScoringContext(touched_sections={"B": 1}, max_weight=20)
        self.assertGreater(sc.score_case(case(), "B", strong).score,
                           sc.score_case(case(), "B", weak).score)

    def test_priority_contributes(self):
        ctx = sc.ScoringContext(touched_sections={"B": 0})
        hi = sc.score_case(case("1", priority="High"), "B", ctx)
        lo = sc.score_case(case("2", priority="Low"), "B", ctx)
        self.assertEqual(hi.score - lo.score,
                         sc.SCORE_PRIORITY_HIGH - sc.SCORE_PRIORITY_LOW)

    def test_reasons_accompany_every_component(self):
        ctx = sc.ScoringContext(
            exact_match_cases={"1"}, touched_sections={"B": 5},
            nimbus_sections={"B"}, engine_hint_sections={"B"}, max_weight=5)
        s = sc.score_case(case("1"), "B", ctx)
        self.assertGreaterEqual(len(s.reasons), 5)


class TestConnectionGate(unittest.TestCase):
    """`Automation` and `Priority` modulate a connection, never create one."""

    def test_manual_only_high_priority_alone_scores_zero(self):
        s = sc.score_case(case("1", automation="Unsuitable", priority="High"),
                          "B", sc.ScoringContext())
        self.assertEqual(s.score, 0)
        self.assertEqual(s.reasons, [])

    def test_an_empty_build_produces_no_candidates(self):
        """`158 b5->RC` has a literally empty diff. Before the gate it still
        returned ~500 cases, each scoring 20 for being manual-only and High."""
        ctx = sc.build_context(mapping(section("Downloads")), [])
        ranked = sc.rank_cases(
            [(case(i, automation="Unsuitable"), "Downloads") for i in range(50)],
            ctx)
        self.assertEqual(ranked, [])

    def test_any_single_connection_opens_the_gate(self):
        for ctx in (
            sc.ScoringContext(exact_match_cases={"1"}),
            sc.ScoringContext(touched_sections={"B": 0}),
            sc.ScoringContext(nimbus_sections={"B"}),
            sc.ScoringContext(engine_hint_sections={"B"}),
        ):
            self.assertGreater(sc.score_case(case("1"), "B", ctx).score, 0)


class TestRankCases(unittest.TestCase):
    def test_drops_cases_with_no_connection_to_the_build(self):
        """High priority alone must not put a case in the list."""
        ctx = sc.ScoringContext()
        ranked = sc.rank_cases(
            [(case("1", automation="Completed", priority="High"), "B")], ctx)
        self.assertEqual(ranked, [])

    def test_sorted_by_score_then_case_id(self):
        ctx = sc.ScoringContext(touched_sections={"B": 0})
        ranked = sc.rank_cases(
            [(case("30"), "B"), (case("10"), "B"), (case("20"), "B")], ctx)
        # All tie, so the order must be deterministic by id.
        self.assertEqual([r.case_id for r in ranked], ["10", "20", "30"])

    def test_limit(self):
        ctx = sc.ScoringContext(touched_sections={"B": 0})
        ranked = sc.rank_cases([(case(i), "B") for i in range(10)], ctx, limit=3)
        self.assertEqual(len(ranked), 3)


class TestSplitPriorities(unittest.TestCase):
    def _ranked(self, n):
        return [sc.ScoredCase(case_id=str(i), section="B", score=100 - i)
                for i in range(n)]

    def test_p0_fills_to_the_budget_floor(self):
        split = sc.split_priorities(self._ranked(50), 10, 28)
        self.assertEqual(len(split["P0"]), 10)
        self.assertEqual(len(split["P1"]), 18)

    def test_p2_is_overflow_not_truncation(self):
        split = sc.split_priorities(self._ranked(100), 10, 28)
        self.assertEqual(len(split["P2"]), 18)

    def test_short_list_degrades_gracefully(self):
        split = sc.split_priorities(self._ranked(4), 10, 28)
        self.assertEqual(len(split["P0"]), 4)
        self.assertEqual(split["P1"], [])
        self.assertEqual(split["P2"], [])


if __name__ == "__main__":
    unittest.main()


class TestSpecificityDiscount(unittest.TestCase):
    """A module shared by many sections is weak evidence for any one of them.

    On 159 b2->b3 a one-line edit to `utils/Settings.kt` lit all 35 sections
    mapped to `settings/` at full strength, filling P0 with Private browsing
    and HTTPS-Only Mode while the build's actual subjects ranked below them.
    """

    def _ctx(self, shared_by: int):
        broad = [section(f"S{i}", [(f"{FENIX}/settings", 10)])
                 for i in range(shared_by)]
        narrow = [section("Narrow", [(f"{FENIX}/downloads", 10)])]
        return sc.build_context(mapping(*broad, *narrow),
                                [f"{FENIX}/settings/X.kt", f"{FENIX}/downloads/Y.kt"])

    def test_spread_is_recorded(self):
        ctx = self._ctx(5)
        self.assertEqual(ctx.section_module_spread["S0"], 5)
        self.assertEqual(ctx.section_module_spread["Narrow"], 1)

    def test_exclusive_module_scores_higher_than_a_shared_one(self):
        ctx = self._ctx(20)
        shared = sc.score_case(case("1"), "S0", ctx)
        exclusive = sc.score_case(case("2"), "Narrow", ctx)
        self.assertGreater(exclusive.score, shared.score)

    def test_discount_has_a_floor(self):
        """A diffuse match is weak, not worthless."""
        ctx = self._ctx(100)
        self.assertGreaterEqual(
            ctx.specificity("S0"), sc.MIN_SPECIFICITY_FACTOR)
        self.assertGreater(sc.score_case(case("1"), "S0", ctx).score, 0)

    def test_exclusive_module_gets_full_credit(self):
        ctx = self._ctx(1)
        self.assertAlmostEqual(ctx.specificity("Narrow"), 1.0)

    def test_reason_names_the_sharing(self):
        ctx = self._ctx(5)
        reasons = sc.score_case(case("1"), "S0", ctx).reasons
        self.assertTrue(any("shared with 4 other" in r for r in reasons))
