"""Tests for align.py — drift detection, module discovery, YAML round-trip.

Interactive review, LLM proposals, and the CLI orchestrator are intentionally
NOT covered here: they require heavy mocking of stdin/anthropic and the payoff
is low. This suite locks down the deterministic layer: what modules the
scanner surfaces, what findings drift produces, and how the YAML writer
mutates the mapping without corrupting comments or structure.
"""

from __future__ import annotations

import datetime
import io
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from align import (
    DriftReport,
    NewModuleFinding,
    NewSectionFinding,
    StaleSectionFinding,
    _contains_swift_recursive,
    _flow_module_entry,
    _make_yaml,
    add_module_to_section,
    append_module_without_section,
    append_section,
    detect_drift,
    discover_repo_modules,
    load_mapping_roundtrip,
    remove_section,
    save_mapping_roundtrip,
    write_pending,
)
from recommend import TestCase


# =============================================================================
# Helpers
# =============================================================================


def _make_test(section_top: str, title: str = "t", automation: str = "Unsuitable", tc_id: str = "C1") -> TestCase:
    """Minimal TestCase factory. Fields not exercised in these tests are stubbed."""
    return TestCase(
        id=tc_id,
        title=title,
        section_top=section_top,
        section_hierarchy=section_top,
        sub_suite="Functional",
        automation=automation,
        automated_test_name=None,
    )


def _touch(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# =============================================================================
# _contains_swift_recursive
# =============================================================================


class ContainsSwiftRecursiveTests(unittest.TestCase):
    def test_empty_dir_false(self):
        with TemporaryDirectory() as d:
            self.assertFalse(_contains_swift_recursive(Path(d)))

    def test_swift_at_root_true(self):
        with TemporaryDirectory() as d:
            _touch(Path(d) / "Foo.swift")
            self.assertTrue(_contains_swift_recursive(Path(d)))

    def test_swift_two_levels_deep_true(self):
        with TemporaryDirectory() as d:
            _touch(Path(d) / "sub1" / "sub2" / "Foo.swift")
            self.assertTrue(_contains_swift_recursive(Path(d)))

    def test_swift_beyond_max_depth_false(self):
        # Default max_depth=3 means root + 3 nested = 4 levels reachable.
        # Explicit max_depth=1 => only root and immediate children.
        with TemporaryDirectory() as d:
            _touch(Path(d) / "sub1" / "sub2" / "Foo.swift")
            self.assertFalse(_contains_swift_recursive(Path(d), max_depth=1))

    def test_hidden_dirs_skipped(self):
        with TemporaryDirectory() as d:
            _touch(Path(d) / ".git" / "Foo.swift")
            self.assertFalse(_contains_swift_recursive(Path(d)))

    def test_only_non_swift_files_false(self):
        with TemporaryDirectory() as d:
            _touch(Path(d) / "README.md")
            _touch(Path(d) / "sub" / "config.plist")
            self.assertFalse(_contains_swift_recursive(Path(d)))


# =============================================================================
# discover_repo_modules
# =============================================================================


class DiscoverRepoModulesTests(unittest.TestCase):
    def test_empty_repo_returns_empty(self):
        with TemporaryDirectory() as d:
            self.assertEqual(discover_repo_modules(Path(d)), [])

    def test_frontend_module_discovered(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            _touch(root / "firefox-ios" / "Client" / "Frontend" / "Home" / "HomeVC.swift", "// swift")
            result = discover_repo_modules(root)
            self.assertIn("firefox-ios/Client/Frontend/Home", result)

    def test_browserkit_sources_module_discovered(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            _touch(root / "BrowserKit" / "Sources" / "ToolbarKit" / "Toolbar.swift", "// swift")
            result = discover_repo_modules(root)
            self.assertIn("BrowserKit/Sources/ToolbarKit", result)

    def test_container_pruning_client_not_surfaced_under_firefox_ios(self):
        # `firefox-ios/Client` is a container (parent of `firefox-ios/Client/Frontend`),
        # not a leaf module. Even with a .swift file directly under it, it should NOT
        # be surfaced when both `firefox-ios` and `firefox-ios/Client` are parent scan roots.
        with TemporaryDirectory() as d:
            root = Path(d)
            _touch(root / "firefox-ios" / "Client" / "SomeFile.swift", "// swift")
            result = discover_repo_modules(root)
            self.assertNotIn("firefox-ios/Client", result)

    def test_frontend_container_not_surfaced_under_client(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            _touch(root / "firefox-ios" / "Client" / "Frontend" / "Home" / "HomeVC.swift", "// swift")
            result = discover_repo_modules(root)
            self.assertNotIn("firefox-ios/Client/Frontend", result)

    def test_noise_dirs_filtered(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            # Noise: Tests, firefox-ios-tests, Documentation, scripts, ThirdParty
            for noise in ("Tests", "firefox-ios-tests", "Documentation", "scripts", "ThirdParty"):
                _touch(root / "firefox-ios" / noise / "X.swift", "// swift")
            result = discover_repo_modules(root)
            for noise in ("Tests", "firefox-ios-tests", "Documentation", "scripts", "ThirdParty"):
                self.assertNotIn(f"firefox-ios/{noise}", result)

    def test_xcodeproj_and_xcworkspace_filtered(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            _touch(root / "firefox-ios" / "Client" / "Client.xcodeproj" / "project.pbxproj", "")
            _touch(root / "firefox-ios" / "Client" / "Client.xcworkspace" / "contents.xcworkspacedata", "")
            result = discover_repo_modules(root)
            self.assertNotIn("firefox-ios/Client/Client.xcodeproj", result)
            self.assertNotIn("firefox-ios/Client/Client.xcworkspace", result)

    def test_dir_without_swift_filtered(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            # A well-named dir under a module parent, but with no Swift → excluded
            _touch(root / "firefox-ios" / "Client" / "Frontend" / "ConfigOnly" / "config.json", "{}")
            result = discover_repo_modules(root)
            self.assertNotIn("firefox-ios/Client/Frontend/ConfigOnly", result)

    def test_output_is_sorted(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            _touch(root / "firefox-ios" / "Client" / "Frontend" / "Zeta" / "A.swift", "// swift")
            _touch(root / "firefox-ios" / "Client" / "Frontend" / "Alpha" / "A.swift", "// swift")
            _touch(root / "firefox-ios" / "Client" / "Frontend" / "Middle" / "A.swift", "// swift")
            result = discover_repo_modules(root)
            self.assertEqual(result, sorted(result))


# =============================================================================
# detect_drift
# =============================================================================


class DetectDriftTests(unittest.TestCase):
    def _mapping(self, sections: list[str], without_section: list[str] | None = None) -> dict:
        return {
            "sections": [
                {"name": s, "modules": [{"path": f"firefox-ios/Client/Frontend/{s}"}]}
                for s in sections
            ],
            "modules_without_clear_section": without_section or [],
        }

    def test_all_aligned_produces_empty_report(self):
        mapping = self._mapping(["Home"])
        tests = [_make_test("Home")]
        repo_modules = ["firefox-ios/Client/Frontend/Home"]
        report = detect_drift(tests, mapping, repo_modules)
        self.assertTrue(report.empty)

    def test_new_section_when_testrail_has_extra(self):
        mapping = self._mapping(["Home"])
        tests = [_make_test("Home"), _make_test("Library")]
        report = detect_drift(tests, mapping, repo_modules=[])
        self.assertEqual([f.name for f in report.new_sections], ["Library"])

    def test_stale_section_when_yaml_has_extra(self):
        mapping = self._mapping(["Home", "OldFeature"])
        tests = [_make_test("Home")]
        report = detect_drift(tests, mapping, repo_modules=[])
        self.assertEqual([f.name for f in report.stale_sections], ["OldFeature"])

    def test_new_module_when_repo_has_extra(self):
        mapping = self._mapping(["Home"])
        report = detect_drift(
            [_make_test("Home")],
            mapping,
            repo_modules=[
                "firefox-ios/Client/Frontend/Home",  # covered
                "firefox-ios/Client/Frontend/Uncovered",  # drift
            ],
        )
        self.assertEqual([f.path for f in report.new_modules], ["firefox-ios/Client/Frontend/Uncovered"])

    def test_prefix_match_skips_child_of_declared_parent(self):
        # Parent `firefox-ios/Client` is declared; child `firefox-ios/Client/Frontend/X`
        # is covered by longest-prefix match at recommend-time, so it's NOT drift.
        mapping = {
            "sections": [
                {"name": "Wide", "modules": [{"path": "firefox-ios/Client"}]},
            ],
        }
        report = detect_drift(
            tests=[_make_test("Wide")],
            mapping=mapping,
            repo_modules=["firefox-ios/Client/Frontend/Sub"],
        )
        self.assertEqual(report.new_modules, [])

    def test_new_module_declared_via_modules_without_clear_section(self):
        mapping = {
            "sections": [{"name": "Home", "modules": [{"path": "firefox-ios/Client/Frontend/Home"}]}],
            "modules_without_clear_section": ["firefox-ios/Shared"],
        }
        report = detect_drift(
            tests=[_make_test("Home")],
            mapping=mapping,
            repo_modules=["firefox-ios/Shared"],
        )
        # Already declared under modules_without_clear_section → not drift.
        self.assertEqual(report.new_modules, [])

    def test_new_section_finding_has_test_count(self):
        mapping = self._mapping(["Home"])
        tests = [
            _make_test("Home"),
            _make_test("NewOne", tc_id="C10"),
            _make_test("NewOne", tc_id="C11", automation="Completed"),
            _make_test("NewOne", tc_id="C12", automation="Completed"),
        ]
        report = detect_drift(tests, mapping, repo_modules=[])
        finding = report.new_sections[0]
        self.assertEqual(finding.name, "NewOne")
        self.assertEqual(finding.test_count, 3)
        self.assertEqual(finding.automated_count, 2)

    def test_sample_titles_capped_at_five(self):
        mapping = self._mapping([])
        tests = [_make_test("Fresh", title=f"title-{i}", tc_id=f"C{i}") for i in range(10)]
        report = detect_drift(tests, mapping, repo_modules=[])
        self.assertEqual(len(report.new_sections[0].sample_titles), 5)
        self.assertEqual(report.new_sections[0].sample_titles[0], "title-0")

    def test_empty_section_top_ignored(self):
        # A TestCase with no section_top must not appear as a new_section.
        mapping = self._mapping(["Home"])
        tests = [_make_test("Home"), _make_test("", tc_id="C99")]
        report = detect_drift(tests, mapping, repo_modules=[])
        self.assertEqual(report.new_sections, [])


class DriftReportEmptyTests(unittest.TestCase):
    def test_default_is_empty(self):
        self.assertTrue(DriftReport().empty)

    def test_new_section_makes_non_empty(self):
        r = DriftReport(new_sections=[NewSectionFinding("x", 1, 0, [])])
        self.assertFalse(r.empty)

    def test_stale_section_makes_non_empty(self):
        r = DriftReport(stale_sections=[StaleSectionFinding("x")])
        self.assertFalse(r.empty)

    def test_new_module_makes_non_empty(self):
        r = DriftReport(new_modules=[NewModuleFinding("x")])
        self.assertFalse(r.empty)


# =============================================================================
# YAML round-trip
# =============================================================================


MAPPING_YAML = textwrap.dedent("""\
    # Firefox iOS section↔module mapping
    sections:
      - name: Home
        test_count: 42
        automated: 10
        modules:
          - {path: firefox-ios/Client/Frontend/Home, confidence: high}

    # Cross-cutting modules that don't belong to a single TestRail section
    modules_without_clear_section:
      - firefox-ios/Shared
""")


class RoundtripLoadSaveTests(unittest.TestCase):
    def test_load_and_save_preserves_top_level_comment(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "mapping.yaml"
            p.write_text(MAPPING_YAML)
            data = load_mapping_roundtrip(p)
            save_mapping_roundtrip(data, p)
            self.assertIn("# Firefox iOS section↔module mapping", p.read_text())

    def test_load_returns_dict_like(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "mapping.yaml"
            p.write_text(MAPPING_YAML)
            data = load_mapping_roundtrip(p)
            self.assertIn("sections", data)
            self.assertIn("modules_without_clear_section", data)
            self.assertEqual(data["sections"][0]["name"], "Home")

    def test_flow_module_entry_has_expected_fields(self):
        entry = _flow_module_entry("firefox-ios/Client/Foo", "medium")
        self.assertIsInstance(entry, CommentedMap)
        self.assertEqual(entry["path"], "firefox-ios/Client/Foo")
        self.assertEqual(entry["confidence"], "medium")


class AppendSectionTests(unittest.TestCase):
    def _load(self) -> tuple[Path, "CommentedMap"]:
        d = TemporaryDirectory()
        p = Path(d.name) / "m.yaml"
        p.write_text(MAPPING_YAML)
        mapping = load_mapping_roundtrip(p)
        self.addCleanup(d.cleanup)
        return p, mapping

    def test_appends_to_sections_list(self):
        _, mapping = self._load()
        before = len(mapping["sections"])
        append_section(mapping, "NewFeature", 12, 3,
                       modules=[{"path": "firefox-ios/Client/Frontend/NewFeature", "confidence": "high"}])
        self.assertEqual(len(mapping["sections"]), before + 1)
        added = mapping["sections"][-1]
        self.assertEqual(added["name"], "NewFeature")
        self.assertEqual(added["test_count"], 12)
        self.assertEqual(added["automated"], 3)
        self.assertEqual(len(added["modules"]), 1)

    def test_raises_when_sections_missing(self):
        with self.assertRaises(RuntimeError):
            append_section({}, "X", 0, 0, modules=[])

    def test_stamp_comment_is_written(self):
        p, mapping = self._load()
        append_section(mapping, "StampedFeature", 5, 1,
                       modules=[{"path": "firefox-ios/Client/Frontend/StampedFeature", "confidence": "low"}],
                       stamp_comment="added 2026-08-27 by align.py")
        save_mapping_roundtrip(mapping, p)
        text = p.read_text()
        self.assertIn("StampedFeature", text)
        self.assertIn("added 2026-08-27 by align.py", text)


class AddModuleToSectionTests(unittest.TestCase):
    def _load(self) -> "CommentedMap":
        with TemporaryDirectory() as d:
            p = Path(d) / "m.yaml"
            p.write_text(MAPPING_YAML)
            return load_mapping_roundtrip(p)

    def test_adds_new_module_returns_true(self):
        mapping = self._load()
        ok = add_module_to_section(mapping, "Home", "firefox-ios/Client/Frontend/NewChild", "medium")
        self.assertTrue(ok)
        mods = [m["path"] for m in mapping["sections"][0]["modules"]]
        self.assertIn("firefox-ios/Client/Frontend/NewChild", mods)

    def test_dedup_returns_false_when_path_present(self):
        mapping = self._load()
        ok = add_module_to_section(mapping, "Home", "firefox-ios/Client/Frontend/Home", "medium")
        self.assertFalse(ok)

    def test_returns_false_when_section_not_found(self):
        mapping = self._load()
        ok = add_module_to_section(mapping, "GhostSection", "firefox-ios/Client/X", "medium")
        self.assertFalse(ok)


class AppendModuleWithoutSectionTests(unittest.TestCase):
    def test_appends_when_list_present(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "m.yaml"
            p.write_text(MAPPING_YAML)
            mapping = load_mapping_roundtrip(p)
            append_module_without_section(mapping, "firefox-ios/NewCrossCutting")
            self.assertIn("firefox-ios/NewCrossCutting",
                          list(mapping["modules_without_clear_section"]))

    def test_creates_list_when_missing(self):
        mapping = CommentedMap()
        mapping["sections"] = CommentedSeq()
        append_module_without_section(mapping, "firefox-ios/OnlyOne")
        self.assertEqual(list(mapping["modules_without_clear_section"]), ["firefox-ios/OnlyOne"])

    def test_tag_comment_written(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "m.yaml"
            p.write_text(MAPPING_YAML)
            mapping = load_mapping_roundtrip(p)
            append_module_without_section(mapping, "firefox-ios/Tagged",
                                          tag_comment="added 2026-08-27 by align.py")
            save_mapping_roundtrip(mapping, p)
            self.assertIn("added 2026-08-27 by align.py", p.read_text())


class RemoveSectionTests(unittest.TestCase):
    def test_removes_by_name_returns_true(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "m.yaml"
            p.write_text(MAPPING_YAML)
            mapping = load_mapping_roundtrip(p)
            ok = remove_section(mapping, "Home")
            self.assertTrue(ok)
            self.assertEqual([s["name"] for s in mapping["sections"]], [])

    def test_returns_false_when_not_found(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "m.yaml"
            p.write_text(MAPPING_YAML)
            mapping = load_mapping_roundtrip(p)
            self.assertFalse(remove_section(mapping, "GhostSection"))


# =============================================================================
# write_pending
# =============================================================================


class WritePendingTests(unittest.TestCase):
    def test_no_file_created_for_empty_entries(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "pending.yaml"
            write_pending(p, [])
            self.assertFalse(p.exists())

    def test_payload_has_generated_by_and_at_and_entries(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "pending.yaml"
            write_pending(p, [{"kind": "new_section", "name": "X"}])
            text = p.read_text()
            self.assertIn("generated_by: align.py", text)
            # ruamel may quote the ISO date; match date substring rather than exact form.
            today = datetime.date.today().isoformat()
            self.assertIn(today, text)
            self.assertIn("new_section", text)
            self.assertIn("X", text)

    def test_multiple_entries_roundtrip(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "pending.yaml"
            write_pending(p, [
                {"kind": "new_section", "name": "A"},
                {"kind": "new_module", "path": "firefox-ios/X"},
            ])
            reloaded = _make_yaml().load(io.StringIO(p.read_text()))
            self.assertEqual(len(reloaded["entries"]), 2)
            self.assertEqual(reloaded["entries"][0]["kind"], "new_section")
            self.assertEqual(reloaded["entries"][1]["path"], "firefox-ios/X")


if __name__ == "__main__":
    unittest.main()
