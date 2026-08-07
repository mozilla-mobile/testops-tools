# Two kinds of denominator

*What a coverage percentage is allowed to mean, on a platform with test factories
and on one without.*

---

[why-factories.md](why-factories.md) makes the case that a hand-written suite has
no denominator, so percentages against it are theater. The factories fix that on
Android by *enumerating* a space. This document is about what to do on a platform
that has no factories — which is to say, on iOS today — and about a second
denominator that turns out to work on both.

## Derived vs assumed

|  | derived | assumed |
|---|---|---|
| source | generation factories enumerate the reachable space | someone wrote down the cases a release needs |
| available on | Android | Android and iOS |
| total is | computed | asserted |
| answers | "of what could be tested, how much is" | "of the plan we wrote, how much is automated" |
| fails when | the page-object model is incomplete | nobody wrote a case for something |

Both are legitimate. They are not interchangeable, and the tool never merges
them into a single number.

## Why iOS gets no derived denominator

The obvious temptation, having ported everything else, is to estimate one: count
the XCUITest screens, multiply by something, call it a candidate space. That
would be inventing the exact quantity the model's coverage claims rest on.

`factories.empty()` therefore returns zeros and `has_candidate_space: False`, and
the report says "not available on Firefox iOS" rather than printing 0. A zero
that looks like a measurement is worse than an absence, because the reader cannot
tell them apart.

Firefox iOS could grow a factory space — a MappaMundi screen graph is a
navigation model, and `FxScreenGraphTests` already walks it. Enumerating
reachability over that graph is the same construction the Fenix reachability
factory uses. That is a real piece of work, not a config change, and until it
exists iOS coverage is counts and gaps.

## Why the TestRail case set is a defensible assumed denominator

Three properties, in order of how much they matter.

**The join is exact.** Both codebases already carry the case id above each test,
in the same URL form, and `corpus.py` extracts it with one regex on both
platforms. So binding automation to cases is an id match. This matters more than
it sounds: a name-similarity heuristic would stack a second assumption on top of
an already-assumed denominator, and the error bars would swallow the result.

**It is a deliberate artefact.** Someone decided each case was worth writing for
a release. That is a statement of intent about what a release needs — and unlike
the automated suite, it was not shaped by what happened to be cheap to automate.

**It answers the question a release manager actually asks.** Not "how much of the
app is covered" but "how much of the plan will a machine run, and what is left
for people?" The remainder *is* the manual-testing plan.

### Where it is weak, stated plainly

TestRail is also a pile that accumulated. Cases cluster where bugs were once
found and thin out where nobody got round to writing them. So:

- The output is named `automated_ratio`, never `coverage`.
- `denominator: "assumed"` travels in the JSON so no downstream consumer can
  mistake it for the derived kind.
- A feature with 100% `automated_ratio` means every case someone wrote is
  automated. It does not mean the feature is well tested.

### Two rules that keep the ratio honest

**Automation that never runs is not automated coverage.** A case whose only
automated test is `@Ignore`d, skipped by every `.xctestplan`, or guarded behind
`#available … else { return }` counts as manual. On firefox-ios `release/v153.3`
this is not a rounding error: of 440 case ids referenced by XCUITests, **125** are
claimed by a test that no test plan runs. Counting those as automated would
overstate automation by 28% and, worse, would hide 125 cases that need a human.

**A referenced id absent from the export is reported, not counted.** Tests
sometimes point at cases in another project or suite, or at deleted ones. Those
inflate the numerator against an export that does not contain them, so they are
surfaced as `unmatched_ids` instead.

## Using both together on Android

Android can compute both, and the pair is more informative than either:

- derived coverage low, assumed high → the written plan is thin relative to what
  the app can do. The factories know about surfaces nobody wrote cases for.
- derived low, assumed low → ordinary under-automation.
- derived high, assumed low → automation exists for things the release plan does
  not ask about. Worth asking whether the plan is stale.

That comparison is the argument for wiring TestRail on Android too, not just as
the iOS consolation prize.
