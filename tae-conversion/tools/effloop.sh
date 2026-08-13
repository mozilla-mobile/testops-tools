#!/usr/bin/env bash
# effloop — build + run ONE ui/efficiency test via mozilla-central's mach, drop concise reports.
#
# Fenix in mozilla-central builds through `./mach gradle` (which sets up the JDK/Android env) from the
# repo root — NOT ./gradlew. The connected task both builds and runs the instrumented test on a device.
#
# Usage:  ./effloop.sh <TestClass|FQN|Class#method> [batch]
#   ./effloop.sh ToolbarTest                                  # whole class
#   ./effloop.sh ToolbarTest#verifyTheExpandedToolbarNewTabButtonTest   # ONE method — use this while
#                                                             # iterating on a single failure; the class
#                                                             # form re-runs everything and is much slower
#   ./effloop.sh org.mozilla.fenix.ui.OtherTest               # fully-qualified, outside the default pkg
#
# Writes into <ui-test-modernization>/conversion-runs/<batch>/ :
#   build-report.txt  compile verdict + errors (effbuild)
#   run-report.txt    run trace (effpretty), prefixed with a FAILURES block when anything failed
#   status.json       machine-readable outcome INCLUDING per-test pass/fail — read this first
#
# ── configure once (or export as env) ──────────────────────────────────────
REPO="${REPO:-$HOME/Workspace/firefox}"                 # mozilla-central root (where ./mach lives)
MACH_TASK="${MACH_TASK:-fenix:connectedDebugAndroidTest}"   # confirmed working task
MACH_ARGS="${MACH_ARGS:---stacktrace}"                      # extra gradle args (stacktrace ⇒ real errors)
TESTS_PKG="${TESTS_PKG:-org.mozilla.fenix.ui.efficiency.tests}"
OUT_ROOT="${OUT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)/conversion-runs}"   # default: tae-conversion/conversion-runs
# Gradle's own per-run JUnit XML. Authoritative for pass/fail; the logcat trace is for *why*.
RESULTS_DIR="${RESULTS_DIR:-$REPO/objdir-frontend/gradle/build/mobile/android/fenix/app/outputs/androidTest-results/connected/debug}"
TOOLS="$(cd "$(dirname "$0")" && pwd)"
# effpretty.py is NOT in this repo — it lives in-tree with the framework it renders, so resolve it under
# $REPO. It used to be called as "$TOOLS/effpretty.py", which only worked for checkouts that happened to have
# a local copy or symlink beside this script; anywhere else the renderer silently never ran, so run-report.txt
# came out empty and effverify had no input to judge (see HARNESS-GOTCHAS A24).
EFFPRETTY="${EFFPRETTY:-$REPO/mobile/android/fenix/app/src/androidTest/java/org/mozilla/fenix/ui/efficiency/devtools/effpretty/effpretty.py}"
[ -f "$EFFPRETTY" ] || EFFPRETTY="$TOOLS/effpretty.py"
# resolve adb the way effpretty does (effwatch's shell often lacks it on PATH)
ADB="${ADB:-$(command -v adb 2>/dev/null || echo "${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}/platform-tools/adb")}"
# ────────────────────────────────────────────────────────────────────────────
set -u
TEST_CLASS="${1:?usage: effloop.sh <TestClass|FQN|Class#method> [batch]}"; BATCH="${2:-adhoc}"
# accept a bare class in the default tests package, a fully-qualified name (has a dot), or either with
# a #method suffix — AndroidJUnitRunner takes "pkg.Class#method" verbatim.
case "$TEST_CLASS" in *.*) FQCLASS="$TEST_CLASS" ;; *) FQCLASS="$TESTS_PKG.$TEST_CLASS" ;; esac
OUT="$OUT_ROOT/$BATCH"; mkdir -p "$OUT"
cd "$REPO" || { echo "REPO not found: $REPO"; exit 2; }
[ -f "$EFFPRETTY" ] || { echo "effpretty.py not found at: $EFFPRETTY (set EFFPRETTY or REPO)"; exit 2; }

# Anything in RESULTS_DIR older than this is from a PREVIOUS run — never report it as this run's result.
RUN_START=$(date +%s)

echo "▶ ./mach gradle $MACH_TASK  (class=$TEST_CLASS)"
"$ADB" logcat -b all -c 2>/dev/null || "$ADB" logcat -c 2>/dev/null || true   # clear ALL buffers (avoid stale runs in the report)

# Attach the trace renderer BEFORE the build so the run streams line-by-line instead of appearing all at
# once when it is over. effpretty's `process()` flushes each line to BOTH stdout and --out, so whoever is
# watching this script (a terminal, or effwatch) follows the test live while the file fills in.
# `--mode watch` attaches to the running logcat; `--mode dump` (the old behaviour) can only snapshot after
# the fact, which is why nothing appeared until the class finished.
PRETTY_PID=""
cleanup_pretty() {
  [ -n "$PRETTY_PID" ] && kill "$PRETTY_PID" 2>/dev/null
  [ -n "$PRETTY_PID" ] && wait "$PRETTY_PID" 2>/dev/null
  PRETTY_PID=""
}
trap 'cleanup_pretty' EXIT INT TERM
python3 "$EFFPRETTY" capture --mode watch --out "$OUT/run-report.txt" &
PRETTY_PID=$!

./mach gradle "$MACH_TASK" $MACH_ARGS \
    -Pandroid.testInstrumentationRunnerArguments.class="$FQCLASS" 2>&1 \
    | tee "$OUT/raw-run.log" \
    | python3 "$TOOLS/effbuild.py" --scope efficiency --out "$OUT/build-report.txt"
COMPILE_OK=${PIPESTATUS[2]}        # effbuild exit: 0 = compiled clean, 1 = compile errors/inconclusive

sleep 2            # let the device's final lines drain into the stream before detaching
cleanup_pretty
trap - EXIT INT TERM
cat "$OUT/build-report.txt"

if [ "${COMPILE_OK:-1}" -eq 0 ]; then
  # Fall back to a snapshot if the live attach produced nothing (e.g. it lost the device mid-run) —
  # better a late trace than none. Buffers were cleared above, so this cannot pick up an older run.
  if [ ! -s "$OUT/run-report.txt" ]; then
    python3 "$EFFPRETTY" capture --mode dump --out "$OUT/run-report.txt" 2>/dev/null || true
  fi
  if [ -s "$OUT/run-report.txt" ]; then RAN=true; echo "▶ run trace → $OUT/run-report.txt"; else RAN=false; fi
else
  RAN=false
  echo "did not compile — no run captured (see build-report.txt / raw-run.log)" > "$OUT/run-report.txt"
  echo "✗ compile failed — skipped run"
fi

# ── outcome: parse gradle's JUnit XML into status.json + a FAILURES header on the trace ──────────────
# Without this, status.json says only "ran: true" (instrumentation started) and every consumer has to
# grep a multi-thousand-line trace to find out what actually passed.
COMPILED_JSON=$([ "${COMPILE_OK:-1}" -eq 0 ] && echo true || echo false)
python3 - "$OUT" "$BATCH" "$TEST_CLASS" "$COMPILED_JSON" "$RAN" "$RESULTS_DIR" "$RUN_START" <<'PY'
import glob, json, os, sys, time, xml.etree.ElementTree as ET

out, batch, test, compiled, ran, results_dir, run_start = sys.argv[1:8]
run_start = int(run_start)
status = {
    "batch": batch, "test": test,
    "compiled": compiled == "true", "ran": ran == "true",
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}

# Only trust XML written by THIS run; a stale file from a previous run is worse than no data.
xmls = [f for f in glob.glob(os.path.join(results_dir, "*.xml"))
        if os.path.getmtime(f) >= run_start - 5]
results, failed = [], []
tests = failures = skipped = 0
for f in xmls:
    try:
        root = ET.parse(f).getroot()
    except ET.ParseError:
        continue
    tests += int(root.get("tests") or 0)
    failures += int(root.get("failures") or 0)
    skipped += int(root.get("skipped") or 0)
    for tc in root.iter("testcase"):
        fails = tc.findall("failure")
        name = tc.get("name")
        if fails:
            msg = next((l.strip() for l in (fails[0].text or "").splitlines() if l.strip()), "")
            results.append({"name": name, "status": "fail"})
            failed.append({"name": name, "message": msg[:300]})
        elif tc.findall("skipped"):
            results.append({"name": name, "status": "skipped"})
        else:
            results.append({"name": name, "status": "pass"})

if xmls:
    status.update(tests=tests, failures=failures, skipped=skipped,
                  results=results, failed=failed)
    status["outcome"] = "pass" if failures == 0 and tests > 0 else ("fail" if failures else "no-tests")
else:
    status["outcome"] = "unknown"
    status["note"] = "no JUnit XML newer than this run in RESULTS_DIR"

with open(os.path.join(out, "status.json"), "w") as fh:
    json.dump(status, fh, indent=2)
    fh.write("\n")

# Prepend a failures block to the trace so the reason is at the TOP, not buried thousands of lines down.
trace = os.path.join(out, "run-report.txt")
if failed and os.path.exists(trace):
    with open(trace) as fh:
        body = fh.read()
    header = ["=" * 78, f"FAILURES ({len(failed)} of {tests})", "=" * 78]
    for fl in failed:
        header.append(f"  ✖ {fl['name']}")
        if fl["message"]:
            header.append(f"      {fl['message']}")
    header += ["=" * 78, ""]
    with open(trace, "w") as fh:
        fh.write("\n".join(header) + "\n" + body)

# One-line console summary.
if xmls:
    mark = "✅" if failures == 0 else "✗"
    print(f"{mark} {tests} test(s), {failures} failed, {skipped} skipped")
    for fl in failed:
        print(f"   ✖ {fl['name']}: {fl['message'][:100]}")
else:
    print("? no JUnit XML for this run — see build-report.txt")
PY

echo "▶ reports in $OUT"

# ── propagate a real exit code ───────────────────────────────────────────────────────────────────────
# Previously the script's last command was the echo above, so effloop ALWAYS exited 0 — even when gradle
# failed or tests failed. effwatch records that as `effloop_exit: 0`, so a red run was reported green to
# every consumer, and the only way to notice was to open status.json by hand.
#
# status.json is the source of truth here: it is parsed from gradle's JUnit XML and already carries the
# per-test verdict. Gradle's own exit code is deliberately not used as the primary signal — it is
# non-zero for a failed test AND for unrelated infrastructure problems, and it cannot distinguish
# "compiled but a test failed" from "did not compile", which callers need to tell apart.
#
# Exit codes:
#   0  compiled, ran, all tests passed
#   1  compiled and ran, but at least one test failed
#   2  compile failure (no test verdict possible)
#   3  compiled but produced no usable test verdict (no JUnit XML) — inconclusive, treat as failure
#   4  the test filter matched nothing — almost always a mistyped class/method, i.e. a caller error
#      rather than a red run, so it is worth distinguishing from 1 and 3
OUTCOME=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("outcome","unknown"))' \
    "$OUT/status.json" 2>/dev/null || echo unknown)
case "$OUTCOME" in
    pass) exit 0 ;;
    fail) echo "✗ effloop: tests failed (see $OUT/status.json)"; exit 1 ;;
    no-tests) echo "✗ effloop: no tests matched '$TEST_CLASS' — check the class/method name"; exit 4 ;;
    *)
        if [ "${COMPILE_OK:-1}" != "0" ]; then
            echo "✗ effloop: compile failure (see $OUT/build-report.txt)"; exit 2
        fi
        echo "✗ effloop: no usable test verdict (see $OUT/build-report.txt)"; exit 3
        ;;
esac
