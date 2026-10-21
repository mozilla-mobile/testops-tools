"""Tests for android/build_mapping.py.

The generator is deterministic given an export and a module inventory, so the
tests build small synthetic indexes rather than touching the real checkout.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from android import build_mapping as bm
from android import testrail_index as ti


def case(case_id, hierarchy, automation="Completed"):
    return ti.TestCase(
        case_id=str(case_id), title=f"case {case_id}",
        section_hierarchy=hierarchy, priority="High",
        automation=automation, automation_coverage="Full",
        case_type="Functional", labels="",
    )


def index(cases, case_to_files=None):
    cases = {c.case_id: c for c in cases}
    return ti.TestRailIndex(
        cases=cases, methods=[], drift=ti.IndexDrift(),
        case_to_files=case_to_files or {}, file_to_cases={},
    )


# =============================================================================
# Module references
# =============================================================================


class TestResolveModule(unittest.TestCase):
    def test_fenix_default(self):
        self.assertEqual(bm.resolve_module("settings"),
                         f"{bm.FENIX_ROOT}/settings")

    def test_android_components_prefix(self):
        self.assertEqual(bm.resolve_module("ac:feature/downloads"),
                         f"{bm.AC_ROOT}/feature/downloads")

    def test_nested_fenix_path(self):
        self.assertEqual(bm.resolve_module("settings/trustpanel"),
                         f"{bm.FENIX_ROOT}/settings/trustpanel")


class TestShortPath(unittest.TestCase):
    def test_disambiguates_same_leaf_across_trees(self):
        """`fenix/search` and `ac/feature/search` both end in `search`; the
        review queue must not render them as a duplicate pair."""
        a = bm._short_path(f"{bm.FENIX_ROOT}/search")
        b = bm._short_path(f"{bm.AC_ROOT}/feature/search")
        self.assertEqual((a, b), ("search", "ac:feature/search"))
        self.assertNotEqual(a, b)


class TestDeterminism(unittest.TestCase):
    def test_ties_break_on_name(self):
        """Counter.most_common() leaves equal counts in insertion order, which
        varies with hash randomisation — the generated YAML churned between
        runs before this."""
        from collections import Counter
        self.assertEqual(
            bm._by_weight_then_name(Counter({"b": 1, "a": 1, "c": 3})),
            [("c", 3), ("a", 1), ("b", 1)],
        )

    def test_evidence_order_is_stable_regardless_of_set_iteration(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / bm.resolve_module("settings")
            d.mkdir(parents=True, exist_ok=True)
            (d / "X.kt").write_text("class X", encoding="utf-8")
            files = {"1": {"a/SettingsTest.kt", "a/SettingsGeneralTest.kt"}}
            first = bm.build_sections(index([case(1, "Menus")], files), str(root))
            second = bm.build_sections(index([case(1, "Menus")], files), str(root))
        self.assertEqual(list(first[0].evidence), list(second[0].evidence))
        self.assertEqual(list(first[0].evidence),
                         ["SettingsGeneralTest", "SettingsTest"])


class TestCuratedTable(unittest.TestCase):
    def test_every_reference_is_well_formed(self):
        for cls, refs in bm.TEST_CLASS_MODULES.items():
            self.assertTrue(refs, cls)
            for ref in refs:
                self.assertFalse(ref.startswith("/"), f"{cls}: {ref}")
                self.assertNotIn("..", ref, f"{cls}: {ref}")

    def test_section_hints_are_well_formed(self):
        for name, refs in bm.SECTION_HINTS.items():
            self.assertTrue(refs, name)


# =============================================================================
# Adaptive depth
# =============================================================================


class TestAssignSectionKeys(unittest.TestCase):
    def test_small_sections_stay_shallow(self):
        cases = [case(i, "Downloads > Files") for i in range(5)]
        keys = bm.assign_section_keys(cases, max_size=80)
        self.assertEqual(set(keys.values()), {"Downloads > Files"})

    def test_oversized_section_descends_one_level(self):
        """`Menus > Settings menu` held 353 cases at depth 2 and accumulated
        20 modules; descending splits it into usable buckets."""
        cases = (
            [case(i, "Menus > Settings menu > General") for i in range(100)]
            + [case(100 + i, "Menus > Settings menu > Advanced") for i in range(20)]
        )
        keys = bm.assign_section_keys(cases, max_size=80)
        self.assertEqual(
            set(keys.values()),
            {"Menus > Settings menu > General", "Menus > Settings menu > Advanced"},
        )

    def test_descends_further_when_still_oversized(self):
        cases = (
            [case(i, "A > B > C > D") for i in range(100)]
            + [case(100 + i, "A > B > C > E") for i in range(10)]
        )
        keys = bm.assign_section_keys(cases, max_size=50)
        self.assertEqual(set(keys.values()), {"A > B > C > D", "A > B > C > E"})

    def test_stops_when_the_hierarchy_runs_out(self):
        """An oversized leaf cannot be split further and must not loop."""
        cases = [case(i, "Downloads") for i in range(200)]
        keys = bm.assign_section_keys(cases, max_size=80)
        self.assertEqual(set(keys.values()), {"Downloads"})

    def test_respects_max_depth(self):
        cases = [case(i, "A > B > C > D > E > F") for i in range(200)]
        keys = bm.assign_section_keys(cases, max_size=10, max_depth=3)
        self.assertEqual(set(keys.values()), {"A > B > C"})

    def test_bracketed_separator_survives(self):
        cases = [case(1, "Accounts & Sync > [Android > 14] Send tabs")]
        keys = bm.assign_section_keys(cases)
        self.assertEqual(keys["1"],
                         "Accounts & Sync > [Android > 14] Send tabs")


# =============================================================================
# Module assignment
# =============================================================================


class TestBuildSections(unittest.TestCase):
    def _repo(self, tmp, modules):
        """Create a checkout skeleton holding exactly `modules`."""
        root = Path(tmp)
        for ref in modules:
            d = root / bm.resolve_module(ref)
            d.mkdir(parents=True, exist_ok=True)
            (d / "X.kt").write_text("class X", encoding="utf-8")
        return str(root)

    def test_evidence_beats_inference(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, ["bookmarks"])
            ix = index(
                [case(1, "Bookmarks")],
                {"1": {"a/BookmarksTest.kt"}},
            )
            sections = bm.build_sections(ix, repo)
        s = sections[0]
        self.assertEqual(s.confidence, "high")
        self.assertEqual([p for p, _, _ in s.modules],
                         [f"{bm.FENIX_ROOT}/bookmarks"])

    def test_module_weight_is_the_case_link_count(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, ["bookmarks"])
            ix = index(
                [case(i, "Bookmarks") for i in range(1, 4)],
                {str(i): {"a/BookmarksTest.kt"} for i in range(1, 4)},
            )
            sections = bm.build_sections(ix, repo)
        self.assertEqual(sections[0].modules[0][2], 3)

    def test_modules_are_sorted_by_weight(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, ["downloads", "ac:feature/downloads", "home"])
            ix = index(
                [case(i, "Downloads") for i in range(1, 5)],
                {
                    "1": {"a/DownloadTest.kt"}, "2": {"a/DownloadTest.kt"},
                    "3": {"a/DownloadTest.kt"}, "4": {"a/HomeScreenTest.kt"},
                },
            )
            sections = bm.build_sections(ix, repo)
        weights = [w for _, _, w in sections[0].modules]
        self.assertEqual(weights, sorted(weights, reverse=True))
        self.assertEqual(weights[-1], 1)      # HomeScreenTest contributed once

    def test_module_list_is_capped(self):
        with TemporaryDirectory() as tmp:
            refs = [r for refs in bm.TEST_CLASS_MODULES.values() for r in refs]
            repo = self._repo(tmp, sorted(set(refs)))
            classes = list(bm.TEST_CLASS_MODULES)[:20]
            ix = index(
                [case(i, "Everything") for i in range(len(classes))],
                {str(i): {f"a/{c}.kt"} for i, c in enumerate(classes)},
            )
            sections = bm.build_sections(ix, repo)
        self.assertLessEqual(len(sections[0].modules), bm.MAX_MODULES)

    def test_renamed_module_is_never_emitted(self):
        """The generator must not point at a directory that no longer exists."""
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, ["home"])        # no `bookmarks/`
            ix = index([case(1, "Bookmarks")], {"1": {"a/BookmarksTest.kt"}})
            sections = bm.build_sections(ix, repo)
        self.assertEqual(sections[0].modules, [])

    def test_name_hint_is_medium_confidence(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, ["translations"])
            ix = index([case(1, "Translations > Error states")])
            sections = bm.build_sections(ix, repo)
        s = sections[0]
        self.assertEqual(s.confidence, "medium")
        self.assertEqual([w for _, _, w in s.modules], [0])

    def test_hint_falls_back_to_a_shorter_prefix(self):
        """A deep section with no exact hint still resolves via its parent."""
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, ["home"])
            ix = index([case(1, "Homescreen > Task continuity > Deep > Deeper")])
            sections = bm.build_sections(ix, repo)
        self.assertEqual([p for p, _, _ in sections[0].modules],
                         [f"{bm.FENIX_ROOT}/home"])

    def test_unmappable_section_is_flagged(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, ["home"])
            ix = index([case(1, "Totally Unknown Area")])
            sections = bm.build_sections(ix, repo)
        s = sections[0]
        self.assertEqual(s.modules, [])
        self.assertIn("UNMAPPED", s.notes)
        self.assertTrue(s.needs_review)

    def test_out_of_scope_section_is_not_mapped(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, ["home"])
            ix = index([case(1, "Relay - not in scope > Something")])
            sections = bm.build_sections(ix, repo)
        self.assertEqual(sections[0].modules, [])
        self.assertIn("out of scope", sections[0].notes)

    def test_unknown_test_class_is_noted(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, ["bookmarks"])
            ix = index(
                [case(1, "Bookmarks"), case(2, "Bookmarks")],
                {"1": {"a/BookmarksTest.kt"}, "2": {"a/BrandNewTest.kt"}},
            )
            sections = bm.build_sections(ix, repo)
        self.assertIn("BrandNewTest", sections[0].notes)

    def test_automation_counts(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, ["downloads"])
            ix = index([
                case(1, "Downloads", "Completed"),
                case(2, "Downloads", "Disabled"),
                case(3, "Downloads", "Unsuitable"),
                case(4, "Downloads", "Suitable"),
                case(5, "Downloads", "Untriaged"),
            ])
            s = bm.build_sections(ix, repo)[0]
        self.assertEqual(
            (s.test_count, s.automated, s.manual_only, s.automation_gap),
            (5, 2, 1, 1))


# =============================================================================
# Rendering
# =============================================================================


class TestRenderYaml(unittest.TestCase):
    def _sections(self, tmp):
        root = Path(tmp)
        for ref in ("bookmarks",):
            d = root / bm.resolve_module(ref)
            d.mkdir(parents=True, exist_ok=True)
            (d / "X.kt").write_text("class X", encoding="utf-8")
        ix = index([case(1, "Bookmarks")], {"1": {"a/BookmarksTest.kt"}})
        return bm.build_sections(ix, str(root)), str(root)

    def test_output_is_valid_yaml_with_expected_shape(self):
        with TemporaryDirectory() as tmp:
            sections, repo = self._sections(tmp)
            text = bm.render_yaml(sections, "export.xlsx", repo)
        parsed = yaml.safe_load(text)
        entry = parsed["sections"][0]
        self.assertEqual(entry["name"], "Bookmarks")
        self.assertEqual(entry["test_count"], 1)
        self.assertEqual(entry["modules"][0]["confidence"], "high")
        self.assertIn("weight", entry["modules"][0])

    def test_quotes_names_containing_yaml_specials(self):
        s = bm.MappedSection("Accounts & Sync > [Android > 14]: tabs")
        s.test_count = 1
        text = bm.render_yaml([s], "e.xlsx", "/repo")
        parsed = yaml.safe_load(text)
        self.assertEqual(parsed["sections"][0]["name"],
                         "Accounts & Sync > [Android > 14]: tabs")

    def test_empty_modules_render_as_a_list(self):
        s = bm.MappedSection("Unknown")
        s.test_count = 2
        parsed = yaml.safe_load(bm.render_yaml([s], "e.xlsx", "/repo"))
        self.assertEqual(parsed["sections"][0]["modules"], [])


class TestRenderReview(unittest.TestCase):
    def test_lists_unmapped_and_inferred_separately(self):
        unmapped = bm.MappedSection("Unknown Area")
        unmapped.test_count = 9
        inferred = bm.MappedSection("Translations > Errors")
        inferred.test_count = 4
        inferred.modules = [(f"{bm.FENIX_ROOT}/translations", "medium", 0)]
        evident = bm.MappedSection("Bookmarks")
        evident.test_count = 30
        evident.modules = [(f"{bm.FENIX_ROOT}/bookmarks", "high", 18)]

        text = bm.render_review([evident, unmapped, inferred])
        self.assertIn("Unmapped sections (1)", text)
        self.assertIn("Unknown Area", text)
        self.assertIn("Mapped by name only (1)", text)
        self.assertIn("Translations > Errors", text)
        # The high-confidence section needs no review mention beyond the total.
        self.assertNotIn("- **Bookmarks**", text)

    def test_reports_coverage(self):
        a = bm.MappedSection("A")
        a.test_count = 30
        a.modules = [(f"{bm.FENIX_ROOT}/bookmarks", "high", 1)]
        b = bm.MappedSection("B")
        b.test_count = 10
        self.assertIn("30/40 cases (75%)", bm.render_review([a, b]))


if __name__ == "__main__":
    unittest.main()
