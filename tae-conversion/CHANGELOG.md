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
  confusingly. 15 rules (T0–T14): 12 match the trace and live in `RULES`, while **T10 (crash), T11 (skip) and T12
  (compile failure) are status-based checks** in `triage()` — so counting `RULES` alone gives 12, not 15.
  Hardened against labelled failures from the search batch and then against batch 2's own, which is where
  T11–T14 came from. (MTE-5827)
- `effdoctor.py` slice 1 — read-only preflight, and specifically the **toolchain map**. The eff* tools exist
  once but are reachable from two checkouts, and `effwatch.sh` derives its queue from `dirname $0`, which does
  not resolve symlinks: the queue it watches depends on the path it was launched from, while the tools are
  identical either way. A request dropped in the other checkout's queue is never consumed and never errors.
  effdoctor now prints which watcher is live and which queue to use, flags a diverged alt checkout, and checks
  effpretty resolution, a stale gradle lock and the device. The watched queue is resolved against the *watcher
  process's* cwd (read via `lsof`), not effdoctor's, because effwatch is normally launched by a relative path —
  resolving it against the caller's cwd yields a directory that never existed. A computed queue that is not on
  disk is reported as a failure, and an unreadable cwd as "undetermined": naming the wrong queue confidently is
  worse than declining to name one. (MTE-5766)
- **Unit tests** (`tae-conversion/tests/`, 58 of them) and a CI job, where previously the toolchain had none.
  Run them with `python -m unittest discover -s tae-conversion/tests -p '*tests.py'`; no device, emulator,
  Firefox checkout or network needed, since `ps`/`lsof`/`adb`/`git` are stubbed. The efftriage rule tests run
  against **real labelled conversion runs** checked in under `tests/fixtures/corpus` with a `labels.json`
  manifest: hand-written traces only test the shapes their author imagined, so they pass while the tool
  mismatches real output — a false green in the suite meant to prevent false greens. That corpus previously
  existed only as batch dirs in one person's `conversion-runs/`, unversioned and unrunnable in CI. Writing
  these found four defects, three of them in code that had already been reviewed by eye and pronounced fine.
- `effbug.py` **update now accepts `comment`**, posting a new comment on an existing bug. Comment 0 cannot be
  edited through the Bugzilla API, so a correction previously had nowhere to go — found the hard way after a
  bug was filed with a wrong TestRail id. On `create` `comment` is still the description; on `update` it is a
  new comment.
- `ALT_TOOLS` env var on `effdoctor`, so the alt-checkout divergence check works for checkouts that are not at
  `~/Workspace/ui-test-modernization`.
- `VERSION` + this changelog, and `--version` on all 12 tools. Version lookup resolves symlinks, so it stays
  correct when a tool is invoked through another checkout's `tools/` dir. (MTE-5770 slice 1)
- Docs: lessons **K13** (ad surfaces are testable offline by faking the app-services client at the seam
  app-services itself uses in its unit tests) and gotchas **A37–A43**.

### Fixed
- `effloop.sh` — **a SKIPPED test was scored as a pass** (gotcha **A44**, the fifth false-green shape). The
  verdict was `failures == 0 and tests > 0`, which a skip satisfies without running, so an `@Ignore`d legacy
  test reported `outcome: pass` having asserted nothing. `outcome` is now `skipped` when nothing ran and
  `partial` when only some tests did, both exiting **5** (new code: ran, but the verdict is incomplete).
  `effverify` already scored these correctly, so a disagreement between the two was the tell.
- `efftriage.py` — new rule **T14** for gotcha **A46**: a checked-state assertion that failed because the
  node it matched does not carry the state. Compose toggle/radio rows keep `selected` on the MERGED row and
  blank the switch with `clearAndSetSemantics`, so `mozVerifyElementIsChecked` can never pass and
  `COMPOSE_BY_TEXT` resolves a stateless descendant. This is the shape behind legacy tests that assert
  checked state via positional `UiSelector().index(n)`, so it will recur. (MTE-5827)
- `efftriage.py` — new rule **T11** for the above. It reads the per-test statuses rather than `outcome`,
  because the field that should raise the alarm was the one lying. On its first run over the existing corpus it
  found **2 silently skipped tests** in an earlier 10-test run that nothing had ever reported.
- `efftriage.py` — **a green run was handed a failure diagnosis.** Traces routinely carry non-fatal `[ERR]`
  lines (nav-graph polling, tolerated absence checks), and the rules scanned them regardless of outcome, so a
  passing run was reported as an absence-assertion failure. Two of the campaign's own labelled runs were
  affected. A passing single-attempt run is no longer triaged; its non-fatal error count is reported as a note
  instead. Deliberately still triaged: a **retry-pass**, where attempt 1 really did fail and `clean=false`
  means flaky-not-done (now labelled `PASSED ONLY ON RETRY`), and a **crash**, because crash mode is where
  `outcome: pass` is itself the lie (MTE-5822). (MTE-5827)
- `efftriage.py` — a nonexistent batch dir was diagnosed as gotcha A24 ("run-report.txt is missing"), sending
  the reader to check effpretty resolution and pull dumps off a device on account of a mistyped path. It is now
  reported as `no-such-batch`, and no longer tracebacks with a `KeyError`.
- `effdoctor.py` — **named the wrong queue, which is the failure it exists to prevent.** effwatch is normally
  launched by a relative path, and that path was resolved with `os.path.abspath` — against effdoctor's cwd
  rather than the watcher's. Run from a Firefox checkout it reported a live queue under
  `firefox/tae-conversion/`, a directory that has never existed, and advised queueing into it; a request
  dropped there is never consumed and never errors. The watcher's own cwd is now read (`/proc` first, `lsof`
  fallback). A computed queue that is not on disk is a FAIL, and an unreadable cwd is reported as undetermined
  with the command to run: declining to answer beats answering wrongly. (MTE-5766)
- `effdoctor.py` — the self-exclusion filter skipped every `ps` line containing the substring `effdoctor`, so
  a watcher running from a directory whose name contained it was invisible. Now skips only this process.
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
- `efftriage` rules **T3, T4 and T5 have no labelled example** anywhere in the 53-run corpus they were
  hardened against, so they are unvalidated rather than known-good — a rule that has never fired on a real
  failure may not match the shape it was written for at all. Listed in `UNVALIDATED_RULES` in the tests, which
  fail if the list goes stale in either direction.
- 3 of the 28 failed runs in the corpus get **no diagnosis** (`gap-*` fixtures). They are checked in as
  tripwires: add a rule that explains one and the test fails, which is the reminder to record the win.
- Mechanized coverage is not yet reported. `effgates --coverage` plus a `Gate:` line on every doc entry is
  MTE-5830; the `effcheck` verb × selector-strategy matrix is MTE-5828; `effparity` (legacy-vs-port assertion
  parity, gating lesson G1) is MTE-5829.
