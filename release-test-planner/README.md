# Fenix Release Test Planner

**Status: early prototype (v0.0.1). Not wired into anything, not producing
numbers anyone should act on yet.** It is here so it can be reviewed and poked
at rather than described in the abstract.

Takes a git range, works out which Fenix features the changes touch, checks what
UI automation exists for those features, scores the risk with FMEA, and produces
a recommended test run plus the manual-testing gap — with a combinatorial
configuration matrix sized by risk.

Stdlib Python 3.9+. No install, no dependencies, no API key, no network.

```bash
cd release-test-planner
./plan.py analyze --repo /path/to/firefox --range "HEAD~300..HEAD" --budget 240 --open
```

Or `export FENIX_REPO=/path/to/firefox` and drop the `--repo`.

## Relationship to `test-recommender`

They solve adjacent problems from opposite directions, and both should probably
exist:

| | `test-recommender` | `release-test-planner` (this) |
|---|---|---|
| platform | Firefox iOS | Fenix / Android |
| starting point | the TestRail manual catalogue | the code, and the automation that exists |
| method | LLM-assisted ranking, deterministic fallback | deterministic scoring, LLM only for named judgement calls |
| output | prioritized Markdown report of tests to run | risk register, selected run, coverage gap, config matrix |
| risk basis | heuristic signals (hotspots, big PRs, flag flips) | FMEA RPN with churn-derived Occurrence |

The interesting overlap is the risk model. If the scoring here proves out, it
would slot under `test-recommender` too — `risk.py` and `matrix.py` are
self-contained and have no Fenix knowledge in them.

## Run it

```bash
./plan.py analyze --repo ~/src/firefox --range "HEAD~300..HEAD" --budget 240
./plan.py analyze --range v146..v147 --answers examples/answers.example.json
./plan.py serve --live --open          # iterate: refresh re-runs the pipeline
python -m unittest discover -s tests -p '*tests.py'
```

Outputs land in `out/` (gitignored):

| file | what it is |
|---|---|
| `report.html` | self-contained dashboard — no CDN, no webfonts, works from `file://` |
| `report.json` | the full analysis |
| `agent-tasks.json` | the questions the pipeline refused to answer on its own |

`report.html` prefers a `report.json` sitting next to it and falls back to a
copy embedded in itself, so the same file works both served and mailed around.
The header says which it used. Note the CSS/JS are inline, so a host with a
strict CSP and no `'unsafe-inline'` would render it blank.

## Pipeline

```
  git range
      |
  [1] changes    git log --numstat -> per-file churn        deterministic
  [2] featuremap path globs -> features                     deterministic + agent for misses
  [3] corpus     parse androidTest Kotlin -> test inventory deterministic
  [4] coverage   bind tests to features, score depth        deterministic + agent for weak bindings
  [5] risk       FMEA: RPN = S x O x D                      deterministic + agent for S and O
  [6] plan       greedy budgeted selection -> gaps          deterministic + agent for manual cases
  [7] factories  generated-case candidate space             deterministic
  [8] matrix     risk-tiered covering arrays                deterministic
      report     static HTML
```

## Risk model

FMEA (IEC 60812), the scheme ISTQB's risk-based testing material builds on:

```
RPN = Severity x Occurrence x Detection      1 .. 1000
```

- **Severity** — blast radius if the feature breaks. From `config/features.json`,
  where every value carries a written rationale (enforced by a test).
- **Occurrence** — likelihood this cycle's change broke it. Derived from
  *relative* churn (churned LOC / total LOC), following Nagappan & Ball, *Use of
  Relative Code Churn Measures to Predict System Defect Density* (ICSE 2005).
  Modified by change breadth, author count, and backout involvement.
- **Detection** — likelihood a defect **escapes** to release. Inverted coverage.
  This is the only factor a test plan can move, which is why FMEA fits the
  problem at all.

Derived: **Criticality** (S x O, the risk you can only code away, not test away),
**inherent RPN** (S x O x 10), **residual RPN** after the planned run, and
**release confidence** = `1 - residual / inherent`. Bands follow conventional
AIAG practice: 200+ action required, 100+ review.

### Two decisions that are load-bearing

**Detection is a curve, not a lookup table.** A tiered table was tried first and
was wrong: it made the second test added to a feature worth exactly zero, so the
greedy planner stalled on the plateau and picked 3 tests out of 769. The
continuous decay is also the honest shape — the fifth test on a feature really
does buy less than the first. `test_every_added_test_still_gains_something`
guards this.

**"Incidental" coverage counts for nothing.** Almost every legacy test imports
`homeScreen` / `navigationToolbar` in order to *navigate somewhere else*.
Counting that as coverage credited the Home Screen feature with 502 tests when
only 16 actually verify it. Overstated coverage is worse than none — it
suppresses the RPN that should have triggered a manual test.

| binding | meaning | weight |
|---|---|---|
| `strong` | class name **and** page object match | 1.0 |
| `name-only` | class name matches | 0.8 |
| `incidental` | only passes through the surface | 0.0, and never scheduled |

Incidental bindings are still recorded and each becomes a question for review.

## The matrix

Two standard reductions of the configuration cross product, both implemented,
both verified (`matrix.verify()` re-derives every t-tuple, so a generation bug
fails loudly instead of quietly under-testing):

**Orthogonal array** — every pair of levels appears *exactly* equally often.
Balance is what lets you attribute an effect to a factor: a design for
**analysis**. Built with the Rao-Hamming construction; four 3-level factors
gives the textbook L9. Mixed level counts fall back to the dummy-level
technique, which the output flags because it breaks the balance that was the
reason to choose an OA.

**Covering array** — every pair appears *at least* once. Smaller, accepts any
mix of level counts: a design for **detection**. Built with IPOG, the algorithm
behind NIST's ACTS.

On the review-band factor set: 96 full factorial, 23 orthogonal, **13 covering**.
Same pairwise coverage, 43% fewer runs.

Strength is allocated by risk band — 3-way for action-required, 2-way for
review, one baseline config for acceptable. Uniform 3-way everywhere is how a
matrix becomes unaffordable. Where an action-required feature has *no*
automation, its matrix is not a test run at all; it is the manual scope, and the
report labels it that way.

## The agent seam

The pipeline never calls a model. It runs deterministically and emits typed
questions for what genuinely needs judgement, each with the evidence attached
and a schema for the answer:

| task type | the judgement call |
|---|---|
| `classify-unmapped-path` | changed code that matched no feature |
| `assess-change-semantics` | churn cannot tell a rename from a behaviour change |
| `review-severity` | catalog severity is a static average |
| `review-weak-binding` | does this test really exercise the feature |
| `author-manual-tests` | turn residual risk into manual cases |

Answers go in a JSON file (`examples/answers.example.json` is a worked one) and
are fed back with `--answers`. Every override is recorded in
`meta.agent_overrides_applied`, so an AI contribution to a risk number always
traces to a question, an answer, and a rationale.

## What is real and what is stubbed

Parsed from the tree: git churn, the UI test corpus (629 legacy + 140
efficiency), 466 selectors, 50 page objects, the behavior capability and
template catalogs, and the `BrowserMode / Account / DeviceClass / Pocket /
RecentlyVisited / UnifiedTrustPanel` context factors out of
`BehaviorContextMatrix.kt`.

Stubbed, and labelled as such in both the UI and `config/environment.json`:
`ApiLevel` values (real minSdk/targetSdk are computed in mach's Python build
config; the shipping matrix should come from Play Console distribution data),
`BuildVariant`, `Network`, `Theme`, the `Foldable` device class, per-config cost
multipliers, and the behavior-factory projection. Feature severities are
hand-assigned judgement.

## Known limits

- **UI tests only.** Unit, component and service coverage are not modelled, so
  confidence is *understated* for well-unit-tested code. This is the biggest
  gap and the next thing worth building.
- **TestRail is read, not integrated.** The parser picks up TestRail IDs from
  comments in test files and displays them. It does not query the TestRail API
  or size manual effort against the case catalogue. Doing that is a next step.
- **Factory candidates are counted, not selected.** The 3,158 generated-case
  candidates are attributed to features but do not yet feed the run plan.
- Occurrence is churn-only — no cyclomatic complexity, no historical defect
  density to calibrate against.
- Test cost is a flat per-suite estimate, not measured runtime, and every test
  is assumed to cost the same in every configuration.
- Flaky tests count as full detection, which is generous.
- Test-to-feature binding is name and surface matching, not execution tracing.
- The matrix assumes every test can run in every configuration; real constraints
  (tablet-only, online-only) need forbidden-tuple support in the generator.

## Layout

```
plan.py                  entry point
config/features.json     feature catalog: severity, source globs, page objects
config/environment.json  matrix factors and the risk -> strength policy
examples/                a worked agent-answers file
testplanner/             one module per pipeline stage
tests/                   69 unit tests, no checkout required
```
