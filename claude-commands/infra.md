---
description: Regenerate mobile/android/test_infra/TEST_MATRIX.md from current taskcluster + Flank state
allowed-tools: Read, Write, Edit, Bash, Glob
argument-hint: "[optional: extra notes to include]"
---

# /infra — Refresh the Android UI test matrix

You are refreshing the Mobile Android UI test matrix document at
`mobile/android/test_infra/TEST_MATRIX.md`. This is a team-facing quick-look
reference for the Fenix and Focus Firebase Test Lab (FTL) surface.

## Prerequisites

- **Must be run from a clone of the Firefox source tree** (`mozilla-firefox/firefox`
  or equivalent). The command resolves all paths relative to the repo root,
  so the working directory must contain `taskcluster/kinds/` and
  `mobile/android/test_infra/`. If those directories are missing, stop
  immediately and tell the user they need to invoke `/infra` from inside a
  Firefox checkout.
- **The output file does not need to exist.** If
  `mobile/android/test_infra/TEST_MATRIX.md` is missing, create it. If it
  already exists, overwrite it. Either way the final state is the freshly
  regenerated document.

## Sources of truth (read these every run — do not trust prior knowledge)

1. **Taskcluster kinds** — task definitions, dependencies, scheduling, treeherder symbols:
   - `taskcluster/kinds/ui-test-apk/kind.yml`
   - `taskcluster/kinds/android-startup-test/kind.yml`

2. **Flank configurations** — what tests actually run, on which device, with which shard count:
   - `mobile/android/test_infra/flank-configs/fenix/*.yml`
   - `mobile/android/test_infra/flank-configs/focus/*.yml`
   - `mobile/android/test_infra/flank-configs/components/*.yml`

Use `Glob` to enumerate the flank-configs (do not hard-code filenames — files
get added and removed). Then `Read` each YAML.

## Output

Overwrite `mobile/android/test_infra/TEST_MATRIX.md` with the regenerated
content. The document MUST include all of these sections, in this order:

0. **Pipeline at a glance** — a Mermaid `flowchart LR` showing
   `signing-apk → ui-test-apk / android-startup-test → android-ui-tests Docker
   image → test-lab.py + Flank YAML → Firebase Test Lab → Treeherder + Slack`.
1. **`ui-test-apk` — primary UI test surface**, split into a Fenix table and a
   Focus table. Columns: Task, Treeherder symbol, Build type, Flank config,
   Where it runs (`run-on-projects`), Optimization, Notes.
2. **`android-startup-test` — Nightly startup / smoke surface**, split into
   Fenix and Focus tables. Columns: Task, Treeherder symbol, Build type, Flank
   config, APK arch, Notes.
2a. **Scheduling model** — a Mermaid `flowchart LR` mapping CI events (every
    push, backstop, trunk, release, Nightly cron) to the tasks they pull in.
3. **Flank configurations — what each config actually runs**, three tables
   (fenix, focus, components). Columns: Config, Device, API, Test targets,
   Shards, Flaky retries, Special. Note any config that is **unwired** (not
   referenced by any task) explicitly.
4. **Cross-cutting defaults & gotchas** — APK source/signing deps, optimization
   model (`skip-unless-backstop` vs. path-based smoke vs. cron-driven),
   GeckoView config files, orchestrator on/off (benchmarks turn it off),
   notification routing (Slack channel `C0134KJ4JHL`), and any unwired configs.
5. **At-a-glance matrix** — task → product / channel / suite / device.
6. **Device × API coverage** — table of devices (mark V = virtual / AVD, P =
   physical) across API levels with `X` marking coverage. Call out gaps (which
   API levels have zero coverage).
7. **Coverage by product × channel × surface** — grid with `Y` cells for
   covered surfaces (Smoke, Full UI, Detect-leaks, Experimental, Legacy,
   Robo, Startup smoke) per product/channel.

## Style rules (follow exactly — Mozilla style guide)

- **No emoji.** Use plain ASCII markers like `X`, `Y`, `V`, `P`, `—` for
  presence/absence. Never use checkmark, cross, or other Unicode symbol
  characters.
- Tables wherever data has 3+ comparable rows.
- Use Mermaid for the two diagrams (sections 0 and 2a) — renders in GitHub
  Gist, HackMD, Phabricator paste, and VS Code preview.
- Headings: `#` for the doc title, `##` for sections, `###` for sub-sections.
- Keep the intro block (worker types, Docker image, Slack channel, GCP
  projects) immediately under the title.
- The doc is the source — do not output a summary to the user, just write the
  file and report what changed.

## Process

1. Glob and read all source files listed above. Do not skip any.
2. For each task in the kind.yml files, extract: name, attributes
   (`build-type`, `shipping-product`, `legacy`), dependencies, `flank-config`,
   `optimization`, `run-on-projects`, `treeherder.symbol`, `treeherder.tier`,
   `no-test-apk`, `artifact-type`, and any task-level overrides.
3. For each Flank YAML, extract: `device.model`, `device.version`,
   `test-targets` (preserve `class`/`package`/`notPackage`/`annotation`
   prefixes), `max-test-shards`, `num-flaky-test-attempts`,
   `use-orchestrator`, `timeout`, and any noteworthy env vars
   (`detect-leaks`, `androidx.benchmark.enabledRules`).
4. Cross-reference: list any Flank config under `flank-configs/` that no task
   references — these are "unwired" and worth flagging.
5. Write the file. Use the same intro block, Mermaid diagrams, and section
   numbering established by the existing doc as a structural reference, but
   regenerate all content from the freshly read sources — do not copy stale
   data from the previous version.
6. After writing:
   - If the file existed before this run, run
     `git diff --stat mobile/android/test_infra/TEST_MATRIX.md` and report
     which sections changed (added tasks, removed tasks, device changes,
     shard changes, newly unwired configs).
   - If the file did **not** exist before (fresh creation), say so explicitly
     and list the task count per kind plus any unwired Flank configs you
     found.
   Keep the report under 10 lines either way.

## Optional arguments

If `$ARGUMENTS` is non-empty, append a final section titled
`## 8. Run notes (${date})` containing the argument text verbatim. Use this
for ad-hoc context like "post-merge audit after bug 2040236".
