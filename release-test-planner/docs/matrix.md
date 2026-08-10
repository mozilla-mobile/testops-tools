# The configuration matrix

A test is not one thing. It is a test **run in a configuration**. This is where
the candidate space stops being a list and becomes a schedule.

---

## The problem

Every feature multiplies out against the environment it runs in: device class,
API level, browser mode, account state, build variant, network, theme. The full
cross product of even a modest factor set is unaffordable, and most of it is
redundant — the same defect surfacing in the fortieth configuration teaches you
nothing the first one didn't.

Two standard reductions exist. They are not interchangeable, and the difference
between them is worth real device hours.

## Orthogonal arrays — a design for *analysis*

Every pair of factor levels appears **exactly** the same number of times.

That balance is the point. It's what lets you attribute an observed effect to a
particular factor, which is why orthogonal arrays come out of Taguchi's design
of experiments — a tradition concerned with *understanding which variable
caused the change*.

Built here with the **Rao-Hamming construction**: runs are the vectors of
GF(q)^m, columns are the points of the projective space PG(m−1, q), and the cell
value is their dot product mod q. Four 3-level factors produces the textbook
**L9** — 9 runs, every pair exactly once. There is a unit test asserting exactly
that, because a construction that silently produces a not-quite-orthogonal array
is worse than none.

Balance has a price. Strength-2 orthogonal arrays only exist for particular run
counts and level structures. Mixed level counts fall back to the standard
dummy-level technique, which preserves pairwise coverage but **breaks the
balance that was the reason to choose an OA in the first place** — so the output
flags it rather than presenting a compromised array as a clean one.

## Covering arrays — a design for *detection*

Every pair appears **at least** once.

Dropping the balance requirement makes the array markedly smaller and lets it
accept any mix of level counts. Built with **IPOG** (In-Parameter-Order-General),
the algorithm behind NIST's ACTS: build the exhaustive array over the first t
factors, then grow one factor at a time — horizontally, choosing for each
existing row the level covering the most still-uncovered tuples, then vertically,
adding rows for whatever is left over.

On the review-band factor set:

| design | configs |
|---|---|
| full factorial | 96 |
| orthogonal array | 23 |
| **covering array (2-way)** | **13** |

Same pairwise coverage. **43% fewer runs.**

For release testing you want to know a combination *breaks*, not to attribute
variance to a factor. You want detection. You want the covering array. The
orthogonal array is implemented anyway because it is what people ask for by
name, and because putting 23 next to 13 is the fastest way to explain why it
usually isn't what you want.

## Everything is verified

`matrix.verify()` re-derives every t-tuple in the factor set and confirms the
generated array actually contains it. Arrays are verified on generation, and the
report shows the tuple count that was checked.

This matters more than it sounds. A subtly wrong covering array does not crash —
it silently under-tests, and reports a coverage number that is simply false.
That is the single worst failure mode available to a tool whose entire job is
telling you how covered you are. So the verifier has its own test
(`test_detects_a_missing_pair`) proving it can fail; a safety net nobody has
watched fail is not a safety net.

## Allocation by risk band

Generating an array is the easy part. Deciding **who gets how much** is where
this connects back to the risk model.

| band | strength | configs | rationale |
|---|---|---|---|
| action-required | 3-way | 40 of 576 | catches interaction faults pairwise provably cannot |
| review | 2-way | 13 of 96 | most reported combinatorial faults are 2-way |
| acceptable | baseline | 1 | enough to notice a total break |

Uniform 3-way everywhere is how a test matrix becomes unaffordable and gets
abandoned. A single config on an action-required feature is how a release ships
broken. The allocation is the compromise, and it is expressed as policy in
`config/environment.json` rather than buried in code, so it can be argued about
by people who don't read Python.

Net effect on the sample range: **73 selected tests become 458 executions and
21.7 device-hours — 8.8x the single-configuration run.** That multiplier is the
number a release manager is actually approving, and most planning conversations
never surface it at all.

## The output that surprised me

Three features on the sample range are action-required with **zero** automation:
App Infrastructure, IP Protection, and the newly-split-out Google Lens
integration.

Each gets a 40-configuration 3-way design. Each has nothing to execute in it.

That is not a bug — it is the most useful thing on the page. Those 40
configurations are not a test run, they are **the manual test scope**, sized and
justified. The report labels those rows *"no automation — this matrix is the
manual scope"* rather than quietly showing zero and letting the eye slide past.

The tool cannot tell you a feature is safe. It can tell you exactly how much
risk you are choosing to accept, and precisely where a human has to go look.

## Where the factors come from

Six are **parsed from the tree** — `BrowserMode`, `Account`, `DeviceClass`,
`Pocket`, `RecentlyVisited`, `UnifiedTrustPanel` — read directly out of
`BehaviorContextMatrix.kt`, including its existing 2^6 exhaustive profile. The
efficiency harness already models product state as a factor space; the planner
just reads it.

The rest are **stubbed** and labelled as such in the UI and the config:
`ApiLevel` values (real minSdk/targetSdk are computed in mach's Python build
config; the shipping matrix should come from Play Console distribution data),
`BuildVariant`, `Network`, `Theme`, the `Foldable` device class, and the
per-config cost multipliers.

## Known limits

- Every selected test is assumed runnable in every configuration. Real
  constraints — tablet-only, online-only, signed-in-only — need
  **forbidden-tuple** support in the generator. This is the most valuable next
  change and is contained to `covering_array()`.
- Cost is a flat per-suite estimate times a per-config multiplier, not measured
  runtime. Real numbers would come from Firebase Test Lab billing or Treeherder
  task durations.
- Allocation is per risk band, not per feature. A feature could plausibly earn a
  bespoke factor subset — a settings-only change has no business varying network
  state.

---

*See also: [why-factories.md](why-factories.md) for where the candidate pool
comes from, and [risk-model.md](risk-model.md) for how bands are assigned.*
