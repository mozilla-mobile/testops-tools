# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for feature_map.py and drift.py against small synthetic repos. Needs PyYAML only."""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import drift  # noqa: E402
import taxonomy  # noqa: E402
import feature_map  # noqa: E402
from feature_map import FeatureMap, Rule  # noqa: E402


IOS_MAP = """\
platform: ios
repo: example/firefox-ios
base: ""
extensions: [".swift"]
roots:
  - App
rules:
  - {path: "App/**", feature: SHARED.SHELL}
  - {path: "App/Library/Bookmarks/**", feature: LIB.BMK}
  - {path: "App/Library/History/**", feature: LIB.HIST}
  - {path: "App/Find/FindInPage.swift", feature: BRW.FIND}
  - {path: "App/Generated/**", feature: EXCLUDED, optional: true}
"""

ANDROID_MAP = """\
platform: android
repo: example/firefox
base: mobile/android
extensions: [".kt", ".java"]
require_path_segment: src/main
skip_dirs: [build]
layers:
  fenix/: Fenix
  ac/: AC
roots:
  - fenix
  - ac
rules:
  - {path: "fenix/**", feature: SHARED.SHELL}
  - {path: "ac/feature/findinpage/**", feature: BRW.FIND}
"""


class Repo:
    """A throwaway checkout plus a copy of the map, so tests can edit both."""

    def __init__(self, map_text, files, platform="ios"):
        self.dir = tempfile.mkdtemp()
        self.repo = os.path.join(self.dir, "repo")
        self.platform = platform
        os.makedirs(os.path.join(self.dir, "maps", platform))
        self.map_path = os.path.join(self.dir, "maps", platform, "feature-map.yml")
        with open(self.map_path, "w") as f:
            f.write(map_text)
        for path in files:
            self.add(path)

    def add(self, path, body="line\n"):
        full = os.path.join(self.repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(body)

    def move(self, old, new):
        os.makedirs(os.path.dirname(os.path.join(self.repo, new)), exist_ok=True)
        os.rename(os.path.join(self.repo, old), os.path.join(self.repo, new))

    def fm(self):
        return FeatureMap(self.platform, self.repo, map_path=self.map_path)

    def map_text(self):
        with open(self.map_path) as f:
            return f.read()

    def cleanup(self):
        shutil.rmtree(self.dir)


IOS_FILES = [
    "App/AppDelegate.swift",
    "App/Library/Bookmarks/BookmarksPanel.swift",
    "App/Library/Bookmarks/BookmarkCell.swift",
    "App/Library/Bookmarks/BookmarksStore.swift",
    "App/Library/Bookmarks/BookmarksSync.swift",
    "App/Library/Bookmarks/BookmarksFolder.swift",
    "App/Library/History/HistoryPanel.swift",
    "App/Find/FindInPage.swift",
]


class RuleTests(unittest.TestCase):
    def test_glob_semantics(self):
        r = Rule({"path": "a/**/c/*.swift", "feature": "X"}, 0)
        self.assertTrue(r.matches("a/c/d.swift"))
        self.assertTrue(r.matches("a/b/b2/c/d.swift"))
        self.assertFalse(r.matches("a/c/e/d.swift"))

    def test_specificity_order(self):
        exact = Rule({"path": "a/b/c.swift", "feature": "X"}, 0)
        deep = Rule({"path": "a/b/**", "feature": "X"}, 1)
        shallow = Rule({"path": "a/**", "feature": "X"}, 2)
        self.assertGreater(exact.specificity, deep.specificity)
        self.assertGreater(deep.specificity, shallow.specificity)

    def test_unreviewed(self):
        self.assertTrue(Rule({"path": "a", "feature": "X"}, 0).reviewed)
        self.assertFalse(Rule({"path": "a", "feature": "X", "by": "ai"}, 0).reviewed)
        self.assertFalse(Rule({"path": "a", "feature": "X", "by": "drift"}, 0).reviewed)


class TaxonomyTests(unittest.TestCase):
    def test_real_taxonomy_loads_with_area_ids(self):
        ids = feature_map.load_taxonomy()
        self.assertIn("BRW.NAV", ids)
        self.assertIn("SHARED.SHELL", ids)
        self.assertIn("EXCLUDED", ids)
        self.assertEqual(ids["CRED"]["group"], "area")

    def test_real_maps_only_use_known_ids(self):
        ids = feature_map.load_taxonomy()
        import yaml
        for platform in feature_map.PLATFORMS:
            with open(os.path.join(os.path.dirname(HERE), platform, "feature-map.yml")) as f:
                cfg = yaml.safe_load(f)
            self.assertEqual(cfg["platform"], platform)
            for rule in cfg["rules"]:
                self.assertIn(rule["feature"], ids, f"{platform}: {rule['path']}")
                Rule(rule, 0)   # parses


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.r = Repo(IOS_MAP, IOS_FILES)

    def tearDown(self):
        self.r.cleanup()

    def test_clean_map_passes_and_optional_rule_is_not_dead(self):
        p = self.r.fm().problems()
        self.assertEqual(sum(len(v) for v in p.values()), 0, p)

    def test_most_specific_rule_wins(self):
        fm = self.r.fm()
        self.assertEqual(fm.feature_of("App/AppDelegate.swift"), "SHARED.SHELL")
        self.assertEqual(fm.feature_of("App/Library/Bookmarks/BookmarkCell.swift"), "LIB.BMK")
        self.assertEqual(fm.feature_of("App/Find/FindInPage.swift"), "BRW.FIND")

    def test_ambiguous_dead_and_unknown(self):
        with open(self.r.map_path, "a") as f:
            f.write('  - {path: "App/Library/*/BookmarksPanel.swift", feature: LIB.BMK}\n'
                    '  - {path: "App/Library/Bookmarks/*Panel.swift", feature: LIB.HIST}\n'
                    '  - {path: "App/Gone.swift", feature: BRW.NAV}\n'
                    '  - {path: "App/Find/FindBar.swift", feature: NOPE.X}\n')
        self.r.add("App/Find/FindBar.swift")
        p = self.r.fm().problems()
        self.assertEqual([a[0] for a in p["ambiguous"]], ["App/Library/Bookmarks/BookmarksPanel.swift"])
        self.assertEqual([r.path for r in p["dead_rules"]], ["App/Gone.swift"])
        self.assertEqual([f for _, f in p["unknown_ids"]], ["NOPE.X"])

    def test_cli_check_exit_code(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(feature_map.main(["ios", "--repo", self.r.repo, "--map", self.r.map_path, "check"]), 0)
        self.r.add("Elsewhere/Ignored.swift")   # outside roots
        os.remove(os.path.join(self.r.repo, "App/Find/FindInPage.swift"))
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(feature_map.main(["ios", "--repo", self.r.repo, "--map", self.r.map_path, "check"]), 1)
        self.assertIn("rule matches no files: App/Find/FindInPage.swift", out.getvalue())


class AndroidDiscoveryTests(unittest.TestCase):
    def test_only_src_main_and_layers(self):
        r = Repo(ANDROID_MAP, [
            "mobile/android/fenix/app/src/main/java/org/A.kt",
            "mobile/android/fenix/app/src/test/java/org/ATest.kt",
            "mobile/android/fenix/app/src/androidTest/java/org/AUi.kt",
            "mobile/android/fenix/app/build/generated/src/main/java/G.kt",
            "mobile/android/ac/feature/findinpage/src/main/java/F.java",
            "mobile/android/ac/feature/findinpage/src/main/res/x.xml",
        ], platform="android")
        try:
            fm = r.fm()
            self.assertEqual(fm.source_files(), ["ac/feature/findinpage/src/main/java/F.java",
                                                 "fenix/app/src/main/java/org/A.kt"])
            self.assertEqual(fm.layer_of("ac/feature/findinpage/src/main/java/F.java"), "AC")
            self.assertEqual(fm.layer_of("fenix/app/src/main/java/org/A.kt"), "Fenix")
        finally:
            r.cleanup()


class DriftTests(unittest.TestCase):
    def setUp(self):
        # Drop the catch-all so new code can actually be unmapped.
        self.r = Repo(IOS_MAP.replace('  - {path: "App/**", feature: SHARED.SHELL}\n',
                                      '  - {path: "App/AppDelegate.swift", feature: SHARED.SHELL}\n'), IOS_FILES)

    def tearDown(self):
        self.r.cleanup()

    def test_tokens(self):
        self.assertEqual(drift.tokens("VPNServerManager"), {"vpn", "server"})
        self.assertEqual(drift.tokens("installation-blockstore"), {"installation", "blockstore"})

    def test_new_directory_is_one_glob_and_stray_file_is_exact(self):
        self.r.add("App/Library/Readinglist/ReadingListPanel.swift")
        self.r.add("App/Library/Readinglist/ReadingListCell.swift")
        self.r.add("App/Library/Bookmarks/BookmarksEditor.swift")   # covered by glob: not unmapped
        self.r.add("App/Find/FindBar.swift")                        # stray file in a mapped dir
        report = drift.build_report(self.r.fm())
        rules = {u["rule"]: u for u in report["unmapped"]}
        self.assertEqual(set(rules), {"App/Library/Readinglist/**", "App/Find/FindBar.swift"})
        self.assertEqual(len(rules["App/Library/Readinglist/**"]["files"]), 2)
        # Every mapped file in App/Find is BRW.FIND, so the stray file is a confident match.
        self.assertEqual(rules["App/Find/FindBar.swift"]["feature"], "BRW.FIND")
        self.assertEqual(rules["App/Find/FindBar.swift"]["confidence"], "high")
        self.assertTrue(report["has_drift"])

    def test_neighbour_majority_gives_high_confidence(self):
        self.r.add("App/Library/Bookmarks/Sub/New.swift")
        # Narrow Bookmarks/** to its own files so the new Sub/ directory is unmapped.
        with open(self.r.map_path) as f:
            text = f.read().replace('"App/Library/Bookmarks/**"', '"App/Library/Bookmarks/*.swift"')
        with open(self.r.map_path, "w") as f:
            f.write(text)
        report = drift.build_report(self.r.fm())
        (u,) = report["unmapped"]
        self.assertEqual(u["rule"], "App/Library/Bookmarks/Sub/**")
        self.assertEqual((u["feature"], u["confidence"]), ("LIB.BMK", "high"))

    def test_moved_file_is_detected_and_applied(self):
        self.r.move("App/Find/FindInPage.swift", "App/Library/FindInPage.swift")
        with open(self.r.map_path, "a") as f:
            f.write('  - {path: "App/Library/**", feature: LIB.BMK}\n')
        report = drift.build_report(self.r.fm())
        (dead,) = report["dead_rules"]
        self.assertEqual(dead["moved_to"], "App/Library/FindInPage.swift")
        self.assertEqual(drift.apply(self.r.fm(), report), 1)
        self.assertIn('path: "App/Library/FindInPage.swift", feature: BRW.FIND', self.r.map_text())
        self.assertEqual(self.r.fm().feature_of("App/Library/FindInPage.swift"), "BRW.FIND")

    def test_apply_writes_only_confident_rules_and_snapshot(self):
        self.r.add("App/Find/FindBar.swift")                         # high
        self.r.add("App/Zzqx/Qwerty.swift")                          # nothing to go on: low
        report = drift.build_report(self.r.fm())
        self.assertEqual(report["snapshot"], "missing")
        self.assertEqual(drift.apply(self.r.fm(), report), 1)
        text = self.r.map_text()
        self.assertIn('{path: "App/Find/FindBar.swift", feature: BRW.FIND, by: drift}', text)
        self.assertNotIn("Zzqx", text)
        fm = self.r.fm()
        self.assertEqual([p for p in fm.problems()["unmapped"]], ["App/Zzqx/Qwerty.swift"])
        snapshot = drift.read_snapshot(fm)
        self.assertEqual(snapshot["App/Find/FindBar.swift"], "BRW.FIND")
        self.assertEqual(snapshot["App/Zzqx/Qwerty.swift"], "UNMAPPED")

    def test_review_section_against_snapshot(self):
        fm = self.r.fm()
        drift.apply(fm, drift.build_report(fm))                      # baseline snapshot, no rule changes
        self.r.add("App/Library/History/HistorySearch.swift")       # silently picked up by a glob
        self.r.move("App/Library/Bookmarks/BookmarksSync.swift", "App/Library/History/BookmarksSync.swift")
        os.remove(os.path.join(self.r.repo, "App/Library/Bookmarks/BookmarksFolder.swift"))
        report = drift.build_report(self.r.fm())
        review = report["review"]
        self.assertEqual([n["path"] for n in review["new"]], ["App/Library/History/HistorySearch.swift"])
        self.assertEqual(review["new"][0]["feature"], "LIB.HIST")
        (moved,) = review["moved"]
        self.assertEqual((moved["old_feature"], moved["feature"]), ("LIB.BMK", "LIB.HIST"))
        self.assertEqual(review["removed"], ["App/Library/Bookmarks/BookmarksFolder.swift"])
        self.assertTrue(report["has_drift"])
        md = drift.to_markdown(self.r.fm(), report)
        self.assertIn("feature changed `LIB.BMK` → `LIB.HIST`", md)

    def test_moved_into_directory_without_glob_is_not_proposed_twice(self):
        # App/Find has only exact rules, so the moved file matches nothing there.
        self.r.move("App/Library/History/HistoryPanel.swift", "App/Find/HistoryPanel.swift")
        report = drift.build_report(self.r.fm())
        (dead,) = report["dead_rules"]
        self.assertEqual(dead["rule"], "App/Library/History/**")   # glob dead: nothing left in History/
        # Now an exact rule whose file moves into App/Find:
        self.r.move("App/Find/HistoryPanel.swift", "App/Library/History/HistoryPanel.swift")
        with open(self.r.map_path, "a") as f:
            f.write('  - {path: "App/Library/History/HistoryPanel.swift", feature: LIB.HIST}\n')
        self.r.move("App/Library/History/HistoryPanel.swift", "App/Find/HistoryPanel.swift")
        self.r.add("App/Library/History/Keep.swift")   # keep the History/** glob alive
        report = drift.build_report(self.r.fm())
        moved = [d for d in report["dead_rules"] if d["moved_to"]]
        self.assertEqual([d["moved_to"] for d in moved], ["App/Find/HistoryPanel.swift"])
        self.assertNotIn("App/Find/HistoryPanel.swift", [u["rule"] for u in report["unmapped"]])
        drift.apply(self.r.fm(), report)
        fm = self.r.fm()
        self.assertEqual(sum(len(v) for v in fm.problems().values()), 0, fm.problems())
        self.assertEqual(fm.feature_of("App/Find/HistoryPanel.swift"), "LIB.HIST")

    def test_review_only_changes_do_not_need_action(self):
        fm = self.r.fm()
        drift.apply(fm, drift.build_report(fm))
        self.r.add("App/Library/History/HistorySearch.swift")       # picked up by a glob: review only
        report = drift.build_report(self.r.fm())
        self.assertTrue(report["needs_review"])
        self.assertFalse(report["needs_action"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(feature_map.main(["ios", "--repo", self.r.repo, "--map", self.r.map_path,
                                               "drift", "--fail-on-action"]), 0)
        self.r.add("App/Zzqx/New.swift")                             # unmapped: needs action
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(feature_map.main(["ios", "--repo", self.r.repo, "--map", self.r.map_path,
                                               "drift", "--fail-on-action"]), 1)

    def test_no_drift_when_clean(self):
        fm = self.r.fm()
        drift.apply(fm, drift.build_report(fm))
        report = drift.build_report(self.r.fm())
        self.assertFalse(report["has_drift"])
        self.assertIn("`check` passes", drift.to_markdown(self.r.fm(), report))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(feature_map.main(["ios", "--repo", self.r.repo, "--map", self.r.map_path,
                                               "drift", "--fail-on-action", "--format", "json"]), 0)


class TaxonomyListTests(unittest.TestCase):
    def test_features_md_is_in_sync_with_features_yml(self):
        with open(taxonomy.FEATURES_MD) as f:
            current = f.read()
        self.assertEqual(current, taxonomy.to_markdown(taxonomy.load()),
                         "FEATURES.md is out of date. Run: uv run mobile-feature-taxonomy/taxonomy.py")

    def test_csv_has_every_feature_once(self):
        import csv
        data = taxonomy.load()
        rows = list(csv.DictReader(io.StringIO(taxonomy.to_csv(data))))
        self.assertEqual([r["l2_id"] for r in rows], [f["id"] for f in data["features"]])
        self.assertTrue(all(r["l2_id"].split(".")[0] == r["l1_id"] for r in rows))

    def test_platform_columns_come_from_the_maps(self):
        data = {"features": [{"id": "A.X", "area": "Area & more", "name": "x"},
                             {"id": "A.Y", "area": "Area & more", "name": "y"}]}
        rows = list(taxonomy.rows(data, mapped={"ios": {"A.Y"}, "android": {"A.X", "A.Y"}}))
        self.assertEqual([(r["ios"], r["android"]) for r in rows], [("no", "yes"), ("yes", "yes")])
        self.assertIn("BRW.NAV", taxonomy.mapped_features("ios"))
        self.assertIn("EXT.ADDON", taxonomy.mapped_features("android"))
        self.assertNotIn("EXT.ADDON", taxonomy.mapped_features("ios"))

    def test_anchor(self):
        self.assertEqual(taxonomy.anchor("A", "Area & more"), "a-area--more")
        self.assertEqual(taxonomy.anchor("LIB", "Library (saved content)"), "lib-library-saved-content")


if __name__ == "__main__":
    unittest.main()
