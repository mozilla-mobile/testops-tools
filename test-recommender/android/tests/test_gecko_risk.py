"""Tests for android/gecko_risk.py.

The cases here encode the three traps found while calibrating this module
against cycle 154, each of which silently distorted the signal:

  - Remote Settings data dumps measured in lines (107,762 in one beta range).
  - Vendored FFmpeg headers counted as engine churn (15,749 lines).
  - Per-record attachments read as separate collections (57 `.meta` files from
    one search-config refresh).
"""

from __future__ import annotations

import unittest

from android import gecko_risk as gr


# =============================================================================
# Path classification
# =============================================================================


class TestClassifyGeckoPath(unittest.TestCase):
    def test_maps_area_and_section_hints(self):
        area, hints = gr.classify_gecko_path("dom/media/MediaDecoder.cpp")
        self.assertEqual(area, "media")
        self.assertIn("Picture in picture", hints)

    def test_specific_area_wins_over_general(self):
        """`dom/media` must be matched before the catch-all `dom` entry."""
        self.assertEqual(gr.classify_gecko_path("dom/media/x.cpp")[0], "media")
        self.assertEqual(gr.classify_gecko_path("dom/base/x.cpp")[0], "dom")

    def test_remote_settings(self):
        area, hints = gr.classify_gecko_path("services/settings/dumps/main/top-sites.json")
        self.assertEqual(area, "remote_settings")
        self.assertIn("Search", hints)

    def test_desktop_only_trees_are_excluded(self):
        for p in ("browser/components/urlbar/x.sys.mjs",
                  "devtools/client/x.js",
                  "toolkit/mozapps/extensions/x.js"):
            self.assertIsNone(gr.classify_gecko_path(p), p)

    def test_out_of_scope_returns_none(self):
        self.assertIsNone(gr.classify_gecko_path("python/mozbuild/x.py"))

    def test_prefix_must_be_a_path_boundary(self):
        """`domain/` must not match the `dom` area."""
        self.assertIsNone(gr.classify_gecko_path("domain/x.cpp"))

    def test_scope_is_derived_from_areas(self):
        for _, _, prefix in gr.GECKO_AREAS:
            self.assertIn(prefix, gr.GECKO_SCOPE)


class TestClassifyEnginePath(unittest.TestCase):
    def test_remote_settings_dump_is_data(self):
        self.assertEqual(
            gr.classify_engine_path("services/settings/dumps/main/top-sites.json"),
            "remote_settings_data")

    def test_vendored_ffmpeg_headers(self):
        self.assertEqual(
            gr.classify_engine_path(
                "dom/media/platforms/ffmpeg/ffmpeg63/include/libavcodec/avcodec.h"),
            "vendored")

    def test_third_party(self):
        self.assertEqual(gr.classify_engine_path("third_party/rust/x/lib.rs"), "vendored")

    def test_engine_tests(self):
        for p in ("dom/base/test/test_foo.html",
                  "layout/reftests/x.html",
                  "testing/web-platform/tests/x.html",
                  "gfx/tests/gtest/TestFoo.cpp"):
            self.assertEqual(gr.classify_engine_path(p), "test", p)

    def test_real_engine_code_is_not_excluded(self):
        cat = gr.classify_engine_path("dom/media/MediaDecoder.cpp")
        self.assertNotIn(cat, gr.EXCLUDED_FROM_CHURN)


class TestCollectionName(unittest.TestCase):
    def test_plain_collection(self):
        self.assertEqual(
            gr.collection_name("services/settings/dumps/main/top-sites.json"),
            "main/top-sites")

    def test_per_record_attachments_collapse_to_the_collection(self):
        """One search-config refresh writes 57 `.meta` files; they are one
        collection, not 57."""
        names = {
            gr.collection_name(
                f"services/settings/dumps/main/search-config-icons/{uid}.meta")
            for uid in ("001500a9-1a6c", "06cf7432-efd7", "0d7668a8-c3f4")
        }
        self.assertEqual(names, {"main/search-config-icons"})

    def test_bloomfilter_attachment(self):
        self.assertEqual(
            gr.collection_name(
                "services/settings/dumps/blocklists/addons-bloomfilters/addons-mlbf.bin.meta"),
            "blocklists/addons-bloomfilters")


class TestRoutineCollections(unittest.TestCase):
    def test_routine(self):
        for c in ("blocklists/addons-bloomfilters", "security-state/onecrl",
                  "security-state/intermediates"):
            self.assertTrue(gr.is_routine_collection(c), c)

    def test_behaviour_changing(self):
        for c in ("main/cookie-banner-rules-list", "main/translations-models",
                  "main/search-config-icons", "main/top-sites"):
            self.assertFalse(gr.is_routine_collection(c), c)


# =============================================================================
# Extraction
# =============================================================================


def numstat(rows: list[tuple[int, int, str]]) -> str:
    return "".join(f"{a}\t{d}\t{p}\n" for a, d, p in rows)


class TestExtractGeckoRisk(unittest.TestCase):
    def setUp(self):
        self._real_git = gr._git

    def tearDown(self):
        gr._git = self._real_git

    def _run(self, rows):
        gr._git = lambda repo, args: numstat(rows)
        return gr.extract_gecko_risk("repo", "base", "head")

    def test_groups_by_area(self):
        risk = self._run([
            (10, 2, "dom/media/MediaDecoder.cpp"),
            (5, 1, "netwerk/protocol/http/nsHttpChannel.cpp"),
            (3, 0, "dom/base/Document.cpp"),
        ])
        self.assertEqual({a.name for a in risk.areas}, {"media", "networking", "dom"})
        self.assertEqual(risk.product_churn, 21)

    def test_data_dumps_excluded_from_churn_but_reported(self):
        """The b6->b7 case: 107k lines of Remote Settings data would otherwise
        swamp every real code change."""
        risk = self._run([
            (15504, 15504, "services/settings/dumps/security-state/intermediates.json"),
            (10, 2, "dom/media/MediaDecoder.cpp"),
        ])
        self.assertEqual(risk.product_churn, 12)
        self.assertEqual(risk.remote_settings_collections,
                         ["security-state/intermediates"])
        # Routine refresh, so not notable on its own.
        self.assertEqual(risk.notable_collections, [])

    def test_vendored_excluded_from_churn(self):
        """The b9->b10 case: 36 vendored FFmpeg header files."""
        risk = self._run([
            (2961, 0, "dom/media/platforms/ffmpeg/ffmpeg63/include/libavcodec/avcodec.h"),
            (9, 1, "dom/media/MediaDecoder.cpp"),
        ])
        self.assertEqual(risk.product_churn, 10)
        self.assertEqual(risk.excluded_vendored, 1)
        self.assertEqual(risk.product_file_count, 1)
        self.assertEqual(risk.file_count, 2)

    def test_engine_tests_excluded_from_churn(self):
        """Test files *inside* an in-scope tree are counted then excluded.
        `testing/` as a whole is not in GECKO_SCOPE, so those never arrive."""
        risk = self._run([
            (5000, 0, "dom/base/test/test_document.html"),
            (4, 0, "dom/base/Document.cpp"),
        ])
        self.assertEqual(risk.product_churn, 4)
        self.assertEqual(risk.excluded_test, 1)

    def test_gecko_test_infrastructure_is_out_of_scope(self):
        risk = self._run([(5000, 0, "testing/web-platform/tests/x.html")])
        self.assertEqual(risk.file_count, 0)

    def test_desktop_only_files_are_dropped_entirely(self):
        risk = self._run([
            (100, 50, "browser/components/urlbar/x.sys.mjs"),
            (1, 1, "dom/base/Document.cpp"),
        ])
        self.assertEqual(risk.file_count, 1)
        self.assertEqual(risk.product_churn, 2)

    def test_binary_counts_are_zeroed(self):
        risk = self._run([(0, 0, "gfx/x.bin")])
        # "-"/"-" is handled in the parser; here just assert no crash and no churn.
        self.assertEqual(risk.product_churn, 0)

    def test_empty_range(self):
        risk = self._run([])
        self.assertEqual(risk.areas, [])
        self.assertFalse(risk.is_material)
        self.assertIn("No engine change", gr.summarize(risk))


class TestMateriality(unittest.TestCase):
    def setUp(self):
        self._real_git = gr._git

    def tearDown(self):
        gr._git = self._real_git

    def _run(self, rows):
        gr._git = lambda repo, args: numstat(rows)
        return gr.extract_gecko_risk("repo", "base", "head")

    def test_small_change_is_not_material(self):
        risk = self._run([(5, 5, "dom/base/Document.cpp")])
        self.assertFalse(risk.is_material)

    def test_large_change_is_material(self):
        risk = self._run([(600, 0, "dom/base/Document.cpp")])
        self.assertTrue(risk.is_material)

    def test_notable_collection_alone_makes_it_material(self):
        """Remote Settings reaches users without a build, so a data-only
        change still counts."""
        risk = self._run([
            (10, 10, "services/settings/dumps/main/cookie-banner-rules-list.json"),
        ])
        self.assertEqual(risk.product_churn, 0)
        self.assertTrue(risk.is_material)

    def test_routine_collection_alone_is_not_material(self):
        risk = self._run([
            (9000, 9000, "services/settings/dumps/blocklists/addons-bloomfilters/a.bin.meta"),
        ])
        self.assertFalse(risk.is_material)


class TestVeto(unittest.TestCase):
    """The guard against reporting "l10n only, nothing to test" for a beta
    whose app diff is quiet but whose engine moved — the b5->b6 shape."""

    def setUp(self):
        self._real_git = gr._git

    def tearDown(self):
        gr._git = self._real_git

    def _risk(self, rows):
        gr._git = lambda repo, args: numstat(rows)
        return gr.extract_gecko_risk("repo", "base", "head")

    def test_fires_when_app_quiet_and_engine_material(self):
        risk = self._risk([(1600, 0, "security/manager/ssl/x.cpp")])
        self.assertTrue(risk.vetoes_no_regression(app_has_product_change=False))

    def test_silent_when_the_app_already_changed(self):
        risk = self._risk([(1600, 0, "security/manager/ssl/x.cpp")])
        self.assertFalse(risk.vetoes_no_regression(app_has_product_change=True))

    def test_silent_when_engine_is_quiet_too(self):
        risk = self._risk([(2, 2, "dom/base/Document.cpp")])
        self.assertFalse(risk.vetoes_no_regression(app_has_product_change=False))


class TestSectionHints(unittest.TestCase):
    def setUp(self):
        self._real_git = gr._git

    def tearDown(self):
        gr._git = self._real_git

    def test_weighted_by_product_churn(self):
        gr._git = lambda repo, args: numstat([
            (500, 0, "toolkit/components/translations/x.sys.mjs"),
            (5, 0, "dom/media/MediaDecoder.cpp"),
        ])
        risk = gr.extract_gecko_risk("repo", "b", "h")
        self.assertEqual(risk.section_hints[0], "Translations")

    def test_vendored_churn_does_not_skew_hints(self):
        """A 15k-line FFmpeg import must not push media sections to the top."""
        gr._git = lambda repo, args: numstat([
            (15000, 0, "dom/media/platforms/ffmpeg/ffmpeg63/include/libavutil/frame.h"),
            (40, 0, "toolkit/components/translations/x.sys.mjs"),
        ])
        risk = gr.extract_gecko_risk("repo", "b", "h")
        self.assertEqual(risk.section_hints[0], "Translations")
        self.assertNotIn("Picture in picture", risk.section_hints)


if __name__ == "__main__":
    unittest.main()


class TestGeneratedDataExclusion(unittest.TestCase):
    """The HSTS preload list and friends are refreshed data, not new security
    logic. On 159 b1 BUILD1->BUILD2 `nsSTSPreloadList.inc` alone was 887 of the
    895 lines attributed to `security`, making it read as the largest engine
    change in the range."""

    def setUp(self):
        self._real_git = gr._git

    def tearDown(self):
        gr._git = self._real_git

    def _run(self, rows):
        gr._git = lambda repo, args: numstat(rows)
        return gr.extract_gecko_risk("repo", "base", "head")

    def test_preload_list_excluded_from_churn_but_named(self):
        risk = self._run([
            (620, 267, "security/manager/ssl/nsSTSPreloadList.inc"),
            (10, 2, "dom/base/Document.cpp"),
        ])
        self.assertEqual(risk.product_churn, 12)
        self.assertEqual(risk.generated_data_files,
                         ["security/manager/ssl/nsSTSPreloadList.inc"])
        self.assertIn("nsSTSPreloadList.inc", gr.summarize(risk))

    def test_all_known_blobs_are_recognised(self):
        risk = self._run([(100, 100, p) for p in gr.GENERATED_DATA])
        self.assertEqual(risk.product_churn, 0)
        self.assertEqual(len(risk.generated_data_files), len(gr.GENERATED_DATA))

    def test_real_security_code_is_not_excluded(self):
        risk = self._run([(50, 0, "security/manager/ssl/nsNSSComponent.cpp")])
        self.assertEqual(risk.product_churn, 50)
        self.assertEqual(risk.generated_data_files, [])
