"""
Deterministic candidate scorer for Firefox Android.

Ranks TestRail cases by how likely this build is to have broken them, with no
LLM involved. Every component is additive and carries a reason string, so a
QA lead can see exactly why a case was suggested.

**What differs from `../candidate_scorer.py`.** iOS scores against PR/module
signal and had to work around two gaps in its TestRail data: `Priority` was
effectively flat and `Labels` was empty. Android has neither problem, and has
one signal iOS lacks entirely:

  - `Automation` partitions the catalogue cleanly — `Unsuitable` cases can
    *only* be covered manually, while `Completed` ones already run in CI. The
    column holds up against the code: essentially every `Completed` case maps
    to a test and no `Unsuitable` one does.
  - `Priority` has a real distribution (High / Medium / Low), so it is worth
    points rather than being ignored.
  - The engine moves on every build and cannot be mapped to individual cases,
    so `GeckoRisk.section_hints` contributes a section-level nudge instead.

Ties break on case ID so output is stable between runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


SCORE_EXACT_MATCH = 50
"""A changed instrumented test links this case. Not inference — the link is a
comment in the source, so this outranks everything else."""

SCORE_TOUCHED_MODULE = 30
"""The case's section maps to a module that changed in this build."""

SCORE_MODULE_WEIGHT_MAX = 15
"""Extra, scaled by how strongly the mapping associates the section with that
module (`weight` in the mapping YAML = backing case links)."""

SCORE_NIMBUS_SECTION = 20
"""A Nimbus experiment or feature definition changed and this section is in
its blast radius."""

SCORE_ENGINE_HINT = 15
"""The section is one `GeckoRisk` flagged for exploratory focus."""

SCORE_MANUAL_ONLY = 12
"""`Unsuitable` — no automation will ever cover this. Running it by hand is
the only way it gets tested."""

SCORE_UNTRIAGED = 4
SCORE_PRIORITY_HIGH = 8
SCORE_PRIORITY_LOW = -5
SCORE_AUTOMATED = -20
"""`Completed` / `Disabled`. CI already covers it; re-running by hand is the
least valuable use of a limited window. Not disqualifying — an exact match
still pulls it back up."""


GENERIC_FEATURE_TOKENS = frozenset({
    "default", "screen", "opening", "main", "page", "view", "mobile",
    "android", "support", "enabled", "config", "settings", "feature",
    "users", "content",
})
"""Tokens too common to carry blast-radius signal.

`homepage-opening-screen-default` otherwise matched `Set as default browser`
and `Default search code` on "default", and `Splash-screen` on "screen" —
three sections with nothing to do with the experiment.
"""


MIN_SPECIFICITY_FACTOR = 0.3
"""Floor on the touched-module bonus for a module shared by many sections.

`settings/` is mapped by a large fraction of all sections, so a one-line edit
to `utils/Settings.kt` previously lit every one of them at full strength —
filling P0 with unrelated settings screens while the build's actual subjects
ranked below them. A module serving one section is strong evidence; one
serving dozens is weak, but not zero.
"""


@dataclass
class ScoringContext:
    """Lookups computed once per build."""
    exact_match_cases: set[str] = field(default_factory=set)
    # section name -> best module weight among its *touched* modules
    touched_sections: dict[str, int] = field(default_factory=dict)
    # section name -> how many sections its best touched module also serves
    section_module_spread: dict[str, int] = field(default_factory=dict)
    nimbus_sections: set[str] = field(default_factory=set)
    engine_hint_sections: set[str] = field(default_factory=set)
    max_weight: int = 1

    def specificity(self, section: str) -> float:
        """1.0 when the touched module serves only this section, falling to
        MIN_SPECIFICITY_FACTOR as it is shared more widely."""
        spread = self.section_module_spread.get(section, 1)
        return MIN_SPECIFICITY_FACTOR + (1 - MIN_SPECIFICITY_FACTOR) / max(spread, 1)


def _module_matches(module_path: str, changed_path: str) -> bool:
    """True when a changed file lives under a mapped module, or vice versa.

    Both directions matter: the mapping may name `settings` while the diff
    touches `settings/logins/X.kt`, or name `settings/trustpanel` while the
    diff is reported at a coarser path.
    """
    a = module_path.rstrip("/")
    b = changed_path.rstrip("/")
    return a == b or b.startswith(a + "/") or a.startswith(b + "/")


def build_context(
    mapping: dict,
    changed_paths: list[str],
    exact_match_cases: set[str] | None = None,
    nimbus_features: list[str] | None = None,
    engine_hints: list[str] | None = None,
) -> ScoringContext:
    """Precompute the lookups `score_case` needs.

    `mapping` is the parsed `section_to_module_mapping.yaml`. Plain types only,
    so this module stays importable without the extractor.
    """
    touched: dict[str, int] = {}
    spread_of_section: dict[str, int] = {}
    nimbus_sections: set[str] = set()
    max_weight = 1

    # How many sections each module serves, so a diffuse module can be
    # discounted. `settings/` serves 35; `settings/deletebrowsingdata` serves 1.
    serves: dict[str, int] = {}
    for section in mapping.get("sections", []):
        for module in section.get("modules") or []:
            serves[module["path"]] = serves.get(module["path"], 0) + 1

    for section in mapping.get("sections", []):
        name = section["name"]
        for module in section.get("modules") or []:
            path = module["path"]
            weight = int(module.get("weight") or 0)
            max_weight = max(max_weight, weight)
            if any(_module_matches(path, c) for c in changed_paths):
                if weight >= touched.get(name, -1):
                    touched[name] = weight
                    spread_of_section[name] = serves.get(path, 1)

    # Match the experiment's own feature IDs against section names. Matching
    # on section-name prefixes instead selects a large slice of the catalogue
    # and leaves the top scores tied, which makes the ranking effectively
    # alphabetical. The feature IDs are far narrower.
    for feature in nimbus_features or ():
        tokens = {
            t for t in re.split(r"[-_]", feature.lower())
            if len(t) > 3 and t not in GENERIC_FEATURE_TOKENS
        }
        if not tokens:
            continue
        for section in mapping.get("sections", []):
            name = section["name"]
            words = set(re.split(r"[^a-z0-9]+", name.lower()))
            if tokens & words:
                nimbus_sections.add(name)

    hints = set(engine_hints or [])
    engine_sections = {
        section["name"] for section in mapping.get("sections", [])
        if any(section["name"].startswith(h) for h in hints)
    }

    return ScoringContext(
        exact_match_cases=set(exact_match_cases or ()),
        touched_sections=touched,
        section_module_spread=spread_of_section,
        nimbus_sections=nimbus_sections,
        engine_hint_sections=engine_sections,
        max_weight=max_weight,
    )


@dataclass
class ScoredCase:
    case_id: str
    section: str
    score: int
    reasons: list[str] = field(default_factory=list)


def score_case(case, section: str, ctx: ScoringContext) -> ScoredCase:
    """Score one TestRail case. Deterministic: same inputs, same output.

    A case must have at least one *connection* to this build — an exact match,
    a touched module, a Nimbus blast radius, or an engine hint — to score at
    all. `Automation` and `Priority` modulate that connection; they never
    create one. Without this gate an RC whose diff is literally empty still
    returned ~500 candidates, every manual-only High case in the catalogue
    scoring 20 for existing.
    """
    score = 0
    reasons: list[str] = []
    connected = False

    if case.case_id in ctx.exact_match_cases:
        score += SCORE_EXACT_MATCH
        connected = True
        reasons.append("a changed instrumented test links this case")

    if section in ctx.touched_sections:
        connected = True
        specificity = ctx.specificity(section)
        spread = ctx.section_module_spread.get(section, 1)
        score += round(SCORE_TOUCHED_MODULE * specificity)
        if spread > 1:
            reasons.append(
                f"section maps to a module changed in this build, shared with "
                f"{spread - 1} other section(s)")
        else:
            reasons.append(
                "section maps to a module changed in this build, and only this "
                "section")
        weight = ctx.touched_sections[section]
        if weight > 0:
            scaled = round(SCORE_MODULE_WEIGHT_MAX * weight / ctx.max_weight
                           * specificity)
            if scaled:
                score += scaled
                reasons.append(f"strong section↔module association (w={weight})")

    if section in ctx.nimbus_sections:
        score += SCORE_NIMBUS_SECTION
        connected = True
        reasons.append("in the blast radius of a Nimbus change")

    if section in ctx.engine_hint_sections:
        score += SCORE_ENGINE_HINT
        connected = True
        reasons.append("engine area flagged for this section")

    if not connected:
        return ScoredCase(case_id=case.case_id, section=section,
                          score=0, reasons=[])

    if case.is_manual_only:
        score += SCORE_MANUAL_ONLY
        reasons.append("manual-only: no automation covers it")
    elif case.automation == "Untriaged":
        score += SCORE_UNTRIAGED
        reasons.append("automation status untriaged")
    elif case.is_automated:
        score += SCORE_AUTOMATED
        reasons.append("already automated in CI")

    if case.priority == "High":
        score += SCORE_PRIORITY_HIGH
    elif case.priority == "Low":
        score += SCORE_PRIORITY_LOW

    return ScoredCase(case_id=case.case_id, section=section,
                      score=score, reasons=reasons)


def rank_cases(cases_with_sections, ctx: ScoringContext,
               limit: int | None = None) -> list[ScoredCase]:
    """Score and sort. `cases_with_sections` is an iterable of (case, section).

    Only positive scores survive: a case with nothing tying it to this build
    should not appear merely because it is High priority.
    """
    scored = [score_case(c, s, ctx) for c, s in cases_with_sections]
    scored = [s for s in scored if s.score > 0]
    scored.sort(key=lambda s: (-s.score, s.case_id))
    return scored[:limit] if limit else scored


def split_priorities(ranked: list[ScoredCase],
                     budget_lo: int, budget_hi: int) -> dict[str, list[ScoredCase]]:
    """Cut the ranked list into P0/P1/P2 against the budget.

    P0 fills to the budget floor — the cases QA should run even if nothing
    else happens. P1 extends to the ceiling. P2 is the next tranche again,
    offered as overflow rather than dropped, since the budget is an estimate
    and the operator may have more capacity than it assumed.
    """
    p0 = ranked[:budget_lo]
    p1 = ranked[budget_lo:budget_hi]
    p2 = ranked[budget_hi:budget_hi + (budget_hi - budget_lo)]
    return {"P0": p0, "P1": p1, "P2": p2}
