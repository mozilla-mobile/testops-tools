# The risk model

Why FMEA, how each factor is derived, and the two modelling decisions that are
load-bearing enough to have regression tests guarding them.

---

## Why FMEA specifically

The requirement was a risk number that is *defensible in a release review* —
something you can point at a standard for when someone asks "where did 51.1%
come from?" Inventing a scoring heuristic is easy; defending one in a go/no-go
meeting is not.

**FMEA** — Failure Mode and Effects Analysis, IEC 60812, and the scheme ISTQB's
risk-based testing material is built on — fits this problem almost suspiciously
well:

```
RPN = Severity x Occurrence x Detection        range 1 .. 1000
```

The reason it fits is the third factor. In FMEA, **Detection** means *how likely
is this failure to escape before it reaches the customer*. That is not an
analogy for the coverage question. It is the coverage question, already
formalised, with fifty years of industrial use behind it.

Which gives the model a property you want:

- **Severity** — you cannot change it. It's what the feature is worth.
- **Occurrence** — you cannot change it either. The code already changed.
- **Detection** — **this is the only factor a test plan moves.**

So "what should we run?" becomes a question about exactly one variable, and
"what did testing buy us?" becomes the measurable difference it made.

## The three factors

### Severity (1-10) — blast radius

Hand-assigned per feature in `config/features.json`. Every value carries a
written rationale, and a unit test fails the build if one is missing — the
number is a judgement call, so the reasoning ships next to it.

The scale is anchored on consequences, not on feelings:

| | |
|---|---|
| 10 | Silent data loss, privacy/security leak, or app unusable. Ships = chemspill. |
| 9 | Core journey broken or trust boundary weakened. Ships = dot release. |
| 8 | Major feature broken for all users of it. Highly visible. |
| 5-7 | Secondary feature broken or degraded. |
| 1-4 | Cosmetic, peripheral, or internal-only. |

Tracking Protection and Private Browsing sit at 10 not because they are complex
but because silent failure means telling users they are protected when they are
not. Theming sits at 4. That gap is the model doing its job.

### Occurrence (1-10) — did this change probably break it

Derived, not guessed, from **relative code churn**: churned LOC over total LOC
of the feature.

The choice of *relative* is deliberate and comes from Nagappan & Ball, *Use of
Relative Code Churn Measures to Predict System Defect Density* (ICSE 2005),
which found that churn normalised against file size predicts defect density
substantially better than absolute churn does. 400 changed lines in a 4,000-line
subsystem is routine. 400 changed lines in a 500-line one is a rewrite. Absolute
churn cannot tell those apart; relative churn can.

Modifiers on top of the churn band:

| signal | delta | why |
|---|---|---|
| 10+ files touched | +1 | broad change surface |
| 15+ commits | +1 | sustained churn, not one clean landing |
| 4+ authors | +1 | coordination risk |
| **touched by a backout** | **+2** | proven instability, not predicted |
| agent semantic review | -3..+3 | see below |

The backout signal is the strongest one available because it is not a
prediction. Something already went wrong there this cycle.

### Detection (1-10) — will a defect escape

Inverted coverage depth. 10 means nothing would catch it; the floor of 2 means a
defect would have to survive the whole suite.

Weighted by what a test is actually worth as evidence:

| binding | meaning | weight |
|---|---|---|
| `strong` | class name **and** page object match | 1.0 |
| `name-only` | class name matches | 0.8 |
| `incidental` | only passes through the surface | **0.0** |

Smoke tests count 1.5x. Disabled tests count zero — automation that is switched
off is not detection, and the report names it separately so it does not hide.

## Two decisions with tests guarding them

These both came out of the prototype being *wrong* first, which is why they have
named regression tests.

### Detection is a curve, not a lookup table

The first implementation mapped coverage tiers to Detection values. It was
wrong, and the failure mode was instructive: with a step function, the second
test added to a feature produces **exactly zero** marginal gain. The greedy
planner, which selects by risk-removed-per-minute, hit that plateau immediately
and stopped — it picked **3 tests out of 769** and reported itself finished.

Detection now decays continuously toward its floor as weighted test count rises.
Every added test earns a positive but diminishing gain, which unblocks the
planner and is also the more honest shape: the fifth test on a feature really
does buy less than the first.

Guarded by `test_every_added_test_still_gains_something`.

### Incidental coverage counts for nothing

The first coverage pass credited Home Screen with **502** covering tests. Only
**16** verify it. The rest import `homeScreen` to navigate somewhere else.

Overstated coverage is worse than no coverage, because it suppresses the RPN
that should have triggered manual testing. A feature reported as "deeply
covered" gets no scrutiny. So an incidental binding is worth zero until a human
or agent confirms it, and the planner refuses to schedule one as coverage.

Guarded by `test_incidental_bindings_are_worth_nothing` and
`test_incidental_tests_are_never_scheduled`.

## Derived numbers

| number | formula | what it tells you |
|---|---|---|
| **Criticality** (FMECA) | S x O | inherent risk of the change. You cannot test this away, only code it away. |
| **Inherent RPN** | S x O x 10 | risk if you shipped with no testing at all. |
| **Residual RPN** | S x O x D(selected) | what survives the planned run. |
| **Release confidence** | 1 − residual / inherent | share of inherent risk the plan removes. |
| **CRAP score** | C² x (1−cov)³ + C | secondary complex-and-untested signal, adapted from per-method to feature scope. |

Bands follow conventional AIAG FMEA practice: **200+ action required**, **100+
review**, below that acceptable.

Release confidence is deliberately weighted so high-severity, high-churn
features dominate. Scoring 90% by covering a pile of trivia while a
severity-10 feature sits untested is exactly the failure this number exists to
prevent.

## Selection

Choosing the run is a **budgeted maximum-coverage problem** — NP-hard, so the
planner uses the standard greedy approximation, which has a (1 − 1/e)
worst-case bound for submodular gain.

The gain of a test is measured, not assumed: after tentatively adding it, the
feature's coverage is **re-derived from the selected set only**, and the gain is
the resulting drop in RPN. A fifth redundant smoke test on an already
well-covered feature scores approximately zero and never gets picked. On the
sample range this classifies **244** bound tests as adding no measurable risk
reduction — that is 244 tests' worth of device time the tool can justify not
spending.

The diminishing returns are real and visible:

| budget | tests | confidence |
|---|---|---|
| 15 min | 9 | 29.1% |
| 45 min | 24 | 43.3% |
| 240 min | 73 | 51.1% |

**45 minutes buys 85% of what 147 minutes buys.** That curve is the actual
deliverable for a release manager deciding how much device time to fund.

## Where judgement enters, and how it stays auditable

The pipeline never calls a model. It runs deterministically and emits typed
questions for the things that genuinely need judgement, each with the gathered
evidence and a schema for the answer:

| task | the judgement call |
|---|---|
| `classify-unmapped-path` | changed code that matched no feature |
| `assess-change-semantics` | churn cannot tell a rename from a behaviour change |
| `review-severity` | catalog severity is a static average |
| `review-weak-binding` | does this test really exercise the feature |
| `author-manual-tests` | turn residual risk into manual cases |

Answers are fed back with `--answers` and recorded in
`meta.agent_overrides_applied`. Every AI-influenced number traces to a question,
an answer, and a rationale — which is the difference between a risk score you
can defend and one you have to trust.

This is not decoration. On the sample range, answering
`assess-change-semantics` by reading the actual diffs found that 342 of 690
lines filed under "App Infrastructure" were a **new Google Lens integration**
(bug 2028573) living under `components/lens/`. It is now its own feature, and it
lands as action-required with zero UI coverage — which it genuinely has. The
deterministic layer found the churn; judgement found the misclassification.

---

*See also: [why-factories.md](why-factories.md) for why a candidate pool worth
selecting from exists at all, and [matrix.md](matrix.md) for configuration
coverage.*
