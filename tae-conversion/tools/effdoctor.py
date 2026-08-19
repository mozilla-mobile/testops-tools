#!/usr/bin/env python3
"""
effdoctor — read-only preflight. Run it at the START of a session, before queueing anything.

Slice 1: the TOOLCHAIN MAP. The eff* tools exist once but are reachable from two checkouts
(`testops-tools/tae-conversion/tools` and `ui-test-modernization/tools`, where the entries are
symlinks into the former). `effwatch.sh` computes its queue from `dirname $0`, which does NOT resolve
symlinks — so the queue it watches is a function of the path it was LAUNCHED from, while the tools
themselves are identical either way. Drop a request in the other checkout's queue and it sits there
forever: nothing consumes it, no error is printed, and the run simply never happens.

That has now bitten us more than once, so this prints where the live watcher is actually listening
rather than leaving anyone to remember which checkout was used this time.

Note the subtlety that `dirname $0` is relative when effwatch was launched by a relative path: the
queue is then a function of that PROCESS's cwd, which is why the cwd is read from the process itself
(see proc_cwd) instead of being resolved against effdoctor's. A queue path that does not exist on
disk is reported as a failure, because pointing anyone at one is worse than saying nothing.

Usage:
  effdoctor.py [--json]

Exit 0 if clean, 1 if anything needs attention. Never modifies anything.
"""
import json, os, re, subprocess, sys

CANON_TOOLS = os.path.dirname(os.path.realpath(__file__))
CANON_ROOT = os.path.dirname(CANON_TOOLS)
REPO = os.environ.get("REPO", os.path.expanduser("~/Workspace/firefox"))
ALT_TOOLS = os.path.expanduser(os.environ.get("ALT_TOOLS", "~/Workspace/ui-test-modernization/tools"))
EFFPRETTY_REL = "mobile/android/fenix/app/src/androidTest/java/org/mozilla/fenix/ui/efficiency/devtools/effpretty/effpretty.py"


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def version():
    try:
        return open(os.path.join(CANON_ROOT, "VERSION")).read().strip()
    except OSError:
        return "unknown"


def queue_for(tools_dir):
    return os.path.join(os.path.dirname(tools_dir), "conversion-runs", "_queue")


def proc_cwd(pid):
    """CWD of another process, via lsof. Returns None if it cannot be determined.

    effwatch is usually launched by a RELATIVE path (`./tae-conversion/tools/effwatch.sh`), so the
    queue it watches depends on the cwd of *that* process. Resolving such a path against effdoctor's
    own cwd invents a directory that never existed and sends requests into a black hole.

    /proc first, because it is exact and always present on Linux; lsof is the macOS path and is not
    installed everywhere.
    """
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        pass
    for line in sh(f"lsof -a -p {pid} -d cwd -Fn").splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def check():
    out = {"tool": "effdoctor", "version": version(), "canonical_tools": CANON_TOOLS,
           "canonical_queue": queue_for(CANON_TOOLS), "watchers": [], "findings": []}

    def add(level, msg, fix=None):
        out["findings"].append({"level": level, "message": msg, "fix": fix})

    # --- live effwatch processes, and the queue each one is really watching
    ps = sh("ps -eo pid,command")
    for line in ps.splitlines():
        m = re.search(r"^\s*(\d+)\s+.*?(\S*effwatch\.sh)", line)
        if not m:
            continue
        pid, path = m.group(1), m.group(2)
        # Skip only THIS process, not every line containing the string "effdoctor": a watcher
        # running from a directory whose name happens to contain it would otherwise be invisible,
        # and an unnoticed watcher is the whole problem this tool exists to surface.
        if pid == str(os.getpid()) or re.search(r"effdoctor\.py", line):
            continue
        cwd = proc_cwd(pid)
        if os.path.isabs(path):
            tools_dir = os.path.dirname(path)
        elif cwd:
            tools_dir = os.path.dirname(os.path.normpath(os.path.join(cwd, path)))
        else:
            tools_dir = None

        q = queue_for(tools_dir) if tools_dir else None
        w = {"pid": pid, "launched_from": path, "proc_cwd": cwd, "watching_queue": q,
             "exists": bool(q) and os.path.isdir(q),
             "canonical": bool(q) and os.path.realpath(q) == os.path.realpath(out["canonical_queue"])}
        out["watchers"].append(w)

        if not q:
            add("WARN",
                f"effwatch (pid {pid}) was launched by the relative path {path}, and its cwd could not "
                "be read, so the queue it watches cannot be determined",
                "Find it with: lsof -a -p %s -d cwd. Do NOT guess — a request in the wrong queue is "
                "never consumed and never errors." % pid)
            continue

        # A computed queue that does not exist means the resolution above is wrong, or this watcher is
        # broken. Either way it is worse than non-canonical: never send anyone to a path with no dir.
        if not w["exists"]:
            add("FAIL",
                f"effwatch (pid {pid}) appears to watch\n      {q}\n    but that directory DOES NOT EXIST",
                "Do not queue into it. Confirm the watcher's real queue (lsof -a -p %s -d cwd) and "
                "restart it from %s/effwatch.sh if needed." % (pid, CANON_TOOLS))
        elif not w["canonical"]:
            add("WARN",
                f"effwatch (pid {pid}) was launched from {path}, so it is watching\n"
                f"      {q}\n"
                f"    which is NOT the canonical queue\n"
                f"      {out['canonical_queue']}",
                "Queue requests into the WATCHED path above, or relaunch effwatch from "
                f"{CANON_TOOLS}/effwatch.sh. A request in the wrong queue is never consumed and never errors.")

    if not out["watchers"]:
        add("INFO", "no effwatch running — queued requests will not be consumed until one is started",
            f"{CANON_TOOLS}/effwatch.sh")
    elif len(out["watchers"]) > 1:
        add("WARN", f"{len(out['watchers'])} effwatch processes are running",
            "Two watchers means two gradle builds against one device, which reads as test flakiness "
            "(MTE-5768). Kill all but one.")

    # --- are the two checkouts really the same files?
    alt = ALT_TOOLS
    if os.path.isdir(alt):
        divergent = []
        for name in sorted(os.listdir(CANON_TOOLS)):
            if not name.startswith("eff"):
                continue
            other = os.path.join(alt, name)
            if not os.path.exists(other):
                divergent.append(f"{name} (missing there)")
            elif os.path.realpath(other) != os.path.realpath(os.path.join(CANON_TOOLS, name)):
                divergent.append(f"{name} (a SEPARATE copy, not a symlink)")
        out["alt_tools"] = {"path": alt, "divergent": divergent}
        if divergent:
            add("WARN", f"{alt} diverges from canonical: " + ", ".join(divergent),
                "A separate copy will drift silently. Replace it with a symlink into "
                f"{CANON_TOOLS}, or delete it.")

    # --- effpretty must be resolvable in-tree (MTE-5764 / gotcha A24)
    ep = os.environ.get("EFFPRETTY", os.path.join(REPO, EFFPRETTY_REL))
    out["effpretty"] = {"path": ep, "found": os.path.isfile(ep)}
    if not out["effpretty"]["found"]:
        add("FAIL", f"effpretty.py not found at {ep}",
            "effloop resolves it under $REPO. Set REPO or EFFPRETTY. Without it the run trace is empty "
            "and effverify has no input (gotcha A24).")

    # --- stale gradle lock (gotcha A38): a killed mach lint leaves the SoftFileLock behind
    lock = os.path.join(REPO, "objdir-frontend/gradle/mach_android.lockfile")
    if os.path.isfile(lock):
        held = sh("pgrep -f 'mach lint|GradleWrapperMain'")
        out["gradle_lock"] = {"present": True, "held": bool(held)}
        if not held:
            add("WARN", f"stale gradle lockfile with no process holding it: {lock}",
                f"rm -f {lock} — otherwise the next mach lint waits out its timeout and reports a "
                "failure that looks like a linter error (gotcha A38).")
    else:
        out["gradle_lock"] = {"present": False, "held": False}

    # --- device
    devices = [l for l in sh("adb devices").splitlines()[1:] if l.strip()]
    out["devices"] = devices
    if not devices:
        add("FAIL", "no adb device — a queued run will fail at the gradle connected task",
            "Start the emulator, then re-run effdoctor.")

    out["repo"] = {"path": REPO, "branch": sh(f"git -C {REPO} rev-parse --abbrev-ref HEAD")}
    out["ok"] = not any(f["level"] in ("WARN", "FAIL") for f in out["findings"])
    return out


def main():
    if "--version" in sys.argv[1:]:
        print(f"{os.path.basename(__file__)} — tae-conversion {version()}")
        sys.exit(0)
    r = check()
    if "--json" in sys.argv[1:]:
        print(json.dumps(r))
        sys.exit(0 if r["ok"] else 1)

    print(f"effdoctor — tae-conversion {r['version']}\n")
    print("toolchain")
    print(f"  canonical tools : {r['canonical_tools']}")
    print(f"  canonical queue : {r['canonical_queue']}")
    print(f"  effpretty       : {r['effpretty']['path']}  [{'OK' if r['effpretty']['found'] else 'MISSING'}]")
    print("\nlive effwatch")
    if r["watchers"]:
        for w in r["watchers"]:
            print(f"  pid {w['pid']}  launched from {w['launched_from']}  (cwd {w['proc_cwd'] or 'unknown'})")
            if not w["watching_queue"]:
                print("     -> queue UNDETERMINED — see below")
            else:
                flag = ("canonical" if w["canonical"] else "NON-CANONICAL") if w["exists"] \
                    else "DOES NOT EXIST"
                print(f"     -> queue requests into: {w['watching_queue']}  [{flag}]")
    else:
        print("  none running")
    print(f"\nrepo   : {r['repo']['path']}  (branch {r['repo']['branch']})")
    print(f"device : {', '.join(r['devices']) or 'none'}")
    print()
    for f in r["findings"]:
        mark = {"FAIL": "✖", "WARN": "⚠", "INFO": "•"}[f["level"]]
        print(f"  {mark} {f['message']}")
        if f["fix"]:
            print(f"      → {f['fix']}")
    print("\nRESULT:", "clean" if r["ok"] else "needs attention")
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
