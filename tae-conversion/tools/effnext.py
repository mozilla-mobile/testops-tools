#!/usr/bin/env python3
"""
effnext — pick the next legacy test(s) to convert, from LOCAL files only. No Google Sheet, no network.

Source of truth for "what to do next":
  - candidate pool : conversion-runs/testrail_smoke_pool.txt  (prioritized `Class.method<TAB>method` lines)
  - already done   : tools/converted_rows.csv                 (Class,Method,...,Converted,... rows)
  - skipped        : conversion-runs/skiplist.tsv             (`Class.method<TAB>reason<TAB>date` lines)
The next candidate = first pool entry that is neither marked Converted nor skipped.

converted_rows.csv is a fast snapshot and can lag reality (the campaign notes warn the "Converted" column is
not authoritative), so by default effnext also greps the efficiency tests package for `fun <method>(` and
drops anything already present in-tree. Point it at a checkout with --repo or $REPO; pass --no-tree-check to
turn the grep off (it is skipped automatically when the checkout cannot be found).

Skipping: a candidate you do not want — too complex for who is picking it up, blocked on a harness gap,
deliberately deferred — should be recorded rather than mentally stepped over, so the next caller (and the
next person) gets a different pick. Skips are advisory and reversible; they never mark a test converted.

Usage:
  effnext.py [-n N] [--json]                     # print the next N (default 1) candidates
  effnext.py --skip Class.method [--reason "…"]  # record a skip, then show the new next pick
  effnext.py --unskip Class.method               # remove a skip
  effnext.py --skips                             # list what is currently skipped
  effnext.py --include-skipped                   # ignore the skiplist for this call
Exit 0 always (unless files are missing, or --skip/--unskip names something not in the pool).
"""
import csv, datetime, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
POOL = os.path.join(ROOT, "conversion-runs", "testrail_smoke_pool.txt")
DONE = os.path.join(HERE, "converted_rows.csv")
SKIPS = os.path.join(ROOT, "conversion-runs", "skiplist.tsv")

DEFAULT_REPO = os.path.expanduser(os.environ.get("REPO", "~/Workspace/firefox"))
EFF_TESTS = "mobile/android/fenix/app/src/androidTest/java/org/mozilla/fenix/ui/efficiency/tests"


def load_done():
    done = set()
    if not os.path.isfile(DONE):
        return done
    with open(DONE, newline="", encoding="utf-8", errors="ignore") as f:
        for row in csv.DictReader(f):
            if (row.get("Converted") or "").strip().lower() == "converted":
                done.add((row.get("Class", "").strip(), row.get("Method", "").strip()))
    return done


def load_pool():
    out = []
    with open(POOL, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fq = line.split("\t")[0].strip()
            if "." not in fq:
                continue
            cls, method = fq.split(".", 1)
            out.append((cls.strip(), method.strip(), fq))
    return out


def load_skips():
    """fq -> reason. Missing file is normal (nothing skipped yet)."""
    skips = {}
    if not os.path.isfile(SKIPS):
        return skips
    with open(SKIPS, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            skips[parts[0].strip()] = parts[1].strip() if len(parts) > 1 else ""
    return skips


def write_skips(skips):
    os.makedirs(os.path.dirname(SKIPS), exist_ok=True)
    existing_dates = {}
    if os.path.isfile(SKIPS):
        with open(SKIPS, encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) > 2:
                    existing_dates[parts[0].strip()] = parts[2].strip()
    today = datetime.date.today().isoformat()
    with open(SKIPS, "w", encoding="utf-8") as f:
        f.write("# Candidates deliberately passed over by effnext. Advisory only — a skip never marks a\n")
        f.write("# test converted. Remove a line (or run `effnext.py --unskip <Class.method>`) to requeue it.\n")
        f.write("# Class.method\treason\tdate\n")
        for fq in sorted(skips):
            f.write(f"{fq}\t{skips[fq]}\t{existing_dates.get(fq, today)}\n")


def converted_in_tree(repo):
    """Method names with a `fun <name>(` in the efficiency tests package. Empty set if the repo isn't there."""
    tests_dir = os.path.join(repo, EFF_TESTS)
    if not os.path.isdir(tests_dir):
        return None
    names = set()
    pattern = re.compile(r"\bfun\s+([A-Za-z0-9_]+)\s*\(")
    for entry in os.listdir(tests_dir):
        if not entry.endswith(".kt"):
            continue
        with open(os.path.join(tests_dir, entry), encoding="utf-8", errors="ignore") as f:
            names.update(pattern.findall(f.read()))
    return names


def converted_on_other_branches(repo, methods):
    """Which local branches already have `fun <method>(` in the efficiency tests package, per method.

    ADVISORY ONLY — deliberately not folded into the filter above. Branches carry work in three different
    states: pending review, abandoned, and dropped. The two faker conversions (bugs 2063093/2063105) still sit
    on backup branches and were REJECTED, so filtering on any branch would silently remove genuinely
    outstanding tests from the pool. Filtering stays on the checkout; other branches only produce a warning,
    which is enough to stop you re-converting something you have already sent for review from another branch.

    backup/* is excluded: those are snapshots of states we deliberately moved away from.
    """
    if not os.path.isdir(os.path.join(repo, ".git")) or not methods:
        return {}
    try:
        refs = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
            cwd=repo, capture_output=True, text=True, timeout=30,
        ).stdout.split()
    except Exception:
        # Not silent: an unlistable ref set must not read as "no other branch has it". That swallowed a
        # NameError once and reported a clean result while checking nothing at all.
        return {"__unchecked__": ["<could not list local branches>"]}
    hits, unchecked = {}, []
    for ref in refs:
        if ref.startswith("backup/"):
            continue
        try:
            out = subprocess.run(
                ["git", "grep", "-h", "-E", "fun +[A-Za-z0-9_]+ *\\(", ref, "--", EFF_TESTS],
                # 120s, not 30: a COLD `git grep <ref>` on mozilla-central can take well over 30 seconds, and a
                # timeout here used to be swallowed for every ref -- reporting "no other branch has it", which is
                # the false green this check exists to prevent. Failures are collected and surfaced instead.
                cwd=repo, capture_output=True, text=True, timeout=120,
            ).stdout
        except Exception:
            unchecked.append(ref)
            continue
        found = set(re.findall(r"\bfun\s+([A-Za-z0-9_]+)\s*\(", out))
        for m in methods & found:
            hits.setdefault(m, []).append(ref)
    if unchecked:
        hits["__unchecked__"] = unchecked
    return hits


def emit(payload, as_json, lines):
    print(json.dumps(payload) if as_json else "\n".join(lines))


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
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]

    def opt(flag):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                print(f"✖ {flag} needs a value")
                sys.exit(2)
            return args[i + 1]
        return None

    n = 1
    if "-n" in args:
        try:
            n = int(args[args.index("-n") + 1])
        except (IndexError, ValueError):
            print(__doc__.strip())
            sys.exit(2)

    repo = opt("--repo") or DEFAULT_REPO
    tree_check = "--no-tree-check" not in args
    include_skipped = "--include-skipped" in args
    to_skip = opt("--skip")
    to_unskip = opt("--unskip")

    for p in (POOL, DONE):
        if not os.path.isfile(p):
            msg = f"missing required file: {p}"
            emit({"tool": "effnext", "ok": False, "error": msg}, as_json, [f"✖ {msg}"])
            sys.exit(1)

    pool = load_pool()
    pool_fqs = {fq for (_, _, fq) in pool}
    skips = load_skips()

    if "--skips" in args:
        payload = {"tool": "effnext", "ok": True, "skipped": [{"fqmethod": k, "reason": v} for k, v in sorted(skips.items())]}
        lines = [f"effnext — {len(skips)} skipped"] + [f"  ⤳ {k}{('  — ' + v) if v else ''}" for k, v in sorted(skips.items())]
        emit(payload, as_json, lines or ["effnext — nothing skipped"])
        sys.exit(0)

    for flag, fq in (("--skip", to_skip), ("--unskip", to_unskip)):
        if fq and fq not in pool_fqs:
            msg = f"{fq} is not in the pool ({POOL}); expected Class.method"
            emit({"tool": "effnext", "ok": False, "error": msg}, as_json, [f"✖ {msg}"])
            sys.exit(2)

    if to_unskip:
        skips.pop(to_unskip, None)
        write_skips(skips)
    if to_skip:
        skips[to_skip] = (opt("--reason") or "").strip()
        write_skips(skips)

    done = load_done()
    in_tree = converted_in_tree(repo) if tree_check else None

    pending, already_in_tree = [], 0
    for (c, m, fq) in pool:
        if (c, m) in done:
            continue
        if in_tree is not None and m in in_tree:
            already_in_tree += 1
            continue
        if not include_skipped and fq in skips:
            continue
        pending.append((c, m, fq))
    picks = pending[:n]
    elsewhere = converted_on_other_branches(repo, {m for (_, m, _) in picks}) if tree_check else {}
    unchecked_branches = elsewhere.pop("__unchecked__", [])

    payload = {
        "tool": "effnext", "ok": True,
        "pool_total": len(pool), "done": len(done), "pending": len(pending),
        "skipped": len(skips), "already_in_tree": already_in_tree,
        "tree_checked": in_tree is not None,
        "branches_unchecked": unchecked_branches,
        "next": [
            {"class": c, "method": m, "fqmethod": fq, **({"also_on_branches": elsewhere[m]} if m in elsewhere else {})}
            for (c, m, fq) in picks
        ],
    }
    if to_skip:
        payload["just_skipped"] = to_skip
    if to_unskip:
        payload["just_unskipped"] = to_unskip

    lines = []
    if to_skip:
        lines.append(f"⤳ skipped {to_skip}{('  — ' + skips[to_skip]) if skips[to_skip] else ''}")
    if to_unskip:
        lines.append(f"↩ unskipped {to_unskip}")
    summary = f"effnext — {len(pending)} pending / {len(pool)} pool ({len(done)} converted"
    if already_in_tree:
        summary += f", {already_in_tree} already in-tree"
    if skips and not include_skipped:
        summary += f", {len(skips)} skipped"
    lines.append(summary + ")")
    if unchecked_branches:
        lines.append(
            f"  ⚠ {len(unchecked_branches)} branch(es) could not be searched "
            f"({', '.join(unchecked_branches[:3])}{'…' if len(unchecked_branches) > 3 else ''}) — "
            "an unlanded conversion there would not be flagged"
        )
    if in_tree is None and tree_check:
        lines.append(f"  (no checkout at {repo} — tree check skipped; pass --repo or set $REPO)")
    for (_, m, fq) in picks:
        lines.append(f"  → {fq}")
        if m in elsewhere:
            lines.append(
                f"      ⚠ already converted on {', '.join(elsewhere[m])} but not in this checkout — "
                "confirm it is not already in review before redoing it"
            )
    if not picks:
        lines.append("  (nothing pending — pool exhausted, or everything left is converted or skipped)")
    emit(payload, as_json, lines)
    sys.exit(0)


if __name__ == "__main__":
    main()
