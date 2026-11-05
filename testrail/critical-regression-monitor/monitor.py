#!/usr/bin/env python3
"""
Monitor iOS and Android Critical Regression and Smoke & Sanity selections
in TestRail, send Slack notifications for added and removed cases, and
update private GCS baselines after successful report delivery.
"""

import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

PLATFORMS = {"ios": (14, 45443), "android": (59, 3192)}
FIELD = "custom_sub_test_suites"
SELECTIONS = {
    "regression": {"id": 10, "label": "Critical Regression", "suffix": "", "id_key": "regression_id"},
    "smoke": {"id": 2, "label": "Smoke & Sanity", "suffix": "_smoke", "id_key": "smoke_id"},
}
REPORT_NAME = "Critical Regression & Smoke"
STATUS = {1: "Untriaged", 2: "Suitable", 3: "Unsuitable", 4: "Completed", 5: "Disabled"}
COVERAGE = {1: "None", 2: "Partial", 3: "Full"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TestRail:
    def __init__(self, email, api_key, host):
        self.host = host
        token = base64.b64encode(f"{email}:{api_key}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        self.opener = build_opener(NoRedirect())

    def get(self, endpoint):
        request = Request(f"{self.host}/index.php?/api/v2/{endpoint}", headers=self.headers)
        for attempt in range(3):
            try:
                with self.opener.open(request, timeout=60) as response:
                    return json.load(response)
            except HTTPError as exc:
                if (exc.code == 429 or 500 <= exc.code < 600) and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise RuntimeError(f"TestRail HTTP {exc.code}; check access and credentials.") from None
            except (URLError, TimeoutError):
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise RuntimeError("TestRail connection failed after three attempts.") from None
            except (ValueError, UnicodeError):
                raise RuntimeError("TestRail did not return valid JSON.") from None

    def cases(self, project_id, suite_id):
        offset, seen = 0, set()
        while True:
            query = urlencode({"suite_id": suite_id, "limit": 250, "offset": offset})
            data = self.get(f"get_cases/{project_id}&{query}")
            if isinstance(data, list):
                page = data
                has_next = len(page) == 250
            elif isinstance(data, dict) and isinstance(data.get("cases"), list):
                page = data["cases"]
                links = data.get("_links")
                if not isinstance(links, dict) or "next" not in links:
                    raise RuntimeError("Missing pagination metadata; refusing an incomplete snapshot.")
                has_next = bool(links["next"])
            else:
                raise RuntimeError("Unexpected get_cases response.")
            if has_next and not page:
                raise RuntimeError("Empty page with a next link; refusing an incomplete snapshot.")
            for case in page:
                if not isinstance(case, dict) or type(case.get("id")) is not int:
                    raise RuntimeError("Invalid case in API response.")
                if case["id"] in seen:
                    raise RuntimeError("Repeated case across pages; please retry the check.")
                if case.get("suite_id") != suite_id:
                    raise RuntimeError("API returned a case from a different suite.")
                if FIELD not in case:
                    raise RuntimeError(f"Missing {FIELD}; check field configuration/access.")
                choices = case[FIELD]
                if choices is not None and (
                    not isinstance(choices, list) or any(type(x) is not int for x in choices)
                ):
                    raise RuntimeError(f"Unexpected value format for {FIELD}.")
                seen.add(case["id"])
                yield case
            if not has_next:
                return
            offset += len(page)


def baseline_filename(platform, selection):
    return f"baseline_{platform}{SELECTIONS[selection]['suffix']}.json"


def selection_label(platform, selection):
    return f"{platform.upper()} — {SELECTIONS[selection]['label']}"


def save_initial_baseline(path, platform, cases, selection="regression"):
    project_id, suite_id = PLATFORMS[platform]
    data = {"schema_version": 1, "platform": platform, "project_id": project_id,
            "suite_id": suite_id, "field": FIELD,
            SELECTIONS[selection]["id_key"]: SELECTIONS[selection]["id"],
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "case_ids": sorted(case["id"] for case in cases)}
    # Exclusive creation: an existing baseline must never be silently reset.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


def load_baseline(path, platform, selection="regression"):
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    project_id, suite_id = PLATFORMS[platform]
    expected = {"schema_version": 1, "platform": platform, "project_id": project_id,
                "suite_id": suite_id, "field": FIELD,
                SELECTIONS[selection]["id_key"]: SELECTIONS[selection]["id"]}
    if not isinstance(data, dict) or any(data.get(k) != v for k, v in expected.items()):
        raise RuntimeError("Baseline configuration does not match the platform and selection.")
    ids = data.get("case_ids")
    if not isinstance(ids, list) or not ids or any(type(i) is not int or i <= 0 for i in ids):
        raise RuntimeError("Baseline has missing or invalid case IDs.")
    if len(set(ids)) != len(ids):
        raise RuntimeError("Baseline contains duplicate IDs.")
    captured_at = data.get("captured_at")
    if not isinstance(captured_at, str):
        raise RuntimeError("Baseline capture timestamp is missing.")
    try:
        timestamp = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        raise RuntimeError("Invalid baseline timestamp.") from None
    if timestamp.tzinfo is None:
        raise RuntimeError("Baseline timestamp must include a timezone.")
    return set(ids), captured_at


def slack_escape(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def preview_message(host, results, preview=True):
    title = "Slack preview" if preview else "check"
    lines = [f"*{REPORT_NAME} — {title}*",
             datetime.now(timezone.utc).strftime("Checked: %Y-%m-%d %H:%M UTC")]
    if preview:
        lines.append("*Baselines will NOT be updated. Additions are since each saved baseline.*")
    for (platform, selection), result in results.items():
        label = selection_label(platform, selection)
        selection_name = SELECTIONS[selection]["label"]
        lines.append("")
        if "error" in result:
            lines.append(f"*{label}: CHECK FAILED* — results unavailable; baseline unchanged.")
            continue
        current = result["cases"]
        baseline_ids = result["baseline_ids"]
        new_ids = sorted(set(current) - baseline_ids)
        removed = baseline_ids - set(current)
        suite_id = PLATFORMS[platform][1]
        suite_link = f"{host}/index.php?/suites/view/{suite_id}"
        if result.get("initialize"):
            lines.append(f"*{label}*: {len(current)} existing cases.")
            lines.append("*Initial baseline*: current cases are the starting reference, not new additions.")
            if preview:
                lines.append("Preview only: no baseline will be created.")
            else:
                lines.append("Baseline creation pending successful report delivery.")
            lines.append(f"<{suite_link}|Open TestRail suite>")
            continue
        lines.append(f"*{label}*: {len(current)} cases | "
                     f"{len(new_ids)} added | {len(removed)} removed")
        lines.append(f"Baseline captured: {slack_escape(result['captured_at'])}")
        if not new_ids:
            lines.append("No new additions.")
        if new_ids:
            lines.append(f"*Entered the monitored {selection_name} selection:*")
        for case_id in new_ids:
            case = current[case_id]
            title = " ".join(str(case.get("title") or "Untitled case").split())[:140]
            status = STATUS.get(case.get("custom_automation_status"), "Unknown / unset")
            coverage = COVERAGE.get(case.get("custom_automation_coverage"), "Unknown / unset")
            lines.append(f"• <{host}/index.php?/cases/view/{case_id}|C{case_id}> — "
                         f"{slack_escape(title)} — {status}; coverage: {coverage}")
        if removed:
            lines.append(f"*Left the monitored {selection_name} selection (reason not verified):*")
            for case_id in sorted(removed):
                lines.append(f"• <{host}/index.php?/cases/view/{case_id}|C{case_id}>")
        lines.append(f"<{suite_link}|Open TestRail suite>")
    lines.extend(["", "*Action:* Review removed and new additions; confirm automation coverage. "
                  "Create or link an automation ticket where needed."])
    return "\n".join(lines)


def split_report(message, limit=3500):
    """Keep each entry/link intact and never omit entries when splitting."""
    chunks, lines, length = [], [], 0
    for line in message.splitlines():
        if len(line) > limit:
            raise RuntimeError("A report entry exceeds the Slack size limit; baselines unchanged.")
        if lines and length + len(line) + 1 > limit:
            chunks.append("\n".join(lines))
            lines, length = [], 0
        lines.append(line)
        length += len(line) + 1
    if lines:
        chunks.append("\n".join(lines))
    if len(chunks) == 1:
        return chunks
    report_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return [f"*{REPORT_NAME} report {report_id} — part {i}/{len(chunks)}*\n{chunk}"
            for i, chunk in enumerate(chunks, 1)]


def deliver_report(webhook, message):
    for i, chunk in enumerate(split_report(message)):
        if i:
            time.sleep(1.1)
        send_slack(webhook, chunk)


class MissingBaseline(RuntimeError):
    """The GCS object lookup explicitly returned 404, not a permission failure."""


def gcloud(*args):
    try:
        return subprocess.run(["gcloud", "storage", *args, "--quiet"],
                              check=True, capture_output=True, text=True, timeout=120).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        # GCS object contents and credential paths must not enter public logs.
        raise RuntimeError("GCS command failed: check permissions, connectivity or concurrent updates.") from None


def gcs_generation(uri, allow_missing=False):
    # Read the HTTP status directly. gcloud's human-readable missing-object
    # diagnostics vary across versions and must not control initialization.
    parsed = urlsplit(uri)
    object_name = parsed.path.lstrip("/")
    if parsed.scheme != "gs" or not parsed.netloc or not object_name or parsed.query or parsed.fragment:
        raise RuntimeError("Invalid GCS baseline URI.")
    try:
        token = subprocess.run(["gcloud", "auth", "print-access-token", "--quiet"],
                               check=True, capture_output=True, text=True, timeout=60).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        raise RuntimeError("Cannot obtain a GCS access token from the configured gcloud identity.") from None
    if not token:
        raise RuntimeError("gcloud returned an empty GCS access token.")
    url = (f"https://storage.googleapis.com/storage/v1/b/{quote(parsed.netloc, safe='')}"
           f"/o/{quote(object_name, safe='')}?fields=generation")
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    opener = build_opener(NoRedirect())
    for attempt in range(3):
        try:
            with opener.open(request, timeout=60) as response:
                data = json.load(response)
            break
        except HTTPError as exc:
            if exc.code == 404 and allow_missing:
                raise MissingBaseline("GCS baseline object not found (HTTP 404).") from None
            if (exc.code == 429 or 500 <= exc.code < 600) and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"GCS baseline metadata HTTP {exc.code}; check object access and location.") from None
        except (URLError, TimeoutError, OSError):
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError("GCS baseline metadata connection failed after three attempts.") from None
        except (ValueError, UnicodeError):
            raise RuntimeError("GCS returned invalid baseline metadata JSON.") from None
    generation = str(data.get("generation", "")) if isinstance(data, dict) else ""
    if not generation.isdigit():
        raise RuntimeError("GCS did not return a valid object generation.")
    return generation


def download_baseline(uri, path, allow_missing=False):
    generation = gcs_generation(uri, allow_missing=allow_missing)
    gcloud("cp", uri, str(path))
    if gcs_generation(uri) != generation:
        raise RuntimeError("Baseline changed while downloading; retry the run.")
    return generation


def run_notify(api, host, webhook, prefix, platforms, selections=None, initialize_smoke=False):
    selections = list(SELECTIONS) if selections is None else selections
    results, errors = {}, []
    with tempfile.TemporaryDirectory(prefix="regression-monitor-") as directory:
        root = Path(directory)
        for platform in platforms:
            project_id, suite_id = PLATFORMS[platform]
            baselines = {}
            # Capture generations BEFORE querying TestRail. Otherwise an older API
            # snapshot could replace a baseline that was refreshed during the query.
            for selection in selections:
                label = selection_label(platform, selection)
                try:
                    filename = baseline_filename(platform, selection)
                    path, uri = root / filename, f"{prefix}/{filename}"
                    initialize = False
                    try:
                        generation = download_baseline(uri, path, allow_missing=True)
                    except MissingBaseline:
                        if selection != "smoke" or not initialize_smoke:
                            raise RuntimeError("Baseline missing. Only initial Smoke setup may use --initialize-smoke.") from None
                        initialize, generation = True, "0"
                    if initialize:
                        baseline_ids, captured_at = None, None
                    else:
                        baseline_ids, captured_at = load_baseline(path, platform, selection)
                    baselines[selection] = {
                        "baseline_ids": baseline_ids, "captured_at": captured_at,
                        "generation": generation, "uri": uri, "initialize": initialize,
                    }
                except (RuntimeError, OSError, ValueError) as exc:
                    results[(platform, selection)] = {"error": True}
                    errors.append(f"{label}: baseline check failed; baseline unchanged.")
                    print(f"{label} ERROR: {exc}", file=sys.stderr)
            if not baselines:
                continue
            try:
                # Query once per platform; a case may belong to both selections.
                cases = list(api.cases(project_id, suite_id))
                if not cases:
                    raise RuntimeError("Suite returned zero cases; check access and configuration.")
                checked_at = datetime.now(timezone.utc).isoformat()
            except (RuntimeError, OSError, ValueError) as exc:
                for selection in baselines:
                    results[(platform, selection)] = {"error": True}
                errors.append(f"{platform.upper()}: API check failed; baselines unchanged.")
                print(f"{platform.upper()} ERROR: {exc}", file=sys.stderr)
                continue

            for selection, baseline in baselines.items():
                label = selection_label(platform, selection)
                try:
                    selected = {c["id"]: c for c in cases
                                if SELECTIONS[selection]["id"] in (c[FIELD] or [])}
                    if not selected:
                        raise RuntimeError("Zero selected cases; manual review required before updating.")
                    result = dict(baseline, cases=selected, checked_at=checked_at)
                    if result["initialize"]:
                        result.update(baseline_ids=set(selected), captured_at=checked_at)
                    results[(platform, selection)] = result
                    print(f"{label}: comparison completed. Details go to Slack only.")
                except (RuntimeError, OSError, ValueError) as exc:
                    results[(platform, selection)] = {"error": True}
                    errors.append(f"{label}: check failed; baseline unchanged.")
                    print(f"{label} ERROR: {exc}", file=sys.stderr)

        results = {(p, s): results[(p, s)] for p in platforms for s in selections}
        try:
            # No upload is attempted until every part has been acknowledged by Slack.
            deliver_report(webhook, preview_message(host, results, preview=False))
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            print("Report delivery incomplete: no baseline uploads attempted.", file=sys.stderr)
            return 1

        update_status = []
        for (platform, selection), result in results.items():
            label = selection_label(platform, selection)
            if "error" in result:
                update_status.append(f"{label}: check failed; baseline unchanged.")
                continue
            try:
                path = root / f"next_{baseline_filename(platform, selection)}"
                save_initial_baseline(path, platform, list(result["cases"].values()), selection)
                # The timestamp refers to the snapshot, not to the end of Slack delivery.
                data = json.loads(path.read_text(encoding="utf-8"))
                data["captured_at"] = result["checked_at"]
                path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                gcloud("cp", str(path), result["uri"],
                       f"--if-generation-match={result['generation']}")
                action = "initialized" if result["initialize"] else "updated"
                update_status.append(f"{label}: baseline {action}.")
                print(f"{label}: baseline {action} successfully.")
            except (RuntimeError, OSError, ValueError) as exc:
                errors.append(f"{label}: baseline update NOT confirmed. "
                              "Review GCS before retrying; differences may be notified again.")
                update_status.append(errors[-1])
                print(f"{label} ERROR: {exc}", file=sys.stderr)
        try:
            # Completion is separate because remote upload can fail after the digest arrives.
            time.sleep(1.1)
            send_slack(webhook, f"*{REPORT_NAME} — processing result*\n" + "\n".join(update_status))
        except RuntimeError as exc:
            errors.append("Completion notification failed; some baselines may already be updated.")
            print(str(exc), file=sys.stderr)
        if errors:
            print("Run completed with errors. Check the workflow and Slack status.", file=sys.stderr)
            return 1
        print("SUCCESS: full report delivered and all selected baselines saved.")
        return 0


def send_slack(webhook, message):
    # No automatic POST retry: a lost response could otherwise duplicate a message.
    payload = json.dumps({"text": message, "unfurl_links": False, "unfurl_media": False}).encode()
    request = Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            if response.read().strip() != b"ok":
                raise RuntimeError("Slack did not confirm delivery.")
    except HTTPError as exc:
        raise RuntimeError(f"Slack returned HTTP {exc.code}.") from None
    except (URLError, TimeoutError, OSError):
        # Never include the exception/URL: it can contain the webhook secret.
        raise RuntimeError("Slack delivery could not be confirmed.") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("check", "init", "slack-preview", "notify"), default="check")
    parser.add_argument("--platform", choices=("all", "ios", "android"), default="all")
    parser.add_argument("--selection", choices=("all", "regression", "smoke"), default="all")
    parser.add_argument("--initialize-smoke", action="store_true",
                        help="notify only: create missing Smoke baselines once; never reset existing ones.")
    parser.add_argument("--baseline-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--gcs-prefix", help="Existing private GCS baseline directory; required for notify.")
    args = parser.parse_args()
    selections = list(SELECTIONS) if args.selection == "all" else [args.selection]
    if args.initialize_smoke and (args.mode != "notify" or "smoke" not in selections):
        parser.error("--initialize-smoke requires notify mode with the Smoke selection included.")
    if args.mode == "notify":
        prefix = (args.gcs_prefix or "").rstrip("/")
        if not prefix.startswith("gs://") or any(c in prefix for c in "*?[]#\n\r") or not prefix[5:]:
            parser.error("notify requires --gcs-prefix gs://BUCKET/PREFIX without wildcards.")
    host = os.environ.get("TESTRAIL_HOST", "").strip().rstrip("/")
    try:
        parsed = urlsplit(host)
        valid_host = (parsed.scheme == "https" and bool(parsed.hostname) and
                      not parsed.username and not parsed.password and not parsed.path and
                      not parsed.query and not parsed.fragment)
    except ValueError:
        valid_host = False
    if not valid_host:
        parser.error("Set TESTRAIL_HOST to an HTTPS base URL, without credentials, path or query.")
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if args.mode in ("slack-preview", "notify"):
        try:
            parsed = urlsplit(webhook)
            valid_webhook = (parsed.scheme == "https" and parsed.netloc == "hooks.slack.com" and
                             parsed.path.startswith("/services/") and not parsed.query and not parsed.fragment)
        except ValueError:
            valid_webhook = False
        if not valid_webhook:
            parser.error("Set SLACK_WEBHOOK_URL to a Slack incoming webhook URL.")
    email = os.environ.get("TESTRAIL_USERNAME") or os.environ.get("TESTRAIL_EMAIL")
    key = os.environ.get("TESTRAIL_PASSWORD") or os.environ.get("TESTRAIL_API_KEY")
    if not email:
        if not sys.stdin.isatty():
            parser.error("Set TESTRAIL_USERNAME when running non-interactively.")
        email = input("TestRail email: ").strip()
    if not key:
        if not sys.stdin.isatty():
            parser.error("Set TESTRAIL_PASSWORD when running non-interactively.")
        key = getpass.getpass("TestRail API key (hidden): ")
    if not email or not key:
        parser.error("Email and API key must not be empty.")
    api = TestRail(email, key, host)
    if args.mode == "notify":
        platforms = list(PLATFORMS) if args.platform == "all" else [args.platform]
        return run_notify(api, host, webhook, prefix, platforms, selections, args.initialize_smoke)
    failed = False
    results = {}
    for platform in PLATFORMS if args.platform == "all" else [args.platform]:
        project_id, suite_id = PLATFORMS[platform]
        try:
            cases = list(api.cases(project_id, suite_id))
            if not cases:
                raise RuntimeError("Suite returned zero cases; check access and suite configuration.")
        except (RuntimeError, OSError, ValueError) as exc:
            failed = True
            for selection in selections:
                results[(platform, selection)] = {"error": True}
            print(f"{platform.upper()} ERROR: {exc}", file=sys.stderr)
            continue
        for selection in selections:
            label = selection_label(platform, selection)
            try:
                baseline_path = args.baseline_dir / baseline_filename(platform, selection)
                selected = [c for c in cases if SELECTIONS[selection]["id"] in (c[FIELD] or [])]
                if args.mode == "slack-preview":
                    baseline_ids, captured_at = load_baseline(baseline_path, platform, selection)
                    if not selected:
                        raise RuntimeError("Zero selected cases; review the field or suite configuration.")
                    results[(platform, selection)] = {
                        "cases": {c["id"]: c for c in selected}, "baseline_ids": baseline_ids,
                        "captured_at": captured_at,
                    }
                    print(f"{label}: comparison completed. Details will go to Slack only.")
                    continue
                print(f"\n{label} | project {project_id} | suite {suite_id}")
                print(f"Cases scanned: {len(cases)} | Selected: {len(selected)}")
                for field, labels in (("custom_automation_status", STATUS),
                                      ("custom_automation_coverage", COVERAGE)):
                    counts = Counter(labels.get(c.get(field), "Unknown / unset") for c in selected)
                    print(field + ": " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
                if args.mode == "init":
                    if not selected:
                        raise RuntimeError("Zero selected cases; refusing baseline initialization.")
                    args.baseline_dir.mkdir(parents=True, exist_ok=True)
                    save_initial_baseline(baseline_path, platform, selected, selection)
                    print(f"Created {baseline_path.name}; existing cases are the initial reference.")
            except (RuntimeError, OSError, ValueError) as exc:
                failed = True
                results[(platform, selection)] = {"error": True}
                print(f"{label} ERROR: {exc}", file=sys.stderr)
    if args.mode == "slack-preview":
        try:
            deliver_report(webhook, preview_message(host, results))
            print("Slack preview delivered. Local and GCS baselines unchanged.")
        except RuntimeError as exc:
            failed = True
            print(str(exc), file=sys.stderr)
    else:
        print("\nNo TestRail changes made. No notifications sent.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
