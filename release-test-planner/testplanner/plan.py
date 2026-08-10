# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Stage 6: choose which tests to actually run, and find the gaps.

The selection problem is a budgeted maximum-coverage problem: pick the subset
of tests that removes the most risk per minute of device time. That is NP-hard,
so we use the standard greedy approximation, which for submodular gain has a
(1 - 1/e) worst-case bound.

The gain of a test is honest rather than assumed: after adding it we RE-DERIVE
the feature's coverage tier from the selected set only, and the gain is the drop
in RPN that re-derivation produces. A fifth redundant smoke test on an already
well-covered feature therefore scores a gain of zero and never gets picked.

Whatever risk survives running every automated test we own is, by definition,
the manual testing gap.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .coverage import _score

# Rough device-minutes per test. The efficiency suite is cheaper by design.
DEFAULT_COST_MINUTES = {
    "ui": 2.5,
    "ui.efficiency": 1.5,
}

# A test must remove at least this many RPN points to be worth its slot. With a
# continuous detection curve the gain of the twentieth redundant test is
# positive but negligible; this is where "diminishing" becomes "not worth it".
MIN_GAIN = 1.0


def _cost(test: Dict, costs: Dict[str, float]) -> float:
    return costs.get(test["suite"], 2.0)


def _rpn_for(row: Dict, selected_tests: List[Dict]) -> float:
    """RPN of a feature given only the tests currently selected for it.

    Kept as a float so the greedy loop sees the smooth diminishing gains of the
    detection curve rather than integer-rounded plateaus.
    """
    detection = _score(selected_tests)["detection"]
    return row["severity"] * row["occurrence"] * detection


def build(
    risk_result: Dict,
    coverage: Dict,
    budget_minutes: Optional[float] = None,
    costs: Optional[Dict[str, float]] = None,
) -> Dict:
    costs = costs or DEFAULT_COST_MINUTES
    rows = {r["feature_id"]: r for r in risk_result["rows"]}

    # Candidate tests, and which at-risk features each one serves.
    candidates: Dict[str, Dict] = {}
    for fid, row in rows.items():
        for test in coverage["per_feature"].get(fid, {}).get("tests", []):
            if test["is_disabled"]:
                continue
            # Never schedule a test as coverage for a feature it merely passes
            # through. If an agent confirms the binding it becomes selectable.
            if test["binding"] == "incidental":
                continue
            key = "{}#{}".format(test["file"], test["name"])
            entry = candidates.setdefault(
                key, {"test": test, "features": [], "key": key}
            )
            entry["features"].append(fid)

    selected_by_feature: Dict[str, List[Dict]] = {fid: [] for fid in rows}
    current_rpn = {fid: _rpn_for(rows[fid], []) for fid in rows}
    baseline_rpn = dict(current_rpn)

    selected: List[Dict] = []
    spent = 0.0
    remaining = dict(candidates)

    while remaining:
        best_key = None
        best_gain = 0.0
        best_abs = 0
        best_cost = 0.0

        for key, entry in remaining.items():
            cost = _cost(entry["test"], costs)
            gain = 0
            for fid in entry["features"]:
                trial = selected_by_feature[fid] + [entry["test"]]
                gain += current_rpn[fid] - _rpn_for(rows[fid], trial)
            if gain < MIN_GAIN:
                continue
            density = gain / cost
            if density > best_gain:
                best_gain, best_key, best_abs, best_cost = density, key, gain, cost

        if best_key is None:
            break
        if budget_minutes is not None and spent + best_cost > budget_minutes:
            del remaining[best_key]
            continue

        entry = remaining.pop(best_key)
        for fid in entry["features"]:
            selected_by_feature[fid].append(entry["test"])
            current_rpn[fid] = _rpn_for(rows[fid], selected_by_feature[fid])

        spent += best_cost
        selected.append(
            {
                **entry["test"],
                "covers_features": entry["features"],
                "rpn_removed": round(best_abs, 1),
                "cost_minutes": best_cost,
            }
        )

    # Anything still on the table adds no measurable risk reduction.
    redundant = [
        {**e["test"], "covers_features": e["features"]} for e in remaining.values()
    ]

    per_feature = []
    gaps = []
    for fid, row in rows.items():
        chosen = selected_by_feature[fid]
        residual = current_rpn[fid]
        tier = _score(chosen)["coverage_tier"]
        entry = {
            "feature_id": fid,
            "name": row["name"],
            "severity": row["severity"],
            "occurrence": row["occurrence"],
            "criticality": row["criticality"],
            "baseline_rpn": int(round(baseline_rpn[fid])),
            "residual_rpn": int(round(residual)),
            "rpn_removed": int(round(baseline_rpn[fid] - residual)),
            "planned_tests": len(chosen),
            "planned_tier": tier,
            "planned_cost_minutes": round(
                sum(_cost(t, costs) for t in chosen), 1
            ),
        }
        per_feature.append(entry)

        if residual >= 100 or tier in ("none", "disabled-only", "minimal", "thin"):
            gaps.append(
                {
                    **entry,
                    "reason": _gap_reason(row, tier, residual),
                    "indirect": row.get("indirect", False),
                    "iso25010": row["iso25010"],
                    "severity_rationale": row["severity_rationale"],
                    "churned_lines": row["churned_lines"],
                    "disabled_count": row["disabled_count"],
                }
            )

    per_feature.sort(key=lambda e: e["residual_rpn"], reverse=True)
    gaps.sort(key=lambda g: g["residual_rpn"], reverse=True)

    total_residual = int(round(sum(e["residual_rpn"] for e in per_feature)))
    total_inherent = sum(r["inherent_rpn"] for r in risk_result["rows"])

    return {
        "budget_minutes": budget_minutes,
        "selected_count": len(selected),
        "estimated_minutes": round(spent, 1),
        "estimated_hours": round(spent / 60.0, 2),
        "selected": sorted(selected, key=lambda t: t["rpn_removed"], reverse=True),
        "redundant_count": len(redundant),
        "redundant": redundant,
        "per_feature": per_feature,
        "gaps": gaps,
        "totals": {
            "residual_rpn": total_residual,
            "inherent_rpn": total_inherent,
            "rpn_removed": total_inherent - total_residual,
            "release_confidence": round(
                1 - total_residual / total_inherent, 3
            ) if total_inherent else 0.0,
            "features_with_gaps": len(gaps),
        },
    }


def _gap_reason(row: Dict, tier: str, residual: float) -> str:
    if tier == "none":
        if row.get("indirect"):
            return (
                "Cross-cutting code with no UI test named for it. The suite "
                "exercises it incidentally, but nothing verifies it directly, "
                "so a regression here would surface as an unrelated failure - "
                "or not at all. Best covered by exploratory testing."
            )
        if row["test_count"] == 0:
            return "No UI automation binds to this feature at all."
        return "Automation exists but none of it reduces risk for this change."
    if tier == "disabled-only":
        return "All {} bound tests are disabled or ignored.".format(row["test_count"])
    if tier in ("minimal", "thin"):
        return (
            "Only {} active test(s) bound, {} of them smoke - not enough to "
            "detect a regression reliably.".format(
                row["active_count"], row["smoke_count"]
            )
        )
    return (
        "Residual RPN {} stays above the review threshold even after running "
        "every bound test.".format(int(round(residual)))
    )
