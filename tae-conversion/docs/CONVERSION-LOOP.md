# Conversion loop — convert → bug → commit → Jira → submit

The end-to-end loop for landing a legacy→efficiency conversion. Who runs what:

- **Claude (sandbox)**: does the conversion + `effcheck`/`effverify`; drives the bridge; creates Jira items
  via the Atlassian connector; hands you the submit command. Cannot reach the repo, Bugzilla, or Phabricator.
- **Bridge (`effwatch.sh`, host-side, you start it once)**: runs `effgit` (git) and `effbug` (Bugzilla) on
  your machine and returns results. Never pushes, never submits.
- **You**: run `effwatch`, keep a device up, and run the final `moz-phab submit` (submitting stays with you).

## One-time setup
1. Give effbug your BMO API key **once** (Claude never sees it). Pick either:
   - **File (set-and-forget, recommended):** `cp tools/.eff.env.example tools/.eff.env`, uncomment the
     `BUGZILLA_API_KEY=…` line and paste your key, then `chmod 600 tools/.eff.env`. effbug reads it
     automatically; it's gitignored. (Alternate locations: `~/.config/eff/eff.env` or `~/.eff.env`, or point
     `BUGZILLA_API_KEY_FILE` at any file.)
   - **Shell env:** put `export BUGZILLA_API_KEY=…` in `~/.zshenv` (loaded for every zsh, including the one
     running effwatch — better than `.zshrc`, which is interactive-only). Env always wins over the file.
   effbug's report prints which source the key came from (never the key itself), so it's easy to confirm.
2. `moz-phab` installed and authed to phabricator.services.mozilla.com.
3. `./tools/effwatch.sh` running (device/emulator attached). It now dispatches `git`, `bug`, and test-run requests.

## The 5 steps

### 1. Do the conversion work (Claude, sandbox)
Fetch main first — a branch that predates someone else's landing cannot see their conversion, and the
duplicate then surfaces as a rebase conflict after review (bug 2060292 vs 2060174). Then pick the next
test with **`effnext --json`** (local pool minus done minus skipped, and minus anything whose
method already exists in the efficiency tests package — never the Google Sheet). If the pick is not one you
should take — too complex for who is picking it up, blocked on a harness gap, deliberately deferred — record
that instead of stepping over it: `effnext --skip Class.method --reason "…"` writes it to
`conversion-runs/skiplist.tsv` and prints the new next pick. Skips are advisory and reversible
(`--unskip`, `--skips`, `--include-skipped`); they never mark a test converted. Convert it onto
ui/efficiency; `effcheck.py` (static pre-flight) then the build-run via `effwatch`, reading **only** the JSON
verdicts (`effbuild --json`, `effverify --json`) — never the raw run report. Iterate until `clean`=true (or
"good enough + notes"). Log lessons to CONVERSION-LESSONS.md.

### 1b. Close out the conversion before you leave it (Claude, sandbox)
Annotate the legacy method `@Converted(replacedBy = [...], bug = NNNNN, since = "YYYY-MM")` **in the same
commit as the conversion** — the burndown keys off that marker, so a conversion landing without it reads as
unconverted. Record deliberate deviations in `notes`.

### 2. Create the Bugzilla bug → get the number (Claude → bridge → `effbug`)
Claude drops `conversion-runs/_queue/<id>.request.json`. Test-conversion bugs must `blocks` the tracking
meta (2030727); tooling/harness/docs bugs must not. Get the mechanism right *before* filing — BMO has no API
for editing a description, so a wrong comment 0 needs a human in the web UI.
```json
{ "bug": "create",
  "summary": "[efficiency] Convert <Test>.<method> to ui/efficiency",
  "comment": "Faithful port of the legacy smoke test onto ui/efficiency. <what/why>.",
  "template_bug": "2057054",
  "type": "task",
  "dry_run": false }
```
`template_bug` clones product/component/version from an already-filed efficiency bug so we file consistently
(no guessing) — resolves to **Firefox for Android :: UI Tests**, type `task`. After filing, effbug **edits the
bug title to prepend `Bug <id> - `** (option `prepend_bug_number`, default on) so the bug summary matches the
commit subject exactly. effwatch runs effbug; the `.done.json` points at `_bug/<id>.bug-result.json` =
`{"bug_id": N, "summary": "Bug N - …", …}`. Claude reads N + the final summary. (Use `"dry_run": true` to
preview the payload without filing.) The bug is **self-assigned** to the API key's owner by default (via BMO
`whoami`); override with `assigned_to` or env `BUGZILLA_ASSIGNEE`, or disable with `self_assign: false`. effbug
also has a `{"bug":"update","ids":[…],"self_assign":true}` action to (re)assign or edit existing bugs.
- One bug per landable unit of work. A conversion that also needed tooling/enablement can be one bug with a
  clear summary, OR split — mirror the Jira split in step 4 if the enablement is substantial.

### 3. Commit with the real bug number (Claude → bridge → `effgit`)

**Pre-commit gate: run `./mach gradle fenix:ktlint`.** This is the authoritative lint for anything under
`mobile/android/fenix` — NOT `./mach format` and NOT `effcheck`. `./mach format` runs mozlint's own ktlint
version and config; `mobile/android/fenix` has its own gradle `:fenix:ktlint` task with the project's config,
and that task is what CI enforces. A commit passed `./mach format` clean and then failed CI on
`import-ordering: aliases must be at the end`. `effcheck` does not run ktlint at all. Use
`fenix:ktlintFormat` to auto-fix. Aliased imports (`... as R`) go LAST in the import block.

Claude writes the commit message to `conversion-runs/<batch>/msg-<n>.txt`:
```
Bug NNNNNNN - [efficiency] Convert <Test>.<method> to ui/efficiency r=isabel_rios,aaronmt
<body: what was ported, any harness capability added, notes>
```
then drops a git commit request: `{ "git":"commit", "message_file":"<batch>/msg-<n>.txt", "paths":[...] }`.
(`effgit` stages the paths and commits `-F`.) Repeat per commit in the stack.

### 4. Jira — track conversion vs. enablement separately (Claude, Atlassian connector)
Goal: later measure how "easy" efficiency conversion is vs. legacy, by separating strict conversion from the
tooling/enablement it sometimes forces. Scheme (project MTE, epic MTE-5504):
- **Conversion work** → a **Sub-task labelled `conversion`** under the standing story **MTE-5731**
  ("Smoke-test conversion campaign", under epic MTE-5504).
- **Tooling / enablement discovered during conversion** → a **separate Sub-task labelled `enablement`**, placed
  under the Harness Hardening story **MTE-5715** (or Tech-Debt **MTE-5688** if it's not harness-shaped), and
  **linked** to the conversion sub-task ("Relates"). Put the Bugzilla bug number + Phab revision in the item.
- **Assign to Jackie at creation:** pass `assignee_account_id: "62d703809189e98a20189bf0"` to `createJiraIssue`
  (also add label `efficiency` alongside `conversion`/`enablement`). cloudId = `mozilla-hub.atlassian.net`;
  issue type = `Sub-task`; labels via `additional_fields: {"labels":[...]}`.
- Because we often don't know upfront whether enablement is needed, create these **after** the work, when the
  split is clear. The label split is what makes the effort comparison possible later.

### 5. Submit the finished stack (YOU, `effsubmit.py`)
When a fully-qualified stack is complete, Claude gives you the command; or just run:
```
python3 tools/effsubmit.py --start <first-new-commit>            # prints the bounded submit command
python3 tools/effsubmit.py --start <first-new-commit> --execute  # runs it (moz-phab still prompts first)
```
Reviewers default to **isabel_rios, aaronmt**. **Mozilla's moz-phab has NO `--dry-run`** — instead it is
interactive: it prints the exact commit list and asks Y/n before creating any revision, so that prompt is the
preview. Pass **`--start <first-new-commit>`** (the commit directly above the landed base) to bound the range to
`<start>..HEAD`, so it can never touch already-landed base revisions even if they carry `Differential Revision:`
trailers. Note: base landed on **autoland** (callsign `FIREFOXAUTOLAND`), which may be ahead of your local
`main`/central — that's fine; moz-phab keys off the commit trailers, not what's in central. Tag
**testing-exception-unchanged**: no moz-phab CLI flag exists (checked at runtime), so add it in the Phabricator
web UI after submit. Submitting/landing stays with you: the bridge refuses submit and Claude never runs it.

## If you rebase a stack that is already submitted
Dropping a commit does not remove its revision from the stack graph: abandoning D-nnn leaves the next
revision still recording it as a parent, with a diff based on the commit you dropped. Resubmit the whole
range so moz-phab re-parents everything — submitting only the changed commits leaves the abandoned
revision wedged in the chain. Every revision gets a fresh diff either way, and accepted ones reset to
needs-review, so warn the reviewers first.

## After landing
Run the repo-side reconcile (see the tae-conversion README) so the tracker's physical/in-review counts catch
up with what landed. The `@Converted` annotations are **not** part of this step — they ship in the conversion
commit itself (step 1b). Annotating after the fact leaves a window where the burndown reads the conversion as
missing, and in practice it is simply forgotten.
