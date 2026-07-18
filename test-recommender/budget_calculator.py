"""
Test budget calculator.

Determines how many tests QA should be asked to run for a given release, based
on:
  - Release type detected from tag names (patch / minor / major)
  - Deterministic bumps triggered by release signal (LOC, big PRs, risks)

The budget flows into two places:
  1. The rerank prompt (as a "return N-M tests" range).
  2. The defensive cap that truncates the LLM output if it overshoots.
  3. A transparency line in the report header, so the QA lead knows why
     THIS release has THIS budget.

Design principles:
  - Predictable base per release type (QA can plan capacity).
  - Bumps are additive to the ceiling only, and each bump carries a
    human-readable reason for audit.
  - Absolute floor (15) and ceiling (200) prevent runaway outputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Version can be referenced either as a shipped tag (`firefox-v153.0`) or as
# an in-flight release branch (`release/v153.0`). Both parse to the same
# version tuple; downstream detection (patch/minor/major) is identical.
TAG_RE = re.compile(r"firefox-v(\d+)(?:\.(\d+))?(?:\.(\d+))?$")
BRANCH_RE = re.compile(r"release/v(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


# Base test-count ranges per release type. 
BASE_RANGES: dict[str, tuple[int, int]] = {
    "patch": (25, 40),
    "minor": (40, 70),
    "major": (100, 160),
}

# Absolute clamps regardless of type or bumps.
ABSOLUTE_FLOOR = 15
ABSOLUTE_CEILING = 200

# Thresholds for the three deterministic bump rules.
BUMP_LOC_THRESHOLD = 15000
BUMP_LOC_AMOUNT = 15
BUMP_BIG_PR_LOC = 2000
BUMP_BIG_PR_AMOUNT = 10
BUMP_HIGH_RISKS_COUNT = 3
BUMP_HIGH_RISKS_AMOUNT = 10


@dataclass
class BudgetDecision:
    """Full budget decision, self-describing enough to render as a report line."""
    release_type: str          # "patch" | "minor" | "major"
    base_lo: int
    base_hi: int
    bump: int
    bump_reasons: list[str]
    final_lo: int
    final_hi: int

    def summary_line(self) -> str:
        """Human-readable line for the report header.

        Example (minor release with two bumps):
            'Test budget: 40-95 (base minor: 40-70; +15 total LOC 20,000 > 15,000; +10 large PR (2,100 LOC))'
        """
        parts = [f"base {self.release_type}: {self.base_lo}-{self.base_hi}"]
        if self.bump:
            parts.extend(f"+{r}" for r in self.bump_reasons)
        # Defensive: report if the floor/ceiling clamp actually kicked in.
        # With current constants (BASE_RANGES min = 25, max realistic ceiling
        # = 160 + 35 bumps = 195, floor = 15, ceiling = 200) this branch is
        # unreachable. Kept as scaffolding so future constant changes don't
        # silently mask a clamp.
        raw_hi = self.base_hi + self.bump
        if raw_hi != self.final_hi or self.base_lo != self.final_lo:
            parts.append(f"clamped to floor/ceiling {ABSOLUTE_FLOOR}/{ABSOLUTE_CEILING}")
        return f"Test budget: {self.final_lo}-{self.final_hi} ({'; '.join(parts)})"


# =============================================================================
# 2.1 — Detect release type
# =============================================================================


def _parse_tag(tag: str) -> tuple[int, ...] | None:
    """Extract numeric parts from a firefox-vX.Y[.Z] tag or release/vX.Y[.Z]
    branch. Returns None if neither pattern matches."""
    s = tag.strip()
    m = TAG_RE.match(s) or BRANCH_RE.match(s)
    if not m:
        return None
    return tuple(int(x) for x in m.groups() if x is not None)


def detect_release_type(from_tag: str, to_tag: str) -> str:
    """Return "patch", "minor", or "major" based on the tag delta.

    Rules:
      - X changes → "major"     (e.g. v153.2 → v154.0)
      - Y changes, no Z         → "minor"     (e.g. v153.1 → v153.2)
      - Z appears/changes       → "patch"     (e.g. v153.2 → v153.2.1)

    Falls back to "minor" if either tag is unparseable (safest middle ground).
    """
    fr = _parse_tag(from_tag)
    to = _parse_tag(to_tag)
    if fr is None or to is None:
        return "minor"

    # Major = first part differs
    if fr[0] != to[0]:
        return "major"

    # Patch = destination has a third component that changed, or appeared
    if len(to) == 3:
        return "patch"

    # Otherwise minor
    return "minor"


# =============================================================================
# 2.2 — Compute bumps
# =============================================================================


@dataclass
class ReleaseSignal:
    """The minimal subset of Analysis this module needs. Kept as its own
    dataclass so the module has no reverse dependency on recommend.py."""
    total_loc: int
    max_pr_loc: int
    high_severity_risk_count: int


def compute_bumps(signal: ReleaseSignal) -> tuple[int, list[str]]:
    """Compute the additive bump to the budget ceiling and the human-readable
    reasons list. Each rule fires independently; total is the sum."""
    bump = 0
    reasons: list[str] = []

    if signal.total_loc > BUMP_LOC_THRESHOLD:
        bump += BUMP_LOC_AMOUNT
        reasons.append(f"{BUMP_LOC_AMOUNT} total LOC {signal.total_loc:,} > {BUMP_LOC_THRESHOLD:,}")

    if signal.max_pr_loc > BUMP_BIG_PR_LOC:
        bump += BUMP_BIG_PR_AMOUNT
        reasons.append(f"{BUMP_BIG_PR_AMOUNT} large PR ({signal.max_pr_loc:,} LOC)")

    if signal.high_severity_risk_count >= BUMP_HIGH_RISKS_COUNT:
        bump += BUMP_HIGH_RISKS_AMOUNT
        reasons.append(f"{BUMP_HIGH_RISKS_AMOUNT} for {signal.high_severity_risk_count} high-severity risks")

    return bump, reasons


# =============================================================================
# 2.3 — Compute final budget
# =============================================================================


def compute_test_budget(release_type: str, signal: ReleaseSignal) -> BudgetDecision:
    """Return the full budget decision, ready to inject into the rerank prompt
    and to render in the report header."""
    base_lo, base_hi = BASE_RANGES.get(release_type, BASE_RANGES["minor"])
    bump, reasons = compute_bumps(signal)

    final_lo = max(base_lo, ABSOLUTE_FLOOR)
    final_hi = min(base_hi + bump, ABSOLUTE_CEILING)

    return BudgetDecision(
        release_type=release_type,
        base_lo=base_lo,
        base_hi=base_hi,
        bump=bump,
        bump_reasons=reasons,
        final_lo=final_lo,
        final_hi=final_hi,
    )
