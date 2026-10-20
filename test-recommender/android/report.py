"""
Report generator for Firefox Android — the CLI that ties the pipeline together.

    python3 -m android.report --repo /path/to/firefox --from TAG --to TAG

**One LLM call, not two.** `../recommend.py` runs a rerank pass before
synthesis because it hands the model the whole candidate pool and needs it
narrowed.
Here `scorer.py` already produces a ranked list cut to `budget.py`'s range,
deterministically and with a reason per case, so the rerank stage has nothing
left to do. The model's job is to *write the report* from a decided test list —
not to decide it.

That split is deliberate: which tests to run is auditable and reproducible,
and only the prose around them is generated. It also means the whole thing
degrades cleanly — `--no-llm`, a missing API key, or an API failure all fall
back to a deterministic Markdown render of the same data.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from android import budget as bd
from android import scorer as sc
from android.build_mapping import assign_section_keys
from android.change_extractor import (
    AndroidTag, ExtractionResult, beta_pairs, enrich_with_bugzilla,
    extract_range, latest_beta, nimbus_features_changed, parse_tag,
    resolve_beta, resolve_rc,
)
from android.gecko_risk import GeckoRisk, extract_gecko_risk, summarize
from android.testrail_index import TestRailIndex, build_index

try:
    import anthropic
except ImportError:  # pragma: no cover - exercised only without the SDK
    anthropic = None


HERE = Path(__file__).parent
DEFAULT_EXPORT = HERE / "config/testrail_export_android.xlsx"
DEFAULT_MAPPING = HERE / "config/section_to_module_mapping.yaml"

# Opus 5 by default: the report is read by QA leads and drives what gets
# tested, so this is not a place to trade quality for tokens. One call per
# build, ~5 builds per cycle. Override with ANDROID_REPORT_MODEL.
LLM_MODEL = os.environ.get("ANDROID_REPORT_MODEL", "claude-opus-5")
LLM_EFFORT = os.environ.get("ANDROID_REPORT_EFFORT", "high")


# =============================================================================
# Analysis
# =============================================================================


@dataclass
class Analysis:
    """Everything the deterministic layer knows about one build."""
    base: str
    head: str
    extraction: ExtractionResult
    risk: GeckoRisk
    budget: bd.BudgetDecision
    signal: bd.BuildSignal
    nimbus_features: list[str] = field(default_factory=list)
    nimbus_slugs: list[str] = field(default_factory=list)
    exact_match_cases: set[str] = field(default_factory=set)
    priorities: dict[str, list[sc.ScoredCase]] = field(default_factory=dict)
    index: Optional[TestRailIndex] = None

    @property
    def veto(self) -> bool:
        app_changed = self.signal.app_product_files > 0
        return self.risk.vetoes_no_regression(app_changed)

    def case(self, case_id: str):
        return self.index.cases.get(case_id) if self.index else None


def analyse(repo: str, base: str, head: str,
            export: str | Path = DEFAULT_EXPORT,
            mapping_path: str | Path = DEFAULT_MAPPING,
            bugzilla: bool = True) -> Analysis:
    """Run the whole deterministic pipeline for one range.

    `bugzilla=False` skips the one network call in the pipeline. Enrichment
    only adds `component` / `severity` / `keywords` to the bug list and
    degrades to a warning on failure, so skipping it costs detail in the
    report's "what changed" section and nothing else.
    """
    extraction = extract_range(repo, base, head)
    if bugzilla:
        enrich_with_bugzilla(extraction)
    risk = extract_gecko_risk(repo, base, head)
    index = build_index(export, repo)

    ui_tests = [f.path for f in extraction.files if f.category == "test_ui"]
    exact = index.cases_for_files(ui_tests)
    features, slugs = nimbus_features_changed(repo, base, head)

    signal = bd.from_extraction(extraction, risk, len(exact))
    decision = bd.compute_budget(signal)

    mapping = yaml.safe_load(Path(mapping_path).read_text(encoding="utf-8"))
    ctx = sc.build_context(
        mapping,
        changed_paths=[f.path for f in extraction.signal_files],
        exact_match_cases=exact,
        nimbus_features=features,
        engine_hints=risk.section_hints,
    )
    keys = assign_section_keys(list(index.cases.values()))
    ranked = sc.rank_cases(
        [(index.cases[cid], keys[cid]) for cid in keys], ctx)
    priorities = sc.split_priorities(ranked, decision.final_lo, decision.final_hi)

    return Analysis(
        base=base, head=head, extraction=extraction, risk=risk,
        budget=decision, signal=signal, nimbus_features=features,
        nimbus_slugs=slugs, exact_match_cases=exact,
        priorities=priorities, index=index,
    )


# =============================================================================
# Prompt payload
# =============================================================================


def _cases_payload(analysis: Analysis, bucket: str) -> list[dict]:
    out = []
    for scored in analysis.priorities.get(bucket, []):
        case = analysis.case(scored.case_id)
        if not case:
            continue
        out.append({
            "case_id": f"C{case.case_id}",
            "title": case.title,
            "section": scored.section,
            "automation": case.automation,
            "priority": case.priority,
            "score": scored.score,
            "why": scored.reasons,
        })
    return out


def build_payload(analysis: Analysis) -> dict:
    """The JSON handed to the model. Facts only — no prose, no prioritisation
    left to decide."""
    extraction = analysis.extraction
    risk = analysis.risk
    categories = extraction.counts_by_category()

    bugs = []
    for bug in extraction.bugs[:25]:
        bugs.append({
            "bug": bug.bug_id,
            "title": bug.title,
            "lines": f"+{bug.additions}/-{bug.deletions}",
            "component": bug.component,
            "severity": bug.severity,
            "keywords": bug.keywords,
            "phabricator": bug.phab_revisions,
            "touches_ui_tests": bug.touches_ui_tests,
            "files": [f.path for f in bug.product_files][:8],
        })

    return {
        "range": {"base": analysis.base, "head": analysis.head},
        "change_profile": {
            "files_total": len(extraction.files),
            "files_by_category": categories,
            "app_product_files": analysis.signal.app_product_files,
            "bugs": len(extraction.bugs),
            "backout_in_range": analysis.signal.has_backout,
        },
        "budget": {
            "tier": analysis.budget.tier,
            "low": analysis.budget.final_lo,
            "high": analysis.budget.final_hi,
            "rationale": analysis.budget.summary_line(),
        },
        "bugs": bugs,
        "nimbus": {
            "changed": analysis.signal.nimbus_changed,
            "feature_ids": analysis.nimbus_features,
            "experiment_slugs": analysis.nimbus_slugs,
        },
        "engine": {
            "summary": summarize(risk),
            "is_material": risk.is_material,
            "product_files": risk.product_file_count,
            "product_lines": risk.product_churn,
            "areas": [
                {"area": a.name, "files": len(a.product_files),
                 "lines": a.product_churn}
                for a in risk.top_areas(8) if a.product_files
            ],
            "remote_settings_collections": risk.notable_collections,
            "generated_data_refreshed": [
                f.rsplit("/", 1)[-1] for f in risk.generated_data_files],
            "exploratory_hints": risk.section_hints,
            "vetoes_no_regression_claim": analysis.veto,
        },
        "exact_match_cases": sorted(f"C{c}" for c in analysis.exact_match_cases),
        "suggested_tests": {
            "P0": _cases_payload(analysis, "P0"),
            "P1": _cases_payload(analysis, "P1"),
            "P2": _cases_payload(analysis, "P2"),
        },
        "warnings": extraction.warnings,
        "index_drift": {
            "stale_declared_tests": len(analysis.index.drift.stale_declared),
            "orphan_links": len(analysis.index.drift.orphan_links),
            "malformed_methods": [
                p for p, _ in analysis.index.drift.malformed_methods],
        } if analysis.index else {},
    }


SYSTEM_PROMPT = """\
You are writing a QA regression report for a single Firefox Android build. \
The reader is a QA lead deciding what to test before the build ships.

The test list has already been decided. A deterministic scorer ranked every \
TestRail case against this build's diff and cut the list to a computed budget; \
P0/P1/P2 arrive settled, each case carrying the reasons it was selected. Do \
not re-rank, drop, or add cases. Your job is the prose around them: explain \
what changed, what it threatens, and where judgement is needed.

Context that shapes every Android report:

- Firefox Android embeds GeckoView, built from the same monorepo, so the \
engine ships with every build. A large share of ranges change no Kotlin \
product code at all — for those the engine and Nimbus are the whole story, and \
a report that concludes "nothing to test" is wrong.
- `vetoes_no_regression_claim: true` means the app diff is quiet but the \
engine moved. You must not state or imply that no regression testing is needed.
- Engine data is area-level only. Say "DOM and layout moved, focus exploratory \
testing on page rendering"; never claim a specific engine change maps to a \
specific manual case.
- Nimbus experiments change behaviour with no code diff and often target new \
users only, so they will not reproduce on an upgraded profile. Say so when one \
is present.
- Exact-match cases are linked from an instrumented test that changed in this \
range. That is a fact from a source comment, not an inference — flag them as \
the highest-confidence items.

Write GitHub-flavoured Markdown with these sections, in order:

1. `## Executive summary` — 3-5 sentences. Lead with the shape of the build \
(what actually changed), then the single biggest risk.
2. `## What changed` — app side and engine side as separate subsections. Use \
the bug list; name Bugzilla components when present. Be concrete about counts.
3. `## Suggested manual tests` — P0/P1/P2 as Markdown tables with columns \
Case / Section / Title. Reproduce every case given, unchanged. Above each \
table, one or two sentences on what that tranche is probing. If a tranche is \
empty, say so instead of inventing entries.
4. `## Risks` — backouts, uplifts, Nimbus, out-of-band Remote Settings, \
dependency bumps. Each as a short named paragraph. Omit the section if the \
data shows none.
5. `## Exploratory focus` — a short ordered list, weighted by where the \
engine actually moved.
6. `## Caveats` — what this report cannot tell you. Draw from the warnings \
and index drift in the data. Be specific and honest; do not pad.

Rules:

- Every number you state must come from the supplied data. Do not estimate, \
extrapolate, or invent counts, file names, bug numbers, or case IDs.
- No preamble, no closing pleasantries. Start at the first heading.
- Prefer plain declarative sentences. No marketing tone, no "comprehensive" or \
"robust".
- When the data is thin, a short report is the correct output. Do not pad to \
look thorough.
"""


# =============================================================================
# Rendering
# =============================================================================


def _table(analysis: Analysis, bucket: str) -> list[str]:
    rows = analysis.priorities.get(bucket, [])
    if not rows:
        return [f"_No {bucket} cases._", ""]
    out = ["| Case | Section | Title |", "|---|---|---|"]
    for scored in rows:
        case = analysis.case(scored.case_id)
        if not case:
            continue
        title = case.title.replace("|", "\\|")
        out.append(f"| C{case.case_id} | {scored.section} | {title} |")
    out.append("")
    return out


def render_deterministic(analysis: Analysis) -> str:
    """Markdown from the data alone — no LLM.

    Not a degraded mode so much as the auditable one: every number here is
    computed, and the report is identical on every run for a given range.
    """
    extraction = analysis.extraction
    risk = analysis.risk
    categories = extraction.counts_by_category()

    out = [
        f"# Firefox Android — {analysis.base} → {analysis.head}",
        "",
        f"- Budget tier: **{analysis.budget.tier}**",
        f"- {analysis.budget.summary_line()}",
        f"- Files changed: {len(extraction.files)} "
        f"({analysis.signal.app_product_files} Kotlin product)",
        f"- Bugs: {len(extraction.bugs)}",
        "",
    ]
    if analysis.veto:
        out += [
            "> **The app diff is quiet but the engine moved.** This build still "
            "needs functional regression; see the engine section.", "",
        ]

    out += ["## What changed", "", "### App", ""]
    if not extraction.bugs:
        out.append("_No attributable app changes._")
    for bug in extraction.bugs[:15]:
        label = f"Bug {bug.bug_id}" if bug.bug_id else "No bug"
        component = f" [{bug.component}]" if bug.component else ""
        out.append(f"- **{label}**{component} +{bug.additions}/-{bug.deletions} "
                   f"— {bug.title}")
    out += ["", f"Categories: `{categories}`", ""]

    if analysis.nimbus_features:
        out += [
            "### Nimbus", "",
            f"- Feature IDs: {', '.join(analysis.nimbus_features)}",
            f"- Experiments: {', '.join(analysis.nimbus_slugs)}",
            "- Experiments often target new users only and will not reproduce "
            "on an upgraded profile.",
            "",
        ]

    out += ["### Engine", "", summarize(risk), ""]
    if risk.areas:
        out += ["| Area | Files | Lines |", "|---|---|---|"]
        out += [f"| {a.name} | {len(a.product_files)} | {a.product_churn} |"
                for a in risk.top_areas(8) if a.product_files]
        out.append("")

    out += ["## Suggested manual tests", ""]
    for bucket in ("P0", "P1", "P2"):
        out += [f"### {bucket}", ""] + _table(analysis, bucket)

    if extraction.warnings or (analysis.index and not analysis.index.drift.is_clean):
        out += ["## Caveats", ""]
        for warning in extraction.warnings:
            out.append(f"- {warning}")
        if analysis.index:
            drift = analysis.index.drift
            if drift.stale_declared:
                out.append(f"- {len(drift.stale_declared)} stale "
                           f"`Automated Test Name(s)` entries in TestRail.")
            if drift.malformed_methods:
                out.append(f"- {len(drift.malformed_methods)} unparseable "
                           f"`@Test` declaration(s) in the working tree; any "
                           f"TestRail links they carried were dropped.")
        out.append("")

    out.append(f"_Generated by android/report.py (deterministic mode) on "
               f"{datetime.date.today().isoformat()}._")
    return "\n".join(out)


def synthesize(analysis: Analysis, model: str = LLM_MODEL) -> str:
    """Write the report with the LLM, falling back to the deterministic render.

    Streaming because the report can run long and `max_tokens` is high;
    adaptive thinking because choosing what to say about a diff is exactly the
    kind of judgement it helps with. The system prompt is cached — it is
    identical across every build.
    """
    if anthropic is None:
        sys.stderr.write("[report] anthropic SDK not installed; "
                         "falling back to deterministic render\n")
        return render_deterministic(analysis)

    payload = build_payload(analysis)
    user_text = (
        "Write the QA report for this build, following the section structure "
        "in the system prompt exactly.\n\n"
        "## Build data (JSON)\n"
        f"```json\n{json.dumps(payload, separators=(',', ':'), default=str)}\n```"
    )

    try:
        client = anthropic.Anthropic(max_retries=6)
        with client.messages.stream(
            model=model,
            max_tokens=64000,
            thinking={"type": "adaptive"},
            output_config={"effort": LLM_EFFORT},
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            final = stream.get_final_message()
    except Exception as e:  # noqa: BLE001 - any failure degrades, never aborts
        sys.stderr.write(f"[report] LLM synthesis failed ({e}); "
                         f"falling back to deterministic render\n")
        return render_deterministic(analysis)

    if final.stop_reason == "refusal":
        sys.stderr.write("[report] model declined; falling back\n")
        return render_deterministic(analysis)

    text = "\n".join(b.text for b in final.content if b.type == "text").strip()
    if not text:
        return render_deterministic(analysis)

    usage = final.usage
    return text + (
        f"\n\n---\n_Generated by `android/report.py` on "
        f"{datetime.date.today().isoformat()} — model {model}, effort "
        f"{LLM_EFFORT}. Test selection is deterministic "
        f"(`budget.py` + `scorer.py`); only the prose is generated. "
        f"Tokens: {usage.input_tokens} in / {usage.output_tokens} out._\n"
    )


# =============================================================================
# CLI
# =============================================================================


def resolve_range(repo: str, args) -> tuple[str, str]:
    """Turn CLI arguments into a (base, head) tag pair."""
    if args.from_tag and args.to_tag:
        for tag in (args.from_tag, args.to_tag):
            if parse_tag(tag) is None:
                sys.stderr.write(
                    f"[report] warning: '{tag}' is not a Firefox Android "
                    f"release tag; using it verbatim\n")
        return args.from_tag, args.to_tag

    if args.cycle is None:
        raise SystemExit("Provide either --from/--to or --cycle.")

    if args.rc:
        last, rc = latest_beta(repo, args.cycle), resolve_rc(repo, args.cycle)
        if not (last and rc):
            raise SystemExit(
                f"Cycle {args.cycle}: no final beta / RC pair in this checkout. "
                f"Fetch, or pass --from/--to.")
        return last.raw, rc.raw

    pairs = beta_pairs(repo, args.cycle)
    if not pairs:
        raise SystemExit(
            f"Cycle {args.cycle}: fewer than two betas in this checkout, so "
            f"there is no beta-to-beta range yet. Fetch, or pass --from/--to.")
    if args.beta is not None:
        for a, b in pairs:
            if a.beta == args.beta:
                return a.raw, b.raw
        raise SystemExit(
            f"Cycle {args.cycle}: no range starting at b{args.beta}. "
            f"Available: {', '.join(f'b{a.beta}' for a, _ in pairs)}")
    a, b = pairs[-1]
    return a.raw, b.raw


def default_output_name(base: str, head: str) -> str:
    """`release_report_*.md` so it lands under the same gitignore rule as the
    iOS reports."""
    def short(tag: str) -> str:
        parsed = parse_tag(tag)
        if not parsed:
            return tag
        version = f"{parsed.major}.0"
        if parsed.beta:
            version += f"b{parsed.beta}"
        if parsed.patch:
            version += f".{parsed.patch}"
        if parsed.build:
            version += f"-build{parsed.build}"
        return version
    return f"release_report_android-{short(base)}_to_{short(head)}.md"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a QA regression report for a Firefox Android build.")
    parser.add_argument("--repo", required=True,
                        help="path to a mozilla-firefox/firefox checkout")
    parser.add_argument("--from", dest="from_tag", help="base tag")
    parser.add_argument("--to", dest="to_tag", help="head tag")
    parser.add_argument("--cycle", type=int,
                        help="resolve tags for this major version instead")
    parser.add_argument("--beta", type=int,
                        help="with --cycle: start the range at this beta "
                             "(default: the most recent pair)")
    parser.add_argument("--rc", action="store_true",
                        help="with --cycle: compare the final beta to the RC")
    parser.add_argument("--export", default=str(DEFAULT_EXPORT))
    parser.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    parser.add_argument("--out", help="output path (default: derived from tags)")
    parser.add_argument("--stdout", action="store_true",
                        help="write to stdout instead of a file")
    parser.add_argument("--no-llm", action="store_true",
                        help="deterministic render only; no API call")
    parser.add_argument("--no-bugzilla", action="store_true",
                        help="skip Bugzilla enrichment (component/severity)")
    parser.add_argument("--model", default=LLM_MODEL)
    args = parser.parse_args(argv)

    base, head = resolve_range(args.repo, args)
    sys.stderr.write(f"[report] {base} -> {head}\n")

    analysis = analyse(args.repo, base, head, args.export, args.mapping,
                       bugzilla=not args.no_bugzilla)
    sys.stderr.write(
        f"[report] tier={analysis.budget.tier} "
        f"budget={analysis.budget.final_lo}-{analysis.budget.final_hi} "
        f"P0={len(analysis.priorities.get('P0', []))} "
        f"P1={len(analysis.priorities.get('P1', []))} "
        f"P2={len(analysis.priorities.get('P2', []))}\n")

    report = (render_deterministic(analysis) if args.no_llm
              else synthesize(analysis, args.model))

    if args.stdout:
        print(report)
        return 0
    out = Path(args.out) if args.out else HERE / default_output_name(base, head)
    out.write_text(report, encoding="utf-8")
    sys.stderr.write(f"[report] wrote {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
