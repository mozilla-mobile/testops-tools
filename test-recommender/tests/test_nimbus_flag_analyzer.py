"""Tests for nimbus_flag_analyzer."""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nimbus_flag_analyzer import (
    FeatureFlag,
    FlagAttribution,
    _build_accessor_pattern,
    _build_wrapper_case_pattern,
    _is_generated_bindings,
    _kebab_to_camel,
    _parse_feature_yaml,
    _resolve_enabled,
    attribute_file,
    attribute_files,
    classify_gating_flags,
    load_flag_catalogue,
    parse_wrapper_mapping,
)


# =============================================================================
# YAML samples mirroring the real firefox-ios shape
# =============================================================================


YAML_FULLY_DARK = textwrap.dedent("""
    features:
      quick-answers-feature:
        variables:
          enabled:
            type: Boolean
            default: false
        defaults:
          - channel: beta
            value:
              enabled: false
          - channel: developer
            value:
              enabled: false
""")

YAML_BETA_ONLY = textwrap.dedent("""
    features:
      ad-blocker-feature:
        variables:
          enabled:
            type: Boolean
            default: false
        defaults:
          - channel: beta
            value:
              enabled: true
          - channel: developer
            value:
              enabled: true
""")

YAML_RELEASE_ON = textwrap.dedent("""
    features:
      homepage-redesign-feature:
        variables:
          enabled:
            type: Boolean
            default: true
""")

YAML_NO_ENABLED_VAR = textwrap.dedent("""
    features:
      messaging-feature:
        variables:
          messages:
            type: Map
            default: {}
""")

YAML_ENABLED_NOT_BOOL = textwrap.dedent("""
    features:
      broken-feature:
        variables:
          enabled:
            type: String
            default: "yes"
""")

YAML_EMPTY = ""


# =============================================================================
# _kebab_to_camel
# =============================================================================


class KebabToCamelTests(unittest.TestCase):
    def test_multi_part(self):
        self.assertEqual(_kebab_to_camel("quick-answers-feature"), "quickAnswersFeature")

    def test_single_part(self):
        self.assertEqual(_kebab_to_camel("messaging"), "messaging")

    def test_two_parts(self):
        self.assertEqual(_kebab_to_camel("ad-blocker"), "adBlocker")


# =============================================================================
# _resolve_enabled
# =============================================================================


class ResolveEnabledTests(unittest.TestCase):
    def test_channel_override_wins(self):
        body = {"defaults": [{"channel": "beta", "value": {"enabled": True}}]}
        self.assertTrue(_resolve_enabled(body, "beta", release_default=False))

    def test_falls_back_to_release_default_when_no_override(self):
        body = {"defaults": []}
        self.assertFalse(_resolve_enabled(body, "beta", release_default=False))
        self.assertTrue(_resolve_enabled(body, "beta", release_default=True))

    def test_no_defaults_key_at_all(self):
        self.assertTrue(_resolve_enabled({}, "beta", release_default=True))

    def test_ignores_non_bool_override(self):
        body = {"defaults": [{"channel": "beta", "value": {"enabled": "true"}}]}
        # String "true" is not a Boolean → fall back to release_default
        self.assertFalse(_resolve_enabled(body, "beta", release_default=False))


# =============================================================================
# _parse_feature_yaml
# =============================================================================


def _write_yaml(tmp: Path, name: str, content: str) -> Path:
    path = tmp / name
    path.write_text(content)
    return path


class ParseFeatureYamlTests(unittest.TestCase):
    def test_fully_dark(self):
        with TemporaryDirectory() as d:
            p = _write_yaml(Path(d), "quickAnswersFeature.yaml", YAML_FULLY_DARK)
            flag = _parse_feature_yaml(p)
        self.assertIsNotNone(flag)
        self.assertEqual(flag.accessor, "quickAnswersFeature")
        self.assertEqual(flag.key, "quick-answers-feature")
        self.assertFalse(flag.release_enabled)
        self.assertFalse(flag.beta_enabled)
        self.assertFalse(flag.developer_enabled)
        self.assertTrue(flag.is_fully_dark)
        self.assertFalse(flag.is_beta_only)

    def test_beta_only(self):
        with TemporaryDirectory() as d:
            p = _write_yaml(Path(d), "adBlockerFeature.yaml", YAML_BETA_ONLY)
            flag = _parse_feature_yaml(p)
        self.assertEqual(flag.accessor, "adBlockerFeature")
        self.assertFalse(flag.release_enabled)
        self.assertTrue(flag.beta_enabled)
        self.assertTrue(flag.developer_enabled)
        self.assertTrue(flag.is_beta_only)
        self.assertFalse(flag.is_fully_dark)

    def test_release_on(self):
        with TemporaryDirectory() as d:
            p = _write_yaml(Path(d), "homepageRedesignFeature.yaml", YAML_RELEASE_ON)
            flag = _parse_feature_yaml(p)
        self.assertTrue(flag.release_enabled)
        # No overrides → both beta and developer inherit release_default (True)
        self.assertTrue(flag.beta_enabled)
        self.assertTrue(flag.developer_enabled)
        self.assertFalse(flag.is_fully_dark)
        self.assertFalse(flag.is_beta_only)

    def test_no_enabled_var_returns_none(self):
        with TemporaryDirectory() as d:
            p = _write_yaml(Path(d), "messagingFeature.yaml", YAML_NO_ENABLED_VAR)
            self.assertIsNone(_parse_feature_yaml(p))

    def test_enabled_not_bool_returns_none(self):
        with TemporaryDirectory() as d:
            p = _write_yaml(Path(d), "brokenFeature.yaml", YAML_ENABLED_NOT_BOOL)
            self.assertIsNone(_parse_feature_yaml(p))

    def test_empty_yaml_returns_none(self):
        with TemporaryDirectory() as d:
            p = _write_yaml(Path(d), "empty.yaml", YAML_EMPTY)
            self.assertIsNone(_parse_feature_yaml(p))

    def test_channel_state_summary(self):
        flag = FeatureFlag(
            accessor="adBlockerFeature", key="ad-blocker-feature", yaml_path="",
            release_enabled=False, beta_enabled=True, developer_enabled=True,
        )
        self.assertEqual(
            flag.channel_state_summary(),
            "release=OFF, beta=ON, developer=ON",
        )


# =============================================================================
# load_flag_catalogue
# =============================================================================


class LoadCatalogueTests(unittest.TestCase):
    def test_missing_directory_returns_empty(self):
        self.assertEqual(load_flag_catalogue(Path("/nonexistent/nimbus-features")), {})

    def test_loads_multiple_and_skips_invalid(self):
        with TemporaryDirectory() as d:
            _write_yaml(Path(d), "quickAnswersFeature.yaml", YAML_FULLY_DARK)
            _write_yaml(Path(d), "adBlockerFeature.yaml", YAML_BETA_ONLY)
            _write_yaml(Path(d), "messagingFeature.yaml", YAML_NO_ENABLED_VAR)
            _write_yaml(Path(d), "empty.yaml", YAML_EMPTY)
            catalogue = load_flag_catalogue(Path(d))
        self.assertEqual(set(catalogue.keys()), {"quickAnswersFeature", "adBlockerFeature"})

    def test_empty_directory_returns_empty(self):
        with TemporaryDirectory() as d:
            self.assertEqual(load_flag_catalogue(Path(d)), {})


# =============================================================================
# Attribution
# =============================================================================


class IsGeneratedBindingsTests(unittest.TestCase):
    def test_fx_nimbus_generated(self):
        self.assertTrue(_is_generated_bindings(
            "firefox-ios/Client/Generated/FxNimbus.swift"
        ))

    def test_nimbus_feature_flag_layer(self):
        self.assertTrue(_is_generated_bindings(
            "firefox-ios/Client/Nimbus/NimbusFeatureFlagLayer.swift"
        ))

    def test_product_code_not_flagged(self):
        self.assertFalse(_is_generated_bindings(
            "firefox-ios/Client/Coordinators/QuickAnswersCoordinator.swift"
        ))


class AccessorPatternTests(unittest.TestCase):
    def test_matches_features_dot_accessor(self):
        pattern = _build_accessor_pattern(["quickAnswersFeature", "adBlockerFeature"])
        content = "let v = FxNimbus.shared.features.quickAnswersFeature.value()"
        matches = [m.group(1) for m in pattern.finditer(content)]
        self.assertEqual(matches, ["quickAnswersFeature"])

    def test_word_boundary_prevents_prefix_match(self):
        # `quickAnswer` should NOT match `quickAnswersFeature` reference.
        pattern = _build_accessor_pattern(["quickAnswer"])
        content = "features.quickAnswersFeature.value()"
        self.assertEqual(list(pattern.finditer(content)), [])

    def test_longer_accessor_wins_on_ambiguity(self):
        # If both `foo` and `fooBar` are accessors, `features.fooBar` matches fooBar.
        pattern = _build_accessor_pattern(["foo", "fooBar"])
        content = "features.fooBar.value() and features.foo.value()"
        matches = [m.group(1) for m in pattern.finditer(content)]
        self.assertEqual(matches, ["fooBar", "foo"])


class AttributeFileTests(unittest.TestCase):
    def setUp(self):
        self.pattern = _build_accessor_pattern(["quickAnswersFeature", "adBlockerFeature"])

    def test_attributes_single_flag(self):
        content = "FxNimbus.shared.features.quickAnswersFeature.value().enabled"
        result = attribute_file("Client/Foo.swift", content, self.pattern)
        self.assertEqual(result.gating_flags, ["quickAnswersFeature"])

    def test_attributes_multiple_flags(self):
        content = """
        if features.quickAnswersFeature.value().enabled { ... }
        if features.adBlockerFeature.value().enabled { ... }
        """
        result = attribute_file("Client/Foo.swift", content, self.pattern)
        self.assertEqual(sorted(result.gating_flags), ["adBlockerFeature", "quickAnswersFeature"])

    def test_deduplicates_repeated_flag(self):
        content = "features.quickAnswersFeature.value(); features.quickAnswersFeature.value()"
        result = attribute_file("Client/Foo.swift", content, self.pattern)
        self.assertEqual(result.gating_flags, ["quickAnswersFeature"])

    def test_no_flag_returns_empty(self):
        result = attribute_file("Client/Foo.swift", "let x = 1", self.pattern)
        self.assertEqual(result.gating_flags, [])

    def test_generated_bindings_skipped(self):
        content = "features.quickAnswersFeature.with(sdk: getSdk)"
        result = attribute_file("firefox-ios/Client/Generated/FxNimbus.swift", content, self.pattern)
        self.assertEqual(result.gating_flags, [])


class AttributeFilesTests(unittest.TestCase):
    def test_empty_catalogue_returns_empty_attributions(self):
        files = [("Client/Foo.swift", "features.quickAnswersFeature.value()")]
        result = attribute_files(files, catalogue={})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].gating_flags, [])

    def test_batch_attribution(self):
        catalogue = {
            "quickAnswersFeature": FeatureFlag(
                "quickAnswersFeature", "quick-answers-feature", "",
                False, False, False,
            ),
        }
        files = [
            ("A.swift", "features.quickAnswersFeature.value()"),
            ("B.swift", "let x = 1"),
        ]
        result = attribute_files(files, catalogue)
        self.assertEqual(result[0].gating_flags, ["quickAnswersFeature"])
        self.assertEqual(result[1].gating_flags, [])


# =============================================================================
# classify_gating_flags
# =============================================================================


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = {
            "quickAnswersFeature": FeatureFlag(
                "quickAnswersFeature", "quick-answers-feature", "",
                release_enabled=False, beta_enabled=False, developer_enabled=False,
            ),
            "adBlockerFeature": FeatureFlag(
                "adBlockerFeature", "ad-blocker-feature", "",
                release_enabled=False, beta_enabled=True, developer_enabled=True,
            ),
            "homepageRedesignFeature": FeatureFlag(
                "homepageRedesignFeature", "homepage-redesign-feature", "",
                release_enabled=True, beta_enabled=True, developer_enabled=True,
            ),
        }

    def test_no_flags_is_unflagged(self):
        self.assertEqual(classify_gating_flags([], self.catalogue), "unflagged")

    def test_unknown_flag_is_unflagged(self):
        self.assertEqual(classify_gating_flags(["ghostFeature"], self.catalogue), "unflagged")

    def test_release_enabled(self):
        self.assertEqual(
            classify_gating_flags(["homepageRedesignFeature"], self.catalogue),
            "enabled",
        )

    def test_beta_only(self):
        self.assertEqual(
            classify_gating_flags(["adBlockerFeature"], self.catalogue),
            "beta_only",
        )

    def test_fully_dark(self):
        self.assertEqual(
            classify_gating_flags(["quickAnswersFeature"], self.catalogue),
            "fully_dark",
        )

    def test_most_permissive_wins_when_multiple(self):
        # If one flag is enabled in release and another is dark, code is
        # user-facing via the enabled flag → classify as `enabled`.
        self.assertEqual(
            classify_gating_flags(
                ["quickAnswersFeature", "homepageRedesignFeature"],
                self.catalogue,
            ),
            "enabled",
        )

    def test_beta_wins_over_fully_dark_when_no_release_flag(self):
        self.assertEqual(
            classify_gating_flags(
                ["quickAnswersFeature", "adBlockerFeature"],
                self.catalogue,
            ),
            "beta_only",
        )


# =============================================================================
# Wrapper mapping (FeatureFlagID → features.<accessor>) tests
# =============================================================================


WRAPPER_SAMPLE = textwrap.dedent("""
    public func checkNimbusConfigFor(_ featureID: FeatureFlagID) -> Bool {
        switch featureID {
        case .adBlocker:
            return checkAdBlockerFeature()
        case .quickAnswers:
            return checkQuickAnswersFeature()
        case .startAtHome:
            return checkStartAtHomeFeature(for: featureID)
        }
    }

    private func checkAdBlockerFeature() -> Bool {
        return nimbus.features.adBlockerFeature.value().enabled
    }

    private func checkQuickAnswersFeature() -> Bool {
        return nimbus.features.quickAnswersFeature.value().enabled
    }

    private func checkStartAtHomeFeature(for featureID: FeatureFlagID) -> StartAtHome {
        return nimbus.features.startAtHomeFeature.value().value
    }
""")


class ParseWrapperMappingTests(unittest.TestCase):
    def test_maps_boolean_flags(self):
        mapping = parse_wrapper_mapping(WRAPPER_SAMPLE)
        self.assertEqual(mapping.get("adBlocker"), "adBlockerFeature")
        self.assertEqual(mapping.get("quickAnswers"), "quickAnswersFeature")

    def test_skips_non_boolean_flags(self):
        # startAtHome returns StartAtHome enum, not Bool → dropped.
        mapping = parse_wrapper_mapping(WRAPPER_SAMPLE)
        self.assertNotIn("startAtHome", mapping)

    def test_empty_content_returns_empty(self):
        self.assertEqual(parse_wrapper_mapping(""), {})

    def test_case_without_matching_method_is_dropped(self):
        content = textwrap.dedent("""
            case .foo:
                return checkFooFeature()
        """)
        # No method definition → nothing to map to
        self.assertEqual(parse_wrapper_mapping(content), {})


class WrapperCasePatternTests(unittest.TestCase):
    def test_matches_isEnabled_variant(self):
        pattern = _build_wrapper_case_pattern(["adBlocker", "googleLens"])
        content = "featureFlagsProvider.isEnabled(.adBlocker)"
        matches = [m.group(1) for m in pattern.finditer(content)]
        self.assertEqual(matches, ["adBlocker"])

    def test_matches_isFeatureEnabled_variant(self):
        pattern = _build_wrapper_case_pattern(["adBlocker"])
        content = "FeatureFlagsManager.shared.isFeatureEnabled(.adBlocker, ...)"
        matches = [m.group(1) for m in pattern.finditer(content)]
        self.assertEqual(matches, ["adBlocker"])

    def test_word_boundary(self):
        pattern = _build_wrapper_case_pattern(["ad"])
        content = ".isEnabled(.adBlocker)"
        self.assertEqual(list(pattern.finditer(content)), [])


class WrapperAttributionTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = {
            "adBlockerFeature": FeatureFlag(
                "adBlockerFeature", "ad-blocker-feature", "",
                release_enabled=False, beta_enabled=True, developer_enabled=True,
            ),
            "quickAnswersFeature": FeatureFlag(
                "quickAnswersFeature", "quick-answers-feature", "",
                release_enabled=False, beta_enabled=False, developer_enabled=False,
            ),
        }
        self.case_to_accessor = {
            "adBlocker": "adBlockerFeature",
            "quickAnswers": "quickAnswersFeature",
        }

    def test_wrapper_reference_attributes_flag(self):
        files = [("Client/Settings/BrowsingSettings.swift",
                  "if featureFlagsProvider.isEnabled(.adBlocker) { ... }")]
        result = attribute_files(files, self.catalogue, self.case_to_accessor)
        self.assertEqual(result[0].gating_flags, ["adBlockerFeature"])

    def test_direct_and_wrapper_are_merged_and_deduped(self):
        files = [("Client/Foo.swift",
                  "features.adBlockerFeature.value(); featureFlagsProvider.isEnabled(.adBlocker)")]
        result = attribute_files(files, self.catalogue, self.case_to_accessor)
        self.assertEqual(result[0].gating_flags, ["adBlockerFeature"])

    def test_wrapper_disabled_when_no_mapping(self):
        # Same content, but no case_to_accessor → only direct grep runs.
        # `.isEnabled(.adBlocker)` alone should NOT attribute.
        files = [("Client/Foo.swift", "featureFlagsProvider.isEnabled(.adBlocker)")]
        result = attribute_files(files, self.catalogue)
        self.assertEqual(result[0].gating_flags, [])


if __name__ == "__main__":
    unittest.main()
