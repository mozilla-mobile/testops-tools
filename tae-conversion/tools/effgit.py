#!/usr/bin/env python3
"""
effgit — git bridge for the mono-repo. Runs whitelisted git actions on YOUR machine (where they're
instant) that time out in Claude's sandbox: branch, stage, commit, amend, rebase --update-refs, and
read-backs. Driven by effwatch from a queued request file. NEVER pushes and NEVER does a real moz-phab
submit — landing stays with you. A safety branch is auto-created before any history rewrite (amend/rebase).

Request JSON (one action per file):
  { "git": "new-branch",  "name": "<branch>", "base": "<start-point?>" }
  { "git": "stage",       "paths": ["<repo-relative path>", ...] }
  { "git": "commit",      "message_file": "<rel to runs>", "paths": ["...?"] }   # stages paths then commits -F
  { "git": "amend",       "message_file": "<rel to runs>?" }
  { "git": "rebase",      "onto": "<base>" }                                     # git rebase --update-refs <base>
  { "git": "status" | "log" | "diff" }                                           # read-back only

Usage (effwatch calls this):  python3 effgit.py <request.json> <report_out.txt>
Exit 0 on success, non-zero on failure (report explains).
"""
import json, os, re, sys, subprocess, datetime

REPO = os.environ.get("REPO", os.path.expanduser("~/Workspace/firefox"))
RUNS = os.environ.get("RUNS", os.path.join(os.path.dirname(__file__), "..", "conversion-runs"))
NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

def git(*args, check=False):
    r = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r

def cur_branch():
    return git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

def safety_branch(tag):
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    b = f"backup/{cur_branch()}-{tag}-{ts}"
    git("branch", b)   # points at current HEAD; non-destructive
    return b

def safe_name(n):
    return bool(n) and NAME_RE.match(n) and ".." not in n

def safe_path(p):
    return bool(p) and not p.startswith("/") and ".." not in p and not p.startswith(".git")

def run(req):
    action = req.get("git")
    lines = [f"# effgit: {action}", f"repo: {REPO}", f"branch (before): {cur_branch()}", ""]

    if action == "new-branch":
        name, base = req.get("name"), req.get("base")
        if not safe_name(name): raise RuntimeError(f"invalid branch name: {name!r}")
        if base and not safe_name(base): raise RuntimeError(f"invalid base: {base!r}")
        args = ["checkout", "-b", name] + ([base] if base else [])
        r = git(*args)
        if r.returncode != 0 and "already exists" in r.stderr:
            r = git("checkout", name)
        if r.returncode != 0: raise RuntimeError(r.stderr.strip())
        lines.append(r.stdout + r.stderr)

    elif action == "stage":
        paths = req.get("paths") or []
        bad = [p for p in paths if not safe_path(p)]
        if bad: raise RuntimeError(f"unsafe paths: {bad}")
        git("add", "--", *paths, check=True)
        lines.append(f"staged {len(paths)} path(s)")

    elif action == "commit":
        paths = req.get("paths") or []
        bad = [p for p in paths if not safe_path(p)]
        if bad: raise RuntimeError(f"unsafe paths: {bad}")
        if paths: git("add", "--", *paths, check=True)
        mf = req.get("message_file")
        if not mf: raise RuntimeError("commit requires message_file")
        mpath = os.path.join(RUNS, mf)
        if not os.path.isfile(mpath): raise RuntimeError(f"message_file not found: {mpath}")
        r = git("commit", "-F", mpath, "--no-verify")
        if r.returncode != 0: raise RuntimeError((r.stdout + r.stderr).strip())
        lines.append(r.stdout.strip())

    elif action == "amend":
        bak = safety_branch("preamend")
        lines.append(f"safety branch: {bak}")
        mf = req.get("message_file")
        args = ["commit", "--amend", "--no-verify"]
        if mf:
            args += ["-F", os.path.join(RUNS, mf)]
        else:
            args += ["--no-edit"]
        git(*args, check=True)
        lines.append("amended HEAD")

    elif action == "rebase":
        onto = req.get("onto")
        if not safe_name(onto): raise RuntimeError(f"invalid onto: {onto!r}")
        bak = safety_branch("prerebase")
        lines.append(f"safety branch: {bak}")
        r = git("rebase", "--update-refs", onto)
        if r.returncode != 0:
            git("rebase", "--abort")
            raise RuntimeError(f"rebase conflict onto {onto} — aborted (repo unchanged). "
                               f"Resolve manually; safety branch {bak}.\n{(r.stdout+r.stderr).strip()[:800]}")
        lines.append(r.stdout.strip() or f"rebased onto {onto} (--update-refs)")

    elif action == "reset":
        ref = req.get("ref")
        if not safe_name(ref): raise RuntimeError(f"invalid ref: {ref!r}")
        bak = safety_branch("prereset")   # preserves the current commit(s) for recovery
        lines.append(f"safety branch: {bak}")
        r = git("reset", "--hard", ref)
        if r.returncode != 0: raise RuntimeError((r.stdout + r.stderr).strip())
        lines.append(r.stdout.strip() or f"reset --hard to {ref}")

    elif action in ("status", "log", "diff"):
        pass  # read-back appended below
    else:
        raise RuntimeError(f"unknown/again-not-allowed action: {action!r} "
                           "(allowed: new-branch, stage, commit, amend, rebase, status, log, diff; never push/submit)")

    # always append current git state for verification
    # NOTE: unscoped `git status` scans untracked files and is very slow on mozilla-central;
    # --untracked-files=no keeps the read-back fast while still showing staged/modified tracked files.
    lines += ["", "── git log --oneline -8 ──", git("log", "--oneline", "-8").stdout.rstrip(),
              "── git status -s (tracked) ──",
              git("status", "-s", "--untracked-files=no").stdout.rstrip() or "(clean)",
              f"branch (after): {cur_branch()}"]
    return "\n".join(lines) + "\n"

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
    req_path, out_path = sys.argv[1], sys.argv[2]
    req = json.load(open(req_path))
    try:
        report = run(req)
        ok = True
    except Exception as e:
        report = f"# effgit: {req.get('git')}\n❌ FAILED: {e}\n"
        ok = False
    open(out_path, "w").write(report)
    sys.stdout.write(report)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
