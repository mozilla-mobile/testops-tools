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

    # --- Scope to the LAST run only. A report can hold several `run started:`..`run finished:`
    # blocks (retries, or stale buffer bleed if a `logcat -c` didn't fully clear). Summing failures
    # across all of them caused false negatives (a prior failed attempt inflated the current verdict).
    # We evaluate the most recent run; earlier blocks only feed the flakiness signal below.
    starts = [m.start() for m in re.finditer(r"^run started:", full, re.M)]
    txt = full[starts[-1]:] if starts else full

    started = set(re.findall(r"started:\s*([A-Za-z0-9_]+)\s*\(", txt))
    ignored = set(re.findall(r"ignored:\s*([A-Za-z0-9_]+)\s*\(", txt))
    # failures reported by the LAST run block (not summed across the whole buffer)
    fails = [int(f) for f in re.findall(r"run finished:\s*\d+\s*tests?,\s*(\d+)\s*failed", txt)]
    failed_total = sum(fails)  # normally one finished-line in the last block

    # Flakiness signal — surface a retry WITHIN the current run instead of masking it.
    # Scope to the last block (txt), NOT the whole file: earlier blocks may be stale buffer bleed
    # (pre-`logcat -c`-fix artifacts) and their retries are not this run's. A `Started try #2+` inside
    # the current run means "passed on retry" = green-but-flaky. n_runs is informational only (whole-file).
    n_runs = len(starts)
    retried = bool(re.search(r"Started try #(?:[2-9]|\d\d)", txt))

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
        if name in ignored or rs == "SKIPPED":
            status, passed = "skipped", False
        elif rs == "FAILED":
            status, passed = "failed", False
        elif name not in started:
            status, passed = "not-run", False
        else:
            status, passed = "passed", True
        ok = ok and passed
        entry = {"name": name, "status": status, "passed": passed, "gradle": rs}
        if not passed and status in ("failed", "not-run"):
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
                lbl = {"skipped": "SKIPPED/ignored — NOT a pass", "failed": "FAILED in gradle log",
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
