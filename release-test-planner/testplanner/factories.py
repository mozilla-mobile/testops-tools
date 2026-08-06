# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Model the generated-test candidate space.

The efficiency framework does not only contain hand-written tests. Under
`generation/` there are factories that synthesise cases from the page-object
model, and they scale very differently from hand-written ones:

  interaction   one case per interactive selector per page
  behavior      capability x template x context variant
  pairs         one case per ordered page-to-page transition
  reachability  one case per reachable page

That is the explosion the planner exists to filter. A pairs factory over 51
page objects is 2,550 candidates before anyone has decided whether a single one
of them is worth running this cycle. Risk is what turns that catalogue into a
run list.

Real counts are parsed from the tree. Where the framework is still early - the
behavior capability catalog currently covers only bookmarks - the parsed number
is small and is reported as-is rather than inflated, with a projection showing
what the same machinery yields once the catalog is filled in.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List

from .coverage import _normalise

SELECTOR_RE = re.compile(r"\bSelector\s*\(")
CAPABILITY_RE = re.compile(
    r"BehaviorCapability\s*\(\s*id\s*=\s*\"([^\"]+)\"\s*,\s*"
    r"feature\s*=\s*\"([^\"]+)\"\s*,\s*"
    r"entity\s*=\s*\"([^\"]+)\"\s*,\s*"
    r"operation\s*=\s*BehaviorOperation\.(\w+)",
    re.DOTALL,
)
TEMPLATE_RE = re.compile(r"BehaviorTemplate\s*\(\s*id\s*=\s*\"([^\"]+)\"")
LIST_OF_RE = re.compile(r"val\s+(\w+)\s*=\s*listOf\(([^)]*)\)")
STRING_RE = re.compile(r"\"([^\"]*)\"")
PAGE_FIELD_RE = re.compile(r"val\s+(\w+)\s*=\s*\w+(?:Page|Component)\s*\(")


def _read(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, errors="replace") as fh:
        return fh.read()


def scan(repo_root: str, efficiency_root: str) -> Dict:
    """Parse the generation framework and quantify the candidate space."""
    eff = os.path.join(repo_root, efficiency_root)
    gen = os.path.join(eff, "generation")

    # ---- interaction factory: selectors per page -------------------------
    selectors_dir = os.path.join(eff, "selectors")
    per_page: Dict[str, int] = {}
    if os.path.isdir(selectors_dir):
        for entry in sorted(os.listdir(selectors_dir)):
            if not entry.endswith(".kt"):
                continue
            stem = entry[:-3].replace("Selectors", "")
            per_page[stem] = len(SELECTOR_RE.findall(_read(os.path.join(selectors_dir, entry))))
    total_selectors = sum(per_page.values())

    # ---- page objects ----------------------------------------------------
    page_src = _read(os.path.join(eff, "helpers", "PageContext.kt"))
    pages = [m for m in PAGE_FIELD_RE.findall(page_src)]
    page_count = len(pages)

    # ---- behavior factory ------------------------------------------------
    cap_src = _read(os.path.join(gen, "behavior", "BehaviorCapability.kt"))
    capabilities = [
        {"id": cid, "feature": feat, "entity": ent, "operation": op}
        for cid, feat, ent, op in CAPABILITY_RE.findall(cap_src)
    ]
    templates = TEMPLATE_RE.findall(
        _read(os.path.join(gen, "behavior", "BehaviorTemplate.kt"))
    )

    # ---- context matrix: the real product-state factors ------------------
    ctx_src = _read(os.path.join(gen, "behavior", "BehaviorContextMatrix.kt"))
    context_factors = []
    for var_name, body in LIST_OF_RE.findall(ctx_src):
        values = STRING_RE.findall(body)
        if len(values) < 2:
            continue
        context_factors.append(
            {
                "name": _factor_name(var_name),
                "levels": values,
                "source": "real",
                "origin": "BehaviorContextMatrix.kt::exhaustivePreview",
            }
        )

    profiles = _profile_sizes(ctx_src, context_factors)

    # ---- candidate counts ------------------------------------------------
    exhaustive_contexts = profiles.get("EXHAUSTIVE_PREVIEW", 1)
    behavior_matched = _match_capabilities_to_templates(capabilities, templates)

    factories = [
        {
            "id": "interaction",
            "name": "Interaction factory",
            "unit": "one case per interactive selector, per page",
            "candidates": total_selectors,
            "basis": "{} selectors across {} selector objects".format(
                total_selectors, len(per_page)
            ),
            "source": "parsed",
        },
        {
            "id": "reachability",
            "name": "Reachability factory",
            "unit": "one case per page reachable from the launch state",
            "candidates": page_count,
            "basis": "{} page objects on PageContext".format(page_count),
            "source": "parsed",
        },
        {
            "id": "pairs",
            "name": "Pairs factory",
            "unit": "one case per ordered page-to-page transition",
            "candidates": page_count * (page_count - 1),
            "basis": "{} pages, ordered pairs".format(page_count),
            "source": "parsed",
        },
        {
            "id": "behavior",
            "name": "Behavior factory",
            "unit": "capability x template x context variant",
            "candidates": behavior_matched * exhaustive_contexts,
            "basis": "{} capability/template matches x {} exhaustive contexts".format(
                behavior_matched, exhaustive_contexts
            ),
            "source": "parsed",
            "note": (
                "The capability catalog currently covers bookmarks only, so this "
                "is small today. Projected at one capability set per feature it "
                "is the largest factory of the four."
            ),
            "projection": _behavior_projection(templates, exhaustive_contexts),
        },
    ]

    return {
        "factories": factories,
        "total_candidates": sum(f["candidates"] for f in factories),
        "selectors_per_page": per_page,
        "page_count": page_count,
        "capabilities": capabilities,
        "capability_features": sorted({c["feature"] for c in capabilities}),
        "templates": templates,
        "context_factors": context_factors,
        "context_profiles": profiles,
    }


def _factor_name(var_name: str) -> str:
    """browserModes -> BrowserMode, deviceClasses -> DeviceClass, pocketValues -> Pocket."""
    if var_name.endswith("Values"):
        name = var_name[: -len("Values")]
    elif var_name.endswith("Classes"):
        name = var_name[: -len("es")]
    elif var_name.endswith("s"):
        name = var_name[:-1]
    else:
        name = var_name
    return name[:1].upper() + name[1:]


def _profile_sizes(src: str, factors: List[Dict]) -> Dict[str, int]:
    """Variant count per BehaviorMatrixProfile."""
    sizes = {}
    for profile, fn in [
        ("SMOKE", "smoke"),
        ("BASE_FLAGS", "baseFlags"),
        ("PAIRWISE_PREVIEW", "pairwisePreview"),
    ]:
        block = re.search(
            r"private fun {}\(\).*?(?=\n    private fun |\n\}})".format(fn),
            src,
            re.DOTALL,
        )
        sizes[profile] = len(re.findall(r"defaultContext\(", block.group(0))) if block else 0

    exhaustive = 1
    for f in factors:
        exhaustive *= len(f["levels"])
    sizes["EXHAUSTIVE_PREVIEW"] = exhaustive
    return sizes


def _match_capabilities_to_templates(capabilities: List[Dict], templates: List[str]) -> int:
    """How many (capability-set, template) pairs are actually satisfiable.

    A template needs every operation it requires to exist for the same
    feature/entity pair, so the real number is well below capabilities x
    templates.
    """
    by_entity: Dict[tuple, set] = {}
    for cap in capabilities:
        by_entity.setdefault((cap["feature"], cap["entity"]), set()).add(cap["operation"])

    matched = 0
    for ops in by_entity.values():
        for template in templates:
            required = _template_ops(template)
            if required and required <= ops:
                matched += 1
    return matched


def _template_ops(template_id: str) -> set:
    """Infer required operations from the template id."""
    ops = set()
    if "create" in template_id:
        ops.add("CREATE")
    if "delete.cancel" in template_id:
        ops.add("CANCEL_DELETE")
    elif "delete" in template_id:
        ops.add("DELETE")
    return ops


def _behavior_projection(templates: List[str], contexts: int) -> Dict:
    """What the behavior factory yields once the catalog covers more features."""
    projected_entities = 30  # stub: roughly one CRUD entity per catalogued feature
    return {
        "assumed_entities": projected_entities,
        "templates": len(templates),
        "contexts": contexts,
        "candidates": projected_entities * len(templates) * contexts,
        "source": "stubbed projection",
    }


def attribute_to_features(scan_result: Dict, catalog, risk_rows: List[Dict]) -> List[Dict]:
    """Split factory candidates across the features touched this cycle.

    Interaction, reachability and pairs candidates belong to whichever feature
    owns the page object. Behavior candidates carry their own `feature` field.
    """
    touched = {r["feature_id"]: r for r in risk_rows}

    stem_to_feature = {}
    for feature in catalog:
        for po in feature.page_objects:
            stem_to_feature[_normalise(po)] = feature.id

    per_feature: Dict[str, Dict] = {
        fid: {
            "feature_id": fid,
            "name": row["name"],
            "band": row["band"],
            "rpn": row["rpn"],
            "interaction": 0,
            "reachability": 0,
            "pairs": 0,
            "behavior": 0,
        }
        for fid, row in touched.items()
    }

    for stem, count in scan_result["selectors_per_page"].items():
        fid = stem_to_feature.get(_normalise(stem))
        if fid in per_feature:
            per_feature[fid]["interaction"] += count
            per_feature[fid]["reachability"] += 1

    page_count = scan_result["page_count"]
    for fid, entry in per_feature.items():
        # A feature's share of the pairs space is its pages against all others.
        entry["pairs"] = entry["reachability"] * (page_count - 1)

    contexts = scan_result["context_profiles"].get("EXHAUSTIVE_PREVIEW", 1)
    templates = len(scan_result["templates"])
    for cap in scan_result["capabilities"]:
        fid = cap["feature"]
        if fid in per_feature:
            per_feature[fid]["behavior"] += templates * contexts

    for entry in per_feature.values():
        entry["total"] = (
            entry["interaction"] + entry["reachability"]
            + entry["pairs"] + entry["behavior"]
        )

    return sorted(per_feature.values(), key=lambda e: e["rpn"], reverse=True)
