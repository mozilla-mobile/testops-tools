# Release Test Planner

**Risk-based release test planning, driven by what actually changed.**

Takes a git range. Works out which features the changes touch, checks what test
automation exists for them, scores the release risk with FMEA, and produces a
recommended test run, the manual-testing gap, and a configuration matrix sized
by risk.

> **Status: early prototype (v0.0.1).** Wired to Fenix/Android only, on UI tests
> only. It is here to be reviewed and argued with, not to gate a release. iOS
> and other platforms follow once the model is proven — the risk scoring and
> array generation carry no platform knowledge and are designed to move
> unchanged.

Stdlib Python 3.9+. No install, no dependencies, no API key, no network.

```bash
cd release-test-planner
./plan.py analyze --repo /path/to/firefox --range "HEAD~300..HEAD" --budget 240 --open
```

---

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
- **TestRail is read, not integrated.** IDs are parsed from test comments and
  displayed. The API is not queried and manual effort is not sized against the
  case catalogue.
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
plan.py                  entry point
config/features.json     feature catalog: severity, source globs, page objects
config/environment.json  matrix factors and the risk -> strength policy
docs/                    the reasoning
examples/                a worked agent-answers file
testplanner/             one module per pipeline stage
tests/                   69 unit tests, no checkout required
```
