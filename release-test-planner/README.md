# Release Test Planner

**Risk-based release test planning, driven by what actually changed.**

Takes a git range. Works out which features the changes touch, checks what test
automation exists for them, scores the release risk with FMEA, and produces a
recommended test run, the manual-testing gap, and a configuration matrix sized
by risk.

> **Status: early prototype (v0.0.2).** Fenix/Android and Firefox iOS, on UI
> tests only. It is here to be reviewed and argued with, not to gate a release.
> The risk scoring and array generation carry no platform knowledge and moved to
> iOS unchanged, as intended — but **iOS has no factory candidate space, so it
> has no derived coverage denominator.** See
> [Two platforms, two denominators](#two-platforms-two-denominators) before
> reading any percentage.

Stdlib Python 3.9+. No install, no dependencies, no API key, no network.

```bash
cd release-test-planner

# Android (default)
./plan.py analyze --repo /path/to/firefox --range "HEAD~300..HEAD" --budget 240 --open

# Firefox iOS
./plan.py analyze --platform ios --repo /path/to/firefox-ios \
  --range "release/v153.0..release/v153.3" --budget 240 --open

# either platform, with TestRail as an assumed denominator
./plan.py analyze --platform ios --repo /path/to/firefox-ios \
  --range "HEAD~120..HEAD" --testrail-export cases.json --budget 240 --open
```

---

## Two platforms, two denominators

Everything below the attribution stage is platform-agnostic and always was:
churn measures, FMEA scoring, the plan builder, the covering arrays. Porting to
iOS needed a Swift reader, a feature catalog, and one honest admission.

| | Android | iOS |
|---|---|---|
| test language | Kotlin, `@Test` | Swift, `func test…()` by convention |
| suites | `ui/`, `ui/efficiency/tests/` | `XCUITests/` |
| surface evidence | `on.<pageObject>`, `robots.*` | `navigator.goto/nowAt/performAction` |
| "does not run" | `@Ignore`, `@Suppress`, `@Manual` | skipped by every `.xctestplan`, `XCTSkip`, `guard #available … else { return }` |
| candidate space | **3,158**, derived by the generation factories | **none** |

The last row is the load-bearing one. The argument for this tool
([docs/why-factories.md](docs/why-factories.md)) is that the factories
*enumerate* a space, which gives coverage a denominator that was computed rather
than asserted. firefox-ios has no factory framework, so on iOS the tool reports
counts and gaps, and refuses to print a coverage percentage it cannot justify.
`factories.empty()` exists to make that refusal explicit rather than a zero that
looks like a measurement.

### TestRail: an assumed denominator that works on both

`--testrail-export cases.json` supplies the other kind of denominator. Both
codebases already write the case id above each test, in the same URL form:

```kotlin
// TestRail link: https://mozilla.testrail.io/index.php?/cases/view/2283299
@Test fun verifyExpandedCollectionItemsTest() { … }
```
```swift
// https://mozilla.testrail.io/index.php?/cases/view/2306905
func testBookmarkCanBeAdded() { … }
```

So the join is an **id match, not a name heuristic** — which matters, because a
heuristic would be another assumption stacked on an already-assumed denominator.

What it is: the TestRail case set is a deliberate artefact. Someone decided each
case was worth writing for a release, and unlike the automated suite it was not
constrained by what was cheap to automate. Taking it as the intended release-test
plan is defensible.

What it is not: complete. TestRail is also a pile that accumulated — dense where
bugs were once found, thin where nobody wrote cases. So the number is reported as
`automated_ratio`, never as `coverage`, and it answers exactly one question:
**how much of the plan we wrote down will a machine run?** The remainder is the
manual-testing gap, which is the number a release manager actually needs.

Three rules keep it honest:

- **A case automated only by a test that never runs is manual.** Same rule the
  corpus applies to `@Ignore` and xctestplan skips. On firefox-ios this is not a
  rounding error: of 440 case ids referenced by XCUITests, 125 are claimed by a
  test that no test plan runs.
- **A referenced id absent from the export is reported, not counted.** A test
  pointing at another project's case would otherwise inflate the ratio.
- **Cases triaged `Unsuitable` leave the denominator.** They are deliberately
  manual forever, so counting them as an automation gap makes the gap
  unshrinkable and the ratio meaningless.

### Which export to ask TestRail for

Two exports, two different jobs, and the tool merges several by case id because
neither is sufficient alone:

| | a **run** export | a **case/suite** export |
|---|---|---|
| e.g. | `full_functional_153.3_rc_1.csv` | `firefox_for_ios.csv` |
| cases | only what that run selected (737) | the whole suite (1,779) |
| has | `Section`, `Section Depth`, `Status`, `Priority` | `Automation`, `Automation Coverage`, `Automated Test Name(s)` |
| gives | feature attribution, and what was actually executed | the real denominator, and TestRail's own triage |
| overlap with automation | 35 of 440 ids | **417 of 440** |

```bash
./plan.py analyze --platform ios --repo ~/Workspace/firefox-ios \
  --range "HEAD~120..HEAD" \
  --testrail-export firefox_for_ios.csv full_functional_153.3_rc_1.csv
```

**A run export alone is the wrong denominator** and the tool now says so instead
of printing the number. A run is a *manual* plan: the automated tests reference
case ids that mostly are not in it, so the ratio comes out at 3.4% and means
nothing. Where overlap is under half, the report leads with the warning.

**Watch the id column.** A run export has both `ID` (the test-instance id,
`T9474971`) and `Case ID` (`C2306813`). Only the case id appears in the source
tree. The loader prefers case-id spellings for exactly this reason — reading `ID`
joins nothing and reports 0–3% automated with no error at all.

Accepted formats are JSON (the raw `get_cases` API response, or a bare list) and
CSV (what the TestRail UI exports). Not xlsx — that needs a dependency this tool
deliberately does not have, and
`testrail/testcases-deduplication/fetch_testrail_export.py` can be pointed at the
API response instead. Rows whose columns have shifted (rich text in a case field
pushes CSS fragments into the automation column) are detected by shape and not
trusted.

### What it said about Firefox iOS on release/v153.3

| | |
|---|---|
| cases in the merged export | 1,775 |
| automated by a test that actually runs | **308 (17.3%)** |
| …of the 1,440 *addressable* cases | **21.4%** |
| triaged manual forever (`Unsuitable`) | 335 |
| triaged automatable, not yet done | 26 |
| never triaged either way | 1,001 |
| triaged automated but no test links to them | 22 |
| linked by a test but not triaged as automated | 26 |
| in the 153.3 RC1 run, left untested | 244 of 737 |

The 1,001 untriaged cases are the largest number on that list, and they are the
reason the automation ratio is hard to act on: over half the suite has no
decision recorded about whether it *should* be automated.

## Read this first: why this is possible now and wasn't before

Risk-based test selection is an old idea that mostly doesn't work in practice,
for two reasons that are rarely stated plainly.

**Selection only matters when supply exceeds budget.** If your release window
fits 200 tests and your suite has 200 tests, the optimal plan is "run
everything." Scoring machinery adds nothing.

**A hand-written suite has no denominator.** You cannot claim "60% coverage of
tabs" when nobody enumerated what 100% would be. The suite isn't a sample of a
defined space — it's a pile of files that accumulated as people found time.
Percentages against a pile are theater.

The **test factories** in the Fenix efficiency harness break both constraints.
They don't write tests; they *enumerate a space* and emit a case per point in
it. From a model of ~50 page objects and 58 selector catalogs, the current
candidate space is **3,158 cases** — and it grows superlinearly, because
registering one new page object adds a reachability case, ~100 pair candidates,
and one interaction candidate per selector, automatically, discovered by
reflection.

That is what makes this tool worth building. Supply now genuinely exceeds
budget, so selection is a real question with a non-obvious answer. And the space
is *enumerable*, so coverage percentages have a denominator and stop being
aspirational.

**→ [docs/why-factories.md](docs/why-factories.md) — the full argument, including
the parts I'm not overselling.**

---

## What it produces

On a sample range of 43 commits touching Fenix:

| | |
|---|---|
| Release confidence | **51.1%** of inherent risk removed by the planned run |
| Recommended run | **73 tests, 2.46 h** — with **244** bound tests skipped as removing no additional risk |
| Action required | **3** features at RPN ≥ 200 — all three with **zero** UI automation |
| Across the matrix | **458 executions, 21.7 device-hours**, 8.8x the single-config run |
| Open questions | **44** typed judgement calls emitted for review |

Plus the diminishing-returns curve a release manager actually needs:

| budget | tests | confidence |
|---|---|---|
| 15 min | 9 | 29.1% |
| 45 min | 24 | 43.3% |
| 240 min | 73 | 51.1% |

**45 minutes buys 85% of what 147 minutes buys.**

## Two things it found on its first real run

**Coverage was being massively overstated.** The first pass credited Home Screen
with **502** covering tests. Only **16** actually verify it — the rest import
`homeScreen` to *navigate somewhere else*. Overstated coverage is more dangerous
than none: it suppresses the risk score that should have triggered manual
testing. Bindings are now graded, and pass-through ones count zero.

This also produced the strongest unplanned argument for the efficiency refactor:
**the legacy suite is not analyzable and the efficiency suite is.** In the legacy
robot DSL, navigation and verification are the same gesture, so what a test
covers isn't recoverable from its source. `on.<page>` makes it machine-readable.
You cannot compute risk-weighted coverage over a suite you cannot parse.

**A new feature was hiding inside "infrastructure."** Answering the
`assess-change-semantics` question by reading the diffs revealed that 342 of 690
lines filed under App Infrastructure were a new **Google Lens integration** (bug
2028573) under `components/lens/`. It is now its own catalog entry, and lands as
action-required with zero UI coverage — which it genuinely has.

## Docs

| | |
|---|---|
| **[why-factories.md](docs/why-factories.md)** | why generated candidates are the precondition for coverage tooling at scale |
| **[denominators.md](docs/denominators.md)** | derived vs assumed denominators, why iOS gets no candidate space, and what TestRail does and does not prove |
| [risk-model.md](docs/risk-model.md) | FMEA, how each factor is derived, the two decisions with regression tests |
| [matrix.md](docs/matrix.md) | orthogonal vs covering arrays, verification, risk-tiered allocation |
| [architecture.md](docs/architecture.md) | pipeline stages, config, the agent seam, how to extend |

## Run it

```bash
./plan.py analyze --repo ~/src/firefox --range "HEAD~300..HEAD" --budget 240
./plan.py analyze --range v146..v147 --answers examples/answers.example.json
./plan.py serve --live --open          # iterate: a browser refresh re-runs the pipeline
python -m unittest discover -s tests -p '*tests.py'
```

`export FENIX_REPO=/path/to/firefox` to skip `--repo`.

### Analysing a release branch

`--range` is handed straight to `git log`, so any revision expression works.
`origin/release..origin/beta` *is* the release candidate — everything in beta
that has not shipped yet.

**Analyse a branch from a worktree of that branch.** Churn comes from the range,
but the test corpus comes from the checked-out tree. Point `--repo` at a `main`
checkout while analysing beta and you score beta's changes against main's tests,
which silently overstates coverage — on a real beta cycle the two corpora
differed by 44 tests. The tool detects this and warns, in the terminal and in a
banner on the report itself, but the fix is to check out the right tree:

```bash
# one-time: sparse worktree, ~65MB, a couple of seconds
cd /path/to/firefox
git worktree add --no-checkout ../firefox-beta origin/beta
cd ../firefox-beta && git sparse-checkout set mobile/android/fenix && git checkout

# each run
cd /path/to/firefox && git fetch origin beta release
cd ../firefox-beta && git checkout origin/beta

cd /path/to/testops-tools/release-test-planner
./plan.py analyze --repo ../../firefox-beta \
  --range "origin/release..origin/beta" --budget 480 --out beta-report
```

Sparse-checkout keeps it to `mobile/android/fenix`, which is all the tool reads.
A full beta cycle — 477 commits, 924 files, ~107k lines churned — analyses in
about 30 seconds. `git worktree remove ../firefox-beta` when finished.

Other useful ranges: `origin/beta..origin/main` for what is queued for the next
merge, and `HEAD~300..HEAD` for a rough nightly cycle.

#### On iOS

firefox-ios is its own repository, so there is no sparse-checkout to do and no
pathspec to scope — but two things differ:

```bash
# release branches are release/vNNN.N. The bare vNNN.N branches stop at v105
# and predate the layout move, so their paths will not match the catalog.
git clone --single-branch --branch release/v153.3 --depth 400 \
  https://github.com/mozilla-mobile/firefox-ios ~/Workspace/firefox-ios

./plan.py analyze --platform ios --repo ~/Workspace/firefox-ios \
  --range "HEAD~120..HEAD" --budget 240 --testrail-export cases.json --open
```

Depth matters: churn is computed by diffing the range, so a `--depth 1` clone
gives an empty analysis. For the uplift delta between two release branches,
fetch both and use `release/v153.2..release/v153.3`.

The checkout also contains **focus-ios**, a separate product, and
`SampleComponentLibraryApp`. Both are in the iOS catalog's `_ignored_globs`; a
release report for Firefox iOS should not be scored on Focus churn.

Layout note: the catalog's globs follow the current layout (app under
`firefox-ios/`, shared packages under `BrowserKit/`). `--tests-root` overrides
the test directory for an older checkout, but the source globs would also need
adjusting.

Outputs land in `out/` (gitignored):

| file | what it is |
|---|---|
| `report.html` | self-contained dashboard — no CDN, no webfonts, works from `file://` |
| `report.json` | the full analysis |
| `agent-tasks.json` | the questions the pipeline refused to answer on its own |

`report.html` prefers a `report.json` next to it and falls back to a copy
embedded in itself, so the same file works served *and* mailed around. The
header says which. CSS/JS are inline, so a host with a strict CSP and no
`'unsafe-inline'` would render it blank.

## The pipeline

```
  git range
      |
  [1] changes     git log --numstat -> per-file churn          deterministic
  [2] featuremap  path globs -> features                       + agent for misses
  [3] corpus      parse androidTest Kotlin -> test inventory   deterministic
  [4] coverage    bind tests to features, score depth          + agent for weak bindings
  [5] risk        FMEA: RPN = S x O x D                        + agent for S and O
  [6] plan        greedy budgeted selection -> gaps            + agent for manual cases
  [7] factories   generated-case candidate space               deterministic
  [8] matrix      risk-tiered covering arrays                  deterministic
      report      static HTML
```

**The pipeline never calls a model.** It runs deterministically and emits typed
questions for what genuinely needs judgement. Answers feed back as auditable
overrides, so every AI-influenced number traces to a question, an answer, and a
rationale. You can always run the whole thing with no AI and get a complete
answer.

## Relationship to `test-recommender`

Adjacent problems from opposite directions; both should exist.

| | `test-recommender` | `release-test-planner` (this) |
|---|---|---|
| platform | Firefox iOS | Fenix / Android |
| starts from | the TestRail manual catalogue | the code, and the automation that exists |
| method | LLM-assisted ranking, deterministic fallback | deterministic scoring, LLM for named judgement calls |
| output | prioritized Markdown report | risk register, selected run, coverage gap, config matrix |
| risk basis | heuristic signals | FMEA RPN with churn-derived Occurrence |

The interesting overlap is the risk model. `risk.py` and `matrix.py` are
self-contained and carry no Fenix knowledge, so they could slot under
`test-recommender` too — and should, if the scoring proves out.

## What is real and what is stubbed

**Parsed from the tree:** git churn; the UI test corpus (629 legacy + 140
efficiency); 466 selectors across 58 catalogs; 50 page objects; the behavior
capability and template catalogs; and the `BrowserMode / Account / DeviceClass /
Pocket / RecentlyVisited / UnifiedTrustPanel` context factors read out of
`BehaviorContextMatrix.kt`.

**Stubbed**, and labelled as such in the UI and config: `ApiLevel` values (real
minSdk/targetSdk are computed in mach's Python build config; the shipping matrix
should come from Play Console distribution data), `BuildVariant`, `Network`,
`Theme`, the `Foldable` device class, per-config cost multipliers, and the
behavior-factory projection. Feature severities are hand-assigned judgement,
each with a written rationale that a unit test enforces.

**Factory status** is as the in-tree architecture doc states: Reachability is
production-ready and auto-covers every registered page; Interaction is
bookmarks-only; Behavior's context matrix is largely unimplemented; Pairs is
unproven. Candidate counts describe the size of the space the model already
defines, not runnable tests today.

## Known limits

- **UI tests only.** Unit, component and service coverage are not modelled, so
  confidence is *understated* for well-unit-tested code. Closing this is worth
  more than any refinement of the existing scoring.
- **TestRail is joined from an export, not queried.** Pass `--testrail-export`;
  the tool does not talk to the API, and the export can be stale. Manual effort
  is counted in cases, not sized in minutes.
- **The iOS feature catalog is hand-written and unreviewed by the iOS team.**
  Severities were carried over from the Android catalog where the feature exists,
  which assumes user impact is the same on both platforms. The globs are fitted
  to `release/v153.3` — 0 of 973 changed files unmapped on that branch, but that
  is a fit to one branch, not a guarantee.
- **iOS surface binding relies on the MappaMundi screen graph.** A test that
  drives the app without `navigator` calls binds by class name alone, which is
  the weaker of the two signals.
- **No iOS candidate space.** Coverage on iOS is counts and gaps only, unless a
  TestRail export supplies an assumed denominator.
- **Factory candidates are counted, not selected.** They are attributed to
  features but do not yet feed the run plan.
- Occurrence is churn-only — no cyclomatic complexity, no historical defect
  density to calibrate against.
- Test cost is a flat per-suite estimate, not measured runtime.
- Flaky tests count as full detection, which is generous.
- Binding is name and surface matching, not execution tracing.
- The corpus is read from the checked-out tree, not from the range. Analysing
  a branch you have not checked out is detected and warned about, but not
  corrected automatically — see *Analysing a release branch*.
- The matrix assumes every test runs in every configuration; real constraints
  need forbidden-tuple support in the generator.

## Layout

```
plan.py                     entry point
config/features.json        Android feature catalog: severity, globs, page objects
config/features-ios.json    iOS feature catalog, plus its own _ignored_globs
config/environment.json     matrix factors and the risk -> strength policy
docs/                       the reasoning
examples/                   a worked agent-answers file
testplanner/                one module per pipeline stage
  platforms.py              where the tests live, what language, factories or not
  testrail.py               the assumed denominator and its join rules
tests/                      121 unit tests, no checkout required
```
