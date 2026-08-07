# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""The deterministic/AI boundary.

The pipeline never calls a model. Instead it emits typed questions for the
things that genuinely need judgement, each with the evidence already gathered
and a schema for the answer. An agent answers them into a JSON file, which is
fed back on the next run as overrides.

Keeping the boundary explicit means every AI-supplied number in the final report
is traceable to a question, an answer, and a rationale - which is what makes the
output defensible in a release readiness review.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

TASK_TYPES = {
    "classify-unmapped-path": {
        "why": "Unrecognised code is unquantified risk. Every changed path must "
               "land in a feature or be explicitly ruled out.",
        "answer_schema": {
            "feature_id": "existing feature id, or 'new' to propose one",
            "proposed_feature": "{id, name, severity, source_globs} if feature_id=='new'",
            "ignore": "true if this path carries no release risk",
            "rationale": "one sentence",
        },
    },
    "assess-change-semantics": {
        "why": "Relative churn cannot tell a mechanical rename from a behaviour "
               "change. The Occurrence factor is materially different for each.",
        "answer_schema": {
            "kind": "refactor | behaviour-change | new-feature | bugfix | config",
            "occurrence_delta": "integer -3..+3 adjustment to the derived Occurrence",
            "rationale": "one sentence citing the diff",
        },
    },
    "review-severity": {
        "why": "Catalog severity is a static default. A specific change may hit a "
               "more or less critical part of the feature than the average.",
        "answer_schema": {
            "severity": "integer 1-10",
            "rationale": "one sentence",
        },
    },
    "review-weak-binding": {
        "why": "A test bound by one weak signal may not actually exercise the "
               "feature. False coverage is more dangerous than no coverage.",
        "answer_schema": {
            "binding_valid": "true|false",
            "rationale": "one sentence",
        },
    },
    "author-manual-tests": {
        "why": "Residual risk after automation is the manual testing scope. This "
               "is the handoff to the human test plan.",
        "answer_schema": {
            "cases": "[{title, steps, expected, priority: P0|P1|P2, est_minutes}]",
            "rationale": "why these cases close the specific residual risk",
        },
    },
}


def _task(task_id: str, kind: str, question: str, context: Dict) -> Dict:
    spec = TASK_TYPES[kind]
    return {
        "id": task_id,
        "type": kind,
        "question": question,
        "why_this_needs_judgement": spec["why"],
        "context": context,
        "answer_schema": spec["answer_schema"],
    }


def emit(
    attribution: Dict,
    coverage: Dict,
    risk_result: Dict,
    plan_result: Dict,
    max_per_type: int = 25,
) -> Dict:
    tasks: List[Dict] = []

    for i, fc in enumerate(attribution["unmapped_files"][:max_per_type]):
        tasks.append(
            _task(
                "unmapped-{}".format(i),
                "classify-unmapped-path",
                "Which Fenix feature does '{}' belong to?".format(fc["path"]),
                {
                    "path": fc["path"],
                    "added": fc["added"],
                    "deleted": fc["deleted"],
                    "commits": fc["commits"],
                },
            )
        )

    high_churn = [
        r for r in risk_result["rows"] if r["churned_lines"] >= 100
    ][:max_per_type]
    for row in high_churn:
        tasks.append(
            _task(
                "semantics-{}".format(row["feature_id"]),
                "assess-change-semantics",
                "Is the change to '{}' a refactor or a behaviour change? "
                "Read the diff before answering.".format(row["name"]),
                {
                    "feature_id": row["feature_id"],
                    "churned_lines": row["churned_lines"],
                    "file_count": row["file_count"],
                    "commits": row["commits"],
                    "derived_occurrence": row["occurrence"],
                    "occurrence_basis": row["occurrence_basis"],
                },
            )
        )

    for row in risk_result["rows"]:
        if row["band"] == "action-required":
            tasks.append(
                _task(
                    "severity-{}".format(row["feature_id"]),
                    "review-severity",
                    "Confirm severity {} for '{}' given what actually changed."
                    .format(row["severity"], row["name"]),
                    {
                        "feature_id": row["feature_id"],
                        "catalog_severity": row["severity"],
                        "catalog_rationale": row["severity_rationale"],
                        "rpn": row["rpn"],
                    },
                )
            )

    weak = []
    for fid, entry in coverage["per_feature"].items():
        for test in entry["tests"]:
            if test["binding"] == "incidental" and not test["is_disabled"]:
                weak.append((fid, test))
    for i, (fid, test) in enumerate(weak[:max_per_type]):
        tasks.append(
            _task(
                "binding-{}".format(i),
                "review-weak-binding",
                "Does {}.{} really exercise feature '{}'? It was bound only by "
                "a shared page object.".format(test["class_name"], test["name"], fid),
                {
                    "feature_id": fid,
                    "test": "{}#{}".format(test["file"], test["name"]),
                    "surfaces": test["surfaces"],
                },
            )
        )

    for gap in plan_result["gaps"][:max_per_type]:
        tasks.append(
            _task(
                "manual-{}".format(gap["feature_id"]),
                "author-manual-tests",
                "Write manual test cases covering the residual risk in '{}'."
                .format(gap["name"]),
                {
                    "feature_id": gap["feature_id"],
                    "residual_rpn": gap["residual_rpn"],
                    "reason": gap["reason"],
                    "severity_rationale": gap["severity_rationale"],
                    "quality_attributes_at_risk": gap["iso25010"],
                    "planned_automated_tests": gap["planned_tests"],
                },
            )
        )

    by_type: Dict[str, int] = {}
    for t in tasks:
        by_type[t["type"]] = by_type.get(t["type"], 0) + 1

    return {"task_count": len(tasks), "by_type": by_type, "tasks": tasks}


def load_answers(path: str) -> Dict[str, Dict]:
    """Load agent answers keyed by task id. Missing file means no overrides."""
    if not path or not os.path.exists(path):
        return {}
    with open(path) as fh:
        data = json.load(fh)
    answers = data.get("answers", data)
    if isinstance(answers, list):
        return {a["id"]: a for a in answers if "id" in a}
    return answers


def apply_overrides(catalog, attribution: Dict, answers: Dict[str, Dict]) -> List[str]:
    """Apply agent answers to the attribution before risk is scored.

    Returns a human-readable audit trail of what the agent changed.
    """
    applied: List[str] = []
    if not answers:
        return applied

    by_feature = {b["feature_id"]: b for b in attribution["features_touched"]}

    for task_id, answer in answers.items():
        if task_id.startswith("severity-"):
            fid = task_id[len("severity-"):]
            bucket = by_feature.get(fid)
            if bucket and "severity" in answer:
                old = bucket["severity"]
                bucket["severity"] = int(answer["severity"])
                applied.append(
                    "severity[{}] {} -> {} ({})".format(
                        fid, old, answer["severity"], answer.get("rationale", "")
                    )
                )

        elif task_id.startswith("semantics-"):
            fid = task_id[len("semantics-"):]
            bucket = by_feature.get(fid)
            if bucket and "occurrence_delta" in answer:
                bucket["agent_occurrence_delta"] = int(answer["occurrence_delta"])
                bucket["agent_change_kind"] = answer.get("kind", "")
                applied.append(
                    "occurrence[{}] {:+d} ({}: {})".format(
                        fid,
                        int(answer["occurrence_delta"]),
                        answer.get("kind", "?"),
                        answer.get("rationale", ""),
                    )
                )

    return applied
