#!/usr/bin/env python3
"""
effbuild — turn a huge Gradle/Kotlin build log into a concise, targeted report.

The build-side analog of effpretty: pipe a `./gradlew ... assemble...AndroidTest` log through it and get a
one-line verdict plus only the compile errors (path:line:col message), so the AI loop reads signal, not
thousands of lines of daemon/download/task noise.

Usage:
  ./gradlew :app:assembleFenixDebugAndroidTest 2>&1 | python3 effbuild.py
  python3 effbuild.py build.log --out build-report.txt --scope efficiency
Exit code: 0 = build succeeded (no errors), 1 = errors / build failed.
Options: --scope efficiency (only errors under ui/efficiency), --warnings (include w:), --max N.
"""
import sys, re, argparse, json

# Kotlin: "e: file:///abs/Foo.kt:12:34 message"  and legacy "e: /abs/Foo.kt: (12, 34): message"
E1 = re.compile(r'^(e|w):\s+(?:file://)?(/[^:]+\.kts?):(\d+):(\d+):?\s*(.*)$')
E2 = re.compile(r'^(e|w):\s+(?:file://)?(/[^:]+\.kts?):\s*\((\d+),\s*(\d+)\):\s*(.*)$')

def parse(lines):
    diags = []            # (level, path, line, col, msg)
    gradle_fail = []      # "What went wrong" block
    verdict = None        # "SUCCESSFUL" | "FAILED"
    grabbing = False
    for ln in lines:
        s = ln.rstrip("\n")
        m = E1.match(s) or E2.match(s)
        if m:
            diags.append((m.group(1), m.group(2), int(m.group(3)), int(m.group(4)), m.group(5).strip()))
            continue
        if s.startswith("BUILD SUCCESSFUL"): verdict = "SUCCESSFUL"
        elif s.startswith("BUILD FAILED"): verdict = "FAILED"
        if s.startswith("* What went wrong:"): grabbing = True; gradle_fail.append(s); continue
        if grabbing:
            if s.startswith("* Try:") or s.startswith("BUILD ") or s.strip() == "":
                grabbing = False
            else:
                gradle_fail.append(s)
        if re.search(r"> Task .*(FAILED)$", s):
            gradle_fail.append(s)
    return diags, gradle_fail, verdict

def short(path, scope):
    i = path.find("ui/efficiency/")
    return path[i:] if i >= 0 else path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile", nargs="?")
    ap.add_argument("--out"); ap.add_argument("--scope", choices=["all", "efficiency"], default="all")
    ap.add_argument("--warnings", action="store_true"); ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--json", action="store_true", help="emit a structured JSON verdict on stdout")
    a = ap.parse_args()
    lines = open(a.logfile, errors="ignore") if a.logfile else sys.stdin
    diags, gradle_fail, verdict = parse(list(lines))

    errs = [d for d in diags if d[0] == "e"]
    warns = [d for d in diags if d[0] == "w"]
    if a.scope == "efficiency":
        errs = [d for d in errs if "ui/efficiency/" in d[1]] or errs  # keep all if none in-scope (a dep broke)
        warns = [d for d in warns if "ui/efficiency/" in d[1]]

    # Classify honestly: compile error vs test-task failure vs build-infra failure vs inconclusive.
    failing = re.findall(r"Task (:\S+)\s+FAILED", "\n".join(gradle_fail))
    is_test = any(re.search(r"connected|androidtest|test$", t, re.I) for t in failing)
    if errs:
        head = f"❌ COMPILE FAILED — {len(errs)} Kotlin error(s)"; compiled = False
    elif verdict == "SUCCESSFUL":
        head = "✅ BUILD OK"; compiled = True
    elif is_test:
        head = "✅ Compiled — ❌ test task failed (" + ", ".join(failing) + "); see run-report"; compiled = True
    elif failing or verdict == "FAILED" or gradle_fail:
        head = ("❌ BUILD FAILED at " + (", ".join(failing) or "a Gradle task") +
                " — no Kotlin compile errors; build-infra/config, not the test code"); compiled = False
    else:
        head = "⚠ INCONCLUSIVE — no 'BUILD SUCCESSFUL' seen (toolchain/config? check raw-run.log)"; compiled = False
    if a.warnings and warns:
        head += f"  [{len(warns)} warning(s)]"
    out = [head]
    if errs:
        out.append("")
        for lvl, p, l, c, msg in errs[:a.max]:
            out.append(f"  {short(p, a.scope)}:{l}:{c}  {msg}")
        if len(errs) > a.max:
            out.append(f"  … +{len(errs)-a.max} more error(s)")
    if a.warnings and warns:
        out.append("")
        for lvl, p, l, c, msg in warns[:a.max]:
            out.append(f"  (w) {short(p, a.scope)}:{l}:{c}  {msg}")
    if not errs and gradle_fail:
        out.append("")
        out.append("Gradle failure (non-compile):")
        for g in gradle_fail[:20]:
            out.append("  " + g.strip())
    text = "\n".join(out) + "\n"
    if a.out:
        open(a.out, "w").write(text)   # the human report file is always written for the run dir
    if a.json:
        print(json.dumps({
            "tool": "effbuild", "ok": compiled, "verdict": head,
            "errors": [{"path": short(p, a.scope), "line": l, "col": c, "msg": msg}
                       for (_lvl, p, l, c, msg) in errs],
            "error_count": len(errs), "warning_count": len(warns),
            "failing_tasks": failing,
            "gradle_failure": [g.strip() for g in gradle_fail[:20]] if (not errs and gradle_fail) else [],
        }))
    else:
        sys.stdout.write(text)
    sys.exit(0 if compiled else 1)

if __name__ == "__main__":
    main()
