#!/usr/bin/env python3
"""Triage TestRail cases for XCUITest automation suitability.

Companion to ``testrail_import.py`` and ``testrail_fetch_section.py``, split
the same way the other agents are: this script does the deterministic TestRail
I/O, and the ``automation-triager`` agent does the judgement. It never decides
suitability by itself.

All TestRail access goes through the shared ``testrail_client`` layer - the
same authenticated client, configuration loader, section helpers and
custom-field resolution the import and fetch scripts use:

    agent -> testrail_triage_automation -> testrail_client -> TestRail API

Every run targets one explicitly chosen TestRail project. There is no default:
`--project` is required, and the agent must ask the user which project to use
before any section lookup or case read. The ids come from that project's own
environment variables, never from a literal in this file.

    --project 1 | firefox-ios     Firefox for iOS - the PRODUCTION project.
                                  Reads TESTRAIL_iOS_PROJECT_ID and
                                  TESTRAIL_iOS_FULL_SUITE_ID. Writing to it also
                                  requires --confirm-firefox-ios, which the
                                  agent may pass only after the user has
                                  explicitly confirmed the run.
    --project 2 | temp-approvals  [TEMP] iOS test project for TC approvals.
                                  Reads TESTRAIL_TMP_PROJECT_ID and
                                  TESTRAIL_TMP_SUITE_ID.

Three subcommands:

    projects  Prints the project selection prompt, verbatim, for the agent to
              show the user. The single source of truth for that wording.

    fetch   Read-only. Prints every case in the requested section (and its
            sub-sections) whose Automation status is "Untriaged", in full
            (title, section path, preconditions, steps, expected results, refs,
            labels), plus a pointer to the XCUITest repo the agent must
            inspect. Writes nothing, changes nothing.

    apply   Takes the agent's decisions file and updates TestRail. This
            performs real writes: for every case still Untriaged, the
            Automation status is set to Suitable or Unsuitable - no label is
            ever set - and each update is re-read afterwards to confirm
            TestRail actually persisted it. Pass --dry-run to analyse and
            print the proposed changes without writing anything.

Both commands are scoped to a single section of the chosen project, named or
given by id when the agent is triggered. A run can never reach cases outside
it, and never touches the project that was not selected.

Usage:
    python3 scripts/testrail_triage_automation.py projects
    python3 scripts/testrail_triage_automation.py fetch "<section>" --project 2 [--limit N] [--json]
    python3 scripts/testrail_triage_automation.py apply "<section>" decisions.json --project 2
    python3 scripts/testrail_triage_automation.py apply "<section>" decisions.json --project 2 --dry-run
    python3 scripts/testrail_triage_automation.py apply "<section>" decisions.json --project 1 --confirm-firefox-ios

Decisions file - a JSON list (or {"decisions": [...]}):

    [
      {"case_id": 4230470, "decision": "suitable",
       "reason": "MainMenuScreen + MainMenuSelectors already cover navigation; ..."},
      {"case_id": 4230471, "decision": "unsuitable",
       "reason": "Expected result is a system share-sheet handoff to a third-party app ..."}
    ]

Configuration comes from the same environment as the other scripts (a local
.env is loaded automatically). Nothing is hardcoded:

    TESTRAIL_URL, TESTRAIL_USER, TESTRAIL_API_KEY   (required)
    XCUITEST_REPO_PATH                              (required - the repo to analyse)

    TESTRAIL_iOS_PROJECT_ID, TESTRAIL_iOS_FULL_SUITE_ID (required for --project 1)
    TESTRAIL_TMP_PROJECT_ID, TESTRAIL_TMP_SUITE_ID          (required for --project 2)

    TESTRAIL_AUTOMATION_STATUS_FIELD = custom_automation_status   (optional)

Only the selected project's pair is read; if either variable is missing or not
an integer the run stops and says so rather than falling back to the other
project. The custom field id and its option ids ("Untriaged"/"Suitable"/
"Unsuitable") are resolved from TestRail metadata at runtime. The API key is
never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from testrail_client import (  # noqa: E402  (path set above)
    CONFIRM_FLAG,
    OUTPUT_ROOT,
    PROJECT_VALUES,
    AutomationField,
    Config,
    ProjectChoice,
    ProjectTarget,
    SectionSubtree,
    TestRailClient,
    TestRailError,
    build_automation_update,
    case_view,
    html_to_text,
    load_config,
    md_fields,
    md_table,
    norm,
    project_banner,
    project_menu,
    project_target,
    resolve_project_choice,
    resolve_automation_field,
    run_cli,
    section_subtree,
    verify_project_target,
    write_report,
)

REPORT_DIR = OUTPUT_ROOT / "automation-triage"

AUTOMATION_FIELD_ENV = "TESTRAIL_AUTOMATION_STATUS_FIELD"
DEFAULT_AUTOMATION_FIELD = "custom_automation_status"
REPO_PATH_ENV = "XCUITEST_REPO_PATH"

STATUS_UNTRIAGED = "Untriaged"
STATUS_SUITABLE = "Suitable"
STATUS_UNSUITABLE = "Unsuitable"
REQUIRED_STATUSES = (STATUS_UNTRIAGED, STATUS_SUITABLE, STATUS_UNSUITABLE)

DECISION_TO_STATUS = {
    "suitable": STATUS_SUITABLE,
    "unsuitable": STATUS_UNSUITABLE,
}

# A decision has to carry a technical reason. This is the floor, not the bar -
# the skill defines what a good reason looks like.
MIN_REASON_CHARS = 25


class TriageError(TestRailError):
    """Raised for triage-specific configuration and input problems."""


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

@dataclass
class TriageConfig:
    """The shared TestRail Config and project target, plus what triage adds."""

    base: Config
    target: ProjectTarget
    repo_path: Path
    automation_field: str

    @property
    def project(self) -> ProjectChoice:
        return self.target.choice

    @property
    def project_id(self) -> int:
        return self.target.project_id

    @property
    def suite_id(self) -> int:
        return self.target.suite_id


def load_triage_config(project: str) -> TriageConfig:
    """Reuse the shared loader and project resolution, then add what triage needs.

    The target project is the one the user chose - resolved from that project's
    own environment variables, so a run can never drift into the other project.
    Fails with an actionable message rather than falling back to a default for
    anything that would silently point the run at the wrong project or repo.
    """
    # require_target=False: project and suite come from the chosen project's
    # own variables, not from TESTRAIL_TMP_PROJECT_ID unconditionally.
    base = load_config(require_target=False)   # raises for URL / credentials
    target = project_target(resolve_project_choice(project))
    base.project_id = target.project_id
    base.suite_id = target.suite_id

    raw_repo = (os.getenv(REPO_PATH_ENV) or "").strip()
    if not raw_repo:
        raise TriageError(
            f"Missing required environment variable: {REPO_PATH_ENV}. "
            "Set it to the local XCUITest checkout to analyse, e.g. "
            f"{REPO_PATH_ENV}=/path/to/firefox-ios (add it to .env)."
        )
    repo_path = Path(raw_repo).expanduser()
    if not repo_path.is_dir():
        raise TriageError(
            f"{REPO_PATH_ENV} points at '{repo_path}', which is not a directory. "
            "Point it at the root of the XCUITest checkout."
        )

    return TriageConfig(
        base=base,
        target=target,
        repo_path=repo_path,
        automation_field=(os.getenv(AUTOMATION_FIELD_ENV)
                          or DEFAULT_AUTOMATION_FIELD).strip(),
    )


def find_xcuitest_root(repo_path: Path) -> Path | None:
    """Best-effort location of the XCUITest target inside the checkout."""
    for candidate in sorted(repo_path.glob("**/XCUITests")):
        if candidate.is_dir():
            return candidate
    return None


def automation_field_for(config: TriageConfig, client: TestRailClient) -> AutomationField:
    """Resolve the Automation status field via the shared resolver."""
    return resolve_automation_field(
        client.get_case_fields(),
        config.project_id,
        config.automation_field,
        required_statuses=REQUIRED_STATUSES,
    )


# --------------------------------------------------------------------------- #
# Section scope
# --------------------------------------------------------------------------- #

def resolve_section_scope(client: TestRailClient, config: TriageConfig,
                          wanted: str) -> SectionSubtree:
    """The section this run is limited to, plus its sub-sections.

    Triage is always scoped to one section - never the whole suite - so a run
    can never reach cases the user did not ask for.
    """
    return section_subtree(client, config.suite_id, wanted)


def cases_with_status(client: TestRailClient, config: TriageConfig,
                      automation: AutomationField, scope: SectionSubtree,
                      status: str) -> list[dict]:
    """Cases inside the requested section whose Automation status is `status`.

    A case with the field unset matches nothing - 'unset' is not a status.
    One listing call for the suite, filtered locally against the section set -
    cheaper than one get_cases call per sub-section.
    """
    automation.id_for(status)      # raises if the status is not a real option
    return [
        case
        for case in client.get_cases(config.suite_id)
        if scope.contains(case) and automation.has_status(case, status)
    ]


# --------------------------------------------------------------------------- #
# Fetch (read-only)
# --------------------------------------------------------------------------- #

def run_projects(_args) -> int:
    """Print the project selection prompt the agents must show the user."""
    print(project_menu())
    return 0


def run_fetch(args) -> int:
    config = load_triage_config(args.project)
    client = TestRailClient(config.base)
    project_name, suite_name = verify_project_target(client, config.target)
    automation = automation_field_for(config, client)
    scope = resolve_section_scope(client, config, args.section)
    status = getattr(args, "status", None) or STATUS_UNTRIAGED

    cases = cases_with_status(client, config, automation, scope, status)
    if args.limit:
        cases = cases[: args.limit]

    views = [case_view(c, client, config.base, config.suite_id) for c in cases]

    if args.json:
        print(json.dumps(
            {
                "project": config.project.key,
                "project_name": config.project.name,
                "project_url": config.project.url,
                "project_protected": config.project.protected,
                "project_id": config.project_id,
                "suite_id": config.suite_id,
                "section": scope.path,
                "section_id": scope.id,
                "repo_path": str(config.repo_path),
                "xcuitest_root": str(find_xcuitest_root(config.repo_path) or ""),
                "automation_field": automation.system_name,
                "status": status,
                "count": len(views),
                "cases": [v.as_dict() for v in views],
            },
            indent=2,
        ))
        return 0

    xcuitest_root = find_xcuitest_root(config.repo_path)
    print("\n".join(project_banner(config.target, project_name, suite_name)))
    print(f"# {status} cases")
    print(f"# Section: {scope.path} (id {scope.id}, "
          f"{len(scope.section_ids)} section(s) including sub-sections)")
    print(f"# Automation field: {automation.system_name} "
          f"({status}={automation.id_for(status)})")
    print(f"# Repo to analyse: {config.repo_path}")
    print(f"# XCUITest target: {xcuitest_root or '(not found - inspect the repo manually)'}")
    print(f"# {len(views)} {status.lower()} case(s)")
    for view in views:
        print("\n" + "\n".join(view.text_lines()))
    if not views:
        print(f"\n! No {status} cases in section '{scope.name}'.", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# Decisions
# --------------------------------------------------------------------------- #

@dataclass
class Decision:
    case_id: int
    decision: str          # "suitable" | "unsuitable"
    reason: str

    @property
    def target_status(self) -> str:
        return DECISION_TO_STATUS[self.decision]


def load_decisions(path: Path) -> list[Decision]:
    if not path.is_file():
        raise TriageError(f"Decisions file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TriageError(f"Decisions file is not valid JSON: {exc}") from exc

    entries = raw.get("decisions") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise TriageError(
            "Decisions file must be a JSON list, or an object with a 'decisions' list."
        )
    if not entries:
        raise TriageError("Decisions file contains no decisions.")

    decisions: list[Decision] = []
    seen: set[int] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise TriageError(f"Decision #{index} is not an object.")
        try:
            case_id = int(entry.get("case_id"))
        except (TypeError, ValueError) as exc:
            raise TriageError(f"Decision #{index} has a missing/invalid 'case_id'.") from exc
        if case_id in seen:
            raise TriageError(f"Decisions file lists case {case_id} more than once.")
        seen.add(case_id)

        verdict = str(entry.get("decision") or "").strip().lower()
        if verdict not in DECISION_TO_STATUS:
            raise TriageError(
                f"Decision for case {case_id} must be 'suitable' or 'unsuitable', "
                f"got {entry.get('decision')!r}."
            )
        reason = norm(str(entry.get("reason") or ""))
        if len(reason) < MIN_REASON_CHARS:
            raise TriageError(
                f"Decision for case {case_id} needs a concrete technical reason "
                f"(at least {MIN_REASON_CHARS} characters). Got: {reason!r}"
            )
        decisions.append(Decision(case_id=case_id, decision=verdict, reason=reason))
    return decisions


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #

@dataclass
class CaseOutcome:
    case_id: int
    title: str = ""
    decision: str = ""
    reason: str = ""
    result: str = ""          # updated | would-update | skipped | failed
    status_change: str = ""
    detail: str = ""

    @property
    def status_label(self) -> str:
        """The single line the report and summary key off.

        One of: '<DECISION> + UPDATED', '<DECISION> + WOULD UPDATE (dry run)',
        'SKIPPED' or 'FAILED'.
        """
        verdict = self.decision.upper() or "UNCLASSIFIED"
        if self.result == "updated":
            return f"{verdict} + UPDATED"
        if self.result == "would-update":
            return f"{verdict} + WOULD UPDATE (dry run)"
        if self.result == "skipped":
            return "SKIPPED"
        if self.result == "failed":
            return "FAILED"
        return self.result.upper()


@dataclass
class TriageSummary:
    discovered: int = 0
    analyzed: int = 0
    suitable: int = 0
    unsuitable: int = 0
    skipped: int = 0
    failed: int = 0
    updated: int = 0
    dry_run: bool = True
    section: str = ""
    outcomes: list[CaseOutcome] = dc_field(default_factory=list)


def apply_decision(client: TestRailClient, case: dict, decision: Decision,
                   automation: AutomationField,
                   dry_run: bool) -> tuple[str, str, str]:
    """Persist one decision.

    Returns (result, status_change, detail). The payload carries the Automation
    status and nothing else - no label is ever set. Unless dry_run is set, the
    update is written and then re-read, so "updated" means TestRail confirmed
    the new value rather than merely accepting the request.
    """
    payload, status_change = build_automation_update(
        case, automation, decision.target_status
    )

    if not payload:
        return "skipped", status_change, (
            "Already in the target state; no update sent."
        )
    if dry_run:
        return "would-update", status_change, ""

    client.update_case(decision.case_id, payload)

    # Confirm persistence instead of trusting the 200.
    stored = client.get_case(decision.case_id)
    if not automation.has_status(stored, decision.target_status):
        actual = automation.status_of(stored) or "unset"
        raise TriageError(
            f"Update was accepted but TestRail still reports Automation "
            f"'{actual}' instead of '{decision.target_status}'."
        )
    return "updated", status_change, ""


def print_outcome(outcome: CaseOutcome) -> None:
    print(f"\nTestRail Case: C{outcome.case_id}")
    print(f"Title: {outcome.title}")
    if outcome.decision:
        print(f"Decision: {outcome.decision.upper()}")
        print(f"Reason: {outcome.reason}")
    print(f"Result: {outcome.status_label}"
          + (f" - {outcome.detail}" if outcome.detail else ""))
    if outcome.result in {"updated", "would-update"}:
        print("TestRail changes:")
        if outcome.status_change:
            print(f"  Automation Status: {outcome.status_change}")
        else:
            print("  (none - already in the target state)")
        if outcome.result == "updated":
            print("  [persisted and verified in TestRail]")


def write_triage_report(summary: TriageSummary, config: TriageConfig,
                        report_path: Path) -> Path:
    """The triage report, built from the shared markdown helpers."""
    updated_label = ("Would update (dry run)" if summary.dry_run
                     else "Successfully updated in TestRail")
    lines = ["# XCUITest Automation Triage Report", ""]
    lines += md_fields([
        ("TestRail URL", config.base.url),
        ("Project", f"{config.project.label} - id {config.project_id} "
                    f"(from {config.project.project_env})"),
        ("Project overview", config.project.url),
        ("Suite", f"{config.suite_id} (from {config.project.suite_env})"),
        ("Section", summary.section or "(all)"),
        ("Repo analysed", config.repo_path),
        ("Run date", datetime.now().astimezone().isoformat(timespec="seconds")),
        ("Mode", "DRY-RUN (no TestRail writes)" if summary.dry_run else "LIVE"),
    ])
    lines.append("")

    if config.project.protected:
        written = ("Nothing was written (dry run)." if summary.dry_run
                   else "The writes below were explicitly confirmed by the user.")
        lines += [
            f"> \u26a0\ufe0f This run targeted **{config.project.name}**, the "
            f"production project. {written}",
            "",
        ]

    lines += ["## Summary", ""]
    lines += md_table(["Metric", "Count"], [
        ["Untriaged cases discovered", summary.discovered],
        ["Analyzed", summary.analyzed],
        ["Suitable", summary.suitable],
        ["Unsuitable", summary.unsuitable],
        [updated_label, summary.updated],
        ["Skipped", summary.skipped],
        ["Failed updates", summary.failed],
    ], aligns="lr")

    lines += ["", "## Decisions", ""]
    lines += md_table(
        ["Case", "Title", "Result", "Changes", "Reason"],
        [
            [f"C{o.case_id}", o.title, o.status_label,
             o.status_change or "-", o.reason or o.detail]
            for o in summary.outcomes
        ],
        aligns="rllll",
    )
    return write_report(report_path, lines)


def require_write_confirmation(choice: ProjectChoice, dry_run: bool,
                               confirmed: bool) -> None:
    """Gate writes to the protected project behind an explicit confirmation.

    Checked before anything else, so an unconfirmed production run stops at the
    gate rather than after touching the API. The agent may only pass the flag
    once the user has confirmed this specific run in words. A dry run writes
    nothing, so it needs no confirmation.
    """
    if dry_run or not choice.protected or confirmed:
        return
    raise TriageError(
        f"'{choice.name}' is the production TestRail project ({choice.url}) and "
        f"this run would modify its test cases. Confirm with the user what will "
        f"change, then re-run with {CONFIRM_FLAG}. Switching to another project "
        "instead is never the right fix."
    )


def run_apply(args) -> int:
    dry_run = bool(getattr(args, "dry_run", False))
    require_write_confirmation(
        resolve_project_choice(args.project), dry_run,
        bool(getattr(args, "confirm_firefox_ios", False)),
    )

    config = load_triage_config(args.project)
    decisions = load_decisions(Path(args.decisions))

    client = TestRailClient(config.base)
    project_name, suite_name = verify_project_target(client, config.target)
    automation = automation_field_for(config, client)
    scope = resolve_section_scope(client, config, args.section)

    # One listing call; the pre-update re-check below is per case and fresh.
    discovered = cases_with_status(client, config, automation, scope,
                                   STATUS_UNTRIAGED)
    discovered_ids = {int(c["id"]) for c in discovered}

    summary = TriageSummary(discovered=len(discovered), dry_run=dry_run,
                            section=scope.path)

    banner = ("DRY-RUN - no TestRail writes" if dry_run
              else "LIVE - TestRail will be updated")
    print(f"# XCUITest automation triage | {banner}")
    print("\n".join(project_banner(config.target, project_name, suite_name)))
    print(f"# Section: {scope.path} (id {scope.id})")
    print(f"# {len(discovered)} untriaged case(s) discovered, "
          f"{len(decisions)} decision(s) supplied")

    for decision in decisions:
        outcome = CaseOutcome(
            case_id=decision.case_id,
            decision=decision.decision,
            reason=decision.reason,
        )
        try:
            # Re-read the case: another user or process may have moved it out of
            # Untriaged while the agent was analysing the repo.
            case = client.get_case(decision.case_id)
            outcome.title = html_to_text(str(case.get("title") or ""))
            summary.analyzed += 1

            if not automation.has_status(case, STATUS_UNTRIAGED):
                current = automation.status_of(case) or "unset"
                outcome.result = "skipped"
                outcome.detail = (
                    f"Automation status is '{current}', no longer Untriaged. "
                    "Left unchanged."
                )
                summary.skipped += 1
                print_outcome(outcome)
                summary.outcomes.append(outcome)
                continue

            if decision.case_id not in discovered_ids:
                outcome.result = "skipped"
                outcome.detail = (
                    f"Case is outside the requested section '{scope.name}' "
                    f"(suite {config.suite_id}). Left unchanged."
                )
                summary.skipped += 1
                print_outcome(outcome)
                summary.outcomes.append(outcome)
                continue

            if decision.decision == "suitable":
                summary.suitable += 1
            else:
                summary.unsuitable += 1

            (outcome.result, outcome.status_change,
             outcome.detail) = apply_decision(
                client, case, decision, automation, dry_run,
            )
            if outcome.result == "updated":
                summary.updated += 1
            elif outcome.result == "skipped":
                summary.skipped += 1

        except Exception as exc:  # noqa: BLE001 - one bad case must not stop the batch
            outcome.result = "failed"
            outcome.detail = str(exc)
            summary.failed += 1

        print_outcome(outcome)
        summary.outcomes.append(outcome)

    undecided = discovered_ids - {d.case_id for d in decisions}
    if undecided:
        print(f"\n! {len(undecided)} untriaged case(s) in '{scope.name}' had no "
              f"decision supplied: {', '.join(f'C{i}' for i in sorted(undecided))}")

    updated_label = ("Would update in TestRail (dry run)" if summary.dry_run
                     else "Successfully updated in TestRail")
    print("\n" + "=" * 60)
    print("Triage summary")
    print("=" * 60)
    print(f"  Untriaged cases discovered:       {summary.discovered}")
    print(f"  Analyzed:                         {summary.analyzed}")
    print(f"  Suitable:                         {summary.suitable}")
    print(f"  Unsuitable:                       {summary.unsuitable}")
    print(f"  {updated_label + ':':<34}{summary.updated}")
    print(f"  Skipped:                          {summary.skipped}")
    print(f"  Failed updates:                   {summary.failed}")
    print("\n  Result by case:")
    for outcome in summary.outcomes:
        print(f"    C{outcome.case_id}: {outcome.status_label}")

    report_path = Path(args.report) if args.report else REPORT_DIR / "triage_report.md"
    write_triage_report(summary, config, report_path)
    print(f"\nReport: {report_path}")

    return 1 if summary.failed else 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Triage TestRail cases for XCUITest automation suitability."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    projects = sub.add_parser(
        "projects",
        help="Print the TestRail project selection prompt to show the user.",
    )
    projects.set_defaults(func=run_projects)

    fetch = sub.add_parser(
        "fetch", help="Print a section's Untriaged cases (read-only)."
    )
    fetch.add_argument(
        "section",
        help="Section id or section/folder name to triage. Sub-sections included.",
    )
    fetch.add_argument(
        "--status", default=STATUS_UNTRIAGED,
        help=f"Automation status to list (default {STATUS_UNTRIAGED}). Use "
             f"{STATUS_SUITABLE} to feed the automation-script-writer agent.",
    )
    fetch.add_argument("--limit", type=int, help="Only print the first N cases.")
    fetch.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    fetch.set_defaults(func=run_fetch)

    apply_cmd = sub.add_parser(
        "apply", help="Apply triage decisions to TestRail (dry-run by default)."
    )
    apply_cmd.add_argument(
        "section",
        help="The same section that was fetched. Decisions outside it are skipped.",
    )
    apply_cmd.add_argument("decisions", help="Path to the decisions JSON file.")
    apply_cmd.add_argument(
        "--dry-run", action="store_true",
        help="Analyse and print the proposed changes without writing to TestRail. "
             "Optional; normal execution updates TestRail.",
    )
    apply_cmd.add_argument("--report", help="Override the report output path.")
    apply_cmd.add_argument(
        "--confirm-firefox-ios", action="store_true",
        help="Required to write to the Firefox for iOS production project. "
             "Only pass it after the user has explicitly confirmed this run.",
    )
    apply_cmd.set_defaults(func=run_apply)

    for cmd in (fetch, apply_cmd):
        cmd.add_argument(
            "--project", required=True, choices=list(PROJECT_VALUES),
            metavar="{1|firefox-ios, 2|temp-approvals}",
            help="Which TestRail project to use. REQUIRED and never defaulted: "
                 "ask the user first (`projects` prints the prompt). "
                 "1/firefox-ios reads TESTRAIL_iOS_PROJECT_ID + "
                 "TESTRAIL_iOS_FULL_SUITE_ID; 2/temp-approvals reads "
                 "TESTRAIL_TMP_PROJECT_ID + TESTRAIL_TMP_SUITE_ID.",
        )

    args = parser.parse_args(argv)
    return run_cli(args.func, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
