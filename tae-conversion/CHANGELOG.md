# Changelog — tae-conversion toolchain and docs

Tools and docs are versioned **together** (they cite each other by gotcha/lesson id, so a split version
would only create skew). **CalVer** (`YYYY.MM.DD`), because the only question anyone asks of an internal
script read from a checkout is "is my copy older than the thing being discussed" — not "is this a breaking
change". Every tool answers `--version`.

This file is curated, not a commit log: entries are changes a *consumer* depends on — a new gate, changed
verdict semantics, changed flags. `git log` has the rest.

## 2026.08.13

### Added
- `efftriage.py` — reads a batch's `run-report.txt` + `status.json` and names the likely cause of a failure
  with its HARNESS-GOTCHAS id and the fix. Read-only, so it is safe to run on every failure. Scans the FIRST
  attempt only, because a failed attempt leaves state behind and later attempts die somewhere later and more
  confusingly. 11 rules (T0–T10), hardened against 8 labelled failures from the search batch. (MTE-5827)
- `VERSION` + this changelog, and `--version` on all 12 tools. Version lookup resolves symlinks, so it stays
  correct when a tool is invoked through another checkout's `tools/` dir. (MTE-5770 slice 1)
- Docs: lessons **K13** (ad surfaces are testable offline by faking the app-services client at the seam
  app-services itself uses in its unit tests) and gotchas **A37–A43**.

### Fixed
- `effverify.py` — **a crashed test was scored as passed**, with `clean=true` and `failed_total=0`. Only
  `failed:` markers and the gradle status line were read, and a crash emits neither (`"gradle": null` was the
  tell). Now also reads the report's `FAILURES (n of m)` header and `CRASH:` lines, and refuses to report
  clean when the declared failure count exceeds what it can attribute. New JSON fields:
  `declared_failures`, `unattributed_failures`. Also fixes a `NameError` that crashed the tool while building
  a failure excerpt for a batch with no `raw-run.log`. (MTE-5822, gotcha A37)
- `effloop.sh` — resolved `effpretty.py` as `$TOOLS/effpretty.py`, but it lives in mozilla-central, so it only
  worked for checkouts that happened to have a copy or symlink beside the script. Everywhere else the renderer
  silently never ran: empty `run-report.txt`, and no verdict from effverify. Now resolved under `$REPO`
  (override with `EFFPRETTY=`), with a `$TOOLS` fallback and a loud exit-2 guard. (MTE-5764, gotcha A24)

### Changed
- Docs: README's tool table described effverify's pre-2026-08-03 "last run" scoping; lessons **K8** documented
  a `NameError` that is now fixed; gotcha **A24** now carries its root cause.

### Known gaps
- Mechanized coverage is not yet reported. `effgates --coverage` plus a `Gate:` line on every doc entry is
  MTE-5830; the `effcheck` verb × selector-strategy matrix is MTE-5828; `effparity` (legacy-vs-port assertion
  parity, gating lesson G1) is MTE-5829.
