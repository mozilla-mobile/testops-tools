# tae-conversion — host-side toolchain for Fenix ui/efficiency test conversions

Python/shell tools that close the loop for converting legacy Fenix UI tests onto the
`ui/efficiency` framework with an AI agent: **pick a candidate → scaffold → static
pre-flight → build/run on a device → read a structured verdict → file/commit/submit**.

The agent runs in a sandbox and can't reach your device, Bugzilla, or Phabricator. These
tools run on *your* machine; a small watcher (`effwatch.sh`) bridges the two.

## Where the other half lives

| Piece | Where |
|---|---|
| Agent skills (`efficiency-test-authoring`, `tae-test-review`, `efficiency-conversion-loop`) | [`firefox-aidev-plugins`](https://github.com/mozilla/firefox-aidev-plugins) → `plugins/tae` |
| Framework reference docs (guides, gotchas, architecture) | mozilla-central, `mobile/android/fenix/app/src/androidTest/java/org/mozilla/fenix/ui/efficiency/docs/` |
| Device-side dump tools (`effview`, `effpretty`) | mozilla-central, same tree under `devtools/` |
| Host-side workflow tools | **here** |

The skills tell the agent *how* to work and reference these tools by name. Install the
plugin for the skills; clone this repo for the tools.

## Prerequisites

- A Firefox/Fenix checkout (`mobile/android/fenix/`), Python 3, and a shell.
- An Android device or emulator with `adb` on PATH.
- `moz-phab` authenticated to phabricator.services.mozilla.com (only for submit).
- A Bugzilla API key (only for auto-filing bugs).

## Setup

```bash
cp tools/.eff.env.example tools/.eff.env   # add BUGZILLA_API_KEY
chmod 600 tools/.eff.env                   # gitignored; never commit it
```

Optional environment, all with sane fallbacks:

| Variable | Default | Purpose |
|---|---|---|
| `REPO` | `~/Workspace/firefox` | Your Firefox checkout |
| `EFF_REVIEWERS` | *(unset)* | Default Phabricator reviewers for `effsubmit` |
| `EFF_EPIC` | *(unset)* | Tracking epic appended to filed-bug descriptions |
| `VARIANT` / `TESTS_PKG` / `MACH_TASK` | Fenix debug defaults | Build/run targets for `effloop` |
| `OUT_ROOT` / `RUNS` | `tae-conversion/conversion-runs` | Where run artifacts land |

## The tools

| Tool | Who runs it | Does |
|---|---|---|
| `effnext.py` | agent | Next unconverted candidate from the local pool minus the done-ledger. Local only, no network. `--json`. |
| `effscaffold.py` | agent | Front-loads a conversion: legacy body, TestRail id, already-converted check, robots + selector lines, existing coverage. |
| `effcheck.py` | agent | Static pre-flight, no device. Resolution, empty nav paths, inline selectors, missing verbs, test-class boilerplate. Exit ≠ 0 = fix something. |
| `effbuild.py` | agent | Gradle log → one-line verdict plus only the compile errors. `--json`. |
| `effverify.py` | agent | **Done-gate.** Confirms the named test ran, wasn't skipped, and its *last* run is 0-failed. `clean=false` = passed only on retry, i.e. flaky. `--json`. |
| `effloop.sh` | you | One command: build → run on device → write `build-report.txt`, `run-report.txt`, `status.json`. |
| `effwatch.sh` | you | Start once, leave running. Polls `conversion-runs/_queue/`, runs the build and the git/Bugzilla actions, writes results back. |
| `effbug.py` | via bridge | Files a Bugzilla bug, rewords the title to match the commit subject, self-assigns. |
| `effgit.py` | via bridge | Commits on your side with a message file. Never pushes. |
| `effsubmit.py` | you | Wraps `moz-phab submit` with a bounded commit range so it can't touch landed base commits. |
| `reconcile_conversion.py` | you | Re-syncs the conversion ledger from `@Converted` annotations after landing. |

`effwatch.sh` is safe by construction: it whitelists the test-class name and runs only the
fixed `effloop` command — never arbitrary text from a request file.

## Smoke-test the wiring (no device needed)

```bash
python3 tools/effnext.py -n 3 --json
python3 tools/effcheck.py --app-root <fenix>/app/src/main \
        --eff-root <fenix>/app/src/androidTest/java/org/mozilla/fenix/ui/efficiency \
        <an-already-converted-file>.kt
```

If both work, the host side is wired. Then attach a device and start `effwatch.sh`.

## Work queue

- `conversion-runs/testrail_smoke_pool.txt` — prioritized candidates, one `Class.method` per line.
- `tools/converted_rows.csv` — the done-ledger.

`effnext` returns the first pool entry absent from the ledger. Replace both files to point
the toolchain at a different project.

## Docs

- `docs/CONVERSION-LOOP.md` — the loop end to end.
- `docs/CONVERSION-LESSONS.md` — assumption → reality → rule, tagged by whether a tool enforces it.
- `docs/HARNESS-GOTCHAS.md` — harness bug catalog and authoring/review checklist. Runs ahead of the
  in-tree `docs/gotchas.md` while entries are still being confirmed.
The end-of-day project-tracker runbook is deliberately **not** published here: it is specific to
one team's Sheet, Slack channel, and Jira tree rather than to this toolchain.

## Reconciling the ledger after landing

`reconcile_conversion.py` recomputes which legacy `@SmokeTest` methods are converted — those
carrying a `@Converted(replacedBy = [...])` annotation, or whose name already exists in the
efficiency suite (in-flight, not yet annotated):

```bash
cd tools && python3 reconcile_conversion.py \
    --ui-dir <fenix>/app/src/androidTest/java/org/mozilla/fenix/ui \
    --out-csv converted_rows.csv
```

That refreshes the done-ledger `effnext` reads. Feeding the numbers into whatever tracker your
team uses is a separate, team-specific step.
