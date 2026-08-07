# Architecture

How the pipeline is put together, what each stage owns, and where to reach in
if you want to change or extend it.

---

## Design rules

Three constraints shaped the whole thing:

1. **Deterministic by default.** The pipeline never calls a model. Same inputs,
   same output, every time — because a risk number that changes between runs is
   not a risk number, it's a mood. AI judgement enters through an explicit,
   auditable seam.
2. **Stdlib only.** Python 3.9+, no install step, no venv, no API key, no
   network. A tool you have to set up is a tool people don't run. This also
   keeps it a comfortable neighbour in `testops-tools`.
3. **Every number traceable.** Every score exposes its inputs. The report shows
   the churn basis under each feature name, the tuple count each array verified,
   and the rationale behind every agent override.

## Stages

```
  git range
      |
  [1] changes     git log --numstat -> per-file churn          deterministic
  [2] featuremap  path globs -> features                       + agent for misses
  [3] corpus      parse Kotlin / Swift tests -> test inventory  deterministic
  [4] coverage    bind tests to features, score depth          + agent for weak bindings
  [5] risk        FMEA: RPN = S x O x D                        + agent for S and O
  [6] plan        greedy budgeted selection -> gaps            + agent for manual cases
  [7] factories   generated-case candidate space               deterministic (Android only)
  [8] matrix      risk-tiered covering arrays                  deterministic
      report      static HTML
```

One module per stage in `testplanner/`. Each returns plain dicts, so any stage
can be run, inspected or replaced in isolation.

| module | owns | watch out for |
|---|---|---|
| `changes.py` | git range -> per-file churn, bug ids, backout detection | the record separator must **prefix** each record; `--numstat` output follows the format string, so a trailing separator pairs each commit with the *previous* commit's files |
| `featuremap.py` | path globs -> features, longest-glob-wins | a file gets exactly one primary feature so churn is never double counted |
| `corpus.py` | Kotlin **and Swift** parsing: tests, TestRail ids, surfaces, what actually runs | one reader per language behind one interface; on iOS a test's `.xctestplan` membership decides whether it runs at all |
| `platforms.py` | where tests live, which language, whether a candidate space exists | `has_factories` gates whether a coverage percentage may be printed |
| `testrail.py` | the assumed denominator: joins a case export to the corpus on case id | never merged with the derived denominator — see denominators.md |
| `coverage.py` | test-to-feature binding, Detection curve | binding strength is the whole ballgame — see risk-model.md |
| `risk.py` | FMEA scoring, bands, CRAP | no Fenix knowledge; reusable as-is |
| `plan.py` | greedy budgeted selection, gap detection | gain is re-derived per candidate, not assumed |
| `factories.py` | parses `generation/` to size the candidate space | the only module that knows about the efficiency harness internals |
| `matrix.py` | IPOG covering arrays, Rao-Hamming OAs, verification | no Fenix knowledge; reusable as-is |
| `agentio.py` | the deterministic/AI boundary | typed questions out, audited overrides in |
| `report.py` | the self-contained HTML dashboard | data embedded *and* fetched — see below |

`risk.py` and `matrix.py` carry no platform knowledge at all. That claim was
tested by the iOS port: both moved unchanged, as did `changes.py` and `plan.py`.
What the port actually needed was a Swift reader in `corpus.py`, a second
catalog, and `platforms.py` to hold the paths that used to be constants in
`cli.py`.

## Configuration is data

Two JSON files hold everything a non-Python-reader might want to argue with:

**`config/features.json`** — the feature catalog. Per feature: severity plus a
written rationale, ISO 25010 quality attributes, production source globs,
efficiency page objects, and test class name patterns. Features marked
`"indirect": true` are cross-cutting code no UI test is named for; a zero there
means "not *directly* covered", not "never executed", and the report says so.

**`config/environment.json`** — matrix factors, each declaring whether it is
`real`, `partly-real` or `stubbed` with its origin, plus the risk-band ->
strength allocation policy and cost multipliers.

Both are validated by unit tests: duplicate feature ids fail, a severity outside
1-10 fails, a missing severity rationale fails, an environment factor that
doesn't declare its provenance fails. Config is data, so it gets tested like
data.

## The agent seam

The pipeline emits typed questions rather than calling a model. Each carries the
evidence already gathered, a statement of *why* the call needs judgement, and a
schema for the answer. An agent (or a person) answers into JSON; `--answers`
folds them back as overrides; `meta.agent_overrides_applied` records what
changed and why.

Adding a question type means adding an entry to `TASK_TYPES` in `agentio.py`,
emitting it in `emit()`, and handling it in `apply_overrides()`.

The property worth preserving: **you can always run the whole thing with no AI
at all and get a complete, defensible answer.** Judgement improves it; nothing
depends on it.

## The report

One HTML file, no external requests — no CDN, no webfonts, no images. It resolves
its data in this order:

1. `report.json` sitting next to it, so `serve` gives you a plain browser refresh
2. a copy embedded in the file itself, so it works from `file://` and can be
   dropped on a static host alone

The header states which one it used. It paints the embedded copy immediately and
swaps in live data when it arrives — under `serve --live` the fetch triggers a
full pipeline re-run, and a page that sits blank for several seconds reads as
broken.

Caveat: CSS and JS are inline, so a host enforcing a strict CSP without
`'unsafe-inline'` renders an empty shell. Fix if needed is external `report.css`
/ `report.js`, or CSP hashes.

## Tests

69 unit tests, ~0.6s, **no Firefox checkout required** — Kotlin parsing runs
against fixtures in `tests/fixtures`, git parsing against a throwaway repo built
in `setUpClass`.

```bash
python -m unittest discover -s tests -p '*tests.py'
```

Two exist specifically because the prototype got it wrong first, and are named
so the next person doesn't undo the fix:

- `test_every_added_test_still_gains_something` — the tiered Detection lookup
  that stalled the greedy planner at 3 tests out of 769
- `GitChangeTests` — the record-separator bug that reported one commit and zero
  files, which looked exactly like an empty range

## Extending it

**A new feature in the catalog** — add an entry to `config/features.json` with
source globs, page objects, test patterns, and a severity rationale. No code.

**A new matrix factor** — add it to `infrastructure_factors` and reference it in
the allocation policy. Declare its `source` honestly.

**A new platform** — add a `Platform` to `platforms.py`, a catalog under
`config/`, and a reader to `corpus.readers` if the language is new. `risk.py`,
`matrix.py`, `changes.py` and `plan.py` need no changes; iOS proved that.
`factories.py` is
Android-specific by nature. The pipeline shape holds.

**A new test layer (unit/component/service)** — this is the highest-value
extension. `corpus.py` grows a parser per layer, and `coverage.py` weights the
layers into Detection. Today's confidence is *understated* for well-unit-tested
code, and closing that is worth more than any refinement of the existing scoring.

---

*See also: [why-factories.md](why-factories.md), [risk-model.md](risk-model.md),
[matrix.md](matrix.md).*
