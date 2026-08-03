#!/usr/bin/env python3
"""
effverify — mechanical DONE-GATE for a converted test.

"Green gradle + 0 failed" is NOT proof a test passed: an @Ignore'd/SKIPPED test also produces 0
failed. This confirms each EXPECTED test actually executed and passed:
  - appears in a `started: <name>(...)` line (it ran),
  - is NOT in any `ignored: <name>(...)` line (it wasn't skipped),
  - lives in a run whose `run finished:` reports 0 failed,
  - and (cross-check) is not marked SKIPPED/FAILED in the raw gradle log.

Usage:
  effverify.py <batchdir> <TestNameA> [TestNameB ...]
     <batchdir> holds run-report.txt (+ optionally raw-run.log). Test names are the bare method names.
Exit 0 only if every expected test is confirmed PASSED; non-zero otherwise.
"""
import os, re, sys, json

def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if len(args) < 2:
        print("usage: effverify.py [--json] <batchdir> <TestName> [TestName ...]"); sys.exit(2)
    batch, expected = args[0], args[1:]
    rr = os.path.join(batch, "run-report.txt")
    raw = os.path.join(batch, "raw-run.log")
    if not os.path.isfile(rr):
        if as_json:
            print(json.dumps({"tool": "effverify", "ok": False, "batch": batch,
                              "error": "no run-report.txt (did it compile/run?)", "tests": []}))
        else:
            print(f"✖ no run-report.txt in {batch} (did it compile/run?)")
        sys.exit(1)
    full = open(rr, encoding="utf-8", errors="ignore").read()

    # --- Evaluate EVERY run block, not just the last one.
    #
    # A single class request legitimately produces many blocks: one for the class run, then one per
    # test that the retry rule re-ran individually. Scoping to the last block (the previous behaviour)
    # read the verdict off whichever 1-test re-run happened to land last, which produced three distinct
    # wrong answers:
    #   - every test not in that final block was reported "not-run", even though it ran and passed;
    #   - `failed_total` came from that block alone, so a real failure recorded in an earlier block was
    #     reported as 0 failures — a green verdict for a red test;
    #   - `retried` only looked at the last block, so a report with 8 runs of a 7-test class still said
    #     retried=false.
    #
    # Per-test truth comes from the report's own `failed:` / `ignored:` / `started:` markers, aggregated
    # across all blocks. A test that failed in ANY block is not clean, even if a later re-run passed —
    # that is precisely the retry-pass the done-gate exists to catch.
    starts = [m.start() for m in re.finditer(r"^run started:", full, re.M)]
    bounds = starts + [len(full)]
    blocks = [full[bounds[i]:bounds[i + 1]] for i in range(len(starts))] or [full]

    def names(pattern, text):
        return set(re.findall(pattern + r":\s*([A-Za-z0-9_]+)\s*\(", text))

    started, ignored, failed_names = set(), set(), set()
    passed_in_some_block = set()
    for b in blocks:
        b_started, b_ignored, b_failed = names("started", b), names("ignored", b), names("failed", b)
        started |= b_started
        ignored |= b_ignored
        failed_names |= b_failed
        # Ran in this block and this block did not record it failing → it passed here.
        passed_in_some_block |= (b_started - b_failed - b_ignored)

    # Count actual per-test failures observed anywhere in the report, not one block's summary line.
    failed_total = len(failed_names)

    n_runs = len(starts)
    # Retried if the harness logged a second attempt anywhere, or a test both failed and later passed.
    #
    # Deliberately NOT keyed on n_runs > 1: effloop emits one block per test after the class run as
    # normal behaviour, so a clean 6-test class legitimately reports 7 blocks. Treating that as a retry
    # marked every multi-test run flaky.
    retried = (
        bool(re.search(r"Started try #(?:[2-9]|\d\d)", full)) or
        bool(failed_names & passed_in_some_block)
    )

    # gradle raw cross-check (authoritative per-test SKIPPED/FAILED)
    raw_txt = open(raw, encoding="utf-8", errors="ignore").read() if os.path.isfile(raw) else ""
    def raw_status(name):
        m = re.search(r">\s*" + re.escape(name) + r"\[[^\]]*\]\s*(SKIPPED|FAILED|PASSED)", raw_txt)
        return m.group(1) if m else None

    def failure_excerpt(name, cap_lines=30, cap_chars=1800):
        """Capped exception+frames for a FAILED test, so a failure never needs a raw-log read.
        Pull from the gradle raw log (has the stack); fall back to the run trace's [ERR] lines."""
        src = raw_txt or txt
        # anchor on the test's FAILED marker if present, else its name
        anchor = re.search(r"(?:>\s*)?" + re.escape(name) + r"\b.*?(?:FAILED|Exception|Error)", src, re.S)
        start_i = anchor.start() if anchor else (src.find(name) if name in src else -1)
        if start_i < 0:
            # last resort: the run-trace error lines from the last run block
            errs = re.findall(r"^\s*\[ERR\].*$", txt, re.M)
            return "\n".join(errs[:cap_lines])[:cap_chars] or None
        chunk = src[start_i:start_i + cap_chars * 3]
        lines = [l for l in chunk.splitlines() if l.strip()][:cap_lines]
        return "\n".join(lines)[:cap_chars] or None

    ok = True
    tests = []
    for name in expected:
        rs = raw_status(name)
        # Order matters. The report's own `failed:` marker is checked BEFORE falling through to
        # "started and not otherwise flagged → passed": previously a test whose gradle line did not
        # match raw_status() but which appeared in `started` was reported passed outright, so a genuine
        # failure came back green whenever that regex missed.
        if name in ignored or rs == "SKIPPED":
            status, passed = "skipped", False
        elif name in failed_names or rs == "FAILED":
            # Failed at least once. If a later block ran it green, it is a retry-pass: usable but flaky,
            # never "clean". Kept out of `passed` so `ok` stays false and the caller cannot mistake it
            # for done.
            if name in passed_in_some_block:
                status, passed = "retry-pass", False
            else:
                status, passed = "failed", False
        elif name not in started:
            status, passed = "not-run", False
        else:
            status, passed = "passed", True
        ok = ok and passed
        entry = {"name": name, "status": status, "passed": passed, "gradle": rs}
        if not passed and status in ("failed", "not-run", "retry-pass"):
            exc = failure_excerpt(name)
            if exc:
                entry["failure_excerpt"] = exc
        tests.append(entry)
    if failed_total > 0:
        ok = False
    clean = ok and not retried  # a retry-pass is green-but-flaky, not "done"
    if as_json:
        print(json.dumps({"tool": "effverify", "ok": ok, "clean": clean, "batch": batch,
                          "failed_total": failed_total, "runs": n_runs, "retried": retried,
                          "tests": tests}))
    else:
        print(f"effverify — {batch}")
        for t in tests:
            if t["passed"]:
                print(f"  ✔ {t['name']}: executed" + (f" (gradle:{t['gradle']})" if t["gradle"] else ""))
            else:
                lbl = {"skipped": "SKIPPED/ignored — NOT a pass", "failed": "FAILED",
                       "retry-pass": "FAILED then passed on a re-run — flaky, NOT done",
                       "not-run": "never executed (no 'started:' line)"}[t["status"]]
                print(f"  ✖ {t['name']}: {lbl}")
        if failed_total > 0:
            print(f"  ✖ last run reports {failed_total} failed test-run(s)")
        if retried:
            print(f"  ⚠ retry detected (runs={n_runs}) — passed-on-retry is flaky, NOT clean-done")
        print("RESULT:", ("ALL PASS ✅" if clean else "PASS BUT FLAKY ⚠️") if ok else "NOT DONE ❌")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
