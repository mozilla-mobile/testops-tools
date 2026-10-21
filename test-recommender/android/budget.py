"""
Test budget for a Firefox Android build.

Answers "how many tests does this build deserve", deterministically and with
an auditable reason string, before any LLM is involved. The number then bounds
the scorer's output and appears in the report header.

**Why iOS's model does not transfer.** `../budget_calculator.py` keys off the
release type parsed from the tag (patch 25-40, minor 40-70, major 100-160).
Two problems here:

  - The ranges are an order of magnitude too large. An iOS release changes
    hundreds of files; an Android beta changes a handful at most.
  - The tag tells you almost nothing. `b3 → b4` can be twenty Kotlin files or
    zero, and a large share of ranges touch no product code at all. Keying off
    "it is a beta" would hand the same budget to a busy build and an empty one.

`python3 -m android.calibrate` prints the measured distribution these tiers
were fitted to; re-run it after a new cycle rather than trusting a figure
written here.

So the tier is chosen from the *content* of the range, not its tag. And
because the engine ships with every Android build, a zero-app-change range
still gets a real budget whenever `GeckoRisk` says the engine moved — there is
no "nothing to test" tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Tier thresholds on Kotlin product files changed. Boundaries follow the
# observed distribution: zero is common enough to deserve its own case, 1-3 is
# the typical beta, and anything above 10 is rare.
# `python3 -m android.calibrate` prints the current distribution.
LIGHT_MAX = 3
MODERATE_MAX = 10

BASE_RANGES: dict[str, tuple[int, int]] = {
    # No product code and a quiet engine. Smoke only — the shape of a
    # final-beta-to-RC comparison where the RC is a straight copy.
    "silent": (3, 8),
    # No product code but the engine moved. Driven entirely by
    # GeckoRisk.section_hints. About half of the zero-app ranges land here.
    "engine_only": (10, 20),
    "light": (12, 25),
    "moderate": (20, 35),
    "heavy": (30, 50),
}

ABSOLUTE_FLOOR = 3
ABSOLUTE_CEILING = 60

BUMP_NIMBUS = 5
BUMP_BACKOUT = 5
BUMP_REMOTE_SETTINGS = 3
BUMP_DEPENDENCY = 3
BUMP_SOURCE_STRINGS = 3


@dataclass
class BuildSignal:
    """The subset of the extraction output the budget needs.

    Its own dataclass so this module has no reverse dependency on the
    extractor; `from_extraction()` builds it from the real objects.
    """
    app_product_files: int = 0
    exact_match_cases: int = 0
    engine_is_material: bool = False
    nimbus_changed: bool = False
    has_backout: bool = False
    notable_collections: int = 0
    dependency_changed: bool = False
    source_strings_changed: bool = False


def from_extraction(result, risk=None, exact_match_cases: int = 0) -> BuildSignal:
    """Build a BuildSignal from an ExtractionResult and an optional GeckoRisk."""
    categories = result.counts_by_category()
    return BuildSignal(
        app_product_files=categories.get("code", 0),
        exact_match_cases=exact_match_cases,
        engine_is_material=bool(risk and risk.is_material),
        nimbus_changed=categories.get("nimbus", 0) > 0,
        has_backout=any(c.is_backout for b in result.bugs for c in b.commits),
        notable_collections=len(risk.notable_collections) if risk else 0,
        dependency_changed=categories.get("dependency", 0) > 0,
        source_strings_changed=categories.get("source_strings", 0) > 0,
    )


def detect_tier(signal: BuildSignal) -> str:
    """Pick the base tier from what actually changed."""
    if signal.app_product_files == 0:
        return "engine_only" if signal.engine_is_material else "silent"
    if signal.app_product_files <= LIGHT_MAX:
        return "light"
    if signal.app_product_files <= MODERATE_MAX:
        return "moderate"
    return "heavy"


@dataclass
class BudgetDecision:
    tier: str
    base_lo: int
    base_hi: int
    bump: int
    bump_reasons: list[str] = field(default_factory=list)
    floor_reason: str = ""
    final_lo: int = 0
    final_hi: int = 0

    def summary_line(self) -> str:
        parts = [f"base {self.tier}: {self.base_lo}-{self.base_hi}"]
        parts.extend(f"+{r}" for r in self.bump_reasons)
        if self.floor_reason:
            parts.append(self.floor_reason)
        return f"Test budget: {self.final_lo}-{self.final_hi} ({'; '.join(parts)})"


def compute_bumps(signal: BuildSignal) -> tuple[int, list[str]]:
    """Additive bumps to the ceiling, each with an audit string."""
    bump = 0
    reasons: list[str] = []

    if signal.nimbus_changed:
        bump += BUMP_NIMBUS
        reasons.append(f"{BUMP_NIMBUS} Nimbus experiments/features changed")
    if signal.has_backout:
        bump += BUMP_BACKOUT
        reasons.append(f"{BUMP_BACKOUT} a backout landed in this range")
    if signal.notable_collections:
        bump += BUMP_REMOTE_SETTINGS
        reasons.append(
            f"{BUMP_REMOTE_SETTINGS} {signal.notable_collections} Remote "
            f"Settings collection(s) shipped out-of-band")
    if signal.dependency_changed:
        bump += BUMP_DEPENDENCY
        reasons.append(f"{BUMP_DEPENDENCY} dependency pin changed")
    if signal.source_strings_changed:
        bump += BUMP_SOURCE_STRINGS
        reasons.append(f"{BUMP_SOURCE_STRINGS} new en-US UI strings")

    return bump, reasons


def compute_budget(signal: BuildSignal) -> BudgetDecision:
    """Return the full decision, ready for the report header and as a cap.

    Exact matches raise the *floor* rather than the ceiling: a case linked from
    a changed instrumented test is known to be affected, not estimated, so the
    budget cannot come in under that count.
    """
    tier = detect_tier(signal)
    base_lo, base_hi = BASE_RANGES[tier]
    bump, reasons = compute_bumps(signal)

    final_lo = base_lo
    floor_reason = ""
    if signal.exact_match_cases > final_lo:
        final_lo = signal.exact_match_cases
        floor_reason = (
            f"floor raised to {signal.exact_match_cases} by exact-match cases")

    final_hi = base_hi + bump
    final_lo = max(ABSOLUTE_FLOOR, min(final_lo, ABSOLUTE_CEILING))
    final_hi = max(final_lo, min(final_hi, ABSOLUTE_CEILING))

    return BudgetDecision(
        tier=tier,
        base_lo=base_lo,
        base_hi=base_hi,
        bump=bump,
        bump_reasons=reasons,
        floor_reason=floor_reason,
        final_lo=final_lo,
        final_hi=final_hi,
    )
