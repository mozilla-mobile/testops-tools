# Why the test factories are the whole ballgame

*The case for why this planner can exist at all, and why it could not have been
built on top of the legacy suite.*

---

## The uncomfortable question every risk tool has to answer

Risk-based test selection sounds obviously good. Score the risk, run the tests
that address it, skip the rest. Every QA org has wanted this forever.

So why doesn't everyone have it?

Because selection is only worth doing when **supply exceeds budget**. If your
release window fits 200 tests and your suite has 200 tests, the optimal plan is
"run everything," and no amount of scoring machinery improves on that. You have
built an expensive way to arrive at the obvious answer.

Worse — and this is the part that quietly kills most coverage initiatives — a
hand-written suite has **no denominator**. You cannot say "this run gives us 60%
coverage of the tabs feature," because nobody ever enumerated what 100% would
be. The suite is not a sample of a defined space. It is a pile of artifacts that
accumulated because somebody had time to write them. Percentages computed
against a pile are theater.

That is the honest reason most test-selection tooling stalls out at "here are
some tests that mention the word you changed."

## What the factories change

A factory does not write tests. It **enumerates a space** and emits a case per
point in it.

That distinction is the entire argument, so it's worth being concrete. The
efficiency harness models the app as a navigation graph of page objects, each
with a catalog of selectors. From that model, without anyone authoring a test:

| factory | enumerates | candidates today |
|---|---|---|
| **Reachability** | every registered page | **50** |
| Interaction | every interactive selector, per page | 466 |
| Pairs | every ordered page-to-page transition | 2,450 |
| Behavior | capability x template x context variant | 192 |

**3,158 candidate cases**, derived from a model that a person maintains at the
cost of ~50 page objects and 58 selector catalogs.

Two things follow, and they are both load-bearing.

### 1. Supply now exceeds budget, so selection means something

3,158 candidates against a release window that fits maybe 70 tests is a genuine
oversupply problem. *Now* the question "which of these actually reduce release
risk?" is a real question with a non-obvious answer worth computing. The planner
in this directory is the answer to a question the factories created.

Run the counterfactual. On the legacy suite — 629 hand-written tests across 71
files — the honest recommendation for most release cycles is "run the smoke
subset, it's what you've got." That's not risk-based testing. That's a
convention with a spreadsheet attached.

### 2. Coverage finally has a denominator

This is the one that matters more, and it's the one that's hard to appreciate
until you've tried to compute a coverage number and found you couldn't.

Because the candidate space is *derived from the model*, it is enumerable. So
these statements become arithmetic rather than aspiration:

- "This run exercises 38 of 50 reachable pages — 76% page reachability."
- "We touched 112 of 466 interactive selectors on the surfaces we changed."
- "Every pairwise combination of device class, API level and browser mode is
  covered by 13 configurations, verified."

Each of those has a real denominator, because something enumerated the space.
Ask a hand-written suite for the same numbers and the only truthful answer is a
shrug. You can count what you wrote. You cannot count what you *should* have
written, because nobody ever built the list.

**A generated suite is defined by its enumeration. That is what makes theoretical
coverage claims defensible instead of embarrassing.**

## The compounding property

Here is the part that decides whether this pays off over five years.

Under hand-authoring, coverage scales with headcount. Test number 630 costs
about the same as test number 12. Linear in, linear out, forever. The suite grows
exactly as fast as people type, and shrinks whenever they stop.

Under the factory model, the marginal artifact is a **page object**, and the
candidate space grows superlinearly against it. Register page object number 51
and, for one authored file, the space gains:

- **+1** reachability case, automatically
- **+100** pair candidates (2 x 50 existing pages, both directions)
- **+k** interaction candidates, one per selector in its catalog

One artifact authored. A hundred-odd candidates generated. And nobody has to
remember to do it — `PageCatalog` discovers page objects by reflection, so a new
page object enters the candidate space by existing. There is no registry to
update and therefore no registry to forget.

That is the difference between a suite that grows when you hire and a suite that
grows when you model.

## Three design decisions that make it work

Pitching the outcome without the mechanism is how you get a skeptic. So:

**Arrival is the assertion.** `navigateToPage()` routes over the graph via BFS
and verifies the target page's `requiredForPage` anchor on arrival. This is why
the reachability factory needs no authored assertions — reaching the page *is*
the check. A generated case with a hand-written assertion isn't generated; it's
a template you still have to fill in. Making arrival self-verifying is what
turns "generate a case per page" from a nice idea into 50 real tests.

**One resolve() seam, and it handles the Compose trap.** Element resolution
tries **both** the merged and unmerged Compose semantic trees and picks the
*displayed* match. Anyone who has fought Compose merged-vs-unmerged flakiness
knows that is a recurring, expensive, deeply annoying bug class. Fixing it once
underneath everything means generated cases inherit the fix — you cannot
generate thousands of cases on top of a resolution layer that's a coin flip.

**Deterministic sharding.** `ShardUtils` splits generated cases across shards by
index modulo shard count. Volume you cannot distribute is volume you cannot run,
so this is the difference between an interesting candidate count and an
executable suite.

## The part I am not going to oversell

The in-tree architecture doc is blunt about factory status, and it's right to be:

- **Reachability** is production-ready. It auto-covers every registered page.
- **Interaction** is implemented for bookmarks only.
- **Behavior**'s context matrix is largely unimplemented.
- **Pairs** has no clear failure class it uniquely catches, and whether to keep,
  cut or redesign it is an open decision.

So today: page-open checks come from the Reachability factory; everything else
is hand-composed on `BasePage`, which is the mature path.

**That does not weaken the argument. It sharpens it.** The claim is not "we have
3,158 tests." The claim is:

> The generation machinery is built, and one factory has already proven the whole
> thesis end to end in production — 50 pages covered, zero per-page authoring,
> self-updating by reflection.

Reachability is the existence proof. The remaining three are the same machine
pointed at richer spaces, and their candidate counts are what the space *is*,
not a promise about what will be runnable. Anyone can go read `PageCatalog`,
`NavigationRegistry`, and `ReachabilityCaseFactory` and check that the mechanism
is real.

The right way to read the 3,158 is: *this is the size of the space the model
already describes.* Turning more of it into runnable cases is engineering
against a proven pattern — not a research bet.

## The evidence that showed up unplanned

While building this planner, something happened that argues for the efficiency
refactor better than anything designed to.

The first coverage pass credited the Home Screen feature with **502 covering
tests**. That's obviously wrong — it's most of the entire suite. The cause: in
the legacy robot DSL, almost every test imports `homeScreen` and
`navigationToolbar` in order to *navigate somewhere else*. A `BookmarksTest`
looks, to any static analysis, exactly like a home screen test.

Only **16** tests actually verify the home screen.

Two conclusions, and the second is the important one:

1. Overstated coverage is more dangerous than no coverage. It suppresses the risk
   score that should have triggered manual testing. A tool confidently reporting
   "deeply covered" on a feature with 16 real tests will get a release shipped
   broken.

2. **The legacy suite is not analyzable, and the efficiency suite is.** In the
   legacy DSL, navigation and verification are the same gesture, so what a test
   *covers* is not recoverable from its source. In the efficiency framework,
   `on.<page>` makes the surface a test touches machine-readable, page objects
   make the model explicit, and the navigation graph makes routing separable
   from assertion.

That second point was not a design goal of the refactor as far as I know. It
fell out of it. And it's the precondition for *any* coverage tooling — including
every future version of this planner, and including the Mozilla-wide,
cross-platform version this is heading toward.

You cannot compute risk-weighted coverage over a suite you cannot parse. The
refactor is what made the suite parseable.

## What this unlocks next

The planner currently reasons about hand-written UI tests. Wiring the factory
candidates into selection is the next step, and it changes the question the tool
answers:

Today: *"Which of our existing tests should we run for this release?"*

Next: *"What is the minimum set of cases — existing or generatable on demand —
that drives residual risk below threshold for this release?"*

That second question is only askable if cases can be *materialized to order*
from a model. It is not askable of a fixed pile of files. The factories are what
make it askable.

And the reason to care about the difference: the first question is bounded by
what someone already wrote. The second is bounded by what the app actually is.

---

*See also: [risk-model.md](risk-model.md) for how risk is scored, and
[matrix.md](matrix.md) for how the candidate space is reduced to a runnable
configuration set.*
