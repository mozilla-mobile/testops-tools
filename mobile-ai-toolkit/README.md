# Mobile AI Toolkit

A Claude Code workspace that turns mobile feature requirements into a reviewed,
TestRail-ready manual test suite — and reads finished suites back out of
TestRail as feature documentation.

It targets **Firefox for Android and iOS**, but nothing in it is
Firefox-specific beyond the defaults in `.env`.

The toolkit is six agents: four wired into one pipeline, plus a triage agent
that classifies existing TestRail cases for XCUITest automation and a writer
agent that implements the ones it marks Suitable.

```
work/inputs/<feature>/            work/outputs/<feature>/
  PRDs, Figma exports,     ──▶  1. testcase-generator  ──▶  <feature>-testcases.csv
  screenshots, telemetry                                    manifest.md
  tables
                                 2. testcase-reviewer   ──▶  <feature>-testcases.csv (rewritten in place)
                                    (interactive)            review_report.md

                                 3. testrail-importer   ──▶  TestRail sections + cases
                                                             testrail_import_report.md

TestRail (read-only)       ──▶  4. feature-documenter  ──▶  feature_documentation.md

TestRail section
  (Untriaged cases)
  + XCUITest checkout      ──▶  5. automation-triager  ──▶  Automation: Suitable / Unsuitable
                                   (asks which project)       triage_report.md

Suitable cases
  + XCUITest checkout      ──▶  6. automation-script-writer ──▶  XCUITest code (in the app repo)
                                   (asks which project;          test_scripts_creation_report.md
                                    never writes TestRail)
```

Steps 1–3 are a chain; step 4 is an independent read-only loop that feeds
authoring lessons back into step 1. Step 5 is independent of all of them — it
classifies cases that already live in TestRail, and step 6 implements the ones
step 5 marked Suitable. Steps 5 and 6 both begin by asking which
[TestRail project](#testrail-project-selection) to work in.

---

## Setup

**Prerequisites**

- [Claude Code](https://claude.com/claude-code) — the agents are Claude Code
  agents/skills, not standalone CLIs.
- Python 3.9+ with `requests`. `python-dotenv` is optional but recommended —
  without it, `.env` is not auto-loaded and you must export the variables
  yourself.
- A TestRail account with an API key (TestRail → *My Settings* → *API Keys*)
  for the importer and documenter. The generator and reviewer work fully
  offline.

```bash
pip install requests python-dotenv
```

**Credentials**

```bash
cd mobile-ai-toolkit
cp .env.example .env   # then fill in URL, user, API key, project and suite ids
```

`.env` is gitignored. No agent prints or logs the API key — that is a hard rule
in every playbook.

**Run Claude Code from `mobile-ai-toolkit/`.** All paths in the agents are
relative to this directory, and `.claude/settings.json` pre-approves the
read/write and Bash permissions the agents need (`work/**`, `python3`, and the
usual read-only shell tools), so a normal run should not prompt you.

**First run**

```text
# 1. drop the requirements into work/inputs/google-lens/
/testcase-generator google-lens
/testcase-reviewer google-lens
/testrail-importer google-lens
```

---

## Repository layout

```
mobile-ai-toolkit/
├── .claude/
│   ├── agents/                    # the runners — one .md per agent
│   │   ├── testcase-generator.md
│   │   ├── testcase-reviewer.md
│   │   ├── testrail-importer.md
│   │   ├── feature-documenter.md
│   │   ├── automation-triager.md
│   │   └── automation-script-writer.md
│   ├── skills/                    # the playbooks the runners execute
│   │   ├── testcase-generator/SKILL.md
│   │   ├── testcase-reviewer/SKILL.md
│   │   ├── testrail-importer/SKILL.md
│   │   ├── feature-documenter/SKILL.md
│   │   ├── automation-triager/SKILL.md
│   │   └── automation-script-writer/SKILL.md
│   ├── assets/templates/
│   │   ├── fifa.csv               # gold standard for structure, naming, detail
│   │   └── layout.png             # reference for UI/Layout case formatting
│   ├── standards.md               # hard rules that override everything
│   ├── testrail-projects.md       # the project choice both automation agents must ask
│   └── settings.json              # team permissions (settings.local.json is yours)
├── scripts/
│   ├── testrail_client.py               # shared TestRail integration layer
│   ├── testrail_import.py               # CSV → TestRail (creates only)
│   ├── testrail_fetch_section.py        # TestRail → stdout (read-only)
│   └── testrail_triage_automation.py    # automation triage: projects + fetch + apply
└── work/
    ├── inputs/<feature>/          # gitignored — unreleased product material
    └── outputs/<feature>/         # gitignored — regenerate, don't version
```

### The TestRail integration layer

`scripts/testrail_client.py` is the single place that talks to TestRail. Every
workflow script goes through it; none of them implement authentication,
configuration, HTTP, retries, pagination or field mapping themselves:

```
agent → testrail_import.py            ┐
agent → testrail_fetch_section.py     ├→ testrail_client.py → TestRail API
agent → testrail_triage_automation.py ┘
```

What it owns — each of these exists exactly once:

| Area | Entry points |
|---|---|
| Credentials and settings | `Config`, `load_config`, `env_int` |
| The selectable TestRail projects | `ProjectChoice`, `FIREFOX_IOS`, `TEMP_APPROVALS`, `project_menu`, `project_target`, `verify_project_target`, `project_banner` |
| Authenticated HTTP, retries, rate limits, pagination | `TestRailClient` |
| Project / suite / section / case reads, metadata cached per run | `TestRailClient`, `section_tree`, `section_subtree` |
| Text normalisation and rich-text flattening | `norm`, `key`, `html_to_text` |
| Numbered steps → (action, expected) pairs | `parse_numbered`, `pair_numbered` |
| A case as plain text | `CaseView`, `case_view` |
| Custom fields and option ids | `find_case_field`, `field_items`, `field_options`, `map_id` |
| Automation status | `AutomationField`, `resolve_automation_field`, `build_automation_update` |
| Markdown reports | `md_table`, `md_fields`, `md_cell`, `write_report` |
| CLI error handling | `run_cli` |

Each workflow script contains only its own logic — CSV parsing, section
printing, triage decisions — and shares everything else. The project registry
lives here rather than in the triage script, so the triager, the writer and the
fetcher cannot disagree about which projects exist, which environment variables
each one uses, or what the selection prompt says. The one project-specific
piece outside it is the production write gate, which belongs to the only script
that writes.

Add a new TestRail script by importing from `testrail_client`, never by copying
an existing script's client, config, parsing or report code. There is one error
type (`TestRailError`), one integer-from-environment reader (`env_int`), one
numbered-step parser and one markdown table builder; a second one is a bug, not
a convenience.

Both `work/` subtrees are gitignored on purpose: inputs hold unreleased product
material that must never enter git history, and outputs are reproducible.

---

## The agents

### 1. `testcase-generator` — requirements → TestRail CSV

**Scope.** Reads every file in `work/inputs/<feature>/` (specs, PRDs, Figma
exports, ticket screenshots, telemetry tables) and writes a TestRail-importable
8-column CSV plus a companion manifest. It writes **manual** cases for a human
tester — never automation code.

**Usage**

```text
/testcase-generator <feature>     # folder name inside work/inputs/, or a path to a requirements file
```

The skill runs a checkpoint inline first — it restates the feature name,
platforms in scope and target paths, then **stops and waits for you to say
"go"** before spawning the agent. Expect it to ask questions mid-run when the
requirements are ambiguous; answers get used, unanswered questions land in the
manifest as gaps.

**Outputs** (exactly two files, in `work/outputs/<feature>/`)

| File | Contents |
|---|---|
| `<feature>-testcases.csv` | The 8-column suite. |
| `manifest.md` | Requirement → case traceability, the design techniques used and why, "Example test data (tester aids, not from spec)", gaps and assumptions, out-of-scope flag behaviour, justification for any third accessibility case, evidence for any iPad case, and contradictions found in the sources. |

**What makes it more than "write me some test cases"**

- **Technique-driven, not ad hoc.** Cases are derived with named techniques —
  Happy Path, Boundary Value Analysis, Equivalence Partitioning, Negative,
  Decision Table, State Transition, Use Case/Scenario, Error Guessing, Pairwise
  — and the ones used are recorded in the manifest so the coverage rationale is
  auditable. Most features need three or four, not all nine.
- **Levels without duplication.** Unit / Integration / System / Acceptance
  expressed as a manual tester can execute them, with an explicit rule that a
  validation is asserted **once**, at the lowest level where it can fail.
- **Concrete test data, always.** No abstract phrasing like "a URL that returns
  404 is available" — every input carries an inline `(e.g., https://httpstat.us/404)`.
  It prefers values visible in the supplied mockups, and falls back to standard
  free utilities (`httpstat.us`, `badssl.com`, non-resolving `.invalid` hosts).
- **Tooling-aware technical steps.** For API-backed features it writes
  beginner-usable Postman / Proxyman / Mockoon instructions — environment setup,
  concrete JSON payloads, which payload fields to inspect, mock configs for
  500/403/504 and route delays.
- **UI/Layout as a checklist.** Layout cases enumerate every expected element
  and walk the Light → Dark → Portrait → Landscape → Normal → Private matrix.
  "The UI is displayed correctly" is banned.
- **Self-validates before delivering.** Re-parses the CSV to confirm every row
  has exactly 8 columns, then counts rows per section against the
  [coverage caps](#coverage-caps-hard-limits) and reports the counts.

**It will not:** test feature flags, Nimbus variants, secret/debug settings or
"feature disabled" states; exceed 2 accessibility or 2 telemetry cases; create
an iPad folder without evidenced tablet-only behaviour; or invent a requirement
that isn't in the source.

---

### 2. `testcase-reviewer` — independent audit of a generated CSV

**Scope.** Acts as an external QA Lead auditing the CSV against the
requirements — deliberately with **no author bias**: it does not assume the CSV
came from the generator or follows any template. It proposes, you approve, then
it edits.

**Usage**

```text
/testcase-reviewer <feature>
```

**Inputs** — resolved from `work/outputs/<feature>/`: the CSV and `manifest.md`
(or any markdown requirements file there). If more than one CSV is present it
stops and asks rather than guessing.

**Workflow — a three-step approval loop.** This is the part to understand
before you run it:

1. **Analyze & propose.** Every finding gets a unique id (`PROP-01`, `PROP-02`).
   Findings affecting several cases are grouped under one id.
2. **Present & wait.** You get a table of *Proposal ID / Type (Gap, Redundancy,
   Technical, Formatting) / Description / Affected test case titles*. The
   affected-titles column lists **verbatim titles**, never just a count or a
   folder, so you know exactly where each change lands. Then it **stops**. You
   reply `Approve PROP-01`, `Approve PROP-01, PROP-03`, or `Approve All`.
3. **Apply & record.** Only approved proposals are applied. The **original CSV
   is overwritten in place** (no `_reviewed` copy — the report is the audit
   trail), then re-parsed to confirm all rows still have 8 columns.

**Outputs**

| File | Contents |
|---|---|
| `<feature>-testcases.csv` | Rewritten in place with the approved changes. |
| `review_report.md` | Review date, target feature, and a status table listing **every** proposal — including the rejected ones — with APPLIED / REJECTED and notes. |

**Audit dimensions** (`.claude/skills/testcase-reviewer/SKILL.md`)

| § | Dimension | Question |
|---|---|---|
| 1 | Requirements traceability & gap analysis | Is anything missing? |
| 2 | Business sufficiency & de-duplication | Is anything redundant? |
| 3 | Technical validation & tooling standards | Are the Postman/Proxyman/Mockoon steps actually executable? |
| 4 | Formatting & TestRail best practices | Will it import and read correctly? |
| 5 | Coverage caps & scope exclusions | Does it break a hard limit? |

§5 mirrors the generator's caps exactly, so the reviewer is a real second
opinion on the same contract rather than a different standard. It reports
per-section case counts with its findings.

---

### 3. `testrail-importer` — reviewed CSV → TestRail

**Scope.** A thin, deterministic wrapper over `scripts/testrail_import.py`. One
action, no modes: create a root section named after the feature and build the
CSV's whole section structure and every case inside it.

**Usage**

```text
/testrail-importer <feature>
# equivalent to:
python3 scripts/testrail_import.py <feature>
```

**Priority-based suite routing.** `Critical` / `High` / `Medium` cases go to
`TESTRAIL_TMP_SUITE_ID`; `Low` cases go to `TESTRAIL_TMP_SUITE_ID_LOW`. Each suite that
receives cases gets its own root section named after the feature
(`google-lens` → `Google Lens`). If the CSV contains Low-priority cases and
`TESTRAIL_TMP_SUITE_ID_LOW` is unset, the import fails **before creating anything**.

**What it does, in order**

1. Parse and validate the CSV (required columns; every row has section, title,
   steps, expected results, priority, type; steps pair with expected results).
2. Read TestRail priorities, case types, case fields, templates, existing
   sections.
3. Verify the configured custom fields exist. External ID and Sub Test Suite are
   optional — missing ones are skipped, not fatal.
4. Split cases by priority, create the root section per target suite, recreate
   the nested structure (`/`, `>` or `::` in `Section (Folder)` express nesting),
   creating parents before children and reusing sections that already exist.
5. Create the cases, mapping Priority and Type to TestRail ids (`P0`–`P3`
   aliases accepted).
6. Write the report.

**Output.** `work/outputs/<feature>/testrail_import_report.md` — target
project/suite, root section, per-suite breakdown, sections created, cases
created, created case ids, failures, and a status of `COMPLETED` or
`COMPLETED_WITH_ERRORS`.

**It will not:** modify the CSV, manifest or review report; update or delete
anything in TestRail. **It only creates, and it does not deduplicate** — see
[Operating notes](#operating-notes) before re-running.

---

### 4. `feature-documenter` — TestRail section → feature briefing

**Scope.** The reverse direction, and fully **read-only**. Fetches a TestRail
section and everything under it, and reverse-engineers a short document
describing what the feature is and how it works — plus an assessment of the
tests themselves.

**Usage**

```text
/feature-documenter <section name or id>
/feature-documenter Ad Blocker V1
/feature-documenter 950892
```

No "go" confirmation is required — it only reads TestRail and writes one file.
If you don't name a section it asks; it never guesses.

**Search target.** The section is looked up in `TESTRAIL_iOS_PROJECT_ID`
(default `14`, Firefox for iOS) and `TESTRAIL_iOS_FULL_SUITE_ID` (default `45443`,
Full Functional Tests Suite) — deliberately **separate** from the importer's
project/suite, so documenting a shipped feature never depends on wherever the
last import happened to run. Override per run with `--project-id` / `--suite-id`.
Resolution is by id, then exact name, then substring; an ambiguous name is an
error, so re-run with the id.

**Output.** Exactly one file:
`work/outputs/<section name>/feature_documentation.md`, under ~1,200 words,
with 11 fixed sections — 1–7 describe the feature, 8–11 discuss the tests:

1. Feature overview · 2. Scope & source · 3. Capabilities · 4. How it works ·
5. Accessibility coverage *(presence only)* · 6. Telemetry coverage
*(presence only)* · 7. Test coverage profile · 8. Test analysis (redundant
tests + missing scenarios) · 9. Inferred authoring rules · 10. Data quality &
contradictions · 11. Open questions.

**Rules that shape the output**

- **Never copies the test cases in.** No step tables, no case-by-case
  walkthroughs. It cites ids (`C3167700`) and summarizes. This is its most
  important rule.
- **Evidence over invention.** Every claim traces to a case id; anything
  deduced is prefixed **(Inferred)** with the cases it rests on. TestRail is the
  only source — no product knowledge from memory, the web, or requirements docs.
- **Contradictions are reported, not resolved.** Two cases disagreeing on copy?
  Both get documented with their ids and flagged.
- **UI copy is quoted verbatim** — short strings only, never paraphrased or
  silently corrected.
- **Suggestions only.** Redundancy findings, gaps, and the inferred authoring
  rules live in the document and change nothing. Section 9 is explicitly written
  as **feedback for `testcase-generator`** — that's the loop back to step 1.

---

### 5. `automation-triager` — TestRail section → automation suitability verdicts

**Scope.** A Senior QA Automation Engineer for iOS/XCUITest. Takes the cases in
**one named section of one chosen project** whose Automation status is
`Untriaged`, works out whether each can realistically be automated with **this
project's** XCUITest framework, and writes the verdict back. It triages only —
it never writes XCUITest tests.

**Usage**

```text
/automation-triager Document Sharing for Auto
/automation-triager 972653
```

**It asks which TestRail project to use first** — before it looks for the
section or reads a single case. See
[TestRail project selection](#testrail-project-selection). The section is
required too — by name or id, sub-sections included. If you don't name one the
agent asks; it never falls back to the whole suite. Under the hood:

```text
# 0. the prompt the agent shows you, verbatim
python3 scripts/testrail_triage_automation.py projects

# 1. read the work list (read-only, writes nothing)
python3 scripts/testrail_triage_automation.py fetch "<section>" --project 2 [--limit N] [--json]

# 2. apply the decisions — this performs the real TestRail updates
python3 scripts/testrail_triage_automation.py apply "<section>" decisions.json --project 2

# writing to Firefox for iOS additionally needs your explicit confirmation
python3 scripts/testrail_triage_automation.py apply "<section>" decisions.json \
    --project 1 --confirm-firefox-ios

# optional: preview without writing (debugging / explicit preview only)
python3 scripts/testrail_triage_automation.py apply "<section>" decisions.json --project 2 --dry-run
```

**The split.** The script does the deterministic TestRail work — resolving the
section, resolving the custom field and its option ids, listing Untriaged
cases, re-checking status before each write, applying minimal updates,
reporting. The **agent** makes the suitability judgement, because that requires
reading the app repository. The script never decides anything.

**Decisions file** — a JSON list (or `{"decisions": [...]}`):

```json
[{"case_id": 4433303, "decision": "suitable", "reason": "ShareToolbarTests.testSharePdfFileSaveToFile() already automates this path..."}]
```

A decision is rejected unless it carries a real technical reason; "Looks
automatable" will not pass.

**What it analyses.** Before judging anything it builds one model of the
XCUITest project at `XCUITEST_REPO_PATH`: test targets, the base test class,
screen/page objects, selector sets, the app's accessibility identifier
catalogue, launch arguments, fixtures and mocks, navigation helpers, and
existing coverage (tests in Firefox iOS link their TestRail case ids, so prior
coverage is findable by id). Reasons must cite this evidence by name.

**The bar.** *Can this reasonably and reliably be automated with XCUITest in
this project?* — **not** *is it already automated?* A missing helper, screen
object, accessibility identifier or test file is ordinary work, not a barrier.
The agent is instructed to be conservative about `Unsuitable` and, when torn,
to choose `Suitable` and say what would need building.

**Outputs**

| Target | Change |
|---|---|
| Suitable case | Automation `Untriaged → Suitable`, no label change |
| Unsuitable case | Automation `Untriaged → Unsuitable`, no label change |
| `work/outputs/automation-triage/triage_report.md` | Counts, per-case results, reasons, run mode |

**Safety.** The project is never chosen for you, and `--project` is required on
every command, so a run cannot drift into the wrong project. Writing to Firefox
for iOS also requires `--confirm-firefox-ios`, which the agent may only pass
after you have confirmed that specific run. Updates are minimal by
construction — the payload carries the automation status and nothing else. Title, steps, expected results,
preconditions, section, priority, refs, labels and unrelated custom fields are
never sent, so existing labels are left exactly as they are. Immediately
before each write the case is
re-read and skipped if somebody else moved it out of `Untriaged` mid-run. A
decision naming a case outside the requested section is skipped, not applied.
One failing case never aborts the batch.

**It will not:** touch a case that is not `Untriaged` (including cases whose
Automation field is unset — that is *not* the same as Untriaged); reach outside
the requested section; set or modify a label on any case; modify any field other
than the automation status; or create XCUITest tests.

---

### 6. `automation-script-writer` — Suitable cases → XCUITest code

**Scope.** A Senior iOS Automation Engineer, and the follow-up to the triager:
it implements the cases step 5 marked `Suitable`. It reads TestRail and
**never writes to it** — code and a report are its only outputs.

**Usage**

```text
/automation-script-writer Document Sharing for Auto MTE-1234 --affected-tests full
```

**It asks which TestRail project to use first**, exactly as the triager does —
see [TestRail project selection](#testrail-project-selection) — and continues
in the project the triager used when a triage report names one. The folder
under test and the **ticket number** are required; the agent asks rather than
guessing either. The **affected-tests mode** (`full` or `list`, see below) is
asked for too when the trigger doesn't say. It takes the triager's analysis
when that is still available, and rebuilds it from TestRail when it is not:

```text
python3 scripts/testrail_triage_automation.py fetch "<section>" --status Suitable --project <1|2>
```

Same read-only fetcher as the triager, filtered to `Suitable`. The output
carries each case's **Sub Test Suite(s)** and **TestRail URL**, which the test
declaration needs.

**Branch.** The changes go on a branch in the XCUITest checkout, named
`<mozilla_username>/<ticket_no>` — `dbigu/MTE-1234`. The username comes from
`MOZILLA_USERNAME`, falling back to the local part of `git config user.email`
and confirmed with the user. The agent creates the branch and leaves the
changes on it: no commit, no push, no pull request unless asked.

**Analyse-then-write, enforced.** No code is written until the agent has gone
through the existing test classes, `PageScreens/`, `Selectors/`, the
accessibility identifier catalogue, the base test class, launch arguments,
fixtures and navigation helpers — and read `AIControlsTests`, the reference
implementation for structure, naming, setup and assertion style. Writing the
test first and hunting for reuse afterwards is explicitly forbidden.

**Duplicate detection.** Before creating anything it checks whether the
scenario is already automated, judged by steps and expected behaviour rather
than method name. An already-covered case is left untouched and recorded as
`Already Automated` with a pointer to the existing test.

**Test declaration.** The TestRail link then the suite marker, in the repo's
existing style:

```swift
// https://mozilla.testrail.io/index.php?/cases/view/4433307
// Regression
func testShareSheetShowsCurrentDocumentAfterNavigatingToASecondPDF() throws {
```

The marker comes from the case's Sub Test Suite field — `Regression` →
`// Regression`, `Smoke & Sanity` → `// Smoketest`, anything else → none. It is
never inferred from the scenario, and a URL is never invented.

**Test plans.** Each new test lands in exactly one `.xctestplan`, chosen from
its TestRail classification — `Smoke` and/or `Sanity` → `Smoketest.xctestplan`;
`Regression` or none of the three → `FullFunctionalTestPlan.xctestplan`. Both
plans work by exclusion (`skippedTests`, no `selectedTests`), so a new test runs
in both until the agent adds it to the other plan's skip list.

**Scoped refactoring.** When adding to an existing class it extracts
duplication **within that class only**, updates the affected tests, and
preserves their behaviour. No repository-wide cleanup.

**It builds and runs what it writes.** After implementing, the agent builds the
project with the CI invocation (scheme `Fennec`, configuration
`Fennec_Testing`), fixes every compilation error, runs each new test by name
with `-only-testing:`, and handles the existing tests its changes touched. A
case is only reported `Created` once its test compiles and has been executed.

**Affected test cases.** The author chooses at trigger time what happens to the
existing tests the change reaches: `full` re-runs every one of them and reports
the observed result; `list` only lists them, stated plainly as not executed.
Under `list` the agent never calls them passing or validated.

Compilation errors are fixed by reading the real API — never by deleting,
skipping, commenting out or weakening a test, and never by editing unrelated
code. Compile-and-run is retried at most **three** times; after three failed
attempts it stops and reports the remaining errors or failing tests verbatim,
marking the case `Unable to Automate`. If a test fails because the
product genuinely misbehaves, the assertion stays and the agent reports a
suspected product bug rather than turning the test green.

This needs a full Xcode (`xcode-select -p` must point at an `Xcode.app`, not
`CommandLineTools`). Where it doesn't, the agent says so and marks nothing
validated — `swiftc -parse` is syntax-only and never counts as a build.

**Output.** `work/outputs/automation_test_scripts/<folder>/test_scripts_creation_report.md`
— one entry per case with the TestRail id, name and link, an automation status
of `Created` / `Updated` / `Already Automated` / `Unable to Automate`, the test
name, its file path, the suite classification, marker and test plan, and notes.
The report also carries the branch name, a validation section, and a
**PR Description** section — links to the relevant tests, a short description
of the changes, and the list of affected files — ready for the author to paste
into the pull request.

**It will not:** automate a case that isn't `Suitable`; modify TestRail;
duplicate an existing test; invent a selector, URL, marker or expected
behaviour to force a case through; weaken or skip a test to get a clean build
or a green run; or claim validation it did not perform.

---

## Shared contracts

### CSV format

Exactly 8 columns, in this order:

```text
Section (Folder), Title, Preconditions, Steps, Expected Results, Priority, Type, Sub Test Suite(s)
```

- Fields containing a comma, quote or line break must be quoted, with internal
  quotes doubled (`""`). Adding an `(e.g., …)` introduces a comma — a frequent
  source of broken rows.
- `Steps` and `Expected Results` use matching line indices (`1.`, `2.`, …); every
  step has its own expected result.
- `Section (Folder)` may nest with `/`, `>` or `::`.
- Approved QA verbs only: `Tap`, `Long press`, `Observe`, `Verify`,
  `Navigate to`, `Enable`, `Disable`, `Close`, `Reopen`. Not "click" or "press".
- Vague expected results ("Works correctly", "Screen is displayed correctly")
  are defects, not style preferences.

Validate any CSV by hand with:

```bash
python3 -c "import csv,sys; rows=list(csv.reader(open(sys.argv[1]))); assert all(len(r)==8 for r in rows), [i for i,r in enumerate(rows) if len(r)!=8]" work/outputs/<feature>/<feature>-testcases.csv
```

### Priorities — defined by what failure means

| Priority | If this test fails |
|---|---|
| `Critical` | the change **cannot be merged** (merge-blocking) |
| `High` | it may be a **release blocker** |
| `Medium` | "we can live with it for now" — non-blocking, should be fixed |
| `Low` | cosmetic with no user impact, or an uncommon edge case |

Priority also drives suite routing on import.

### `Sub Test Suite(s)` tags

One cell, comma-separated, in order: base → priority tag → folder tag(s).

| Source | Tag |
|---|---|
| Base (every case) | `Special Case` |
| `Critical` | `Smoke & Sanity` |
| `High` | `Regression` |
| `Medium` | `Functional` |
| `Low` | `Exploratory` |
| Accessibility folder | `Accessibility` |
| Localization folder | `L10n` |
| Telemetry folder | `Telemetry` |

Examples: a High telemetry case → `Special Case, Regression, Telemetry`; a
Critical functional case → `Special Case, Smoke & Sanity`.

### Coverage caps (hard limits)

Both the generator and the reviewer enforce these. Exceeding one is a defect in
the suite, not a judgement call.

| Area | Limit | Rationale |
|---|---|---|
| Feature flags, Nimbus variants, secret/debug settings, "feature disabled" | **0 cases** | The feature is assumed enabled and configured; that belongs in Preconditions. Flag behaviour described in the requirements goes in the manifest as out of scope. |
| Accessibility | **2 cases** — one Dynamic Text, one VoiceOver, happy path only | A third requires written justification in the manifest. |
| Telemetry | **1 case**, 2 at most | Each event/metric/field is a **step** inside that case, never its own case. |
| iPad specific | **0 cases** unless tablet behaviour is evidenced | Cases are device-agnostic by default; prefer a note over a duplicate tablet case. |
| Error handling | Grouped | `404` and `402` with the same expected UI are two steps of one case, not two cases. Split only when the expected behaviour genuinely differs. |

### Session isolation

Every agent runs a **zero-context policy**: each invocation is a fresh,
stateless session. No requirements, URLs, variables or screens carry over from a
previous run or an earlier chat. If something isn't in the current input, the
agent asks rather than reusing what it saw last time.

### TestRail project selection

`automation-triager` and `automation-script-writer` work in **one explicitly
chosen TestRail project**. Before either of them searches for a section or
folder, or retrieves a single test case, it asks:

```text
Which TestRail project should I use?

1. Firefox for iOS (*)
https://mozilla.testrail.io/index.php?/projects/overview/14

⚠️ IMPORTANT: This is the official TestRail project containing the production
test cases used by the Firefox for iOS team. Exercise extra caution when working
with this project. Any changes to test cases, automation statuses, labels, or
other TestRail data must be intentional and explicitly confirmed by the user
before execution.

Configuration:
  TESTRAIL_iOS_PROJECT_ID (expected value: 14)
  TESTRAIL_iOS_FULL_SUITE_ID (expected value: 45443)

2. [TEMP] iOS test project for TC approvals
https://mozilla.testrail.io/index.php?/projects/overview/92

This is the temporary project used for testing and approvals.

Configuration:
  TESTRAIL_TMP_PROJECT_ID (expected value: 92)
  TESTRAIL_TMP_SUITE_ID (expected value: 107983)
```

**There is no default.** The agent never infers the project from the section
name, the repository, or a previous run, and the `(*)` and its warning are
shown every time the choice is presented. The canonical wording lives in
[`.claude/testrail-projects.md`](.claude/testrail-projects.md) and is printed
by `python3 scripts/testrail_triage_automation.py projects`.

Your answer becomes `--project` on every subsequent command:

| Answer | `--project` | Project id from | Suite id from |
|---|---|---|---|
| 1 — Firefox for iOS (*) | `1` or `firefox-ios` | `TESTRAIL_iOS_PROJECT_ID` | `TESTRAIL_iOS_FULL_SUITE_ID` |
| 2 — [TEMP] TC approvals | `2` or `temp-approvals` | `TESTRAIL_TMP_PROJECT_ID` | `TESTRAIL_TMP_SUITE_ID` |

`--project` is **required** — `fetch` and `apply` refuse to run without it, so
the choice cannot be skipped by invoking the script directly.

**How it is enforced**

| Guarantee | Mechanism |
|---|---|
| No silent default | `--project` is a required argument on `fetch` and `apply` |
| Ids never hardcoded | Only the selected project's env pair is read; the documented values are used solely to warn when `.env` disagrees |
| Missing config stops the run | A missing or non-integer id raises, naming the variable and the project — it never falls back to the other project |
| Project and suite must agree | The suite is fetched and rejected if it belongs to a different project |
| No accidental production write | Writing with `--project 1` also requires `--confirm-firefox-ios`, which the agent may pass only after you confirm that specific run in words |
| Nothing mixed between projects | Every run echoes the project, id, suite and source variables; the triage report and the creation report both record them |

Reads from Firefox for iOS need no confirmation, and neither does a
`--dry-run` — it writes nothing. `automation-script-writer` never writes to
TestRail at all, so the choice matters there for a different reason: reading the
wrong project would automate the wrong behaviour.

### `standards.md`

Four rules that override everything else: write in English; use simple language
that manual QA can read and automation can later consume; keep steps concise;
evidence over invention — always map cases to explicit requirements.

---

## Environment variables

Copy `.env.example` to `.env`. Required and optional variables:

| Variable | Used by | Default | Notes |
|---|---|---|---|
| `TESTRAIL_URL` | importer, documenter, triager | — | `https://<instance>.testrail.io` |
| `TESTRAIL_USER` | importer, documenter, triager | — | Your TestRail account email |
| `TESTRAIL_API_KEY` | importer, documenter, triager | — | Never printed or logged |
| `TESTRAIL_TMP_PROJECT_ID` | importer, triager, writer | — | Import target; also **project 2** ([TEMP] TC approvals) for `--project 2` |
| `TESTRAIL_TMP_SUITE_ID` | importer, triager, writer | — | Critical / High / Medium cases; also project 2's suite for `--project 2` |
| `TESTRAIL_TMP_SUITE_ID_LOW` | importer | — | Low-priority cases; required only if the CSV has any |
| `TESTRAIL_iOS_PROJECT_ID` | documenter, triager, writer | `14` (documenter only) | Firefox for iOS (*) — the documenter's read source, and **project 1** for `--project 1`, where it is required |
| `TESTRAIL_iOS_FULL_SUITE_ID` | documenter, triager, writer | `45443` (documenter only) | Full Functional Tests Suite — same split as above |
| `XCUITEST_REPO_PATH` | triager, writer | — | **Required.** Local XCUITest checkout to analyse; the run fails if unset or not a directory |
| `TESTRAIL_AUTOMATION_STATUS_FIELD` | triager | `custom_automation_status` | Matched by system name, then by label. Option ids come from metadata |

The triager and the writer read **only the selected project's pair** — see
[TestRail project selection](#testrail-project-selection). Neither has a
default there: a missing or non-integer id stops the run instead of falling
back to the other project. The `14` / `45443` defaults apply to the documenter
alone.
| `TESTRAIL_TEMPLATE_ID` | importer | — | Use a steps-style template with separated steps |
| `TESTRAIL_USE_SEPARATED_STEPS` | importer | `false` (`.env.example` ships `true`) | `true` pairs each step with its expected result |
| `TESTRAIL_PRECONDITIONS_FIELD` | importer | `custom_preconds` | |
| `TESTRAIL_STEPS_FIELD` | importer | `custom_steps` | |
| `TESTRAIL_EXPECTED_FIELD` | importer | `custom_expected` | |
| `TESTRAIL_SEPARATED_STEPS_FIELD` | importer | `custom_steps_separated` | |
| `TESTRAIL_SUB_TEST_SUITE_FIELD` | importer | `custom_sub_test_suites` | Multi-select; labels map to option ids. Skipped if absent |
| `TESTRAIL_EXTERNAL_ID_FIELD` | importer | `custom_external_id` | Optional; skipped if absent |
| `TESTRAIL_REFERENCES_FIELD` | importer | `refs` | |
| `TESTRAIL_REQUEST_TIMEOUT` | importer, documenter | `30` | Seconds |
| `TESTRAIL_MAX_RETRIES` | importer, documenter | `3` | |

`TESTRAIL_USE_SEPARATED_STEPS=true` needs a matching separated-steps
`TESTRAIL_TEMPLATE_ID` (e.g. "Test Case (Steps)"). Otherwise steps and expected
results are written to the plain-text fields, which requires a text template.

---

## Operating notes

- **The importer does not deduplicate.** Re-running creates a second copy of
  everything. To reimport cleanly, delete the feature's section in TestRail
  first. There is no update or delete path.
- **Run from `mobile-ai-toolkit/`.** Every path in the agents is relative to it,
  and the pre-approved permissions in `.claude/settings.json` are scoped to it.
- **Feature slugs are lowercase-hyphenated** and shared by the input folder, the
  output folder and the CSV filename (`tracker-blocking-module` →
  `tracker-blocking-module-testcases.csv`). The documenter is the exception: its
  output folder preserves the TestRail section's own casing and spacing
  (`Ad Blocker V1` → `work/outputs/Ad Blocker V1/`).
- **The reviewer overwrites the CSV in place.** `review_report.md` is the only
  record of what changed — keep it.
- **The triager's `apply` writes to TestRail.** It is the only agent that
  modifies cases that already exist there. Each write is re-validated
  immediately before (still `Untriaged`?) and verified immediately after (did
  TestRail store it?), so re-running is safe and a silent no-op is reported as
  a failure rather than a success. `--dry-run` previews without writing.
- **An unset Automation field is not `Untriaged`.** In suite 107983 only 5 of
  328 cases are actually `Untriaged`; the rest have the field empty. The
  triager leaves those alone rather than assuming they need triaging.
- **Never place fetch dumps in `work/outputs/`.** If a documenter fetch is too
  large to read inline, redirect it to `/tmp/`. The output folder holds exactly
  one file per agent run.
- **`work/inputs/` and `work/outputs/` are gitignored.** Inputs may contain
  unreleased product material; outputs are regenerable. Don't force-add them.
- **`.claude/settings.local.json` is yours** and gitignored; team-wide
  permissions belong in `.claude/settings.json`.
- **No `requirements.txt` ships with the toolkit** — install `requests` (and
  `python-dotenv`) yourself. Without `python-dotenv`, `.env` is silently ignored
  and the scripts fail on missing configuration.

---

## Extending the toolkit

The split between the two `.claude` directories is the thing to understand:

| | `.claude/agents/<name>.md` | `.claude/skills/<name>/SKILL.md` |
|---|---|---|
| Role | The **runner** — a subagent persona, its tool allowlist, and the reminders that matter most | The **playbook** — the full step-by-step procedure, formats and hard limits |
| Size | Short | Long, the source of truth |
| Invoked | Spawned by the skill's checkpoint, or directly by name | `/`-invoked by the user |

Both files exist for each of the four agents, and the agent file always points
back at its skill ("read that skill now and execute it"). When you change a
rule, **change it in the skill** — the agent file should only ever restate or
emphasize what the skill already says.

To add a fifth agent, mirror the pattern: a `SKILL.md` with an inline checkpoint
that resolves arguments and (if the workflow writes anything risky) waits for
confirmation, plus an agent file that declares its tools and executes the
playbook. Reuse `standards.md`, the 8-column CSV contract, and the
`work/inputs` → `work/outputs` convention so the new agent composes with the
existing pipeline.

**Two shared assets are worth keeping current**, since the generator and
reviewer both treat them as the gold standard: `.claude/assets/templates/fifa.csv`
(folder hierarchy, naming, writing style, level of detail) and
`.claude/assets/templates/layout.png` (expected formatting for UI/Layout cases).
Improving these improves every future suite more cheaply than editing prompts.
