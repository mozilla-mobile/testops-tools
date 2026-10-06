#!/usr/bin/env python3
"""
Pull critical-test automation coverage from TestRail.

Why it pulls everything: TestRail's API cannot filter on custom fields
(Automation, Sub Test Suite). So we fetch all cases once per suite and
filter in Python. This also avoids the UI's 250-per-page limit, which
silently truncates any count above 250.

Setup (either name works for the host and the key):
    export TESTRAIL_URL=https://mozilla.testrail.io   # or TESTRAIL_HOST
    export TESTRAIL_USER=you@mozilla.com             # or TESTRAIL_USERNAME
    export TESTRAIL_KEY=<your api key>                # or TESTRAIL_PASSWORD

In a GitHub Action, map the repository secrets into the step:
    env:
      TESTRAIL_HOST: ${{ secrets.TESTRAIL_HOST }}
      TESTRAIL_USERNAME: ${{ secrets.TESTRAIL_USERNAME }}
      TESTRAIL_PASSWORD: ${{ secrets.TESTRAIL_PASSWORD }}

First run - find out what the fields are actually called:
    python testrail_metrics.py --discover

Then set the CONFIG values below and run:
    python testrail_metrics.py
    python testrail_metrics.py --csv metrics.csv

Each run saves the case IDs behind every number to a state file
(tr-state.json by default) and compares against the previous run, so the
next run says WHICH cases moved rather than only that a count changed.
Pass --no-state to skip saving, e.g. for an ad-hoc run you do not want
to become the comparison point.
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# CONFIG - set these after running --discover
# ---------------------------------------------------------------------------

SUITES = {
    "android": 3192,
    "ios": 45443,
}

# System name of the custom field holding sub test suites.
# Seen in your TestRail URLs as "cases:custom_sub_test_suites".
SUB_SUITE_FIELD = "custom_sub_test_suites"

# System name of the custom field holding automation status.
# Run --discover to confirm. Common values: custom_automation_status,
# custom_automation, custom_automation_type.
AUTOMATION_FIELD = "custom_automation_status"

# Option labels as they appear in the TestRail UI.
SUB_SUITE_CRITICAL = "Regression"
AUTOMATION_COMPLETED = "Completed"
AUTOMATION_UNSUITABLE = "Unsuitable"

# TestRail's default value on a newly created case. A case with this, or
# with the field left blank, has not been assessed yet.
AUTOMATION_UNTRIAGED = "Untriaged"

# Format version of the --json output.
JSON_SCHEMA_VERSION = 1

# Where the previous run's case IDs are kept, for the delta report.
STATE_FILE = "tr-state.json"

# Label marking a case as migrated to TAE.
TAE_LABEL = "TAE"

# Older automation field. Several cases had "Full" here while Automation was
# never set, so the two are compared. Run --discover to confirm the system
# name; if it is wrong, that one check is skipped with a notice.
COVERAGE_FIELD = "custom_automation_coverage"
COVERAGE_FULL = "Full"

# Type every critical case should end up with once the cleanup is done.
EXPECTED_TYPE = "Functional"

# ---------------------------------------------------------------------------


class TestRail:
    def __init__(self, base_url, user, key):
        self.base = base_url.rstrip("/") + "/index.php?/api/v2/"
        self.session = requests.Session()
        self.session.auth = (user, key)
        self.session.headers.update({"Content-Type": "application/json"})

    def get(self, endpoint):
        """GET with retry on TestRail's 429 rate limit."""
        for attempt in range(5):
            resp = self.session.get(self.base + endpoint, timeout=60)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 10))
                print(f"  rate limited, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"gave up after rate limits on {endpoint}")

    def get_all_cases(self, project_id, suite_id):
        """Page through every case in a suite. Handles both the paginated
        response (TestRail 6.7+) and the older bare-list response."""
        cases, offset, limit = [], 0, 250
        while True:
            payload = self.get(
                f"get_cases/{project_id}&suite_id={suite_id}"
                f"&limit={limit}&offset={offset}"
            )
            if isinstance(payload, list):
                return payload
            batch = payload.get("cases", [])
            cases.extend(batch)
            if len(batch) < limit:
                return cases
            offset += limit
            print(f"  fetched {len(cases)}...", file=sys.stderr)

    def get_all_sections(self, project_id, suite_id):
        """Return {section_id: full path}, e.g. "Normal mode > Portrait".

        Sections nest, and leaf names repeat across branches, so the leaf
        alone cannot tell two cases apart.
        """
        raw, offset, limit = {}, 0, 250
        while True:
            payload = self.get(
                f"get_sections/{project_id}&suite_id={suite_id}"
                f"&limit={limit}&offset={offset}"
            )
            batch = payload if isinstance(payload, list) \
                else payload.get("sections", [])
            for section in batch:
                raw[section["id"]] = (section["name"], section.get("parent_id"))
            if isinstance(payload, list) or len(batch) < limit:
                break
            offset += limit

        def path(sid, seen=None):
            seen = seen or set()
            if sid not in raw or sid in seen:
                return []
            seen.add(sid)
            name, parent = raw[sid]
            return path(parent, seen) + [name]

        return {sid: " > ".join(path(sid)) for sid in raw}


def option_map(field):
    """Build {id: label} from a custom field's dropdown/multiselect options.

    TestRail stores these as newline-separated "1, Completed" strings.
    """
    out = {}
    for config in field.get("configs", []):
        items = config.get("options", {}).get("items", "")
        for line in items.splitlines():
            if "," not in line:
                continue
            raw_id, label = line.split(",", 1)
            try:
                out[int(raw_id.strip())] = label.strip()
            except ValueError:
                continue
    return out


def values_of(case, field_name, mapping):
    """Return the case's value(s) for a field as a set of labels.

    Handles single-select (int), multi-select (list of ints) and
    plain string fields.
    """
    raw = case.get(field_name)
    if raw is None:
        return set()
    if isinstance(raw, list):
        return {mapping.get(v, str(v)) for v in raw}
    if isinstance(raw, int):
        return {mapping.get(raw, str(raw))}
    return {str(raw)}


def label_names(case):
    """Case labels come back as dicts or plain strings depending on version."""
    out = set()
    for label in case.get("labels") or []:
        if isinstance(label, dict):
            name = label.get("title") or label.get("name")
            if name:
                out.add(name)
        else:
            out.add(str(label))
    return out


def discover(api):
    """Print field system names and their options so CONFIG can be filled in."""
    print("=== CASE FIELDS ===\n")
    for field in api.get("get_case_fields"):
        opts = option_map(field)
        print(f"{field['system_name']}")
        print(f"  label: {field['label']}")
        if opts:
            print(f"  options: {', '.join(sorted(opts.values()))}")
        print()

    print("=== A SAMPLE CASE (raw) ===\n")
    suite_id = next(iter(SUITES.values()))
    project_id = api.get(f"get_suite/{suite_id}")["project_id"]
    payload = api.get(f"get_cases/{project_id}&suite_id={suite_id}&limit=1")
    sample = payload[0] if isinstance(payload, list) else payload["cases"][0]
    print(json.dumps(sample, indent=2))


def measure(api, platform, suite_id):
    suite = api.get(f"get_suite/{suite_id}")
    project_id = suite["project_id"]

    fields = {f["system_name"]: f for f in api.get("get_case_fields")}
    for name in (SUB_SUITE_FIELD, AUTOMATION_FIELD):
        if name not in fields:
            sys.exit(
                f"Field '{name}' not found. Run --discover and update CONFIG."
            )

    sub_suite_opts = option_map(fields[SUB_SUITE_FIELD])
    automation_opts = option_map(fields[AUTOMATION_FIELD])
    case_types = {t["id"]: t["name"] for t in api.get("get_case_types")}

    print(f"{platform}: fetching suite {suite_id}...", file=sys.stderr)
    cases = api.get_all_cases(project_id, suite_id)

    critical = [
        c for c in cases
        if SUB_SUITE_CRITICAL in values_of(c, SUB_SUITE_FIELD, sub_suite_opts)
    ]

    def automation_is(case, value):
        return value in values_of(case, AUTOMATION_FIELD, automation_opts)

    unsuitable = [c for c in critical if automation_is(c, AUTOMATION_UNSUITABLE)]
    automatable = [c for c in critical if c not in unsuitable]

    # Completed is the only status that means "this test is automated".
    # The TAE label says which framework. The two are set independently in
    # TestRail, so a case can carry the label without Completed - that is a
    # data-quality problem, not coverage, and it gets its own line below.
    automated = [c for c in automatable if automation_is(c, AUTOMATION_COMPLETED)]
    in_tae = [c for c in automated if TAE_LABEL in label_names(c)]
    in_legacy = [c for c in automated if TAE_LABEL not in label_names(c)]

    # Labelled TAE but not marked Completed. These inflate the TAE count if
    # you take the label at face value. in_tae + in_legacy must equal
    # automated; if it does not, this is why.
    tae_not_completed = [
        c for c in automatable
        if TAE_LABEL in label_names(c) and not automation_is(c, AUTOMATION_COMPLETED)
    ]

    # Every other automation status among automatable critical cases, so a
    # value nobody has accounted for (Disabled, blank, a new option) shows up
    # instead of hiding inside "not yet automated".
    other_status = {}
    for case in automatable:
        if automation_is(case, AUTOMATION_COMPLETED):
            continue
        for label in (values_of(case, AUTOMATION_FIELD, automation_opts)
                      or {"(none)"}):
            other_status[label] = other_status.get(label, 0) + 1

    # Triage progress. Untriaged is TestRail's default on a new case and a
    # blank means the field was never set, so both mean "nobody has assessed
    # this yet". Until triage completes, the automatable denominator can
    # still move in either direction.
    triaged = [
        c for c in critical
        if values_of(c, AUTOMATION_FIELD, automation_opts)
        - {AUTOMATION_UNTRIAGED}
    ]

    # Non-critical TAE work - Richard's metric 2 numerator.
    tae_non_critical = [
        c for c in cases
        if TAE_LABEL in label_names(c) and c not in critical
    ]

    # Duplicate titles inside the critical suite. A repeated title is only
    # redundancy when the cases sit in the SAME section - across sections it
    # usually means a legitimate second context (iPad vs iPhone, private vs
    # normal browsing) that the title alone does not carry.
    sections = api.get_all_sections(project_id, suite_id)

    by_title = {}
    for case in critical:
        by_title.setdefault(case["title"].strip().lower(), []).append(case)
    duplicates = {t: v for t, v in by_title.items() if len(v) > 1}

    # Compared by full path, not section id: two section records with the
    # same path are themselves a duplicate, and that is worth catching too.
    same_section = {
        title: group for title, group in duplicates.items()
        if len({sections.get(c.get("section_id"), c.get("section_id"))
                for c in group}) < len(group)
    }

    # --- Anomalies ---------------------------------------------------------
    # Each is a case worth a human look, not necessarily a mistake. Every
    # entry keeps the case's last-updated date: something touched today is
    # probably mid-edit, something untouched for weeks is probably forgotten.
    anomalies = {key: [] for key, _ in ANOMALY_CHECKS}

    def automation_label(case):
        return ", ".join(sorted(values_of(case, AUTOMATION_FIELD, automation_opts))) \
            or "blank"

    def flag(key, case, detail):
        anomalies[key].append({
            "id": case["id"],
            "detail": detail,
            "updated": case.get("updated_on"),
        })

    for case in tae_not_completed:
        flag("tae_not_completed", case, f"Automation: {automation_label(case)}")

    # Automation Coverage says Full but Automation was never set to
    # Completed. This is how four iOS cases went uncounted.
    if COVERAGE_FIELD in fields:
        coverage_opts = option_map(fields[COVERAGE_FIELD])
        for case in critical:
            if (COVERAGE_FULL in values_of(case, COVERAGE_FIELD, coverage_opts)
                    and not automation_is(case, AUTOMATION_COMPLETED)):
                flag("coverage_mismatch", case,
                     f"Coverage {COVERAGE_FULL}, Automation: {automation_label(case)}")
    else:
        print(f"  note: field '{COVERAGE_FIELD}' not found, coverage check "
              f"skipped. Run --discover to find its system name.",
              file=sys.stderr)

    # Variants of one test (same title, different section or config) where
    # one is on TAE and another still on legacy. Often legitimate - the
    # variants can carry different configs - but each one should be a
    # decision, not an oversight.
    for group in duplicates.values():
        done = [c for c in group if automation_is(c, AUTOMATION_COMPLETED)]
        on_tae = [c for c in done if TAE_LABEL in label_names(c)]
        on_legacy = [c for c in done if TAE_LABEL not in label_names(c)]
        if on_tae and on_legacy:
            pair = ", ".join(f"C{c['id']}" for c in on_tae)
            for case in on_legacy:
                flag("split_framework", case, f"legacy; variant {pair} is on TAE")

    # Critical cases whose Type is not Functional. Tracks the cleanup of
    # iOS cases filed as "Other" years ago.
    for case in critical:
        type_name = case_types.get(case.get("type_id"), "unknown")
        if type_name != EXPECTED_TYPE:
            flag("type_not_functional", case, f"Type: {type_name}")

    n_automatable = len(automatable)
    return {
        "date": date.today().isoformat(),
        "platform": platform,
        "full_suite": len(cases),
        "critical": len(critical),
        "unsuitable": len(unsuitable),
        "automatable": n_automatable,
        "automated": len(automated),
        "in_tae": len(in_tae),
        "in_legacy": len(in_legacy),
        "tae_not_completed": len(tae_not_completed),
        "not_yet_automated": n_automatable - len(automated),
        "remaining_to_tae": n_automatable - len(in_tae),
        "pct_automated": round(100 * len(automated) / n_automatable, 1)
        if n_automatable else 0.0,
        "pct_in_tae": round(100 * len(in_tae) / n_automatable, 1)
        if n_automatable else 0.0,
        "tae_non_critical": len(tae_non_critical),
        "triaged": len(triaged),
        "pct_triaged": round(100 * len(triaged) / len(critical), 1)
        if critical else 0.0,
        "duplicate_titles": len(duplicates),
        "dupes_same_section": len(same_section),
        "_other_status": other_status,
        "_duplicates": {
            title: [
                (c["id"], sections.get(c.get("section_id"), "?"))
                for c in group
            ]
            for title, group in sorted(duplicates.items())
        },
        "_dupes_same_section": sorted(same_section),
        "_anomalies": {k: sorted(v, key=lambda a: a["id"])
                       for k, v in anomalies.items()},
        **{f"anomaly_{k}": len(v) for k, v in anomalies.items()},
        # ID sets behind each headline number, saved to the state file so the
        # next run can say which cases moved.
        "_ids": {
            "critical": sorted(c["id"] for c in critical),
            "unsuitable": sorted(c["id"] for c in unsuitable),
            "automated": sorted(c["id"] for c in automated),
            "in_tae": sorted(c["id"] for c in in_tae),
        },
    }


# Cases worth a human look. Order is the order they print.
ANOMALY_CHECKS = [
    ("tae_not_completed", "TAE label, Automation not Completed"),
    ("coverage_mismatch", "Coverage Full, Automation not Completed"),
    ("split_framework", "Variant on legacy while its pair is on TAE"),
    ("type_not_functional", "Critical case not typed Functional"),
]

ROWS = [
    ("Full functional suite", "full_suite"),
    ("Critical identified so far", "critical"),
    ("Unsuitable for automation", "unsuitable"),
    ("Automatable critical", "automatable"),
    ("Automated (any framework)", "automated"),
    ("  in legacy", "in_legacy"),
    ("  in TAE", "in_tae"),
    ("Not yet automated", "not_yet_automated"),
    ("Remaining to 100% TAE", "remaining_to_tae"),
    ("% automated", "pct_automated"),
    ("% in TAE", "pct_in_tae"),
    ("TAE outside critical suite", "tae_non_critical"),
    ("Triaged", "triaged"),
    ("% triaged", "pct_triaged"),
    ("Repeated titles", "duplicate_titles"),
    ("  same section", "dupes_same_section"),
    ("Anomalies", None),
    ("  TAE label, not Completed", "anomaly_tae_not_completed"),
    ("  Coverage Full, not Completed", "anomaly_coverage_mismatch"),
    ("  Split framework in a pair", "anomaly_split_framework"),
    ("  Type not Functional", "anomaly_type_not_functional"),
]


def fmt_updated(ts):
    if not ts:
        return "unknown"
    day = date.fromtimestamp(ts)
    age = (date.today() - day).days
    when = "today" if age == 0 else f"{age}d ago"
    return f"{day.isoformat()} ({when})"


def report(results, show_repeats=False):
    platforms = [r["platform"] for r in results]
    width = max(len(label) for label, _ in ROWS) + 2
    header = "".ljust(width) + "".join(p.rjust(12) for p in platforms)
    print("\n" + header)
    print("-" * len(header))
    for label, key in ROWS:
        line = label.ljust(width)
        if key is not None:
            line += "".join(str(r[key]).rjust(12) for r in results)
        print(line)
    print()

    # Every automation status that is not Completed, so an unaccounted value
    # (Disabled, blank, a new option) is visible rather than buried.
    print("Automatable critical cases not marked Completed:")
    labels = sorted({k for r in results for k in r["_other_status"]})
    for label in labels:
        line = ("  " + label).ljust(width)
        line += "".join(
            str(r["_other_status"].get(label, 0)).rjust(12) for r in results
        )
        print(line)
    print()

    # Anomalies, each case with its detail and when it was last touched.
    # Long lists are capped; the full set is in the state file.
    CAP = 15
    any_found = False
    for key, title in ANOMALY_CHECKS:
        for r in results:
            items = r["_anomalies"][key]
            if not items:
                continue
            if not any_found:
                print("Anomalies:")
                any_found = True
            print(f"  {r['platform']}: {title} ({len(items)})")
            for a in items[:CAP]:
                print(f"    C{a['id']:<9} {a['detail']:<44} "
                      f"updated {fmt_updated(a['updated'])}")
            if len(items) > CAP:
                print(f"    +{len(items) - CAP} more")
    if any_found:
        print()

    # A repeated title in the SAME section is likely redundancy and always
    # prints. Across sections it is usually an intended variant (toolbar
    # placement, entry point), so those only list with --show-repeats.
    for r in results:
        for title in r["_dupes_same_section"]:
            group = r["_duplicates"][title]
            print(f'{r["platform"]}: SAME SECTION - "{title[:70]}"')
            for cid, section in group:
                print(f"    C{cid}  {section}")
    if show_repeats:
        for r in results:
            for title, group in r["_duplicates"].items():
                if title in r["_dupes_same_section"]:
                    continue
                print(f'{r["platform"]}: repeated title - "{title[:70]}"')
                for cid, section in group:
                    print(f"    C{cid}  {section}")
        print()


def load_state(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path, results):
    state = load_state(path)
    for r in results:
        state[r["platform"]] = {
            "date": r["date"],
            **r["_ids"],
            "anomalies": {k: [a["id"] for a in v]
                          for k, v in r["_anomalies"].items()},
        }
    with open(path, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)


MOVES = [
    ("critical", "added", "added to the critical suite"),
    ("critical", "removed", "removed from the critical suite"),
    ("automated", "added", "newly automated"),
    ("automated", "removed", "no longer marked automated"),
    ("in_tae", "added", "newly in TAE"),
    ("in_tae", "removed", "no longer in TAE"),
    ("unsuitable", "added", "newly flagged unsuitable"),
    ("unsuitable", "removed", "reassessed out of unsuitable"),
]


def compute_delta(state, r):
    """Which cases moved since the last saved run, as data.

    Returns None when there is no previous snapshot for this platform.
    Used by both the terminal report and latest.json.
    """
    prev = state.get(r["platform"])
    if not prev:
        return None

    changes = []
    for key, direction, label in MOVES:
        before = set(prev.get(key, []))
        now = set(r["_ids"][key])
        ids = sorted(now - before if direction == "added" else before - now)
        if ids:
            changes.append({"label": label, "ids": ids})

    # Anomalies that appeared or cleared. A snapshot from before these checks
    # existed has no "anomalies" key; skip rather than call everything new.
    anomaly_changes = []
    prev_anom = prev.get("anomalies")
    if prev_anom is not None:
        for key, title in ANOMALY_CHECKS:
            before = set(prev_anom.get(key, []))
            now = {a["id"] for a in r["_anomalies"][key]}
            for word, ids in (("new", sorted(now - before)),
                              ("cleared", sorted(before - now))):
                if ids:
                    anomaly_changes.append(
                        {"check": key, "title": title, "kind": word, "ids": ids})

    return {"since": prev["date"], "changes": changes,
            "anomaly_changes": anomaly_changes}


def show_delta(deltas):
    """Print the change report computed by compute_delta."""
    shown_any = False

    def ids_text(ids):
        text = ", ".join(f"C{i}" for i in ids[:12])
        return text + (f", +{len(ids) - 12} more" if len(ids) > 12 else "")

    for platform, d in deltas.items():
        if d is None:
            continue
        if not shown_any:
            print("Changes since the previous run:")
            shown_any = True
        lines = [f"    {len(c['ids'])} {c['label']}: {ids_text(c['ids'])}"
                 for c in d["changes"]]
        lines += [f"    {len(a['ids'])} {a['kind']} - {a['title']}: "
                  f"{ids_text(a['ids'])}" for a in d["anomaly_changes"]]
        print(f"  {platform} (since {d['since']})")
        print("\n".join(lines) if lines else "    no change")
    if shown_any:
        print()


def append_csv(path, results):
    """Append one dated row per platform.

    If this run has columns the file does not (a check was added since the
    file was started), the file is rewritten under the combined header, so
    no value ever lands under the wrong column.
    """
    path = Path(path)
    rows = [{k: v for k, v in r.items() if not k.startswith("_")}
            for r in results]
    new_fields = list(rows[0].keys())

    existing, old_fields = [], []
    if path.exists() and path.stat().st_size:
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            old_fields = reader.fieldnames or []
            existing = list(reader)

    if existing and old_fields == new_fields:
        with path.open("a", newline="") as fh:
            csv.DictWriter(fh, fieldnames=new_fields).writerows(rows)
    else:
        fields = old_fields + [f for f in new_fields if f not in old_fields]
        with path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, restval="")
            writer.writeheader()
            writer.writerows(existing)
            writer.writerows(rows)
    print(f"appended {len(rows)} rows to {path}")


def write_json(path, results, deltas, testrail_url):
    """Everything the dashboard needs about the latest run, in one file."""
    out = {
        # Bump when a field is renamed or removed, so readers can tell.
        "schema_version": JSON_SCHEMA_VERSION,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "testrail_url": testrail_url,
        "checks": [{"key": k, "title": t} for k, t in ANOMALY_CHECKS],
        "platforms": {},
    }
    for r in results:
        out["platforms"][r["platform"]] = {
            "suite_id": SUITES[r["platform"]],
            "metrics": {k: v for k, v in r.items() if not k.startswith("_")},
            "status_breakdown": r["_other_status"],
            "anomalies": r["_anomalies"],
            "delta": deltas.get(r["platform"]),
        }
    with open(path, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"wrote {path}")


# Each setting accepts either name, first match wins. The second names match
# the secrets already in mozilla-mobile/testops-tools, so the GitHub Action can pass them
# straight through; the first are what a local shell has been using.
CREDENTIALS = {
    "url": ("TESTRAIL_URL", "TESTRAIL_HOST"),
    "user": ("TESTRAIL_USER", "TESTRAIL_USERNAME"),
    "key": ("TESTRAIL_KEY", "TESTRAIL_PASSWORD"),
}


def resolve_credentials():
    """Read TestRail credentials from the environment.

    Never prints a value - only which variable names were looked for - so
    it is safe in an Action log even before GitHub's secret masking kicks in.
    """
    found, missing = {}, []
    for setting, names in CREDENTIALS.items():
        value = next((os.environ[n].strip() for n in names
                      if os.environ.get(n, "").strip()), None)
        if value is None:
            missing.append(" or ".join(names))
        found[setting] = value
    if missing:
        in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
        hint = ("Map the repository secrets into the step's env: block."
                if in_actions else "Export them in your shell first.")
        sys.exit("Missing TestRail credentials: " + "; ".join(missing)
                 + ". " + hint)

    # A host secret is often stored bare ("mozilla.testrail.io").
    url = found["url"]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/"), found["user"], found["key"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discover", action="store_true",
                        help="print field names and a sample case, then exit")
    parser.add_argument("--csv", metavar="PATH",
                        help="append a dated row per platform to this file")
    parser.add_argument("--platform", choices=list(SUITES),
                        help="limit to one platform")
    parser.add_argument("--state", metavar="PATH", default=STATE_FILE,
                        help=f"case-ID snapshot file (default {STATE_FILE})")
    parser.add_argument("--show-repeats", action="store_true",
                        help="list repeated titles across sections too "
                             "(same-section repeats always print)")
    parser.add_argument("--json", metavar="PATH",
                        help="write the latest run, anomalies and changes "
                             "as JSON for the dashboard")
    parser.add_argument("--no-state", action="store_true",
                        help="do not update the snapshot with this run")
    args = parser.parse_args()

    url, user, key = resolve_credentials()
    api = TestRail(url, user, key)

    if args.discover:
        discover(api)
        return

    suites = ({args.platform: SUITES[args.platform]}
              if args.platform else SUITES)
    results = [measure(api, name, sid) for name, sid in suites.items()]

    # Read the previous snapshot before the report, so the delta compares
    # against the last run rather than this one.
    previous = load_state(args.state)
    deltas = {r["platform"]: compute_delta(previous, r) for r in results}

    report(results, show_repeats=args.show_repeats)
    show_delta(deltas)

    if args.csv:
        append_csv(args.csv, results)
    if args.json:
        write_json(args.json, results, deltas, url)
    if not args.no_state:
        save_state(args.state, results)


if __name__ == "__main__":
    main()
