#!/usr/bin/env python3
"""Print the test cases inside a TestRail section, for analysis.

Read-only companion to ``testrail_import.py``. Resolves a section by id or by
name, walks the sub-sections under it, downloads every case, and prints them as
compact plain text on stdout. Nothing is written to disk and nothing in TestRail
is modified.

The output is the input for the ``feature-documenter`` agent.

Usage:
    python3 scripts/testrail_fetch_section.py <section> [--project-id N] [--suite-id N]

    <section>   Section id (e.g. 654483) or section/folder name
                (e.g. "Pull to refresh").

Search target - project 1, Firefox for iOS, from the shared project registry:

    TESTRAIL_iOS_PROJECT_ID   default 14     - Firefox for iOS
    TESTRAIL_iOS_FULL_SUITE_ID    default 45443  - Full Functional Tests Suite

Kept separate from the importer's TESTRAIL_TMP_PROJECT_ID / TESTRAIL_TMP_SUITE_ID, so
documenting a shipped feature never depends on wherever the last import ran.
Unlike the triage script, this one falls back to the documented ids when the
variables are unset: it only ever reads.

Credentials come from the same environment variables as the importer; a local
.env is loaded automatically. The API key is never printed.

The client, project resolution, section helpers, rich-text flattening and the
case rendering all come from ``testrail_client`` - this script contains only
the fetch-and-print workflow.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from testrail_client import (  # noqa: E402  (path set above)
    FIREFOX_IOS,
    TestRailClient,
    case_view,
    load_config,
    project_banner,
    project_target,
    run_cli,
    section_subtree,
    verify_project_target,
)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def run(args) -> int:
    config = load_config(require_target=False)

    # Project 1 of the shared registry, with the documented ids as defaults and
    # per-run overrides for the rare "document another project" request.
    target = project_target(FIREFOX_IOS, fallback_to_documented=True)
    target.project_id = args.project_id or target.project_id
    target.suite_id = args.suite_id or target.suite_id
    config.project_id = target.project_id

    client = TestRailClient(config)
    project_name, suite_name = verify_project_target(client, target)
    subtree = section_subtree(client, target.suite_id, args.section)

    out: list[str] = []
    total = 0
    for section in subtree.sections:
        cases = client.get_cases(target.suite_id, int(section["id"]))
        if not cases:
            continue
        out.append(f"\n## {subtree.relative_path(section) or subtree.name}  "
                   f"({len(cases)} cases)")
        for case in cases:
            total += 1
            view = case_view(case, client, config, target.suite_id)
            # The '##' heading above already states the section.
            out.append("\n" + "\n".join(view.text_lines(include_section=False)))

    print(f"# {subtree.name} (section {subtree.id})")
    print("\n".join(project_banner(target, project_name, suite_name)))
    print(f"# {total} cases in {len(subtree.sections)} sections")
    print("\n".join(out))
    if not total:
        print("\n! The section resolved but contains no test cases.", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Print a TestRail section's test cases as plain text (read-only)."
    )
    parser.add_argument("section", help="Section id or section/folder name.")
    parser.add_argument(
        "--project-id", type=int,
        help=f"Override {FIREFOX_IOS.project_env} "
             f"(default {FIREFOX_IOS.documented_project_id}).",
    )
    parser.add_argument(
        "--suite-id", type=int,
        help=f"Override {FIREFOX_IOS.suite_env} "
             f"(default {FIREFOX_IOS.documented_suite_id}).",
    )
    return run_cli(run, parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
