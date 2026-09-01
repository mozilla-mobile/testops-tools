"""
Nimbus feature-flag analyzer.

Two responsibilities:

1. Load the Nimbus flag catalogue from `<repo>/firefox-ios/nimbus-features/`.
   Each yaml declares a feature flag with an `enabled: Boolean` variable and
   optional per-channel overrides. We build a `FeatureFlag` record per flag
   with the release / beta / developer state.

2. Attribute changed Swift files to their gating flags. A `.swift` file that
   references `features.<accessorName>` is gated by that flag. Generated
   bindings files (Client/Generated/FxNimbus.swift and
   Nimbus/NimbusFeatureFlagLayer.swift) reference every flag by construction
   and are excluded from attribution.

Classification for the pipeline (channel-aware, per user decision):

    unflagged   → no gating flag found (or the flag has no `enabled` var)
    enabled     → flag is ON in the release channel
    beta_only   → OFF in release, ON in beta or developer (dogfooding)
    fully_dark  → OFF in all channels

`fully_dark` candidates get a hard deprioritization instruction in the
rerank prompt; `beta_only` gets a soft annotation only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import yaml


CHANNELS = ("release", "beta", "developer")

# Generated bindings files that reference every flag by construction —
# exclude them from attribution so a change to them doesn't attribute the
# whole diff to every flag.
GENERATED_FILE_SUFFIXES = (
    "Client/Generated/FxNimbus.swift",
    "Nimbus/NimbusFeatureFlagLayer.swift",
)


@dataclass
class FeatureFlag:
    """A single Nimbus feature flag with its per-channel enabled state.

    `accessor` is the Swift identifier (camelCase, derived from the yaml
    filename). `key` is the kebab-case name used inside the yaml
    (`quick-answers-feature`). Both are recorded so callers can match on
    either form.
    """
    accessor: str
    key: str
    yaml_path: str
    release_enabled: bool
    beta_enabled: bool
    developer_enabled: bool

    @property
    def is_fully_dark(self) -> bool:
        return not (self.release_enabled or self.beta_enabled or self.developer_enabled)

    @property
    def is_beta_only(self) -> bool:
        return (not self.release_enabled) and (self.beta_enabled or self.developer_enabled)

    def channel_state_summary(self) -> str:
        """Compact 'release=OFF, beta=ON, developer=ON' style for prompts/report."""
        return ", ".join(
            f"{ch}={'ON' if getattr(self, f'{ch}_enabled') else 'OFF'}"
            for ch in CHANNELS
        )


@dataclass
class FlagAttribution:
    """Result of attributing a single Swift file to gating flags.

    `gating_flags` is a list of accessor names. Empty list means the file is
    unflagged (no known Nimbus reference).
    """
    file_path: str
    gating_flags: list[str] = field(default_factory=list)


# =============================================================================
# Catalogue loading
# =============================================================================


def _kebab_to_camel(kebab: str) -> str:
    parts = kebab.split("-")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _resolve_enabled(feature_body: dict, channel: str, release_default: bool) -> bool:
    """Return the enabled state for `channel`. Falls back to release_default
    if the yaml has no override for that channel."""
    for override in feature_body.get("defaults") or []:
        if override.get("channel") == channel:
            value = (override.get("value") or {}).get("enabled")
            if isinstance(value, bool):
                return value
    return release_default


def _parse_feature_yaml(yaml_path: Path) -> Optional[FeatureFlag]:
    """Parse a single nimbus-features/*.yaml file into a FeatureFlag record.

    Returns None if the file declares no `enabled: Boolean` variable — some
    features are always-on config carriers and don't map to a rollout switch.
    """
    try:
        doc = yaml.safe_load(yaml_path.read_text())
    except (yaml.YAMLError, OSError):
        return None

    features = (doc or {}).get("features") or {}
    if not features:
        return None

    # Each yaml declares exactly one feature keyed by kebab-case name.
    # If more, we take the first — this is the shape firefox-ios follows today.
    key, body = next(iter(features.items()))

    enabled_var = ((body.get("variables") or {}).get("enabled")) or {}
    if enabled_var.get("type") != "Boolean":
        return None
    release_default = bool(enabled_var.get("default", False))

    accessor = yaml_path.stem
    return FeatureFlag(
        accessor=accessor,
        key=key,
        yaml_path=str(yaml_path),
        release_enabled=release_default,
        beta_enabled=_resolve_enabled(body, "beta", release_default),
        developer_enabled=_resolve_enabled(body, "developer", release_default),
    )


def load_flag_catalogue(nimbus_features_dir: Path) -> dict[str, FeatureFlag]:
    """Load every *.yaml under nimbus-features/ into a {accessor: FeatureFlag} map.

    Files without an `enabled: Boolean` variable are skipped silently — they
    are features with only configuration knobs (no rollout switch).

    Missing directory returns an empty map — the pipeline is expected to
    treat that as "Nimbus analysis unavailable" and continue.
    """
    catalogue: dict[str, FeatureFlag] = {}
    if not nimbus_features_dir.is_dir():
        return catalogue
    for yaml_file in sorted(nimbus_features_dir.glob("*.yaml")):
        flag = _parse_feature_yaml(yaml_file)
        if flag is not None:
            catalogue[flag.accessor] = flag
    return catalogue


# =============================================================================
# Wrapper mapping (FeatureFlagID enum → features.<accessor>)
# =============================================================================
#
# Product code in firefox-ios rarely calls `features.<accessor>` directly.
# Most references go through `FeatureFlagsProvider.isEnabled(.<caseName>)`,
# which resolves via `NimbusFeatureFlagLayer.swift`:
#
#     case .foo:
#         return checkFooFeature()
#
#     private func checkFooFeature() -> Bool {
#         return nimbus.features.fooFeature.value().enabled
#     }
#
# Without this two-hop resolution, we miss ~half the real flag usages.


_CASE_TO_METHOD_RE = re.compile(
    r"case\s+\.(\w+)\s*:\s*\n?\s*return\s+(\w+)\s*\(",
    re.MULTILINE,
)

_METHOD_TO_ACCESSOR_RE = re.compile(
    r"func\s+(\w+)\s*\([^)]*\)\s*->\s*Bool\s*\{[^}]*?nimbus\.features\.(\w+)",
    re.DOTALL,
)


def parse_wrapper_mapping(wrapper_source: str) -> dict[str, str]:
    """Return {enum_case_name: features_accessor} from a NimbusFeatureFlagLayer
    source. Cases that resolve to a non-boolean method (e.g. StartAtHome enum)
    are silently skipped — this attributor only tracks on/off flags.
    """
    case_to_method = dict(_CASE_TO_METHOD_RE.findall(wrapper_source))
    method_to_accessor = dict(_METHOD_TO_ACCESSOR_RE.findall(wrapper_source))
    return {
        case_name: method_to_accessor[method]
        for case_name, method in case_to_method.items()
        if method in method_to_accessor
    }


# =============================================================================
# Attribution
# =============================================================================


def _is_generated_bindings(file_path: str) -> bool:
    return any(file_path.endswith(suffix) for suffix in GENERATED_FILE_SUFFIXES)


def _build_accessor_pattern(accessors: Iterable[str]) -> re.Pattern:
    """Compile one regex that matches `features.<accessor>` for any accessor.

    Word boundary after the accessor prevents `features.quickAnswer` from
    matching `features.quickAnswersFeature`.
    """
    alternatives = "|".join(re.escape(a) for a in sorted(accessors, key=len, reverse=True))
    return re.compile(rf"\bfeatures\.({alternatives})\b")


def _build_wrapper_case_pattern(case_names: Iterable[str]) -> re.Pattern:
    """Compile a regex that matches `.isEnabled(.<caseName>)` (or `.isFeatureEnabled(...)`)
    for any enum case in the wrapper mapping. Both call sites resolve to a
    boolean feature check via the layer file we already parsed.
    """
    alternatives = "|".join(re.escape(c) for c in sorted(case_names, key=len, reverse=True))
    return re.compile(rf"\.(?:isEnabled|isFeatureEnabled)\s*\(\s*\.({alternatives})\b")


def attribute_file(
    file_path: str,
    file_content: str,
    accessor_pattern: re.Pattern,
    wrapper_case_pattern: Optional[re.Pattern] = None,
    case_to_accessor: Optional[dict[str, str]] = None,
) -> FlagAttribution:
    """Attribute a single Swift file to gating flags by grepping its content.

    Two independent grep passes contribute to the result:
      1. Direct: `features.<accessor>` matches → the accessor is a gating flag.
      2. Wrapper: `.isEnabled(.<caseName>)` → resolve caseName through
         `case_to_accessor` to get the accessor.

    Both feed the same deduplicated `gating_flags` list. Generated bindings
    files are skipped (they reference every flag by construction).
    """
    if _is_generated_bindings(file_path):
        return FlagAttribution(file_path=file_path, gating_flags=[])
    seen: list[str] = []
    for m in accessor_pattern.finditer(file_content):
        accessor = m.group(1)
        if accessor not in seen:
            seen.append(accessor)
    if wrapper_case_pattern is not None and case_to_accessor:
        for m in wrapper_case_pattern.finditer(file_content):
            case_name = m.group(1)
            accessor = case_to_accessor.get(case_name)
            if accessor and accessor not in seen:
                seen.append(accessor)
    return FlagAttribution(file_path=file_path, gating_flags=seen)


def attribute_files(
    files: list[tuple[str, str]],
    catalogue: dict[str, FeatureFlag],
    case_to_accessor: Optional[dict[str, str]] = None,
) -> list[FlagAttribution]:
    """Attribute a batch of (file_path, file_content) pairs to gating flags.

    Empty catalogue returns empty attributions (equivalent to skipping).
    When `case_to_accessor` is provided, wrapper-style `.isEnabled(.case)`
    references are also resolved and attributed.
    """
    if not catalogue:
        return [FlagAttribution(file_path=fp) for fp, _ in files]
    accessor_pattern = _build_accessor_pattern(catalogue.keys())
    wrapper_pattern: Optional[re.Pattern] = None
    if case_to_accessor:
        wrapper_pattern = _build_wrapper_case_pattern(case_to_accessor.keys())
    return [
        attribute_file(fp, content, accessor_pattern, wrapper_pattern, case_to_accessor)
        for fp, content in files
    ]


# =============================================================================
# Classification (channel-aware)
# =============================================================================


def classify_gating_flags(
    gating_flags: list[str],
    catalogue: dict[str, FeatureFlag],
) -> str:
    """Return one of: unflagged | enabled | beta_only | fully_dark.

    When multiple flags gate the same code, the MOST-permissive state wins —
    if any gating flag is enabled in release, the code is user-facing and
    counted as `enabled`. This matches how QA thinks about it: if any flag
    exposes the code path, that path is testable.
    """
    resolved = [catalogue[f] for f in gating_flags if f in catalogue]
    if not resolved:
        return "unflagged"
    if any(f.release_enabled for f in resolved):
        return "enabled"
    if any(f.beta_enabled or f.developer_enabled for f in resolved):
        return "beta_only"
    return "fully_dark"
