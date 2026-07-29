#!/usr/bin/env python3
"""
effsubmit — YOU run this on YOUR machine to submit a finished stack with moz-phab. Landing/submitting
deliberately stays on your side: Claude does NOT drive this and the effwatch bridge still refuses submit.
Claude's job is to tell you the exact command; this helper fills in the reviewers, dry-runs first, and
figures out whether your installed moz-phab can set the Phabricator tag from the CLI (it probably can't —
see below), so you don't have to remember any of it.

Default reviewers: $EFF_REVIEWERS (comma-separated), or pass --reviewers a,b.
Default tag:       testing-exception-unchanged  (a Phabricator *project* tag; see note).

NOTE: Mozilla's moz-phab has NO --dry-run. It is interactive instead — it prints the exact commit list and
prompts Y/n before creating any revision, so that prompt IS your preview. Read it before confirming.

Usage (all optional):
  python3 effsubmit.py                      # print the submit command + tag guidance
  python3 effsubmit.py --start <commit>     # bound the stack: submit <commit>..HEAD only (never touches below it)
  python3 effsubmit.py --execute            # run moz-phab submit (it still prompts before creating revisions)
  python3 effsubmit.py --reviewers a,b --tag some-project

REPO defaults to ~/Workspace/firefox (override with REPO=...).
"""
import argparse, os, shutil, subprocess, sys

REPO = os.environ.get("REPO", os.path.expanduser("~/Workspace/firefox"))

def mozphab_help():
    try:
        r = subprocess.run(["moz-phab", "submit", "--help"], cwd=REPO,
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return ""
    except Exception as e:
        return f"(could not run moz-phab submit --help: {e})"

def detect_tag_flag(help_text):
    # moz-phab historically has NO flag to set Phabricator projects/tags. Detect any that appear.
    for flag in ("--project", "--tag", "--projects", "--add-project"):
        if flag in help_text:
            return flag
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="", help="first commit to submit (inclusive); end is always HEAD. Empty = moz-phab auto-detects the stack. Set to your first NEW commit to bound the range and never touch the landed base.")
    ap.add_argument("--reviewers", default=os.environ.get("EFF_REVIEWERS", ""),
                    help="comma-separated Phabricator reviewers; defaults to $EFF_REVIEWERS")
    ap.add_argument("--tag", default="testing-exception-unchanged")
    ap.add_argument("--execute", action="store_true", help="run the REAL submit after printing the dry-run")
    args = ap.parse_args()

    if not shutil.which("moz-phab"):
        print("⚠️  moz-phab not found on PATH. Install it, then re-run.", file=sys.stderr)
    revs = [r.strip() for r in args.reviewers.split(",") if r.strip()]
    if not revs:
        print("⚠️  No reviewers. Set EFF_REVIEWERS=user1,user2 or pass --reviewers a,b.", file=sys.stderr)
    rev_flags = []
    for r in revs:
        rev_flags += ["--reviewer", r]
    start = [args.start] if args.start else []

    help_text = mozphab_help()
    tag_flag = detect_tag_flag(help_text)

    real = ["moz-phab", "submit", *rev_flags, *start]
    if tag_flag:
        real += [tag_flag, args.tag]

    print("Repo:", REPO)
    print("Reviewers:", ", ".join(revs))
    print("\nMozilla's moz-phab has NO --dry-run. It is INTERACTIVE: it prints the exact commit list and asks")
    print("Y/n before creating any revision — read that list before you confirm.")
    print("\nSUBMIT COMMAND:")
    print("   " + " ".join(real))
    if start:
        print(f"   (bounded: submits {args.start}..HEAD only — it cannot touch anything below {args.start})")
    else:
        print("   (no --start: moz-phab auto-detects the stack. Pass --start <first-new-commit> to bound it hard.)")

    if tag_flag:
        print(f"\nTag: your moz-phab supports {tag_flag}, so '{args.tag}' is set on submit. ✅")
    else:
        print(f"\nTag: your moz-phab has NO CLI flag to set a Phabricator project tag "
              f"(checked `moz-phab submit --help`). After submit, add '{args.tag}' to the "
              f"revision's Tags/Projects field in the Phabricator web UI (or via `arc`/conduit). "
              f"It can't be done from moz-phab itself.")

    print("\nNote: submitting/landing stays with you by design — this helper won't submit unless you pass --execute.")

    if args.execute:
        print("\n▶ Running moz-phab submit — it will show the stack and prompt before creating revisions…\n")
        subprocess.run(real, cwd=REPO)
        if not tag_flag:
            print(f"\n⚠️  Remember to add the '{args.tag}' tag in the Phabricator web UI.")

if __name__ == "__main__":
    main()
