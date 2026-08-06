# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Combinatorial test matrices: orthogonal arrays and covering arrays.

Two different reductions of the same explosion, and the difference matters when
you are arguing about how many device-hours a release needs.

ORTHOGONAL ARRAY (OA)
    Every pair of factor levels appears exactly the same number of times. That
    balance is what lets you attribute an effect to a factor - it is a design
    for ANALYSIS, inherited from Taguchi's design of experiments. The cost of
    balance is size, and the constraint is rigid: a strength-2 OA only exists
    for particular run counts and level structures.

COVERING ARRAY (CA)
    Every pair of factor levels appears AT LEAST once. Dropping the balance
    requirement makes the array substantially smaller and lets it accept any
    mix of level counts. It is a design for DETECTION - you want to know a
    combination breaks, not to attribute variance to a factor. This is the form
    used for large-scale combinatorial test selection, generated here with
    IPOG (In-Parameter-Order-General), the algorithm behind NIST's ACTS.

For release testing you almost always want the covering array. The OA is kept
because it is what people ask for by name, and because the size difference
between the two is the clearest way to show why.

Both outputs are verified: `verify()` re-derives every t-tuple and confirms the
array actually covers it, so a bug in generation shows up as a failed check
rather than a quietly under-covered test run.
"""

from __future__ import annotations

from itertools import combinations, product
from typing import Dict, List, Optional, Sequence, Tuple

Factor = Tuple[str, List[str]]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def full_factorial_size(factors: Sequence[Factor]) -> int:
    n = 1
    for _, levels in factors:
        n *= len(levels)
    return n


def verify(rows: List[Dict[str, str]], factors: Sequence[Factor],
           strength: int = 2) -> Dict:
    """Confirm every t-way combination of levels appears at least once."""
    names = [n for n, _ in factors]
    by_name = dict(factors)

    required = 0
    missing = []
    for combo in combinations(names, strength):
        for values in product(*[by_name[n] for n in combo]):
            required += 1
            target = dict(zip(combo, values))
            if not any(all(r.get(k) == v for k, v in target.items()) for r in rows):
                missing.append(target)

    return {
        "strength": strength,
        "tuples_required": required,
        "tuples_covered": required - len(missing),
        "complete": not missing,
        "missing_examples": missing[:5],
    }


# --------------------------------------------------------------------------
# covering array - IPOG
# --------------------------------------------------------------------------

def covering_array(factors: Sequence[Factor], strength: int = 2) -> List[Dict[str, str]]:
    """IPOG (In-Parameter-Order-General) t-way covering array.

    Builds the exhaustive array over the first t factors, then grows one factor
    at a time: horizontally, by picking for each existing row the level that
    covers the most still-uncovered tuples; then vertically, by adding rows for
    whatever tuples horizontal growth could not place.
    """
    factors = list(factors)
    if not factors:
        return []
    if strength <= 0:
        # Baseline: one representative configuration, no combinatorics.
        return [{n: lv[0] for n, lv in factors}]
    if len(factors) <= strength:
        names = [n for n, _ in factors]
        return [
            dict(zip(names, values))
            for values in product(*[lv for _, lv in factors])
        ]

    # Largest domains first - fewer rows result.
    factors = sorted(factors, key=lambda f: len(f[1]), reverse=True)
    names = [n for n, _ in factors]
    levels = {n: lv for n, lv in factors}

    rows: List[Dict[str, Optional[str]]] = [
        dict(zip(names[:strength], values))
        for values in product(*[levels[n] for n in names[:strength]])
    ]

    for i in range(strength, len(names)):
        current = names[: i + 1]
        new_factor = names[i]

        uncovered = set()
        for combo in combinations(current[:-1], strength - 1):
            for values in product(*[levels[n] for n in combo]):
                for nv in levels[new_factor]:
                    uncovered.add(
                        tuple(sorted(list(zip(combo, values)) + [(new_factor, nv)]))
                    )

        # Horizontal growth.
        for row in rows:
            best_level, best_gain, best_covered = None, -1, set()
            for candidate in levels[new_factor]:
                trial = dict(row)
                trial[new_factor] = candidate
                covered = _tuples_in_row(trial, current, strength) & uncovered
                if len(covered) > best_gain:
                    best_level, best_gain, best_covered = candidate, len(covered), covered
            row[new_factor] = best_level
            uncovered -= best_covered

        # Vertical growth.
        for tup in sorted(uncovered, key=lambda t: [str(x) for x in t]):
            assignment = dict(tup)
            placed = False
            for row in rows:
                if all(
                    row.get(k) is None or row.get(k) == v
                    for k, v in assignment.items()
                ):
                    row.update(assignment)
                    placed = True
                    break
            if not placed:
                new_row: Dict[str, Optional[str]] = {n: None for n in current}
                new_row.update(assignment)
                rows.append(new_row)

    # Fill any remaining don't-cares with the first level.
    return [{n: (r.get(n) or levels[n][0]) for n in names} for r in rows]


def _tuples_in_row(row: Dict, current: Sequence[str], strength: int) -> set:
    present = [n for n in current if row.get(n) is not None]
    out = set()
    for combo in combinations(present, strength):
        out.add(tuple(sorted((n, row[n]) for n in combo)))
    return out


# --------------------------------------------------------------------------
# orthogonal array - Rao-Hamming construction
# --------------------------------------------------------------------------

PRIMES = [2, 3, 5, 7, 11, 13]


def _rao_hamming(q: int, m: int) -> List[List[int]]:
    """OA(q^m, (q^m-1)/(q-1), q, strength 2) for prime q.

    Runs are all vectors in GF(q)^m. Columns are the points of the projective
    space PG(m-1, q) - nonzero vectors normalised so the leading nonzero entry
    is 1 - and the cell value is the dot product mod q.
    """
    columns = []
    for vec in product(range(q), repeat=m):
        if all(v == 0 for v in vec):
            continue
        lead = next(v for v in vec if v != 0)
        if lead != 1:
            continue
        columns.append(vec)

    rows = []
    for x in product(range(q), repeat=m):
        rows.append([sum(a * b for a, b in zip(x, col)) % q for col in columns])
    return rows


def orthogonal_array(factors: Sequence[Factor]) -> Dict:
    """Strength-2 orthogonal array covering `factors`.

    A true OA needs every factor to share one level count. Mixed-level inputs
    are handled with the standard dummy-level technique: build the OA at the
    largest level count and fold surplus levels back onto real ones. That keeps
    pairwise coverage complete but breaks perfect balance, so the return value
    says so explicitly rather than presenting a compromised array as a clean one.
    """
    factors = list(factors)
    if not factors:
        return {"rows": [], "runs": 0, "balanced": True, "notes": []}

    max_levels = max(len(lv) for _, lv in factors)
    q = next((p for p in PRIMES if p >= max_levels), None)
    notes = []

    if q is None:
        return {
            "rows": [], "runs": 0, "balanced": False,
            "notes": ["No supported orthogonal array for {} levels.".format(max_levels)],
        }

    mixed = len({len(lv) for _, lv in factors}) > 1
    if mixed or q != max_levels:
        notes.append(
            "Mixed level counts, so the dummy-level technique was applied: "
            "pairwise coverage is complete but the array is no longer perfectly "
            "balanced, and factor effects cannot be cleanly attributed."
        )

    m = 2
    while (q ** m - 1) // (q - 1) < len(factors):
        m += 1
        if m > 6:
            return {
                "rows": [], "runs": 0, "balanced": False,
                "notes": ["Too many factors for a tractable orthogonal array."],
            }

    grid = _rao_hamming(q, m)
    names = [n for n, _ in factors]
    levels = {n: lv for n, lv in factors}

    rows = []
    for line in grid:
        row = {}
        for idx, name in enumerate(names):
            lv = levels[name]
            row[name] = lv[line[idx] % len(lv)]
        rows.append(row)

    # Identical rows can appear once surplus levels fold back.
    deduped, seen = [], set()
    for r in rows:
        key = tuple(sorted(r.items()))
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    if len(deduped) != len(rows):
        notes.append(
            "{} duplicate runs collapsed after level folding.".format(
                len(rows) - len(deduped)
            )
        )

    return {
        "rows": deduped,
        "runs": len(deduped),
        "designation": "OA({}, {}, {}, 2) via Rao-Hamming".format(
            q ** m, (q ** m - 1) // (q - 1), q
        ),
        "balanced": not mixed and q == max_levels,
        "notes": notes,
    }


def allocate(risk_rows: List[Dict], plan_result: Dict, env: Dict,
             context_factors: List[Dict]) -> Dict:
    """Give each feature as much matrix as its FMEA band earns.

    This is the join between the two halves of the tool. Risk decides the
    strength; the covering array decides the configurations; the selected test
    list decides what runs in each one. The product is the real device cost of
    the release, which is the number a release manager actually has to approve.
    """
    pool: Dict[str, Dict] = {}
    for f in context_factors:
        pool[f["name"]] = f
    for f in env["infrastructure_factors"]:
        # A factor declared in both places keeps the richer level list.
        existing = pool.get(f["name"])
        if not existing or len(f["levels"]) >= len(existing["levels"]):
            pool[f["name"]] = f

    policy = env["allocation_policy"]
    multipliers = env.get("config_cost_multiplier", {})

    planned_minutes = {e["feature_id"]: e["planned_cost_minutes"]
                       for e in plan_result["per_feature"]}
    planned_tests = {e["feature_id"]: e["planned_tests"]
                     for e in plan_result["per_feature"]}

    designs: Dict[str, Dict] = {}
    for band, spec in policy.items():
        selected = [(n, pool[n]["levels"]) for n in spec["factors"] if n in pool]
        rows = covering_array(selected, strength=spec["strength"])
        check = verify(rows, selected, spec["strength"]) if spec["strength"] >= 2 else None
        oa = orthogonal_array(selected) if spec["strength"] == 2 else None
        designs[band] = {
            "band": band,
            "strength": spec["strength"],
            "rationale": spec["rationale"],
            "factors": [{"name": n, "levels": lv} for n, lv in selected],
            "configs": rows,
            "config_count": len(rows),
            "full_factorial": full_factorial_size(selected),
            "reduction": round(1 - len(rows) / full_factorial_size(selected), 4)
            if full_factorial_size(selected) else 0.0,
            "verification": check,
            "orthogonal_alternative": {
                "runs": oa["runs"],
                "balanced": oa["balanced"],
                "designation": oa.get("designation", ""),
                "notes": oa["notes"],
            } if oa else None,
        }

    per_feature = []
    for row in risk_rows:
        fid = row["feature_id"]
        design = designs.get(row["band"], designs["acceptable"])
        tests = planned_tests.get(fid, 0)
        base_minutes = planned_minutes.get(fid, 0.0)

        cost = 0.0
        for cfg in design["configs"]:
            mult = 1.0
            for factor, level in cfg.items():
                mult *= multipliers.get(factor, {}).get(level, 1.0)
            cost += base_minutes * mult

        per_feature.append({
            "feature_id": fid,
            "name": row["name"],
            "band": row["band"],
            "rpn": row["rpn"],
            "strength": design["strength"],
            "config_count": design["config_count"],
            "planned_tests": tests,
            "executions": tests * design["config_count"],
            "est_minutes": round(cost, 1),
        })

    per_feature.sort(key=lambda e: e["executions"], reverse=True)
    total_exec = sum(e["executions"] for e in per_feature)
    total_min = sum(e["est_minutes"] for e in per_feature)

    return {
        "factor_pool": [
            {"name": n, **{k: v for k, v in f.items() if k != "name"}}
            for n, f in sorted(pool.items())
        ],
        "designs": designs,
        "per_feature": per_feature,
        "totals": {
            "executions": total_exec,
            "est_minutes": round(total_min, 1),
            "est_hours": round(total_min / 60.0, 1),
            "single_config_minutes": plan_result["estimated_minutes"],
            "matrix_multiplier": round(total_min / plan_result["estimated_minutes"], 2)
            if plan_result["estimated_minutes"] else 0.0,
        },
    }


def compare(factors: Sequence[Factor], strength: int = 2) -> Dict:
    """Full factorial vs orthogonal array vs covering array, all verified."""
    full = full_factorial_size(factors)

    ca = covering_array(factors, strength=strength)
    ca_check = verify(ca, factors, strength=strength)

    oa = orthogonal_array(factors)
    oa_check = verify(oa["rows"], factors, strength=2) if oa["rows"] else None

    return {
        "factors": [{"name": n, "levels": lv, "count": len(lv)} for n, lv in factors],
        "full_factorial": full,
        "covering_array": {
            "strength": strength,
            "runs": len(ca),
            "rows": ca,
            "reduction": round(1 - len(ca) / full, 4) if full else 0.0,
            "verification": ca_check,
        },
        "orthogonal_array": {
            "runs": oa["runs"],
            "rows": oa["rows"],
            "designation": oa.get("designation", ""),
            "balanced": oa["balanced"],
            "notes": oa["notes"],
            "reduction": round(1 - oa["runs"] / full, 4) if full and oa["runs"] else 0.0,
            "verification": oa_check,
        },
    }
