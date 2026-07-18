"""
Deterministic candidate scorer and pre-filter.

Before sending candidates to the LLM rerank stage, score each one with a
transparent heuristic and truncate to the top K. Two benefits:

  1. Cost: input tokens drop from ~43k (999 candidates) to ~10-15k (~280).
  2. Stability: with a smaller, better-ranked pool the LLM makes fewer
     marginal choices between near-equivalents → output overlap between
     runs improves.

Score components (additive):
  +50   exact match (Automated Test Name references a file changed in this release)
  +30   the test's section maps to a touched module in the top quartile of LOC
  +20   the test's section maps to a module that has any risk signal attached
  +10   automation status is manual-only ("Unsuitable" or "Untriaged")
  -20   automation status is "Completed" (CI already covers it)

Ties are broken deterministically by test ID to keep output stable.
"""

from __future__ import annotations

from dataclasses import dataclass


# =============================================================================
# Data — a minimal protocol so this module has no reverse dependency
# =============================================================================


@dataclass
class ScoringContext:
    """Everything the scorer needs to look at, pre-computed once per pipeline."""
    exact_match_ids: set[str]                     # test IDs matched by file path
    high_loc_modules: set[str]                    # top-quartile of touched modules
    sections_with_risk: set[str]                  # section_top names with an associated risk
    section_to_touched_modules: dict[str, set[str]]  # section_top → set of touched module paths


# =============================================================================
# Context builder
# =============================================================================


def _top_quartile(values: dict[str, int]) -> set[str]:
    """Return the keys whose values fall in the top quartile (25%). Ties are
    resolved by keeping keys with equal-or-greater than the quartile threshold."""
    if not values:
        return set()
    sorted_vals = sorted(values.values(), reverse=True)
    quartile_size = max(1, len(sorted_vals) // 4)
    threshold = sorted_vals[quartile_size - 1]
    return {k for k, v in values.items() if v >= threshold}


def build_scoring_context(
    exact_matched_tests: list,
    module_changes: dict,           # module_path → ModuleChange
    risks: list,                    # RiskSignal list
    mapping: dict,                  # the section_to_module_mapping YAML content
) -> ScoringContext:
    """Compute the lookup structures used by score_candidate.

    Kept as plain positional args of common types so this module doesn't need
    to import from recommend.py (avoids a cycle when tests import both).
    """
    exact_match_ids = {tc.id for tc in exact_matched_tests}

    # Top-quartile modules by LOC touched
    module_locs = {m: mc.total_loc for m, mc in module_changes.items()}
    high_loc_modules = _top_quartile(module_locs)

    # section_top → set of touched module paths (from mapping.yaml, filtered by what actually changed)
    section_to_touched: dict[str, set[str]] = {}
    for section_def in mapping.get("sections", []):
        section_name = section_def["name"]
        for m in section_def.get("modules", []):
            module_path = m["path"]
            for touched in module_changes.keys():
                if touched == module_path or touched.startswith(module_path.rstrip("/") + "/") \
                        or module_path.startswith(touched.rstrip("/") + "/"):
                    section_to_touched.setdefault(section_name, set()).add(touched)

    # Sections with risk: any section whose touched modules host a risk signal
    # whose `location` is a file path (not a PR-level signal).
    # A risk signal's location is either "PR #N" or a file path like
    # "firefox-ios/Client/Frontend/Reader/ReaderModeSchemeHandler.swift".
    sections_with_risk: set[str] = set()
    for r in risks:
        loc = r.location
        if loc.startswith("PR #") or "/" not in loc:
            continue
        # Find which touched module this file lives under, then which sections cover it
        for section_name, touched_modules in section_to_touched.items():
            if any(loc.startswith(tm.rstrip("/") + "/") or loc == tm for tm in touched_modules):
                sections_with_risk.add(section_name)

    return ScoringContext(
        exact_match_ids=exact_match_ids,
        high_loc_modules=high_loc_modules,
        sections_with_risk=sections_with_risk,
        section_to_touched_modules=section_to_touched,
    )


# =============================================================================
# Scoring
# =============================================================================


SCORE_EXACT_MATCH = 50
SCORE_HIGH_LOC_MODULE = 30
SCORE_RISK_ASSOCIATION = 20
SCORE_MANUAL_ONLY = 10
SCORE_CI_COMPLETED = -20


def score_candidate(tc, ctx: ScoringContext) -> int:
    """Compute the score for a TestCase against the scoring context.

    Higher is more relevant to this release. Purely deterministic — same
    (tc, ctx) always returns the same value.
    """
    score = 0

    if tc.id in ctx.exact_match_ids:
        score += SCORE_EXACT_MATCH

    touched = ctx.section_to_touched_modules.get(tc.section_top, set())
    if touched and any(m in ctx.high_loc_modules for m in touched):
        score += SCORE_HIGH_LOC_MODULE

    if tc.section_top in ctx.sections_with_risk:
        score += SCORE_RISK_ASSOCIATION

    if tc.automation in ("Unsuitable", "Untriaged"):
        score += SCORE_MANUAL_ONLY
    elif tc.automation == "Completed":
        score += SCORE_CI_COMPLETED

    return score


def pre_filter_candidates(candidates: list, ctx: ScoringContext, top_k: int) -> list[tuple[object, int]]:
    """Score every candidate, sort by score desc (ties broken by test ID for
    stability), and return the top_k as (TestCase, score) pairs."""
    scored = [(tc, score_candidate(tc, ctx)) for tc in candidates]
    scored.sort(key=lambda pair: (-pair[1], pair[0].id))
    return scored[:top_k]
