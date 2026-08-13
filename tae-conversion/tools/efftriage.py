#!/usr/bin/env python3
"""
efftriage — map a failed conversion run to the gotcha that explains it.

HARNESS-GOTCHAS is at 57 entries and CONVERSION-LESSONS ~40. Nobody recalls that mid-debug, so the
same failures get re-derived on device at 1-2 cycles each with the answer already written down. This
reads the run the loop already produced and names the likely cause, with the gotcha ID to go read.

Read-only: it never touches the tree or the device, so it is safe to run on every failure.

Usage:
  efftriage.py <batchdir> [--json]

Two rules of triage are built in, because they are the ones people get wrong:
  1. Read the FIRST attempt's first failure, not the reported one. A failed attempt leaves state
     behind, so attempt 2 usually dies somewhere later and far more confusingly (lesson: 3 device
     cycles were once burned on an attempt-2 artifact).
  2. status.json is authoritative for pass/fail; the trace explains WHY (lesson G5). A green
     effverify next to a non-zero effloop_exit means believe the exit code (gotcha A37).
"""
import json, os, re, sys

# (id, gotcha, one-line cause, what to do) keyed off patterns seen in real run reports.
# Ordered most-specific first: the first rule that matches a failure window wins the headline.
RULES = [
    (
        "T0", "A42/A41",
        "an absence assertion never came true — the selector is probably matching a different surface",
        "'expected to disappear but is still visible' usually means the selector also matches something "
        "else on screen (the Pocket sponsored story owns its own 'Sponsored' label), or it matches a node "
        "that legitimately stays. Read the dump for WHAT matched, then scope the selector to its container "
        "with COMPOSE_ON_ALL_NODES_BY_TAG_WITH_CHILD_TEXT_ON_FIRST.",
        # match the TRACE phrasing (what mozWaitUntilAbsent / mozVerifyElementStaysAbsent log), not the
        # thrown-exception wording — the latter only appears in the FAILURES header and the stack.
        lambda w: re.search(r"still present after \d+ms|appeared before \d+ms elapsed", w)
        or "was expected to disappear but is still visible" in w,
    ),
    (
        "T1", "A39",
        "an arrival check was satisfied by an element BEHIND an overlay",
        "The run reported arrival on a page it never reached, so a later step failed instead. After a "
        "query submit use mozWaitUntilAbsent(TOOLBAR_IN_EDIT_MODE) before the next hop; when backing "
        "out, anchor on something genuinely occluded (MAIN_MENU_BUTTON), not HOMEPAGE_VIEW.",
        lambda w: re.search(r"already (visible|loaded)", w) and re.search(r"\[ERR\].*(Enter text failed|Click .* failed)", w),
    ),
    (
        "T2", "A22/A27",
        "UiObject.click() returned false for a click that probably landed",
        "clickAndSync reports a slow-but-successful click as a failure (a dialog dismissal, a toolbar "
        "swap that staled the node). Use mozClickIfPresent, or a UiObject2 strategy "
        "(UIAUTOMATOR2_BY_TEXT / UIAUTOMATOR2_BY_RAW_RES).",
        lambda w: "Failed to click UiObject" in w,
    ),
    (
        "T3", "mozEnterText locate",
        "mozEnterText's locate reported success on a Compose node that does not exist",
        "'found (0.0 ms)' is not evidence: mozGetElement returns the lazy SemanticsNodeInteraction "
        "without asserting. Only mozVerify / mozWaitUntilAbsent do a real assertExists + "
        "assertIsDisplayed. Put an explicit mozVerify before typing.",
        lambda w: re.search(r"found \(0\.0 ms\)", w) and "Enter text failed" in w,
    ),
    (
        "T4", "A41",
        "an AMBIGUOUS Compose match was reported as 'not found'",
        "COMPOSE_BY_TEXT resolves through the singular onNodeWithText, which throws when more than one "
        "node matches; the verb swallows that and says absent. Use COMPOSE_BY_TEXT_SUBSTRING, or scope "
        "to a container with COMPOSE_ON_ALL_NODES_BY_TAG_WITH_CHILD_TEXT_ON_FIRST.",
        lambda w: re.search(r"Expected exactly '1' node|expected 1, found|Can't retrieve node at index", w),
    ),
    (
        "T5", "A9/F1",
        "a non-application window was over the app when the element was 'not found'",
        "A system overlay (stylus prompt, permission dialog, keyboard) masks as absence. Read the "
        "[windows] dump block: it names the blocking window. dismissKnownOverlaysIfPresent covers the "
        "known ones; a new one needs adding there.",
        # The status bar is itself a SYSTEM window, so the "non-application window(s) present" warning
        # appears in nearly every dump and this rule used to fire on almost any not-found. Require that
        # the app does NOT hold focus: if an APPLICATION window is active+focused, nothing is masking it.
        lambda w: "non-application window(s) present" in w and "not found" in w
        and not re.search(r"type=APPLICATION \[[^\]]*focused", w),
    ),
    (
        "T6", "A40",
        "a long press behaved as a TAP and opened the item",
        "UiObject.longClick() is not held long enough for some View rows, so the row treats it as a "
        "click. Select the row with an ESPRESSO_* strategy so mozLongClick goes through Espresso's "
        "longClick(), which honours the platform long-press timeout.",
        lambda w: "Long clicked" in w and re.search(r"\[ERR\]", w),
    ),
    (
        "T7", "A29/A30",
        "a stale PageStateTracker sent navigation down a destructive path",
        "findPath started from the page the tracker still believed you were on. A SearchBar->anything "
        "path TYPES A URL; a Browser->Home path clicks 'New tab'. Re-anchor with an explicit "
        "navigateToPage on the page you are actually on before the next hop.",
        lambda w: re.search(r"Navigation path found from '(SearchBarComponent|BrowserPage)'", w)
        and re.search(r"EnterText|New tab", w),
    ),
    (
        "T8", "A3/A42",
        "a text assertion missed because of the merged-vs-unmerged tree, or matched the wrong surface",
        "mozGetAllElements queries the MERGED tree and a tagged Box does not merge its descendants, so "
        "a caption on a child is invisible to a tag-scoped text query. Conversely a bare text match can "
        "hit an unrelated surface (the Pocket sponsored story owns its own 'Sponsored' label). Assert "
        "the text node directly, or scope to the container with a tag+child-text strategy.",
        lambda w: re.search(r"No '.*' (found )?containing text", w),
    ),
    (
        "T9", "A6",
        "a page-arrival check timed out — the most common failure shape",
        "The named anchor never appeared. Check the requiredForPage selectors cover this runtime state "
        "(gotcha B7): a layout variant, an empty-vs-populated list, or a different entry point often "
        "needs a second anchor.",
        lambda w: re.search(r"Navigation to '.*' failed", w)
        or (re.search(r"not visible yet", w) and re.search(r"\[ERR\].*not found after \d+ms", w)),
    ),
    (
        "T14", "A46",
        "a checked-state assertion failed on a node that does not carry the state",
        "Compose toggle/radio rows put the state on the row as `semantics { selected = ... }` and blank "
        "the Switch with clearAndSetSemantics, so no ToggleableState exists and mozVerifyElementIsChecked "
        "can never pass — assert with mozVerifyElementIsSelected. The state also lives on the MERGED row, "
        "so COMPOSE_BY_TEXT (which forces useUnmergedTree) resolves a stateless descendant: use "
        "COMPOSE_BY_TEXT_MERGED. A surviving testTag on the switch/radio icon is a decoy; it is set before "
        "the clearAndSetSemantics that strips the state. Read the dump these verbs now emit.",
        # The [ERR] marker is required. Without it this matched the `[CMD] Verifying ... is checked...`
        # and `[OK] ... is checked` lines of runs that PASSED that assertion and failed elsewhere, and it
        # stole the diagnosis from two unrelated failures.
        lambda w: re.search(r"\[ERR\][^\n]*' is (?:not )?checked", w),
    ),
    # LAST on purpose, and deliberately narrow. An earlier, looser version of this rule keyed on
    # "not found", which appears in almost every failing trace, and it stole the diagnosis from six
    # other rules. It now requires the group-level failure line together with the short-circuit, and
    # sits at the end so anything more specific wins first.
    (
        "T13", "A45",
        "the arrival check passed on the WRONG screen, so navigateToPage short-circuited and never "
        "performed its steps",
        "'already visible/already loaded' followed by a group-level miss means a requiredForPage anchor "
        "also matches the page you were coming FROM — typically a parent Settings screen carrying a row "
        "with the destination's own title, or a generic control like Navigate up. mozIsOnPageNow() then "
        "reports arrival before any click happens. Pick an anchor that exists ONLY on the destination "
        "(and needs no scrolling); read the [uiautomator] block to confirm which screen you were on.",
        lambda w: re.search(r"already (?:visible|loaded)", w)
        and "missing required elements" in w,
    ),
]


def read(p):
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def attempts(report):
    """Split the trace per RetryTestRule attempt. Attempt 1 is the one that matters."""
    marks = [m.start() for m in re.finditer(r"RetryTestRule: Started try #\d+", report)]
    if not marks:
        return [report] if report.strip() else []
    return [report[a:b] for a, b in zip(marks, marks[1:] + [len(report)])]


def failure_windows(attempt, before=60, after=25):
    """Text around each [ERR] line — rules match on the window, not the bare line, because the cause
    is usually in the preceding steps rather than the failing one."""
    lines = attempt.splitlines()
    out = []
    for i, l in enumerate(lines):
        if "[ERR]" in l:
            out.append((i + 1, "\n".join(lines[max(0, i - before):i + after])))
    return out


def triage(batch):
    report, status_raw = read(os.path.join(batch, "run-report.txt")), read(os.path.join(batch, "status.json"))
    # Every key main() reads is initialised here: an early return below must not be able to
    # leave one unset, which is how a bad path turned into a KeyError traceback.
    res = {"tool": "efftriage", "batch": batch, "findings": [], "notes": [],
           "outcome": "unknown", "failed": [], "retried": False}

    # A path that does not exist is a mistyped batch name, not a harness problem. Without this it fell
    # through to the A24 "run-report.txt is missing" diagnosis and sent the reader off to check effpretty
    # resolution and pull dumps off the device, none of which has anything to do with a typo.
    if not os.path.isdir(batch):
        res["outcome"] = "no-such-batch"
        res["notes"].append(
            f"no such batch directory: {batch}. Check the name against `ls conversion-runs/`; this is a "
            "bad path, not a failed run."
        )
        return res

    try:
        status = json.loads(status_raw) if status_raw else {}
    except json.JSONDecodeError:
        status = {}
    res["outcome"] = status.get("outcome", "unknown")
    res["failed"] = status.get("failed", [])

    if not report.strip():
        res["notes"].append(
            "A24: run-report.txt is missing or empty, so there is no trace to triage and effverify has no "
            "input. Take the verdict from status.json and read dumps off the device with "
            "`adb logcat -d -s EffScreenDump:I`. If this is a clean checkout, check effpretty resolves "
            "(effloop resolves it under $REPO; override with EFFPRETTY=)."
        )
        return res

    # A compile failure is stated outright in status.json, so there is never a reason to answer
    # "no rule matched" for one and send the reader hunting through a trace that was never produced.
    if status.get("compiled") is False:
        res["findings"].append({
            "rule": "T12", "gotcha": "A24", "line": 0,
            "cause": "the test did not COMPILE, so no run happened and there is no trace to read",
            "fix": "Read build-report.txt — effloop puts the Kotlin errors there with file:line. "
                   "run-report.txt is empty by design here, and effloop exits 2.",
        })
        return res

    # A SKIP IS NOT A PASS (gotcha A44). Read the per-test statuses rather than trusting
    # status.json's `outcome`, because an older effloop scored an all-skipped run as `pass` — so the
    # field that should raise the alarm is exactly the one that was lying.
    skipped_tests = [r.get("name") for r in status.get("results", []) if r.get("status") == "skipped"]
    if skipped_tests:
        res["skipped"] = skipped_tests
        verified = [r for r in status.get("results", []) if r.get("status") == "pass"]
        res["findings"].append({
            "rule": "T11", "gotcha": "A44", "line": 0,
            "cause": ("every test was SKIPPED, so nothing was verified"
                      if not verified else
                      f"{len(skipped_tests)} test(s) were SKIPPED, so the verdict is incomplete")
                     + ": " + ", ".join(t for t in skipped_tests if t),
            "fix": "A skipped test asserts nothing and must not be read as green. Find the gate that "
                   "held it back — an Assume()/assumeTrue in the test or its rule, a Nimbus feature "
                   "flag, a pref, or absent hardware — and either satisfy it or drive the feature from "
                   "the test. Cross-check effverify, which scores a skip as passed=false.",
        })

    if re.search(r"^CRASH:", report, re.M):
        crash = re.search(r"^CRASH: (.+)$", report, re.M)
        res["findings"].append({
            "rule": "T10", "gotcha": "A37", "line": 0,
            "cause": "the test CRASHED (uncaught exception), it did not fail an assertion"
                     + (f": {crash.group(1)[:120]}" if crash else ""),
            "fix": "Fix the crash, not the assertions. Note this is the mode that also fools a stale "
                   "effverify into reporting clean — cross-check status.json and effloop_exit.",
        })
        res["notes"].append(
            "A37: this run contains CRASH: lines, i.e. a test died from an uncaught exception rather than a "
            "failed assertion. Cross-check status.json — and if effverify says clean while effloop_exit is "
            "non-zero, believe the exit code."
        )

    # Whenever a selector did not resolve, point at the dump tool. It already exists in-tree and is easy to
    # miss: without it the reflex is to provoke a failure with a throwaway assertion just to get a dump,
    # which costs a device cycle per question and is how several selectors were authored the slow way.
    if re.search(r"\[ERR\][^\n]*not found", report):
        res["notes"].append(
            "A selector did not resolve. Author selectors against a live dump rather than inferring them "
            "from legacy robots, whose locators are often stale: queue "
            '{"test_class": "org.mozilla.fenix.ui.efficiency.devtools.EffScreenDumpRunner", '
            '"batch": "effdump", "mach_args": '
            '"-Pandroid.testInstrumentationRunnerArguments.effdump.page=<pageContextProperty>"} '
            "and read the EFF_SCREEN_DUMP back with effpretty. Graph-navigable pages only — a "
            "launch-reached page such as customTabs has no nav edge, so dump it from within a test instead."
        )

    atts = attempts(report)
    retried = bool(re.search(r"Started try #(?:[2-9]|\d\d)", report))
    res["retried"] = retried
    if retried:
        res["notes"].append(
            "This report contains a RETRY. Everything below is from the FIRST attempt: a failed attempt "
            "leaves state behind, so later attempts die somewhere later and more confusingly."
        )

    # A green single-attempt run must not be handed a failure diagnosis. Traces routinely carry
    # non-fatal [ERR] lines — nav-graph polling ("not visible yet") and tolerated absence checks — and
    # the rules below would otherwise invent a cause for a run that is fine, which trains the reader to
    # ignore the tool. Two deliberate exceptions: a RETRY pass, where attempt 1 really did fail and
    # clean=false means flaky-not-done, and an already-recorded CRASH finding, because crash-mode is
    # exactly the case where `outcome: pass` is itself the lie (MTE-5822).
    if res["outcome"] == "pass" and not retried and not res["findings"]:
        nonfatal = len(re.findall(r"^\s*\[ERR\]", report, re.M))
        if nonfatal:
            res["notes"].append(
                f"This run PASSED on its first attempt. Its trace contains {nonfatal} non-fatal [ERR] "
                "line(s), which is normal (nav-graph polling, tolerated absence checks) and is NOT "
                "triaged. If you expected a failure here, check status.json rather than the trace."
            )
        return res

    if res["outcome"] == "pass" and retried:
        res["notes"].append(
            "This run PASSED ONLY ON RETRY — flaky, which the campaign counts as NOT done (clean=false). "
            "The diagnosis below is the first attempt's real failure, not a hard failure of this run."
        )

    for lineno, window in failure_windows(atts[0]) if atts else []:
        for rid, gotcha, cause, fix, match in RULES:
            try:
                hit = match(window)
            except re.error:
                hit = False
            if hit:
                res["findings"].append(
                    {"rule": rid, "gotcha": gotcha, "line": lineno, "cause": cause, "fix": fix}
                )
                break  # most-specific rule wins for this failure

    # de-dup repeated identical diagnoses, keeping the earliest occurrence
    seen, uniq = set(), []
    for f in res["findings"]:
        if f["rule"] not in seen:
            seen.add(f["rule"])
            uniq.append(f)
    res["findings"] = uniq
    return res


def _tae_version():
    """Version of the whole tae-conversion toolchain (tools + docs are stamped together).

    realpath, not __file__: these tools are commonly invoked through symlinks from another checkout's
    tools/ dir, and an unresolved path would look for VERSION in the wrong repo and report "unknown"
    exactly where a staleness check matters most.
    """
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "VERSION")
    try:
        return open(p).read().strip()
    except OSError:
        return "unknown"


def main():
    if "--version" in sys.argv[1:]:
        print(f"{os.path.basename(__file__)} \u2014 tae-conversion {_tae_version()}")
        sys.exit(0)
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv[1:]
    if not args:
        print("usage: efftriage.py <batchdir> [--json]")
        sys.exit(2)
    res = triage(args[0])

    if as_json:
        print(json.dumps(res))
        sys.exit(0)

    print(f"efftriage — {res['batch']}  (outcome: {res['outcome']})")
    for f in res["failed"]:
        print(f"  ✖ {f.get('name')}: {f.get('message', '')[:160]}")
    for n in res["notes"]:
        print(f"  ⚠ {n}")
    if not res["findings"]:
        if res["outcome"] == "no-such-batch":
            pass  # the note above already says it, and there is no run to comment on
        elif res["outcome"] == "pass":
            print("  run passed — nothing to triage")
        else:
            print("  no rule matched — triage by hand, and add a rule (MTE-5827) once you know why")
    for f in res["findings"]:
        print(f"\n  [{f['rule']}] line {f['line']} — gotcha {f['gotcha']}")
        print(f"      cause: {f['cause']}")
        print(f"      fix:   {f['fix']}")
    sys.exit(0)


if __name__ == "__main__":
    main()
