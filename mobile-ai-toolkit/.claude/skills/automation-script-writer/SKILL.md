---
name: automation-script-writer
description: Writes XCUITest automation for the TestRail cases the automation-triager marked Suitable. Analyses the existing automation first, reuses screens, selectors, helpers and flows, adds the test to the class where it belongs, and records the outcome in a creation report. Never modifies TestRail. Triggers when the user asks to automate, implement or write test scripts for a triaged section.
argument-hint: "[section / folder under test, e.g. \"Document Sharing for Auto\"]"
---

# Write XCUITest automation for triaged cases

Follow-up to [`automation-triager`](../automation-triager/SKILL.md). It decides
*what* should be automated; this skill writes the code.

**Only cases marked `Suitable` are automated.** Never `Unsuitable`, never
`Untriaged`, never `Completed`.

The objective is **not** to maximise code written. It is the smallest correct
change that automates the scenario while maximising reuse and staying
consistent with the existing framework. Obey
[`standards.md`](../../standards.md).

**Contents**

| Section | Purpose |
|---|---|
| [Scope](#scope) | What this skill touches and what it must not |
| [Step 0 — Choose the project](#step-0--choose-the-testrail-project) | **Ask first.** Nothing is read before this |
| [Step 1 — Inputs](#step-1--gather-the-inputs) | Triage results + TestRail data |
| [Step 2 — Analyse first](#step-2--analyse-the-existing-automation-first) | Mandatory, before any code |
| [Step 3 — Already automated?](#step-3--decide-whether-it-is-already-automated) | Duplicate detection |
| [Step 4 — Where it belongs](#step-4--decide-where-the-test-belongs) | Existing class vs. new |
| [Step 5 — Implement](#step-5--implement) | Branch, framework rules, declaration, test plans |
| [Step 6 — Duplication](#step-6--handle-duplication-in-the-modified-class) | Scoped helper extraction |
| [Step 7 — Review](#step-7--review) | Self-check before building |
| [Step 8 — Compile and run](#step-8--compile-fix-every-error-and-run-the-tests) | Build, fix all errors, execute |
| [Step 9 — Report](#step-9--write-the-creation-report) | The required output file + PR description |
| [Hard rules](#hard-rules) | Limits |

---

## Scope

**In scope:** reading TestRail (read-only) in the **one project the user
chose**, reading and modifying the XCUITest project at `XCUITEST_REPO_PATH`,
and writing the creation report.

**Out of scope, absolutely:**

* **Never modify TestRail.** Not the automation status, not labels, not any
  field. Already-automated cases are recorded in the report only. If the user
  wants TestRail updated, that is the triager's job.
* Never automate a case that is not `Suitable`.
* Never run repository-wide cleanup or refactoring.
* Never push a branch, open a pull request, or commit unless the user asks.
  The branch is created locally and the PR description is written into the
  report for the author to use.

---

## Step 0 — Choose the TestRail project

**Ask before anything else.** Before searching for a section or folder, and
before retrieving a single test case, ask the user which TestRail project to
use and **wait for the answer**. There is no default. Never infer the project
from the section name, the repository, or a previous run.

Display the options exactly as written in
[`testrail-projects.md`](../../testrail-projects.md) — including the `(*)` on
Firefox for iOS and its ⚠️ warning, every time you present the choice. The
script prints the same block, so you can render it rather than retype it:

```text
python3 scripts/testrail_triage_automation.py projects
```

The answer becomes `--project` on every later command:

| Answer | `--project` | Project id from | Suite id from |
|---|---|---|---|
| 1 — Firefox for iOS (*) | `1` or `firefox-ios` | `TESTRAIL_iOS_PROJECT_ID` | `TESTRAIL_iOS_FULL_SUITE_ID` |
| 2 — [TEMP] TC approvals | `2` or `temp-approvals` | `TESTRAIL_TMP_PROJECT_ID` | `TESTRAIL_TMP_SUITE_ID` |

**If `automation-triager` has already run for this section, use the project it
used** — its report names the project, id and suite. Still show the user which
project you are continuing in and let them correct it. If the triage results
arrive without a stated project, ask; never assume the two agents are on the
same one.

This agent **never writes to TestRail**, so no write confirmation applies. That
is exactly why the choice still matters: reading the wrong project yields the
wrong cases, and the code written from them would automate the wrong
behaviour. Use the chosen project and suite for every step that follows, and
never mix cases between the two projects.

Every command echoes the project it resolved — name, id, suite and the
variables they came from. Check that banner matches what the user chose, and
repeat it to the user. Ids come from `.env`; if a required variable is missing
or invalid, stop and explain rather than switching projects.

---

## Step 1 — Gather the inputs

You need the **section / folder under test** (given when the agent is
triggered), the **triage results**, the **TestRail case data**, the **branch
inputs**, and the **affected-tests mode**.

1. **Confirm the TestRail project** chosen in
   [Step 0](#step-0--choose-the-testrail-project), then **resolve the folder
   under test**. If the request does not name one, ask — never guess. The
   folder is looked up only in the chosen project's suite.

2. **Reuse the triage analysis if it is still available** — the triager's
   verdicts and reasoning for this section, either in the conversation or in
   `work/outputs/automation-triage/`. Its reasons already name the screens,
   selectors and helpers it found, which is a head start on Step 2.

3. **If the triage analysis is gone, rebuild it.** Do not guess and do not skip
   ahead. Pull the Suitable cases straight from TestRail:

   ```text
   python3 scripts/testrail_triage_automation.py fetch "<section>" --status Suitable --project <1|2>
   ```

   Read-only. Prints each case with its title, section, priority, type,
   labels, **Sub Test Suite(s)**, **TestRail URL**, preconditions and
   step/expected pairs — everything Steps 5 and 8 need. `--json` gives the same
   data machine-readably.

   Then perform the repository analysis in Step 2 yourself, from scratch.

4. **Resolve the branch inputs.** The work goes on a branch in the XCUITest
   project named `<mozilla_username>/<ticket_no>` — for example
   `dbigu/MTE-1234`.

   | Input | Where it comes from |
   |---|---|
   | Ticket number | Given when the agent is triggered. **If it was not given, ask for it before creating the branch.** Never invent or guess one. |
   | Mozilla username | `MOZILLA_USERNAME` from the environment (a local `.env` loads automatically). If it is unset, fall back to the local part of `git config user.email` and **confirm it with the user** before using it. |

5. **Resolve the affected-tests mode** used in [Step 8.5](#85-affected-test-cases).
   The author chooses, when the agent is triggered, between:

   | Mode | Meaning |
   |---|---|
   | `full` | Re-run every affected existing test and report the observed result of each. |
   | `list` | Do not re-run them — only list the affected tests in the report. |

   If the trigger did not say, **ask**. `full` is the default when the user
   expresses no preference, because it is the only mode that validates
   anything.

Never take the triage reasoning on trust for details you are about to depend
on. If a reason claims a helper exists, open it.

---

## Step 2 — Analyse the existing automation first

**Do not write or edit a single line before this is done.** For each Suitable
case, work out what already exists:

| Look at | For |
|---|---|
| Test classes covering the feature area | An existing test for the same scenario, and the natural home for a new one |
| `PageScreens/` | Screen objects for the screens the case touches |
| `Selectors/` | Selector sets for the controls involved |
| The app's accessibility identifier catalogue | Whether the elements are addressable, or need an identifier added |
| Base test class | Setup, teardown, relaunch and wait helpers every test inherits |
| Launch arguments, fixtures, mocks, local servers | How the case's starting state can be forced |
| Navigation helpers and reusable flows | How to reach the entry point |
| Existing tests linking the same TestRail id | Prior coverage — search by case id |

**`AIControlsTests` is the reference implementation.** Read it before writing
anything. It demonstrates the structure, naming, setup, screen usage,
assertion style and private-helper placement every new test must follow.

---

## Step 3 — Decide whether it is already automated

Before creating anything, establish whether the scenario is already covered.

* Compare **scenario, steps and expected behaviour** — not method names. A test
  covering the same flow under a different name is still the same coverage.
* Search for the TestRail case id; the suite links cases in comments.

If an equivalent test exists:

* **Leave it unchanged.**
* Record the case as **Already Automated** in the report, naming the existing
  test and its file path.
* Do **not** create a second test, and do **not** touch TestRail.

Only genuine equivalence counts. A test that exercises a neighbouring flow, or
covers part of the scenario, is not the same coverage — say so in the report
and automate the gap.

---

## Step 4 — Decide where the test belongs

If a class is already the natural home for the scenario, **add the test there**
and follow that class's existing structure.

Create a new test class only when no existing class is an appropriate match.
When you do, follow the conventions of the new framework, using
`AIControlsTests` as the structural reference.

Do not create a new class when an existing one is the obvious location.

---

## Step 5 — Implement

### Create the branch before you edit anything

The changes live on their own branch in the XCUITest project, named from the
inputs resolved in Step 1:

```bash
cd "$XCUITEST_REPO_PATH"
git status --short                              # stop if the tree is dirty — ask what to do
git switch -c "<mozilla_username>/<ticket_no>"  # e.g. dbigu/MTE-1234
```

* **No ticket number, no branch.** Ask for it rather than inventing one.
* Branch from the repository's current default branch unless the user names
  another base.
* One branch per run. If it already exists, switch to it instead of creating a
  second one.
* **Do not commit, push, or open a pull request** unless the user asks. The
  branch holds the changes; the PR description goes in the report (Step 9) for
  the author to use.

### Use the framework, do not bypass it

* Drive the UI through screen classes in `PageScreens/`.
* Address controls through selector sets in `Selectors/`.
* **Before adding a screen method or selector, verify an equivalent does not
  already exist.**
* If new functionality is genuinely needed, put it in the right layer — a
  screen method or a selector — not raw `XCUIElement` interaction inside the
  test, where that would break the existing pattern.
* Follow the architecture, naming, setup, assertion and interaction patterns of
  the existing new-framework tests.

### Test declaration

Every newly automated case carries the TestRail link and, where the Sub Test
Suite calls for it, the suite marker — in the repository's existing style,
immediately above the test function:

```swift
// https://mozilla.testrail.io/index.php?/cases/view/3960880
// Regression
func testAIFeaturesSetToOffAreNotAvailable() throws {
```

* **TestRail link** — use the URL from the fetch output (`TestRail:` line).
  Never invent one.
* **Suite marker** — determined from the case's **Sub Test Suite(s)** field,
  *not* from the scenario:

  | Sub Test Suite contains | Marker |
  |---|---|
  | `Regression` | `// Regression` |
  | `Smoke & Sanity` | `// Smoketest` |
  | neither | no marker — do not invent one |

  Other values in the field (`Special Case`, `Functional`, …) map to nothing
  and are ignored. If a case carries both, use the one the class's neighbouring
  tests use and note it in the report.

### Update the test plans

Every newly automated test must land in exactly one test plan, chosen from the
case's **Sub Test Suite(s)** and TestRail classification — the same field that
decides the marker, **never** from the scenario:

| TestRail classification | Runs in |
|---|---|
| `Smoke` and/or `Sanity` | `Smoketest.xctestplan` |
| `Regression`, or none of `Regression`/`Smoke`/`Sanity` | `FullFunctionalTestPlan.xctestplan` |

**Both plans work by exclusion, not selection.** Each has a single `XCUITests`
target with a `skippedTests` array and no `selectedTests`, so **a new test runs
in both plans until you skip it in one.** Doing nothing is therefore wrong in
either direction. Add one entry, to the plan the test must *not* run in:

| Runs in | Add `XCUITests/<Class>/<method>()` to |
|---|---|
| `Smoketest` | `FullFunctionalTestPlan.xctestplan` → `skippedTests` |
| `FullFunctionalTestPlan` | `Smoketest.xctestplan` → `skippedTests` |

Confirm the convention against the class you are editing before you touch
anything — a `// Smoketest` test is skipped in FullFunctional, a `// Regression`
test is skipped in Smoketest:

```bash
find "$XCUITEST_REPO_PATH" -name "*.xctestplan"
python3 -c "import json;d=json.load(open('<plan>'));print(d['testTargets'][0]['skippedTests'])"
```

* Entries carry the trailing `()` and are kept in the file's existing
  alphabetical order.
* Never remove or reorder an existing entry, and never clean up stale entries
  for tests that no longer exist — out of scope.
* Record in the report which plan each test runs in and which skip list you
  added it to.

### Comments

Keep them to an absolute minimum — only where the code cannot speak for itself,
and never more than two lines. Prefer descriptive method and helper names.
Never write long explanatory comments.

---

## Step 6 — Handle duplication in the modified class

When adding a test to an existing class, check that class for duplication
introduced or exposed by your change.

If the same logical sequence now appears in more than one test:

1. Extract it into a well-named `private func` in that class.
2. Update the existing tests that contained the sequence to call it.
3. Use it in the new test too.

**Behaviour must be identical afterwards.** The refactor is limited to the
class you are already modifying and to duplication relevant to the automation
being added. No repository-wide cleanup.

---

## Step 7 — Review

Review every file you changed and confirm:

* no equivalent test already existed;
* existing screens, selectors, helpers and flows were reused where applicable;
* `PageScreens/` and `Selectors/` are used rather than bypassed;
* the implementation matches the `AIControlsTests` patterns;
* the TestRail link is present in the repository's convention;
* the correct `// Regression` / `// Smoketest` marker is applied, derived from
  the Sub Test Suite;
* the test was added to the test plan its classification calls for;
* the work is on the `<mozilla_username>/<ticket_no>` branch, not on the
  default branch;
* no duplicate selector, screen method or test flow was introduced;
* refactored existing tests behave exactly as before.

---

## Step 8 — Compile, fix every error, and run the tests

**A test you have not compiled and run is not finished.** Writing plausible
Swift is the easy half; XCUITest code fails on symbol names, selector types and
timing that only a real build and a real run expose. Work through 8.1 to 8.5 in
order and do not stop early because the code "looks right".

When compilation or test execution fails: identify the errors, fix them, then
compile and run again — **up to three attempts**. After three unsuccessful
attempts, stop retrying and report the remaining errors or failing tests
verbatim. An honest blocker beats a fabricated green.

### 8.1 Toolchain preflight

```bash
xcode-select -p          # must be an Xcode.app, NOT /Library/Developer/CommandLineTools
xcodebuild -version
xcrun simctl list devices available | grep iPhone
```

If `xcode-select -p` points at `CommandLineTools`, `xcodebuild` cannot build the
project. Say so, give the user the one-line fix, and **stop** — do not report
the work as validated:

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

Never substitute `swiftc -parse` for a build and call it validation. It checks
syntax only: it resolves no symbols and type-checks nothing, so it passes code
that cannot possibly compile.

### 8.2 Build for testing

Mirror the project's CI invocation (`firefox-ios`, scheme `Fennec`,
configuration `Fennec_Testing` — confirm against `bitrise.yml` and the repo's
`AGENTS.md`, and prefer a documented wrapper such as `fxios test` when one is
on `PATH`):

```bash
xcodebuild \
  -project firefox-ios/Client.xcodeproj \
  -scheme Fennec \
  -configuration Fennec_Testing \
  -sdk iphonesimulator \
  -destination "platform=iOS Simulator,name=<an available iPhone>" \
  -derivedDataPath /tmp/fxios-dd \
  CODE_SIGNING_ALLOWED=NO COMPILER_INDEX_STORE_ENABLE=NO \
  -skipMacroValidation \
  build-for-testing 2>&1 | tail -60
```

A first build of this project is slow — allow a generous timeout and let it
finish rather than killing and restarting it.

### 8.3 Fix every compilation error

Iterate: build, read the **first** real error, fix it, rebuild. Later errors are
often cascades of the first, so do not batch-guess fixes.

**How to fix matters more than that it compiles.** When an error names a symbol,
open the file that defines it and use the real signature — never guess a second
time, and never invent an overload:

* wrong helper name or signature → find the actual one in `BaseTestCase`,
  `XCUIElementHelpers` or the screen class;
* unknown screen-graph state or action → check `FxScreenGraph.swift` and the
  `register*Navigation.swift` files;
* selector strategy missing → add it to `SelectorHelper` as a new case handled
  in *both* switches, resolving to exactly the element query you need;
* concurrency or `@MainActor` complaints → match how the neighbouring screen
  classes are annotated.

Forbidden ways to "fix" a build:

* commenting out, `XCTSkip`-ing or deleting the failing test or assertion;
* weakening an assertion (`assertX` → `if x.exists`) to dodge an error;
* changing unrelated existing code to accommodate your new code;
* casting or force-unwrapping purely to silence the compiler.

If the same error survives **three** attempts, stop. Report it verbatim in the
creation report with what you tried, and mark the affected case
`Unable to Automate`.

### 8.4 Run the new tests

Run each new test individually, by name, against a booted simulator:

```bash
xcodebuild \
  -project firefox-ios/Client.xcodeproj \
  -scheme Fennec \
  -configuration Fennec_Testing \
  -destination "platform=iOS Simulator,name=<the same iPhone>" \
  -derivedDataPath /tmp/fxios-dd \
  CODE_SIGNING_ALLOWED=NO \
  -only-testing:XCUITests/<TestClass>/<testMethod> \
  test-without-building 2>&1 | tail -40
```

Triage each failure honestly — the fix depends entirely on the cause:

| Failure | What to do |
|---|---|
| Wrong identifier / element type / query | Fix the selector, then re-run |
| Timing, animation or CI-only race | Use the existing wait helpers, never a bare `sleep` |
| Test expects something the case never stated | Fix the test to match the TestRail case |
| **The product genuinely misbehaves** | **Leave the assertion alone.** Report it as a suspected product bug |

**Never edit an assertion so a failing test turns green.** If the test is right
and the app is wrong, that is a finding, not a defect in your test.

The same three-attempt cap applies here: fix and re-run at most three times,
then report the test as still failing, with the failure output.

### 8.5 Affected test cases

First **identify** every existing test your change touched — directly, or
through an extracted helper, a shared screen or a shared selector. What happens
next depends on the affected-tests mode the author chose at trigger time
(Step 1):

| Mode | What you do |
|---|---|
| `full` | Re-run every affected test and record the observed result of each. |
| `list` | Do not re-run them. List them in the report under a heading that states plainly that they were **not executed**. |

If the mode was never resolved, ask before continuing — do not assume one.

Under `list`, never describe the affected tests as passing, unaffected or
validated. The report says which tests the change reaches and that they were
not run at the author's request; nothing more.

Under `full`, re-run them:

```bash
-only-testing:XCUITests/ShareToolbarTests -only-testing:XCUITests/ShareMenuTests
```

Also lint when SwiftLint is installed (`brew install swiftlint`); the config is
`.swiftlint.yml` at the **repository root**, above the `firefox-ios/` directory:

```bash
swiftlint lint --config .swiftlint.yml --quiet <changed files>
```

Lint in both modes. Record the real outcome of every command in the report —
build status, each test's pass/fail, and the affected-test run or list.
**Never describe unvalidated code as validated, and never report a pass you did
not observe.**

---

## Step 9 — Write the creation report

```text
work/outputs/automation_test_scripts/<folder under test>/test_scripts_creation_report.md
```

Create the directory if needed. **Append to or update the existing file** —
never discard entries for cases processed earlier in the same task.

One entry per TestRail case processed, with at least:

* TestRail Test Case ID
* TestRail Test Case Name
* TestRail Link
* Automation Status — `Created`, `Updated`, `Already Automated` or
  `Unable to Automate`
* Automation Test Name
* Script location in the repository
* Test Suite Classification, the marker applied, and the test plan it was
  added to
* **Build result** and **test result** — the observed outcome from Step 8
* Notes, where relevant

Use `Created` only for a test that **compiles and has been run**. A test that
cannot be made to compile, or that cannot be executed because the toolchain is
unavailable, is not `Created` — say what actually happened.

The report must also carry:

* **The TestRail project the cases came from** — name, id and suite, exactly as
  the fetch banner reported them. It is what tells a later reader, or a later
  run, which project this work belongs to.
* **The branch** — `<mozilla_username>/<ticket_no>`, and the base it was cut
  from.
* **A validation section** stating, plainly: the exact build command used,
  whether the build succeeded, the per-test pass/fail, the affected tests
  (re-run with their results under `full`, listed as not executed under
  `list`), and the SwiftLint result. If any of these could not be performed,
  name the reason instead of omitting it.
* **A PR description section** — ready for the author to paste when they open
  the pull request.

Example entry:

```markdown
### C12345 — Verify AI Controls behavior

- TestRail ID: C12345
- TestRail Name: Verify AI Controls behavior
- TestRail Link: https://mozilla.testrail.io/index.php?/cases/view/12345
- Automation Status: Created
- Automation Test: testVerifyAIControlsBehavior
- Script Location: firefox-ios-tests/Tests/XCUITests/AIControlsTests.swift
- Test Suite: Regression
- Marker: // Regression
- Build: Succeeded (Fennec / Fennec_Testing, iPhone 17 simulator)
- Test Result: Passed (42.1s)
- Notes: Reused the existing AI Controls navigation flow.
```

### The PR description

A single `## PR Description` section at the end of the report, containing:

* **Links to the relevant tests** — as a list, one TestRail URL per case
  automated in this run, each with its case id and title.
* **A short description of the changes** — a few sentences: what was automated
  and how, no more.
* **A list of the affected files** — every file added or modified, including
  the test plans.

```markdown
## PR Description

Branch: `dbigu/MTE-1234`

### Tests

- [C12345 — Verify AI Controls behavior](https://mozilla.testrail.io/index.php?/cases/view/12345)
- [C12346 — Verify AI Controls are hidden when disabled](https://mozilla.testrail.io/index.php?/cases/view/12346)

### Changes

Automates two AI Controls cases in `AIControlsTests`, reusing the existing AI
Controls navigation flow and settings screen. Adds one selector for the
controls toggle; both tests are registered in `FullFunctionalTestPlan`.

### Affected files

- `firefox-ios-tests/Tests/XCUITests/AIControlsTests.swift`
- `firefox-ios-tests/Tests/XCUITests/Selectors/AIControlsSelectors.swift`
- `firefox-ios-tests/Tests/XCUITests/FullFunctionalTestPlan.xctestplan`
```

List only files you actually changed, and only tests you actually automated in
this run — the PR description is not a place to pad.

For **Already Automated**, give the existing test name and location as the
reference. For **Unable to Automate**, state the blocking reason plainly — do
not invent selectors, requirements, TestRail data or expected behaviour to
force a case through.

---

## Required execution order

Per case, in this order — never write the test first and look for reuse
afterwards:

```text
project choice → triage result → TestRail case → existing-automation search
  → framework analysis → reuse decision → already-automated check
  → class selection → branch
  → implementation / scoped refactor → test plan update → review → build
  → fix compilation → run the test → affected tests (re-run or list)
  → report entry + PR description
```

---

## Hard rules

1. **Always ask which TestRail project to use before searching for a section
   or reading a case.** Never default, never infer. Show the `(*)` and the ⚠️
   warning every time the choice is presented, per
   [`testrail-projects.md`](../../testrail-projects.md).
2. **One project per run.** Use the project the user chose — the one the
   triager used — for every read. Never mix cases or sections between the two
   projects, and never hardcode a project or suite id: they come from `.env`
   via the selected project's variables. If one is missing or invalid, stop
   and explain.
3. **Automate only `Suitable` cases.**
4. **Never modify TestRail** — not status, not labels, not any field.
5. **Analyse before implementing.** No code until Step 2 is complete.
6. **Reuse beats writing.** No new screen method, selector, helper or flow when
   an equivalent exists.
7. **Never duplicate an existing test** because its method name differs. Judge
   by scenario, steps and expected behaviour.
8. **Minimal, targeted changes.** Do not rename or alter unrelated tests,
   methods or classes; do not rewrite working code for style; no
   repository-wide cleanup.
9. **Preserve behaviour** of every existing test you touch.
10. **Use the framework** — `PageScreens/` and `Selectors/`, patterned on
    `AIControlsTests`.
11. **Never invent** a TestRail URL, a suite marker, a selector or an expected
   behaviour. Missing information is a blocker to report, not to fill in.
12. **Comments minimal**, two lines maximum.
13. **Branch before you edit.** Work on `<mozilla_username>/<ticket_no>`, with
    the ticket number from the trigger — ask if it was not given. Never
    commit, push or open a pull request unless asked.
14. **Every new test lands in exactly one test plan.** The plans skip rather
    than select, so a new test runs in both until you add it to the other
    plan's `skippedTests`. `Smoke`/`Sanity` → runs in `Smoketest`, skipped in
    `FullFunctionalTestPlan`; everything else → runs in
    `FullFunctionalTestPlan`, skipped in `Smoketest`.
15. **Build it and run it.** A test that has not compiled and executed is not
    done. `swiftc -parse` is not a build and never counts as validation.
16. **Three attempts, then stop.** Fix and re-run at most three times, then
    report the remaining errors or failing tests verbatim.
17. **Fix compilation errors properly** — by reading the real API, never by
    deleting, skipping, weakening or commenting out the test.
18. **Never turn a failing test green by changing what it asserts.** If the
    product is wrong, report a suspected product bug and leave the test failing.
19. **Never claim validation you did not perform**, and never report a pass you
    did not observe — including the affected tests under `list` mode, which are
    listed as not executed.
20. **English, clear and concise**, per `standards.md`.
