# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Stage 5: score risk per feature using FMEA.

The model is Failure Mode and Effects Analysis (IEC 60812), the same scheme
ISTQB's risk-based testing material builds on:

    RPN = Severity x Occurrence x Detection      (1 .. 1000)

  Severity   blast radius if the feature breaks. From the feature catalog.
  Occurrence likelihood this cycle's change broke it. Derived from relative
             code churn (Nagappan & Ball, ICSE 2005).
  Detection  likelihood the defect ESCAPES to release. Inverted coverage, so
             better automation lowers RPN. This is the factor a test plan moves.

Two derived numbers matter for release decisions:

  Criticality (FMECA) = S x O
      Inherent risk of the change, independent of how well we test it. You
      cannot reduce this without changing the code.

  Residual RPN
      What is left after the planned tests run. The gap between criticality
      and residual risk is exactly the argument for running a given suite.

RPN action thresholds follow conventional AIAG FMEA practice.
"""

from __future__ import annotations

from typing import Dict, List

ACTION_REQUIRED = 200
REVIEW_REQUIRED = 100

# Relative churn (churned LOC / total LOC) -> base Occurrence.
CHURN_BANDS = [
    (0.02, 1),
    (0.05, 2),
    (0.10, 3),
    (0.20, 4),
    (0.35, 5),
    (0.50, 6),
    (0.75, 7),
    (10.0, 8),
]


def occurrence(bucket: Dict) -> Dict:
    """Derive the FMEA Occurrence factor from churn measures."""
    ratio = bucket.get("m1_churn_ratio", 0.0)

    base = 8
    for threshold, score in CHURN_BANDS:
        if ratio < threshold:
            base = score
            break

    modifiers = []
    score = base

    if bucket.get("file_count", 0) >= 10:
        score += 1
        modifiers.append("touched 10+ files (broad change surface)")
    if bucket.get("commits", 0) >= 15:
        score += 1
        modifiers.append("15+ commits (sustained churn)")
    if bucket.get("authors", 0) >= 4:
        score += 1
        modifiers.append("4+ authors (coordination risk)")
    if bucket.get("backout_touched"):
        score += 2
        modifiers.append("touched by a backout/revert (proven instability)")

    delta = bucket.get("agent_occurrence_delta")
    if delta:
        score += int(delta)
        modifiers.append(
            "agent review: {} ({:+d})".format(
                bucket.get("agent_change_kind", "semantics"), int(delta)
            )
        )

    score = max(1, min(10, score))

    return {
        "occurrence": score,
        "occurrence_base": base,
        "occurrence_basis": "relative churn {:.1%} of feature LOC".format(ratio),
        "occurrence_modifiers": modifiers,
    }


def _crap(occ: int, detection: int) -> float:
    """CRAP score adapted from per-method to per-feature scope.

    Original: CRAP(m) = CC(m)^2 * (1 - cov(m))^3 + CC(m). We substitute a
    change-complexity proxy for cyclomatic complexity and derive coverage from
    the Detection factor, keeping the shape that punishes complex-and-untested.
    """
    complexity = occ * 3.0
    cov = (10 - detection) / 9.0
    return round(complexity ** 2 * (1 - cov) ** 3 + complexity, 1)


def band(rpn: int) -> str:
    if rpn >= ACTION_REQUIRED:
        return "action-required"
    if rpn >= REVIEW_REQUIRED:
        return "review"
    return "acceptable"


def score(attribution: Dict, coverage: Dict) -> Dict:
    """Produce a per-feature FMEA row for every feature touched this cycle."""
    rows: List[Dict] = []

    for bucket in attribution["features_touched"]:
        fid = bucket["feature_id"]
        cov = coverage["per_feature"].get(fid, {})

        occ = occurrence(bucket)
        s = bucket["severity"]
        o = occ["occurrence"]
        d = cov.get("detection", 10.0)

        rpn = int(round(s * o * d))
        inherent = s * o * 10
        criticality = s * o

        rows.append(
            {
                "feature_id": fid,
                "name": bucket["name"],
                "severity": s,
                "severity_rationale": bucket["severity_rationale"],
                "iso25010": bucket["iso25010"],
                "indirect": bucket.get("indirect", False),
                "detection": round(d, 1),
                "coverage_tier": cov.get("coverage_tier", "none"),
                "rpn": rpn,
                "inherent_rpn": inherent,
                "criticality": criticality,
                "band": band(rpn),
                "risk_reduced_by_automation": round(1 - (d / 10.0), 3),
                "crap_score": _crap(o, d),
                "churned_lines": bucket["churned_lines"],
                "file_count": bucket["file_count"],
                "commits": bucket["commits"],
                "authors": bucket["authors"],
                "m1_churn_ratio": bucket["m1_churn_ratio"],
                "backout_touched": bucket["backout_touched"],
                "test_count": cov.get("test_count", 0),
                "active_count": cov.get("active_count", 0),
                "direct_count": cov.get("direct_count", 0),
                "incidental_count": cov.get("incidental_count", 0),
                "smoke_count": cov.get("smoke_count", 0),
                "disabled_count": cov.get("disabled_count", 0),
                "modernised_count": cov.get("modernised_count", 0),
                **occ,
            }
        )

    rows.sort(key=lambda r: r["rpn"], reverse=True)

    total_rpn = sum(r["rpn"] for r in rows)
    total_inherent = sum(r["inherent_rpn"] for r in rows)
    confidence = (1 - total_rpn / total_inherent) if total_inherent else 0.0

    return {
        "rows": rows,
        "totals": {
            "features_touched": len(rows),
            "total_rpn": total_rpn,
            "total_inherent_rpn": total_inherent,
            "total_criticality": sum(r["criticality"] for r in rows),
            "action_required": sum(1 for r in rows if r["band"] == "action-required"),
            "review": sum(1 for r in rows if r["band"] == "review"),
            "acceptable": sum(1 for r in rows if r["band"] == "acceptable"),
            "coverage_confidence": round(confidence, 3),
            "uncovered_features": sum(1 for r in rows if r["test_count"] == 0),
        },
    }
