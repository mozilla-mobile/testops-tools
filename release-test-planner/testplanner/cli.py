# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Command line entry point for the Fenix release test planner PoC."""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser

from . import (
    agentio, changes, corpus, coverage, factories, featuremap, matrix, plan,
    report, risk,
)

DEFAULT_REPO = os.environ.get("FENIX_REPO", "")
FENIX_APP = "mobile/android/fenix/app"
FENIX_SRC = FENIX_APP + "/src/main"
FENIX_UI_TESTS = FENIX_APP + "/src/androidTest/java/org/mozilla/fenix/ui"
FENIX_EFFICIENCY = FENIX_UI_TESTS + "/efficiency"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CATALOG = os.path.join(HERE, "..", "config", "features.json")
DEFAULT_ENV = os.path.join(HERE, "..", "config", "environment.json")


def run_analysis(args, quiet: bool = False):
    """Run the whole pipeline and return the report payload.

    Shared by `analyze` (writes files) and `serve --live` (regenerates on each
    request), so the served JSON can never drift from the written one.
    """
    log = (lambda *a: None) if quiet else (lambda *a: print(*a))

    repo = os.path.abspath(os.path.expanduser(args.repo))

    catalog = featuremap.FeatureCatalog.load(os.path.abspath(args.catalog))

    log("[1/8] reading git range {}".format(args.range))
    change_data = changes.collect(
        repo,
        args.range,
        pathspec=args.pathspec or ["mobile/android/fenix/"],
        max_commits=args.max_commits,
    )
    log("      {} commits, {} files, {} lines churned".format(
        change_data["commit_count"],
        change_data["file_count"],
        change_data["total_churn"],
    ))

    if not change_data["files"]:
        log("\nNo changed files in that range. Try a wider --range.")
        return None

    log("[2/8] mapping paths to features")
    attribution = featuremap.attribute(catalog, change_data["files"])
    log("      {} features touched, {} paths unmapped, {} ignored".format(
        len(attribution["features_touched"]),
        len(attribution["unmapped_files"]),
        attribution["ignored_count"],
    ))

    answers = agentio.load_answers(args.answers)
    audit = agentio.apply_overrides(catalog, attribution, answers)
    if audit:
        log("      applied {} agent override(s)".format(len(audit)))

    log("[3/8] indexing test corpus")
    inventory = corpus.build(repo, FENIX_UI_TESTS)
    log("      {} tests ({}), {} smoke, {} disabled".format(
        inventory["total_tests"],
        ", ".join("{} {}".format(v, k) for k, v in inventory["by_suite"].items()),
        inventory["smoke_tests"],
        inventory["disabled_tests"],
    ))

    log("[4/8] binding tests to features")
    cov = coverage.bind(catalog, inventory)
    log("      {} tests bound to no feature".format(cov["unbound_count"]))

    log("[5/8] scoring FMEA risk")
    risk_result = risk.score(attribution, cov)
    t = risk_result["totals"]
    log("      total RPN {} / inherent {} | {} action-required".format(
        t["total_rpn"], t["total_inherent_rpn"], t["action_required"]
    ))

    log("[6/8] planning test selection")
    plan_result = plan.build(risk_result, cov, budget_minutes=args.budget)
    pt = plan_result["totals"]
    log("      {} tests selected, {} min, confidence {:.1%}, {} gaps".format(
        plan_result["selected_count"],
        plan_result["estimated_minutes"],
        pt["release_confidence"],
        pt["features_with_gaps"],
    ))

    log("[7/8] scanning generated-test factories")
    factory_scan = factories.scan(repo, FENIX_EFFICIENCY)
    factory_by_feature = factories.attribute_to_features(
        factory_scan, catalog, risk_result["rows"]
    )
    log("      {} candidate cases across {} factories".format(
        factory_scan["total_candidates"], len(factory_scan["factories"])
    ))

    log("[8/8] building the combinatorial matrix")
    with open(os.path.abspath(args.environment)) as fh:
        env_config = json.load(fh)
    matrix_result = matrix.allocate(
        risk_result["rows"], plan_result, env_config,
        factory_scan["context_factors"],
    )
    mt = matrix_result["totals"]
    log("      {} executions, {} h device time ({}x the single-config run)".format(
        mt["executions"], mt["est_hours"], mt["matrix_multiplier"]
    ))

    tasks = agentio.emit(attribution, cov, risk_result, plan_result)

    payload = {
        "meta": {
            "repo": repo,
            "range": args.range,
            "budget_minutes": args.budget,
            "catalog": os.path.abspath(args.catalog),
            "agent_overrides_applied": audit,
        },
        "changes": change_data,
        "attribution": attribution,
        "inventory": {k: v for k, v in inventory.items() if k != "tests"},
        "coverage_summary": {
            "unbound_count": cov["unbound_count"],
        },
        "risk": risk_result,
        "plan": plan_result,
        "factories": {
            **{k: v for k, v in factory_scan.items() if k != "selectors_per_page"},
            "per_feature": factory_by_feature,
        },
        "matrix": matrix_result,
        "agent_tasks": tasks,
    }

    return payload


def _write(payload, outdir: str, quiet: bool = False) -> str:
    """Write report.json, agent-tasks.json and the standalone report.html."""
    log = (lambda *a: None) if quiet else (lambda *a: print(*a))
    os.makedirs(outdir, exist_ok=True)

    json_path = os.path.join(outdir, "report.json")
    with open(json_path, "w") as fh:
        json.dump(payload, fh, indent=2)

    tasks = payload["agent_tasks"]
    tasks_path = os.path.join(outdir, "agent-tasks.json")
    with open(tasks_path, "w") as fh:
        json.dump(tasks, fh, indent=2)

    html_path = os.path.join(outdir, "report.html")
    report.render(payload, html_path)

    log("\nwrote:")
    log("  {}".format(json_path))
    log("  {}  ({} questions for an agent)".format(tasks_path, tasks["task_count"]))
    log("  {}  (standalone - embeds its own data)".format(html_path))
    return html_path


def _analyze(args) -> int:
    payload = run_analysis(args)
    if payload is None:
        return 1
    html_path = _write(payload, os.path.abspath(os.path.expanduser(args.out)))
    if args.open:
        webbrowser.open("file://" + html_path)
    return 0


def _serve(args) -> int:
    """Serve out/ so a browser refresh picks up fresh data.

    With --live the pipeline re-runs on every request for report.json, so
    refreshing the page is enough to see a config or catalog edit take effect.
    Without it, the last written report.json is served as static files.
    """
    import http.server
    import socketserver

    outdir = os.path.abspath(os.path.expanduser(args.out))

    if not os.path.exists(os.path.join(outdir, "report.html")):
        print("No report in {} yet - running the pipeline once.".format(outdir), flush=True)
        payload = run_analysis(args)
        if payload is None:
            return 1
        _write(payload, outdir)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=outdir, **kw)

        def do_GET(self):
            if args.live and self.path.split("?")[0].rstrip("/") in ("/report.json",):
                print("regenerating report.json ...", flush=True)
                try:
                    payload = run_analysis(args, quiet=True)
                except Exception as exc:  # keep the server alive on a bad edit
                    self.send_error(500, "analysis failed: {}".format(exc))
                    return
                if payload is None:
                    self.send_error(500, "no changes in range")
                    return
                _write(payload, outdir, quiet=True)
                print("  done - {} features, confidence {:.1%}".format(
                    payload["risk"]["totals"]["features_touched"],
                    payload["plan"]["totals"]["release_confidence"],
                ))
            return super().do_GET()

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, fmt, *a):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), Handler) as httpd:
        url = "http://127.0.0.1:{}/report.html".format(args.port)
        print("serving {} at {}".format(outdir, url), flush=True)
        print("live regeneration: {}".format("on" if args.live else "off"), flush=True)
        print("refresh the page to pick up changes. ctrl-c to stop.", flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.", flush=True)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="testplanner",
        description="Risk-based release test planner for Fenix (proof of concept).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--range", default="HEAD~200..HEAD",
                       help="git revision range (default: HEAD~200..HEAD)")
        p.add_argument("--repo", default=DEFAULT_REPO,
                       help="path to a mozilla-central / firefox checkout "
                            "(or set FENIX_REPO)")
        p.add_argument("--catalog", default=DEFAULT_CATALOG)
        p.add_argument("--environment", default=DEFAULT_ENV,
                       help="JSON file of environment factors and allocation policy")
        p.add_argument("--budget", type=float, default=None,
                       help="device-minutes available for the test run")
        p.add_argument("--answers", default=None,
                       help="JSON file of agent answers to apply as overrides")
        p.add_argument("--pathspec", nargs="*", default=None)
        p.add_argument("--max-commits", type=int, default=2000)
        p.add_argument("--out", default="out")
        p.add_argument("--open", action="store_true",
                       help="open the report in a browser")
        return p

    a = common(sub.add_parser("analyze", help="run the pipeline over a git range"))
    a.set_defaults(func=_analyze)

    s = common(sub.add_parser(
        "serve", help="serve the report so a browser refresh picks up changes"))
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--live", action="store_true",
                   help="re-run the pipeline on every request for report.json")
    s.set_defaults(func=_serve)

    args = parser.parse_args(argv)

    if not args.repo:
        parser.error(
            "no Firefox checkout given. Pass --repo /path/to/firefox, or set "
            "FENIX_REPO in your environment."
        )
    if not os.path.isdir(os.path.join(os.path.expanduser(args.repo), FENIX_APP)):
        parser.error(
            "{} does not look like a Firefox checkout - expected to find {} "
            "under it.".format(args.repo, FENIX_APP)
        )

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
