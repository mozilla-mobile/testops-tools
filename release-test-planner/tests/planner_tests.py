#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for the release test planner.

Runs without a Firefox checkout: the Kotlin parsers are exercised against
fixtures in tests/fixtures, and the git parser against a throwaway repo built
in a temp dir. No network, no device, no API key.

    python -m unittest discover -s release-test-planner/tests -p '*tests.py'
"""

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, TOOL_ROOT)

from testplanner import (  # noqa: E402
    changes, corpus, coverage, factories, featuremap, matrix, plan,
    platforms, risk, testrail,
)


# ---------------------------------------------------------------------------
# combinatorial arrays
# ---------------------------------------------------------------------------

class CoveringArrayTests(unittest.TestCase):
    SHAPES = [
        [("A", ["1", "2"]), ("B", ["x", "y"]), ("C", ["p", "q"])],
        [("A", ["1", "2", "3"]), ("B", ["w", "x", "y", "z"]), ("C", ["p", "q"]),
         ("D", ["m", "n"]), ("E", ["j", "k"])],
        [("A", ["1", "2"]), ("B", ["x", "y"]), ("C", ["p", "q"]),
         ("D", ["m", "n"]), ("E", ["j", "k"]), ("F", ["s", "t"]),
         ("G", ["u", "v"])],
    ]

    def test_pairwise_covers_every_pair(self):
        for factors in self.SHAPES:
            rows = matrix.covering_array(factors, strength=2)
            check = matrix.verify(rows, factors, strength=2)
            self.assertTrue(
                check["complete"],
                "missing pairs for {}: {}".format(
                    [n for n, _ in factors], check["missing_examples"]),
            )

    def test_three_way_covers_every_triple(self):
        factors = self.SHAPES[1]
        rows = matrix.covering_array(factors, strength=3)
        self.assertTrue(matrix.verify(rows, factors, strength=3)["complete"])

    def test_smaller_than_full_factorial(self):
        factors = self.SHAPES[2]
        rows = matrix.covering_array(factors, strength=2)
        self.assertLess(len(rows), matrix.full_factorial_size(factors))

    def test_higher_strength_is_never_smaller(self):
        factors = self.SHAPES[1]
        two = len(matrix.covering_array(factors, strength=2))
        three = len(matrix.covering_array(factors, strength=3))
        self.assertGreaterEqual(three, two)

    def test_strength_zero_is_one_baseline_config(self):
        rows = matrix.covering_array(self.SHAPES[0], strength=0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {"A": "1", "B": "x", "C": "p"})

    def test_every_row_assigns_every_factor(self):
        factors = self.SHAPES[1]
        names = {n for n, _ in factors}
        for row in matrix.covering_array(factors, strength=2):
            self.assertEqual(set(row), names)
            for name, levels in factors:
                self.assertIn(row[name], levels)


class VerifierTests(unittest.TestCase):
    """The verifier is the safety net, so it has to be able to fail."""

    def test_detects_a_missing_pair(self):
        factors = [("A", ["1", "2"]), ("B", ["x", "y"])]
        incomplete = [{"A": "1", "B": "x"}, {"A": "2", "B": "y"}]
        check = matrix.verify(incomplete, factors, strength=2)
        self.assertFalse(check["complete"])
        self.assertEqual(check["tuples_required"], 4)
        self.assertEqual(check["tuples_covered"], 2)


class OrthogonalArrayTests(unittest.TestCase):
    def test_four_three_level_factors_gives_textbook_l9(self):
        factors = [(n, ["a", "b", "c"]) for n in "ABCD"]
        oa = matrix.orthogonal_array(factors)
        self.assertEqual(oa["runs"], 9)
        self.assertTrue(oa["balanced"])
        self.assertTrue(matrix.verify(oa["rows"], factors, 2)["complete"])

    def test_l9_is_perfectly_balanced(self):
        factors = [(n, ["a", "b", "c"]) for n in "ABCD"]
        rows = matrix.orthogonal_array(factors)["rows"]
        for first in "ABCD":
            for second in "ABCD":
                if first >= second:
                    continue
                seen = {}
                for r in rows:
                    key = (r[first], r[second])
                    seen[key] = seen.get(key, 0) + 1
                self.assertEqual(
                    set(seen.values()), {1},
                    "{}x{} is not balanced: {}".format(first, second, seen))

    def test_three_two_level_factors_gives_l4(self):
        factors = [(n, ["0", "1"]) for n in "ABC"]
        oa = matrix.orthogonal_array(factors)
        self.assertEqual(oa["runs"], 4)
        self.assertTrue(oa["balanced"])

    def test_mixed_levels_still_cover_but_are_flagged_unbalanced(self):
        factors = [("A", ["1", "2", "3"]), ("B", ["x", "y"]), ("C", ["p", "q"])]
        oa = matrix.orthogonal_array(factors)
        self.assertFalse(oa["balanced"])
        self.assertTrue(oa["notes"])
        self.assertTrue(matrix.verify(oa["rows"], factors, 2)["complete"])

    def test_covering_array_is_no_larger_than_the_orthogonal_one(self):
        factors = [("A", ["1", "2", "3"]), ("B", ["w", "x", "y", "z"]),
                   ("C", ["p", "q"]), ("D", ["m", "n"]), ("E", ["j", "k"])]
        ca = len(matrix.covering_array(factors, strength=2))
        oa = matrix.orthogonal_array(factors)["runs"]
        self.assertLessEqual(ca, oa)


# ---------------------------------------------------------------------------
# risk scoring
# ---------------------------------------------------------------------------

def _bucket(**kw):
    base = {
        "feature_id": "f", "name": "F", "severity": 5, "severity_rationale": "",
        "iso25010": [], "files": [], "added": 0, "deleted": 0,
        "churned_lines": 0, "total_lines": 100, "commits": 1, "authors": 1,
        "backout_touched": False, "file_count": 1, "m1_churn_ratio": 0.0,
        "m2_delete_ratio": 0.0, "indirect": False,
    }
    base.update(kw)
    return base


class OccurrenceTests(unittest.TestCase):
    def test_rises_with_relative_churn(self):
        low = risk.occurrence(_bucket(m1_churn_ratio=0.01))["occurrence"]
        mid = risk.occurrence(_bucket(m1_churn_ratio=0.25))["occurrence"]
        high = risk.occurrence(_bucket(m1_churn_ratio=0.90))["occurrence"]
        self.assertLess(low, mid)
        self.assertLess(mid, high)

    def test_backout_raises_occurrence_and_is_explained(self):
        clean = risk.occurrence(_bucket(m1_churn_ratio=0.1))
        backed = risk.occurrence(_bucket(m1_churn_ratio=0.1, backout_touched=True))
        self.assertEqual(backed["occurrence"], clean["occurrence"] + 2)
        self.assertTrue(any("backout" in m for m in backed["occurrence_modifiers"]))

    def test_agent_delta_is_applied_and_recorded(self):
        out = risk.occurrence(_bucket(
            m1_churn_ratio=0.25, agent_occurrence_delta=-2,
            agent_change_kind="refactor"))
        base = risk.occurrence(_bucket(m1_churn_ratio=0.25))["occurrence"]
        self.assertEqual(out["occurrence"], base - 2)
        self.assertTrue(any("refactor" in m for m in out["occurrence_modifiers"]))

    def test_clamped_to_the_fmea_scale(self):
        floor = risk.occurrence(_bucket(m1_churn_ratio=0.0,
                                        agent_occurrence_delta=-9))
        ceiling = risk.occurrence(_bucket(
            m1_churn_ratio=0.99, file_count=50, commits=99, authors=9,
            backout_touched=True, agent_occurrence_delta=3))
        self.assertGreaterEqual(floor["occurrence"], 1)
        self.assertLessEqual(ceiling["occurrence"], 10)


class RiskScoreTests(unittest.TestCase):
    def _score(self, severity, churn, detection):
        attribution = {
            "features_touched": [_bucket(severity=severity, m1_churn_ratio=churn)],
            "unmapped_files": [], "ignored_count": 0,
        }
        cov = {"per_feature": {"f": {"detection": detection, "coverage_tier": "x",
                                     "test_count": 1, "active_count": 1}},
               "unbound_tests": [], "unbound_count": 0}
        return risk.score(attribution, cov)

    def test_rpn_is_the_product_of_the_three_factors(self):
        row = self._score(5, 0.25, 4.0)["rows"][0]
        self.assertEqual(row["rpn"], round(row["severity"] * row["occurrence"] * 4.0))

    def test_bands_follow_the_aiag_thresholds(self):
        self.assertEqual(risk.band(250), "action-required")
        self.assertEqual(risk.band(200), "action-required")
        self.assertEqual(risk.band(199), "review")
        self.assertEqual(risk.band(100), "review")
        self.assertEqual(risk.band(99), "acceptable")

    def test_better_detection_lowers_rpn(self):
        poor = self._score(8, 0.3, 10.0)["rows"][0]["rpn"]
        good = self._score(8, 0.3, 2.0)["rows"][0]["rpn"]
        self.assertLess(good, poor)

    def test_confidence_is_zero_with_no_detection_at_all(self):
        totals = self._score(8, 0.3, 10.0)["totals"]
        self.assertAlmostEqual(totals["coverage_confidence"], 0.0, places=6)

    def test_inherent_rpn_ignores_detection(self):
        a = self._score(7, 0.3, 2.0)["rows"][0]
        b = self._score(7, 0.3, 10.0)["rows"][0]
        self.assertEqual(a["inherent_rpn"], b["inherent_rpn"])
        self.assertEqual(a["criticality"], b["criticality"])


# ---------------------------------------------------------------------------
# coverage / detection
# ---------------------------------------------------------------------------

def _test_row(**kw):
    base = {"name": "t", "class_name": "C", "suite": "ui.efficiency",
            "file": "C.kt", "annotations": [], "testrail_id": "",
            "surfaces": [], "line": 1, "is_smoke": False, "is_disabled": False,
            "binding": "strong"}
    base.update(kw)
    return base


class DetectionTests(unittest.TestCase):
    def test_no_tests_means_no_detection(self):
        self.assertEqual(coverage.detection_for([]), coverage.DETECTION_CEILING)

    def test_detection_decreases_monotonically_and_never_passes_the_floor(self):
        previous = coverage.DETECTION_CEILING + 1
        for count in range(0, 40):
            d = coverage.detection_for([_test_row() for _ in range(count)])
            self.assertLessEqual(d, previous)
            self.assertGreaterEqual(d, coverage.DETECTION_FLOOR)
            previous = d

    def test_every_added_test_still_gains_something(self):
        """A plateau here is what stalled the greedy planner. Guard it."""
        for count in range(0, 12):
            a = coverage.detection_for([_test_row() for _ in range(count)])
            b = coverage.detection_for([_test_row() for _ in range(count + 1)])
            self.assertLess(b, a, "no gain going from {} to {} tests".format(
                count, count + 1))

    def test_incidental_bindings_are_worth_nothing(self):
        many = [_test_row(binding="incidental") for _ in range(500)]
        self.assertEqual(coverage.detection_for(many), coverage.DETECTION_CEILING)

    def test_disabled_tests_are_worth_nothing(self):
        self.assertEqual(
            coverage.detection_for([_test_row(is_disabled=True) for _ in range(9)]),
            coverage.DETECTION_CEILING)

    def test_smoke_counts_for_more_than_a_plain_test(self):
        self.assertLess(
            coverage.detection_for([_test_row(is_smoke=True)]),
            coverage.detection_for([_test_row()]))

    def test_disabled_only_is_labelled_distinctly(self):
        scored = coverage._score([_test_row(is_disabled=True)])
        self.assertEqual(scored["coverage_tier"], "disabled-only")
        self.assertEqual(scored["detection"], coverage.DETECTION_CEILING)


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.catalog = featuremap.FeatureCatalog([
            featuremap.Feature(id="downloads", name="Downloads", severity=8,
                               page_objects=["downloads"],
                               test_patterns=["Download"]),
        ])

    def _bind(self, test):
        return coverage.bind(self.catalog, {"tests": [test]})

    def test_name_and_surface_is_a_strong_binding(self):
        out = self._bind(_test_row(class_name="DownloadTest",
                                   surfaces=["downloads"]))
        self.assertEqual(out["per_feature"]["downloads"]["tests"][0]["binding"],
                         "strong")

    def test_name_only_binding(self):
        out = self._bind(_test_row(class_name="DownloadTest"))
        self.assertEqual(out["per_feature"]["downloads"]["tests"][0]["binding"],
                         "name-only")

    def test_surface_without_a_matching_name_is_only_incidental(self):
        out = self._bind(_test_row(class_name="BookmarksTest",
                                   surfaces=["downloads"]))
        self.assertEqual(out["per_feature"]["downloads"]["tests"][0]["binding"],
                         "incidental")

    def test_unrelated_test_binds_to_nothing(self):
        out = self._bind(_test_row(class_name="SyncTest", surfaces=["sync"]))
        self.assertEqual(out["unbound_count"], 1)


# ---------------------------------------------------------------------------
# feature mapping
# ---------------------------------------------------------------------------

class FeatureMapTests(unittest.TestCase):
    def setUp(self):
        self.catalog = featuremap.FeatureCatalog([
            featuremap.Feature(id="broad", name="Broad", severity=5,
                               source_globs=["**/org/mozilla/fenix/settings/**"]),
            featuremap.Feature(id="narrow", name="Narrow", severity=9,
                               source_globs=[
                                   "**/org/mozilla/fenix/settings/logins/**"]),
        ])

    def test_most_specific_glob_becomes_the_primary_feature(self):
        path = "mobile/android/fenix/app/src/main/java/org/mozilla/fenix/settings/logins/L.kt"
        out = featuremap.attribute(self.catalog, [self._file(path)])
        primary = out["features_touched"][0]
        self.assertEqual(primary["feature_id"], "narrow")
        self.assertIn("broad", primary["files"][0]["secondary_features"])

    def test_a_file_is_counted_once(self):
        path = "mobile/android/fenix/app/src/main/java/org/mozilla/fenix/settings/logins/L.kt"
        out = featuremap.attribute(self.catalog, [self._file(path)])
        self.assertEqual(len(out["features_touched"]), 1)

    def test_test_sources_are_ignored_not_unmapped(self):
        path = "mobile/android/fenix/app/src/androidTest/java/org/mozilla/fenix/ui/ATest.kt"
        out = featuremap.attribute(self.catalog, [self._file(path)])
        self.assertEqual(out["ignored_count"], 1)
        self.assertEqual(out["unmapped_files"], [])

    def test_unrecognised_source_is_surfaced_not_dropped(self):
        out = featuremap.attribute(self.catalog, [self._file("some/other/File.kt")])
        self.assertEqual(len(out["unmapped_files"]), 1)

    @staticmethod
    def _file(path):
        return {"path": path, "added": 10, "deleted": 2, "commits": 1,
                "authors": 1, "total_lines": 100, "is_binary": False,
                "touched_by_backout": False, "churned_lines": 12}


# ---------------------------------------------------------------------------
# kotlin parsing, against fixtures
# ---------------------------------------------------------------------------

class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.cases = corpus.parse_file(
            os.path.join(FIXTURES, "ui", "SampleFeatureTest.kt"), "ui", FIXTURES)
        self.by_name = {c.name: c for c in self.cases}

    def test_finds_every_annotated_test(self):
        self.assertEqual(
            sorted(self.by_name),
            ["disabledTest", "plainTest", "smokeTest"])

    def test_helper_methods_are_not_tests(self):
        self.assertNotIn("notATest", self.by_name)

    def test_reads_the_smoke_annotation(self):
        self.assertTrue(self.by_name["smokeTest"].is_smoke)
        self.assertFalse(self.by_name["plainTest"].is_smoke)

    def test_reads_the_ignore_annotation(self):
        self.assertTrue(self.by_name["disabledTest"].is_disabled)
        self.assertFalse(self.by_name["smokeTest"].is_disabled)

    def test_reads_the_testrail_id_from_the_comment(self):
        self.assertEqual(self.by_name["smokeTest"].testrail_id, "3205329")

    def test_picks_up_page_object_surfaces(self):
        self.assertIn("downloads", self.by_name["smokeTest"].surfaces)

    def test_picks_up_legacy_robot_imports(self):
        self.assertIn("downloadRobot", self.by_name["plainTest"].surfaces)


class FactoryScanTests(unittest.TestCase):
    def setUp(self):
        self.scan = factories.scan(FIXTURES, "efficiency")
        self.by_id = {f["id"]: f for f in self.scan["factories"]}

    def test_counts_selectors_for_the_interaction_factory(self):
        self.assertEqual(self.by_id["interaction"]["candidates"], 3)

    def test_counts_page_objects(self):
        self.assertEqual(self.scan["page_count"], 2)

    def test_pairs_are_ordered_page_transitions(self):
        self.assertEqual(self.by_id["pairs"]["candidates"], 2)  # 2 pages -> 2*1

    def test_parses_context_factors_and_names_them_readably(self):
        names = {f["name"] for f in self.scan["context_factors"]}
        self.assertEqual(names, {"BrowserMode", "DeviceClass"})

    def test_exhaustive_profile_is_the_product_of_the_factors(self):
        self.assertEqual(self.scan["context_profiles"]["EXHAUSTIVE_PREVIEW"], 4)

    def test_parses_capabilities_with_their_feature(self):
        self.assertEqual(self.scan["capability_features"], ["bookmarks"])


# ---------------------------------------------------------------------------
# git parsing, against a throwaway repo
# ---------------------------------------------------------------------------

@unittest.skipIf(shutil.which("git") is None, "git not available")
class GitChangeTests(unittest.TestCase):
    """Guards the record-separator handling in changes.collect().

    git emits --numstat *after* the format string, so a trailing separator
    silently pairs each commit with the previous commit's file list. That bug
    reported one commit and zero files, which looked like an empty range.
    """

    @classmethod
    def setUpClass(cls):
        cls.repo = tempfile.mkdtemp(prefix="planner-git-")
        run = lambda *a: subprocess.run(  # noqa: E731
            a, cwd=cls.repo, check=True, capture_output=True)
        run("git", "init", "-q")
        run("git", "config", "user.email", "t@example.com")
        run("git", "config", "user.name", "Tester")

        # Seed commit so HEAD~4 resolves once the four below are in.
        cls._commit(run, "seed.txt", "seed\n", "No bug - seed")
        cls._commit(run, "a.txt", "one\ntwo\nthree\n", "Bug 111111 - add a")
        cls._commit(run, "b.txt", "x\n", "Bug 222222 - add b")
        # Rewrites line 2 (+1/-1) and appends two lines (+2) => +3/-1.
        cls._commit(run, "a.txt", "one\nCHANGED\nthree\nfour\nfive\n",
                    "Bug 333333 - grow a")
        cls._commit(run, "b.txt", "x\ny\n",
                    'Revert "Bug 222222 - add b" for bustage')

    @classmethod
    def _commit(cls, run, name, body, message):
        with open(os.path.join(cls.repo, name), "w") as fh:
            fh.write(body)
        run("git", "add", name)
        run("git", "commit", "-q", "-m", message)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.repo, ignore_errors=True)

    def test_finds_every_commit(self):
        out = changes.collect(self.repo, "HEAD~4..HEAD")
        self.assertEqual(out["commit_count"], 4)

    def test_attributes_files_to_the_right_commits(self):
        out = changes.collect(self.repo, "HEAD~4..HEAD")
        by_path = {f["path"]: f for f in out["files"]}
        self.assertEqual(set(by_path), {"a.txt", "b.txt"})
        self.assertEqual(by_path["a.txt"]["commits"], 2)
        self.assertEqual(by_path["b.txt"]["commits"], 2)

    def test_counts_added_and_deleted_lines(self):
        out = changes.collect(self.repo, "HEAD~4..HEAD")
        a = next(f for f in out["files"] if f["path"] == "a.txt")
        self.assertEqual(a["added"], 3 + 3)   # 3 on create, 3 on the edit
        self.assertEqual(a["deleted"], 1)     # one line replaced
        self.assertEqual(a["churned_lines"], 7)

    def test_extracts_bug_numbers(self):
        out = changes.collect(self.repo, "HEAD~4..HEAD")
        bugs = {b for c in out["commits"] for b in c["bugs"]}
        self.assertEqual(bugs, {"111111", "222222", "333333"})

    def test_flags_files_touched_by_a_backout(self):
        out = changes.collect(self.repo, "HEAD~4..HEAD")
        by_path = {f["path"]: f for f in out["files"]}
        self.assertTrue(by_path["b.txt"]["touched_by_backout"])
        self.assertFalse(by_path["a.txt"]["touched_by_backout"])

    def test_pathspec_restricts_the_result(self):
        out = changes.collect(self.repo, "HEAD~4..HEAD", pathspec=["a.txt"])
        self.assertEqual([f["path"] for f in out["files"]], ["a.txt"])

    def test_empty_range_yields_no_files(self):
        self.assertEqual(changes.collect(self.repo, "HEAD..HEAD")["files"], [])


@unittest.skipIf(shutil.which("git") is None, "git not available")
class WorkingTreeMismatchTests(unittest.TestCase):
    """Guards the silent-wrong-answer case.

    Churn comes from the range; the test corpus comes from the checked-out
    tree. Analysing `origin/release..origin/beta` from a `main` checkout scores
    one branch's changes against another branch's tests and reports an inflated
    confidence number, with nothing else in the pipeline noticing.
    """

    @classmethod
    def setUpClass(cls):
        cls.repo = tempfile.mkdtemp(prefix="planner-mismatch-")

        def run(*a):
            subprocess.run(a, cwd=cls.repo, check=True, capture_output=True)

        def commit(name, body, message):
            with open(os.path.join(cls.repo, name), "w") as fh:
                fh.write(body)
            run("git", "add", name)
            run("git", "commit", "-q", "-m", message)

        run("git", "init", "-q")
        run("git", "config", "user.email", "t@example.com")
        run("git", "config", "user.name", "Tester")
        commit("base.txt", "base\n", "No bug - base")

        # A side branch whose commits never reach the checked-out main line.
        run("git", "checkout", "-q", "-b", "sidebranch")
        commit("side.txt", "side\n", "Bug 999999 - only on the side branch")
        run("git", "checkout", "-q", "-")
        commit("main.txt", "main\n", "Bug 888888 - only on the main line")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.repo, ignore_errors=True)

    def test_flags_a_range_the_checkout_does_not_contain(self):
        data = changes.collect(self.repo, "HEAD..sidebranch")
        tip = changes.tip_in_working_tree(self.repo, data["commits"])
        self.assertIsNotNone(tip, "side-branch range should have been flagged")

    def test_does_not_flag_a_range_the_checkout_does_contain(self):
        data = changes.collect(self.repo, "HEAD~1..HEAD")
        self.assertIsNone(changes.tip_in_working_tree(self.repo, data["commits"]))

    def test_no_commits_is_not_a_mismatch(self):
        self.assertIsNone(changes.tip_in_working_tree(self.repo, []))


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------

class PlanTests(unittest.TestCase):
    def _fixture(self, test_count=10):
        rows = [{
            "feature_id": "f", "name": "F", "severity": 9, "occurrence": 8,
            "detection": 10.0, "band": "action-required", "rpn": 720,
            "inherent_rpn": 720, "criticality": 72, "test_count": test_count,
            "active_count": test_count, "smoke_count": 0, "disabled_count": 0,
            "indirect": False, "iso25010": ["functional_suitability"],
            "severity_rationale": "fixture", "churned_lines": 100,
        }]
        cov = {"per_feature": {"f": {"tests": [
            _test_row(name="t{}".format(i), suite="ui.efficiency")
            for i in range(test_count)
        ]}}}
        return {"rows": rows, "totals": {}}, cov

    def test_selects_more_than_one_test(self):
        """Regression guard: a tiered detection curve stalled this at 3."""
        risk_result, cov = self._fixture(test_count=10)
        out = plan.build(risk_result, cov)
        self.assertGreater(out["selected_count"], 1)

    def test_budget_is_never_exceeded(self):
        risk_result, cov = self._fixture(test_count=40)
        for budget in (1.5, 3.0, 7.5, 15.0):
            out = plan.build(risk_result, cov, budget_minutes=budget)
            self.assertLessEqual(out["estimated_minutes"], budget)

    def test_a_bigger_budget_never_lowers_confidence(self):
        risk_result, cov = self._fixture(test_count=40)
        previous = -1.0
        for budget in (3.0, 7.5, 15.0, 60.0):
            confidence = plan.build(
                risk_result, cov,
                budget_minutes=budget)["totals"]["release_confidence"]
            self.assertGreaterEqual(confidence, previous)
            previous = confidence

    def test_residual_risk_is_below_the_baseline(self):
        risk_result, cov = self._fixture(test_count=10)
        out = plan.build(risk_result, cov)
        entry = out["per_feature"][0]
        self.assertLess(entry["residual_rpn"], entry["baseline_rpn"])

    def test_incidental_tests_are_never_scheduled(self):
        risk_result, cov = self._fixture(test_count=5)
        for t in cov["per_feature"]["f"]["tests"]:
            t["binding"] = "incidental"
        out = plan.build(risk_result, cov)
        self.assertEqual(out["selected_count"], 0)

    def test_a_feature_with_no_automation_is_reported_as_a_gap(self):
        risk_result, cov = self._fixture(test_count=0)
        out = plan.build(risk_result, cov)
        self.assertEqual(len(out["gaps"]), 1)
        self.assertIn("No UI automation", out["gaps"][0]["reason"])


class MatrixAllocationTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(TOOL_ROOT, "config", "environment.json")) as fh:
            self.env = json.load(fh)
        self.context = [
            {"name": "BrowserMode", "levels": ["Default", "Private"]},
            {"name": "Account", "levels": ["SignedOut", "SignedIn"]},
        ]

    def _allocate(self, band):
        rows = [{"feature_id": "f", "name": "F", "band": band, "rpn": 500,
                 "severity": 9, "occurrence": 8}]
        plan_result = {
            "per_feature": [{"feature_id": "f", "planned_cost_minutes": 10.0,
                             "planned_tests": 4}],
            "estimated_minutes": 10.0,
        }
        return matrix.allocate(rows, plan_result, self.env, self.context)

    def test_higher_risk_earns_more_configurations(self):
        counts = {b: self._allocate(b)["designs"][b]["config_count"]
                  for b in ("acceptable", "review", "action-required")}
        self.assertEqual(counts["acceptable"], 1)
        self.assertLess(counts["acceptable"], counts["review"])
        self.assertLess(counts["review"], counts["action-required"])

    def test_each_design_actually_covers_its_strength(self):
        for band in ("review", "action-required"):
            design = self._allocate(band)["designs"][band]
            self.assertTrue(design["verification"]["complete"])

    def test_executions_are_tests_times_configs(self):
        out = self._allocate("review")
        entry = out["per_feature"][0]
        self.assertEqual(entry["executions"],
                         entry["planned_tests"] * entry["config_count"])

    def test_context_factors_from_source_reach_the_pool(self):
        pool = {f["name"] for f in self._allocate("review")["factor_pool"]}
        self.assertIn("BrowserMode", pool)
        self.assertIn("ApiLevel", pool)


class ConfigTests(unittest.TestCase):
    """The shipped config is data, so it gets validated like data."""

    def test_feature_catalog_loads_and_is_well_formed(self):
        catalog = featuremap.FeatureCatalog.load(
            os.path.join(TOOL_ROOT, "config", "features.json"))
        ids = [f.id for f in catalog]
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)), "duplicate feature ids")
        for feature in catalog:
            self.assertTrue(1 <= feature.severity <= 10, feature.id)
            self.assertTrue(feature.name, feature.id)
            self.assertTrue(feature.severity_rationale,
                            "{} has no severity rationale".format(feature.id))
            self.assertTrue(feature.source_globs, feature.id)

    def test_allocation_policy_covers_every_band(self):
        with open(os.path.join(TOOL_ROOT, "config", "environment.json")) as fh:
            env = json.load(fh)
        self.assertEqual(set(env["allocation_policy"]),
                         {"action-required", "review", "acceptable"})
        for name, spec in env["allocation_policy"].items():
            self.assertIn("strength", spec)
            self.assertTrue(spec["factors"], name)
            self.assertTrue(spec["rationale"], name)

    def test_every_environment_factor_declares_whether_it_is_real(self):
        with open(os.path.join(TOOL_ROOT, "config", "environment.json")) as fh:
            env = json.load(fh)
        for factor in env["infrastructure_factors"]:
            self.assertIn(factor["source"], ("real", "partly-real", "stubbed"),
                          factor["name"])
            self.assertTrue(factor.get("origin"), factor["name"])
            self.assertGreaterEqual(len(factor["levels"]), 2, factor["name"])




# ---------------------------------------------------------------------------
# iOS: Swift corpus, test plans, platform descriptors
# ---------------------------------------------------------------------------

IOS_FIXTURE = os.path.join(FIXTURES, "ios")


class SwiftCorpusTests(unittest.TestCase):
    """XCUITest parsing. A test is a naming convention here, not an annotation."""

    def setUp(self):
        self.cases = corpus.parse_swift_file(
            os.path.join(IOS_FIXTURE, "XCUITests", "SampleFeatureTests.swift"),
            "xcuitest", IOS_FIXTURE)
        self.by_name = {c.name: c for c in self.cases}

    def test_finds_every_test_method(self):
        self.assertEqual(
            sorted(self.by_name),
            ["testBookmarkCanBeAdded", "testExplicitlySkipped",
             "testHistoryListShows", "testNewToolbarOnly",
             "testWithoutATestRailCase"])

    def test_a_helper_named_like_a_test_is_not_a_test(self):
        self.assertNotIn("helperThatLooksLikeATest", self.by_name)

    def test_class_name_is_read_from_the_declaration(self):
        self.assertEqual(self.by_name["testBookmarkCanBeAdded"].class_name,
                         "SampleFeatureTests")

    def test_testrail_id_uses_the_same_url_form_as_fenix(self):
        self.assertEqual(self.by_name["testBookmarkCanBeAdded"].testrail_id,
                         "1000001")

    def test_a_test_without_a_case_link_has_no_id_rather_than_the_previous_one(self):
        self.assertEqual(self.by_name["testWithoutATestRailCase"].testrail_id, "")

    def test_surfaces_come_from_the_navigator_screen_graph(self):
        surfaces = self.by_name["testBookmarkCanBeAdded"].surfaces
        self.assertIn("LibraryPanel_Bookmarks", surfaces)
        self.assertIn("NewTabScreen", surfaces)
        self.assertIn("Action.AddNewBookmark", surfaces)

    def test_xctskip_is_recognised_as_a_skip(self):
        self.assertTrue(self.by_name["testExplicitlySkipped"].skipped_in_code)

    def test_an_availability_guard_that_returns_is_a_skip(self):
        # `guard #available ... else { return }` passes having asserted nothing.
        self.assertTrue(self.by_name["testNewToolbarOnly"].skipped_in_code)

    def test_an_ordinary_test_is_not_marked_skipped(self):
        self.assertFalse(self.by_name["testBookmarkCanBeAdded"].skipped_in_code)


class TestPlanResolutionTests(unittest.TestCase):
    def setUp(self):
        self.plans = corpus.load_test_plans(IOS_FIXTURE, "plans", "XCUITests")

    def test_only_plans_including_the_ui_target_are_read(self):
        # UnitTest.xctestplan lists ClientTests and no XCUITests, so reading it
        # would make every UI test look as though it ran there.
        self.assertEqual(sorted(self.plans), ["Smoketest"])

    def test_method_and_class_skips_are_kept_apart(self):
        plan_data = self.plans["Smoketest"]
        self.assertIn("testHistoryListShows", plan_data["skipped_tests"])
        self.assertIn("SomeOtherClass", plan_data["skipped_classes"])

    def test_a_skipped_method_does_not_run_in_that_plan(self):
        cases = corpus.parse_swift_file(
            os.path.join(IOS_FIXTURE, "XCUITests", "SampleFeatureTests.swift"),
            "xcuitest", IOS_FIXTURE)
        corpus.apply_test_plans(cases, self.plans)
        by_name = {c.name: c for c in cases}
        self.assertEqual(by_name["testHistoryListShows"].plans, [])
        self.assertEqual(by_name["testBookmarkCanBeAdded"].plans, ["Smoketest"])

    def test_a_test_no_plan_runs_is_disabled(self):
        cases = corpus.parse_swift_file(
            os.path.join(IOS_FIXTURE, "XCUITests", "SampleFeatureTests.swift"),
            "xcuitest", IOS_FIXTURE)
        corpus.apply_test_plans(cases, self.plans)
        by_name = {c.name: c for c in cases}
        self.assertTrue(by_name["testHistoryListShows"].is_disabled)
        self.assertFalse(by_name["testBookmarkCanBeAdded"].is_disabled)

    def test_android_tests_are_not_disabled_by_absent_plans(self):
        # `plans is None` means the platform has no test plans; `[]` means every
        # plan skips the test. Conflating them would disable the Android suite.
        case = corpus.TestCase(name="t", class_name="C", suite="ui", file="C.kt")
        self.assertIsNone(case.plans)
        self.assertFalse(case.is_disabled)


class PlatformTests(unittest.TestCase):
    def test_android_declares_a_candidate_space_and_ios_does_not(self):
        self.assertTrue(platforms.ANDROID.has_factories)
        self.assertFalse(platforms.IOS.has_factories)

    def test_unknown_platform_fails_loudly(self):
        with self.assertRaises(SystemExit):
            platforms.get("windows-phone")

    def test_empty_factory_scan_matches_the_real_scan_shape(self):
        # matrix.allocate and the report both read these keys.
        real_keys = {"total_candidates", "page_count", "capabilities",
                     "capability_features", "templates", "factories",
                     "selectors_per_page", "context_factors", "context_profiles"}
        self.assertTrue(real_keys.issubset(set(factories.empty("ios"))))
        self.assertEqual(factories.empty("ios")["total_candidates"], 0)
        self.assertFalse(factories.empty("ios")["has_candidate_space"])


class CatalogIgnoreTests(unittest.TestCase):
    def test_a_catalog_can_replace_the_ignore_list(self):
        cat = featuremap.FeatureCatalog([], ignored_globs=["**/*.swift"])
        self.assertTrue(featuremap.is_ignored("a/b/C.swift", cat.ignored_globs))
        self.assertFalse(featuremap.is_ignored("a/b/C.kt", cat.ignored_globs))

    def test_the_default_ignore_list_still_applies_without_one(self):
        cat = featuremap.FeatureCatalog([])
        self.assertTrue(featuremap.is_ignored("x/androidTest/Y.kt",
                                              cat.ignored_globs))

    def test_the_shipped_ios_catalog_loads_and_ignores_its_test_target(self):
        cat = featuremap.FeatureCatalog.load(
            os.path.join(TOOL_ROOT, "config", "features-ios.json"))
        self.assertEqual(cat.platform, "ios")
        self.assertTrue(cat.features)
        self.assertTrue(featuremap.is_ignored(
            "firefox-ios/firefox-ios-tests/Tests/XCUITests/A.swift",
            cat.ignored_globs))
        # focus-ios is a different product living in the same repository.
        self.assertTrue(featuremap.is_ignored(
            "focus-ios/Blockzilla/AppDelegate.swift", cat.ignored_globs))

    def test_ios_feature_ids_overlap_android_so_reports_compare(self):
        ios = featuremap.FeatureCatalog.load(
            os.path.join(TOOL_ROOT, "config", "features-ios.json"))
        android = featuremap.FeatureCatalog.load(
            os.path.join(TOOL_ROOT, "config", "features.json"))
        shared = {f.id for f in ios} & {f.id for f in android}
        self.assertGreater(len(shared), 20)
        # A feature that exists on both platforms describes the same user impact,
        # so its severity must not drift between the two catalogs.
        for fid in shared:
            self.assertEqual(ios.get(fid).severity, android.get(fid).severity,
                             "severity differs for %s" % fid)


# ---------------------------------------------------------------------------
# TestRail as an assumed denominator
# ---------------------------------------------------------------------------

class TestRailLoaderTests(unittest.TestCase):
    CASES = [
        {"id": 2306905, "title": "Bookmark a page", "section": "Bookmarks"},
        {"id": 2306906, "title": "Delete a bookmark", "section": "Bookmarks"},
        {"id": 2307300, "title": "Clear history", "section": "History"},
    ]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.json_path = os.path.join(self.tmp, "export.json")
        with open(self.json_path, "w") as fh:
            json.dump({"cases": self.CASES}, fh)
        self.csv_path = os.path.join(self.tmp, "export.csv")
        with open(self.csv_path, "w") as fh:
            fh.write("Case ID,Title,Section\n")
            for c in self.CASES:
                fh.write("C%d,%s,%s\n" % (c["id"], c["title"], c["section"]))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_id_forms_all_normalise_to_the_bare_integer(self):
        for raw in (2306905, "2306905", "C2306905",
                    "https://mozilla.testrail.io/index.php?/cases/view/2306905"):
            self.assertEqual(testrail.normalise_id(raw), "2306905")

    def test_missing_id_is_empty_not_an_exception(self):
        self.assertEqual(testrail.normalise_id(None), "")
        self.assertEqual(testrail.normalise_id("no digits here"), "")

    def test_json_and_csv_produce_the_same_cases(self):
        from_json = testrail.load_export(self.json_path)
        from_csv = testrail.load_export(self.csv_path)
        self.assertEqual([c["id"] for c in from_json], [c["id"] for c in from_csv])
        self.assertEqual(len(from_json), 3)

    def test_a_bare_json_list_is_accepted_too(self):
        path = os.path.join(self.tmp, "bare.json")
        with open(path, "w") as fh:
            json.dump(self.CASES, fh)
        self.assertEqual(len(testrail.load_export(path)), 3)

    def test_an_unsupported_format_fails_with_a_readable_error(self):
        path = os.path.join(self.tmp, "export.xlsx")
        open(path, "w").close()
        with self.assertRaises(SystemExit):
            testrail.load_export(path)

    def test_a_csv_without_an_id_column_fails_loudly(self):
        path = os.path.join(self.tmp, "bad.csv")
        with open(path, "w") as fh:
            fh.write("Name,Section\nfoo,Bookmarks\n")
        with self.assertRaises(SystemExit):
            testrail.load_export(path)

    def test_a_missing_file_fails_loudly(self):
        with self.assertRaises(SystemExit):
            testrail.load_export(os.path.join(self.tmp, "nope.json"))


class TestRailJoinTests(unittest.TestCase):
    """The join rules that decide what counts as automated coverage."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.catalog = featuremap.FeatureCatalog([
            featuremap.Feature(id="bookmarks", name="Bookmarks", severity=7,
                               test_patterns=["BookmarksTests"]),
            featuremap.Feature(id="history", name="History", severity=7,
                               test_patterns=["HistoryTests"]),
        ])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _export(self, cases):
        path = os.path.join(self.tmp, "export.json")
        with open(path, "w") as fh:
            json.dump({"cases": cases}, fh)
        return path

    def _inventory(self, tests):
        return {"tests": tests}

    def test_a_live_test_makes_its_case_automated(self):
        path = self._export([{"id": 1, "title": "t", "section": "Bookmarks"}])
        inv = self._inventory([
            {"class_name": "BookmarksTests", "name": "testA", "testrail_id": "1",
             "is_disabled": False}])
        out = testrail.build(path, self.catalog, inv, {})
        self.assertEqual(out["totals"]["automated"], 1)
        self.assertEqual(out["totals"]["manual_only"], 0)

    def test_a_case_automated_only_by_a_skipped_test_is_manual(self):
        # Automation that never runs is not coverage - the same rule the corpus
        # applies to @Ignore and to xctestplan skips.
        path = self._export([{"id": 1, "title": "t", "section": "Bookmarks"}])
        inv = self._inventory([
            {"class_name": "BookmarksTests", "name": "testA", "testrail_id": "1",
             "is_disabled": True}])
        out = testrail.build(path, self.catalog, inv, {})
        self.assertEqual(out["totals"]["automated"], 0)
        self.assertEqual(out["totals"]["manual_only"], 1)
        self.assertEqual(out["totals"]["skipped_automation"], 1)

    def test_a_case_no_test_references_is_manual(self):
        path = self._export([{"id": 9, "title": "t", "section": "History"}])
        out = testrail.build(path, self.catalog, self._inventory([]), {})
        self.assertEqual(out["totals"]["manual_only"], 1)
        self.assertEqual(out["totals"]["automated_ratio"], 0.0)

    def test_ids_referenced_but_absent_from_the_export_are_reported_not_counted(self):
        # Otherwise a test pointing at another project's case would inflate the
        # ratio against this export.
        path = self._export([{"id": 1, "title": "t", "section": "Bookmarks"}])
        inv = self._inventory([
            {"class_name": "BookmarksTests", "name": "testA", "testrail_id": "1",
             "is_disabled": False},
            {"class_name": "BookmarksTests", "name": "testB",
             "testrail_id": "424242", "is_disabled": False}])
        out = testrail.build(path, self.catalog, inv, {})
        self.assertEqual(out["totals"]["cases"], 1)
        self.assertEqual(out["totals"]["automated"], 1)
        self.assertEqual(out["totals"]["unmatched_ids"], 1)

    def test_cases_are_attributed_to_features_by_section(self):
        path = self._export([
            {"id": 1, "title": "x", "section": "Bookmarks"},
            {"id": 2, "title": "y", "section": "History"}])
        out = testrail.build(path, self.catalog, self._inventory([]), {})
        per = {e["feature_id"]: e["cases"] for e in out["per_feature"]}
        self.assertEqual(per["bookmarks"], 1)
        self.assertEqual(per["history"], 1)

    def test_a_case_matching_no_feature_is_reported_rather_than_spread_around(self):
        path = self._export([{"id": 1, "title": "z", "section": "Telemetry"}])
        out = testrail.build(path, self.catalog, self._inventory([]), {})
        self.assertEqual(out["totals"]["unattributed_cases"], 1)
        self.assertEqual(sum(e["cases"] for e in out["per_feature"]), 0)

    def test_tests_without_a_case_id_are_counted_separately(self):
        path = self._export([{"id": 1, "title": "t", "section": "Bookmarks"}])
        inv = self._inventory([
            {"class_name": "BookmarksTests", "name": "testA", "testrail_id": "",
             "is_disabled": False}])
        out = testrail.build(path, self.catalog, inv, {})
        self.assertEqual(out["totals"]["tests_without_case_id"], 1)

    def test_the_denominator_is_labelled_assumed(self):
        # The report must never present this as a derived coverage percentage.
        path = self._export([{"id": 1, "title": "t", "section": "Bookmarks"}])
        out = testrail.build(path, self.catalog, self._inventory([]), {})
        self.assertEqual(out["denominator"], "assumed")
        self.assertIn("not how much of the app is covered",
                      out["denominator_note"])


class TestRailRunExportTests(unittest.TestCase):
    """Run exports: the columns that differ, and the one that silently lies."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _csv(self, header, rows, name="run.csv"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            for r in rows:
                w.writerow(r)
        return path

    def test_case_id_column_wins_over_the_run_instance_id(self):
        # A run export has both. `ID` is the test-instance id and appears nowhere
        # in the source tree, so preferring it joins nothing and reports 0%
        # automated - plausible and completely wrong.
        path = self._csv(["ID", "Title", "Case ID", "Status"],
                         [["T9474971", "Update from previous version",
                           "C2306813", "Passed"]])
        [case] = testrail.load_export(path)
        self.assertEqual(case["id"], "2306813")

    def test_status_and_priority_are_read_when_present(self):
        path = self._csv(["Case ID", "Title", "Status", "Priority"],
                         [["C1", "t", "Untested", "Critical"]])
        [case] = testrail.load_export(path)
        self.assertEqual(case["status"], "Untested")
        self.assertEqual(case["priority"], "Critical")

    def test_section_ancestors_are_rebuilt_from_the_depth_column(self):
        # TestRail exports only the leaf name, in tree order, with a depth. Many
        # leaves are called "Layout" or "Other" and mean nothing alone.
        path = self._csv(["Case ID", "Title", "Section", "Section Depth"],
                         [["C1", "a", "Bookmarks", "0"],
                          ["C2", "b", "Layout", "1"],
                          ["C3", "c", "History", "0"],
                          ["C4", "d", "Other", "1"]])
        cases = testrail.load_export(path)
        by_id = {c["id"]: c for c in cases}
        self.assertEqual(by_id["2"]["section_path"], ["Bookmarks"])
        # Depth returning to 0 must pop the stack, not accumulate.
        self.assertEqual(by_id["4"]["section_path"], ["History"])

    def test_ancestors_give_an_ambiguous_leaf_a_feature(self):
        catalog = featuremap.FeatureCatalog([
            featuremap.Feature(id="bookmarks", name="Bookmarks", severity=7)])
        ambiguous = {"section": "Layout", "section_path": ["Bookmarks"],
                     "title": "Verify images across all cards"}
        self.assertEqual(testrail._match_feature(ambiguous, catalog), "bookmarks")

    def test_the_longest_match_wins_rather_than_catalog_order(self):
        catalog = featuremap.FeatureCatalog([
            featuremap.Feature(id="settings-general", name="Settings",
                               severity=7, testrail_keywords=["setting"]),
            featuremap.Feature(id="logins-passwords", name="Logins & Passwords",
                               severity=9, testrail_keywords=["password"]),
        ])
        case = {"section": "Settings -> Passwords section", "section_path": [],
                "title": ""}
        # "password" is longer than "setting", so the more specific feature wins
        # even though settings-general is listed first.
        self.assertEqual(testrail._match_feature(case, catalog),
                         "logins-passwords")

    def test_a_row_with_shifted_columns_is_flagged(self):
        # Rich text in a case field pushes the remaining columns along; the id
        # column still parses, so the wrong values would look like real statuses.
        path = self._csv(["Case ID", "Title", "Automation"],
                         [["C1", "fine", "Completed"],
                          ["sans-serif; font-size: 14px", "broken", "32"]])
        cases = testrail.load_export(path)
        self.assertFalse(cases[0]["malformed"])
        self.assertTrue(cases[1]["malformed"])


class TestRailMergeTests(unittest.TestCase):
    """Two exports carry different columns; neither alone is enough."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.suite = os.path.join(self.tmp, "suite.csv")
        with open(self.suite, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["ID", "Title", "Automation", "Automation Coverage"])
            w.writerow(["C1", "Bookmark a page", "Completed", "Full"])
            w.writerow(["C2", "Verify swipe functionality", "Unsuitable", "None"])
            w.writerow(["C3", "Something new", "Suitable", "None"])
        self.run = os.path.join(self.tmp, "run.csv")
        with open(self.run, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["ID", "Case ID", "Title", "Section", "Section Depth",
                        "Status"])
            w.writerow(["T9", "C2", "Verify swipe functionality", "Bookmarks",
                        "0", "Passed"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_merging_fills_blanks_without_overwriting(self):
        cases = testrail.load_exports([self.suite, self.run])
        by_id = {c["id"]: c for c in cases}
        self.assertEqual(len(cases), 3)
        # section came from the run export...
        self.assertEqual(by_id["2"]["section"], "Bookmarks")
        # ...and the automation triage from the suite export.
        self.assertEqual(by_id["2"]["automation_status"], "Unsuitable")

    def test_the_first_file_wins_a_contested_field(self):
        cases = testrail.load_exports([self.suite, self.run])
        by_id = {c["id"]: c for c in cases}
        self.assertEqual(by_id["2"]["title"], "Verify swipe functionality")

    def test_claims_normalise_to_four_verdicts(self):
        self.assertEqual(testrail._claim({"automation_status": "Completed"}),
                         "automated")
        self.assertEqual(testrail._claim({"automation_status": "Unsuitable"}),
                         "manual")
        self.assertEqual(testrail._claim({"automation_status": "Suitable"}),
                         "automatable")
        self.assertEqual(testrail._claim({"automation_status": "Untriaged"}),
                         "untriaged")
        # Coverage alone is enough when the status column is absent.
        self.assertEqual(testrail._claim({"automation_coverage": "Full"}),
                         "automated")

    def test_deliberately_manual_cases_leave_the_addressable_denominator(self):
        catalog = featuremap.FeatureCatalog([
            featuremap.Feature(id="bookmarks", name="Bookmarks", severity=7)])
        inv = {"tests": [{"class_name": "B", "name": "testA",
                          "testrail_id": "1", "is_disabled": False}]}
        out = testrail.build([self.suite], catalog, inv, {})
        t = out["totals"]
        self.assertEqual(t["cases"], 3)
        self.assertEqual(t["deliberately_manual"], 1)
        self.assertEqual(t["addressable_cases"], 2)
        # 1 of 3 overall, but 1 of the 2 that could ever be automated.
        self.assertEqual(t["automated_ratio"], round(1 / 3, 4))
        self.assertEqual(t["automated_ratio_addressable"], 0.5)

    def test_triage_disagreeing_with_the_tree_is_reported_both_ways(self):
        catalog = featuremap.FeatureCatalog([
            featuremap.Feature(id="bookmarks", name="Bookmarks", severity=7)])
        # C1 is triaged automated but nothing links to it; C3 is linked but
        # triaged only "Suitable".
        inv = {"tests": [{"class_name": "B", "name": "testC",
                          "testrail_id": "3", "is_disabled": False}]}
        out = testrail.build([self.suite], catalog, inv, {})
        self.assertEqual(out["totals"]["claimed_not_in_code"], 1)
        self.assertEqual(out["totals"]["in_code_not_claimed"], 1)
        self.assertIn("1", out["claimed_not_in_code"])
        self.assertIn("3", out["in_code_not_claimed"])

    def test_near_disjoint_populations_are_flagged(self):
        # A run export is usually a manual plan. If the automation references
        # hundreds of ids and almost none are here, the ratio is meaningless and
        # printing it without saying so would be the worst output of the tool.
        catalog = featuremap.FeatureCatalog([
            featuremap.Feature(id="bookmarks", name="Bookmarks", severity=7)])
        inv = {"tests": [{"class_name": "B", "name": "test%d" % i,
                          "testrail_id": str(1000 + i), "is_disabled": False}
                         for i in range(50)]}
        out = testrail.build([self.suite], catalog, inv, {})
        self.assertTrue(out["populations_disjoint"])
        self.assertIn("different case sets", out["disjoint_note"])

    def test_overlapping_populations_are_not_flagged(self):
        catalog = featuremap.FeatureCatalog([
            featuremap.Feature(id="bookmarks", name="Bookmarks", severity=7)])
        inv = {"tests": [{"class_name": "B", "name": "testA",
                          "testrail_id": "1", "is_disabled": False}]}
        out = testrail.build([self.suite], catalog, inv, {})
        self.assertFalse(out["populations_disjoint"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
