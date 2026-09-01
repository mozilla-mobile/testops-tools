"""Tests for candidate_scorer."""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from candidate_scorer import (
    SCORE_CI_COMPLETED,
    SCORE_EXACT_MATCH,
    SCORE_HIGH_LOC_MODULE,
    SCORE_MANUAL_ONLY,
    SCORE_RISK_ASSOCIATION,
    ScoringContext,
    _top_quartile,
    build_scoring_context,
    pre_filter_candidates,
    score_candidate,
)


# =============================================================================
# Lightweight fixtures that mimic the recommend.py dataclasses
# =============================================================================


@dataclass
class TC:
    """Test-case stub — matches the fields score_candidate reads from recommend.TestCase."""
    id: str
    section_top: str = ""
    automation: str = "Suitable"
    sub_suite: str = "Functional"


@dataclass
class MC:
    """ModuleChange stub."""
    total_loc: int


@dataclass
class Risk:
    location: str
    severity: str = "medium"


# =============================================================================
# _top_quartile
# =============================================================================


class TopQuartileTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_top_quartile({}), set())

    def test_single(self):
        self.assertEqual(_top_quartile({"a": 10}), {"a"})

    def test_four_items_returns_top_one(self):
        result = _top_quartile({"a": 100, "b": 50, "c": 30, "d": 10})
        self.assertEqual(result, {"a"})

    def test_ties_at_boundary(self):
        # Top quartile includes anything >= threshold. If several tie at the
        # threshold, they all get included.
        result = _top_quartile({"a": 100, "b": 100, "c": 100, "d": 100, "e": 50})
        self.assertIn("a", result)


# =============================================================================
# score_candidate — each component isolated
# =============================================================================


class ScoreCandidateTests(unittest.TestCase):
    def _ctx(self, **kw) -> ScoringContext:
        return ScoringContext(
            exact_match_ids=kw.get("exact_match_ids", set()),
            high_loc_modules=kw.get("high_loc_modules", set()),
            sections_with_risk=kw.get("sections_with_risk", set()),
            section_to_touched_modules=kw.get("section_to_touched_modules", {}),
        )

    def test_exact_match_adds_50(self):
        tc = TC(id="C123")
        ctx = self._ctx(exact_match_ids={"C123"})
        self.assertEqual(score_candidate(tc, ctx), SCORE_EXACT_MATCH)

    def test_no_match_no_signal_returns_zero(self):
        tc = TC(id="C123")
        self.assertEqual(score_candidate(tc, self._ctx()), 0)

    def test_high_loc_module_adds_30(self):
        tc = TC(id="C1", section_top="Reader")
        ctx = self._ctx(
            high_loc_modules={"firefox-ios/Reader"},
            section_to_touched_modules={"Reader": {"firefox-ios/Reader"}},
        )
        self.assertEqual(score_candidate(tc, ctx), SCORE_HIGH_LOC_MODULE)

    def test_section_not_touched_no_bonus(self):
        tc = TC(id="C1", section_top="Reader")
        # Section maps to a module, but that module isn't in high_loc set
        ctx = self._ctx(
            high_loc_modules={"other/module"},
            section_to_touched_modules={"Reader": {"firefox-ios/Reader"}},
        )
        self.assertEqual(score_candidate(tc, ctx), 0)

    def test_risk_association_adds_20(self):
        tc = TC(id="C1", section_top="Reader")
        ctx = self._ctx(sections_with_risk={"Reader"})
        self.assertEqual(score_candidate(tc, ctx), SCORE_RISK_ASSOCIATION)

    def test_manual_only_unsuitable(self):
        tc = TC(id="C1", automation="Unsuitable")
        self.assertEqual(score_candidate(tc, self._ctx()), SCORE_MANUAL_ONLY)

    def test_manual_only_untriaged(self):
        tc = TC(id="C1", automation="Untriaged")
        self.assertEqual(score_candidate(tc, self._ctx()), SCORE_MANUAL_ONLY)

    def test_ci_completed_penalty(self):
        tc = TC(id="C1", automation="Completed")
        self.assertEqual(score_candidate(tc, self._ctx()), SCORE_CI_COMPLETED)

    def test_all_components_stack(self):
        tc = TC(id="C1", section_top="Reader", automation="Unsuitable")
        ctx = self._ctx(
            exact_match_ids={"C1"},
            high_loc_modules={"firefox-ios/Reader"},
            sections_with_risk={"Reader"},
            section_to_touched_modules={"Reader": {"firefox-ios/Reader"}},
        )
        # 50 + 30 + 20 + 10 = 110
        self.assertEqual(score_candidate(tc, ctx), 110)


# =============================================================================
# build_scoring_context
# =============================================================================


class BuildScoringContextTests(unittest.TestCase):
    def test_top_quartile_module_selection(self):
        module_changes = {
            "a/big":       MC(total_loc=1000),
            "b/medium":    MC(total_loc=200),
            "c/small":     MC(total_loc=50),
            "d/tiny":      MC(total_loc=10),
        }
        ctx = build_scoring_context([], module_changes, [], mapping={"sections": []})
        # Top quartile of 4 items = top 1 → "a/big"
        self.assertEqual(ctx.high_loc_modules, {"a/big"})

    def test_section_mapping_captures_touched_modules(self):
        module_changes = {"firefox-ios/Reader": MC(total_loc=100)}
        mapping = {
            "sections": [
                {"name": "Reader Mode", "modules": [{"path": "firefox-ios/Reader"}]},
                {"name": "Unused", "modules": [{"path": "other/thing"}]},
            ]
        }
        ctx = build_scoring_context([], module_changes, [], mapping)
        self.assertIn("Reader Mode", ctx.section_to_touched_modules)
        self.assertNotIn("Unused", ctx.section_to_touched_modules)

    def test_file_level_risk_maps_to_section(self):
        module_changes = {"firefox-ios/Reader": MC(total_loc=100)}
        mapping = {
            "sections": [
                {"name": "Reader Mode", "modules": [{"path": "firefox-ios/Reader"}]},
            ]
        }
        risks = [Risk(location="firefox-ios/Reader/Foo.swift", severity="high")]
        ctx = build_scoring_context([], module_changes, risks, mapping)
        self.assertIn("Reader Mode", ctx.sections_with_risk)

    def test_pr_level_risk_does_not_map(self):
        module_changes = {"firefox-ios/Reader": MC(total_loc=100)}
        mapping = {"sections": [
            {"name": "Reader Mode", "modules": [{"path": "firefox-ios/Reader"}]},
        ]}
        risks = [Risk(location="PR #12345", severity="high")]
        ctx = build_scoring_context([], module_changes, risks, mapping)
        self.assertEqual(ctx.sections_with_risk, set())


# =============================================================================
# pre_filter_candidates
# =============================================================================


class PreFilterTests(unittest.TestCase):
    def test_truncates_to_top_k(self):
        candidates = [TC(id=f"C{i}") for i in range(100)]
        ctx = ScoringContext(set(), set(), set(), {})
        result = pre_filter_candidates(candidates, ctx, top_k=10)
        self.assertEqual(len(result), 10)

    def test_higher_score_ranks_first(self):
        candidates = [
            TC(id="C_low"),
            TC(id="C_high", automation="Unsuitable"),  # +10
        ]
        ctx = ScoringContext(set(), set(), set(), {})
        result = pre_filter_candidates(candidates, ctx, top_k=2)
        self.assertEqual(result[0][0].id, "C_high")
        self.assertEqual(result[1][0].id, "C_low")

    def test_stable_tie_break_by_id(self):
        # Both tests have score 0; ties should break by ID ascending
        candidates = [TC(id="C_zebra"), TC(id="C_apple"), TC(id="C_mango")]
        ctx = ScoringContext(set(), set(), set(), {})
        result = pre_filter_candidates(candidates, ctx, top_k=3)
        ordered_ids = [tc.id for tc, _ in result]
        self.assertEqual(ordered_ids, ["C_apple", "C_mango", "C_zebra"])

    def test_return_pairs_include_score(self):
        candidates = [TC(id="C1", automation="Completed")]
        ctx = ScoringContext(set(), set(), set(), {})
        result = pre_filter_candidates(candidates, ctx, top_k=1)
        self.assertEqual(result[0][1], SCORE_CI_COMPLETED)


if __name__ == "__main__":
    unittest.main()
