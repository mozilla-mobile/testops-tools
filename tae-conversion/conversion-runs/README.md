# conversion-runs/ — the AI-loop feedback channel

`effloop.sh` drops per-batch build/run reports here; Claude reads them to iterate on conversions.

Layout: `conversion-runs/<batch>/` containing
- `build-report.txt` — concise compile verdict + errors (from effbuild)
- `run-report.txt` — concise structured run trace (from effpretty; only if the build passed)
- `status.json` — `{ build_ok, ran, test, batch, ts }`
- `raw-build.log` / `raw-test.log` — full logs (kept for deep dives; Claude reads the reports, not these)

## Hands-off mode — `_queue/` protocol (with effwatch)
Start `tools/effwatch.sh` once on your machine and leave it running (device attached). Then:
- Claude writes `_queue/<id>.request.json` = `{ "test_class": "...", "batch": "..." }`
- effwatch claims it (`<id>.claimed`), runs `effloop <test_class> <batch>` on your toolchain, writes the
  reports to `<batch>/`, then writes `_queue/<id>.done.json` = `{ id, test, batch, effloop_exit, reports, ts }`
- Claude polls for `<id>.done.json` and reads the reports.
The watcher only runs the fixed effloop command with a whitelisted class name — it never executes text from
the request file.

Safe to delete old batch folders and processed `_queue/*.done.json`; they're disposable run artifacts.

## Conversion toolchain (tools/)
- `effscaffold.py <Class.method>` — front-loads a conversion: prints the legacy body, TestRail link,
  @Ignore status, robots+selector lines, an already-converted check, and existing efficiency coverage.
- `effcheck.py` — static pre-flight (RES/ID/TAG/NAV/CAT/VERB + MWS/IMP/DUP). Run before every build.
- `effbuild.py` — gradle log → concise compile/test verdict.
- `effloop.sh` — build+run one class via ./mach; writes build-report/run-report/status.
- `effverify.py <batchdir> <TestName...>` — DONE-GATE: confirms each named test executed (started, not
  ignored, in a 0-failed run). "green + 0 failed" alone can hide a SKIPPED test — always effverify.
- `effgit.py` / `effwatch.sh` — git bridge + queue watcher.

## On-demand screen dump — `EffScreenDumpRunner` (dev tool)
Author selectors against the live UI tree instead of guessing from legacy robots. Enqueue:
`{ "test_class": "org.mozilla.fenix.ui.efficiency.devtools.EffScreenDumpRunner", "batch": "effdump",
   "mach_args": "--stacktrace -Pandroid.testInstrumentationRunnerArguments.effdump.page=<pageContextProperty>" }`
Then read the EFF_SCREEN_DUMP in effdump/run-report.txt. `mach_args` passthrough was added to effwatch
(requires ONE watcher restart to take effect). Graph-navigable pages only.
