# Firefox iOS Test Recommender

LLM-assisted system that suggests which TestRail tests to run for each Firefox iOS
release, by cross-referencing the code changes in the release against the
manual + automated test catalogue.

---

## Objective

The full functional regression suite for Firefox iOS (well over a thousand
cases) cannot be fully executed on every release. This project produces,
per release, a prioritized Markdown report that answers:

1. Which manual tests from the existing test plan are most likely affected by
   the PRs in this release (P0 / P1 / P2 priority with per-test reasons).
2. Whether any new manual tests should be added — coverage gaps in the
   catalogue.
3. Whether any new automated regression tests should be added for critical
   flows.
4. What risks the release introduces (concurrency changes, force-unwraps,
   dependency bumps, Nimbus flag flips, hotspot files, large PRs without
   tests).
5. Which areas should be the focus of exploratory testing.
6. Which PRs warrant deeper code review beyond QA.

The system is a **suggestion layer that complements QA judgment**, never a
replacement. The goal is to make the limited manual testing time hit the
highest-value subset of the catalogue, not to declare anything "safe to skip".

### Why this is feasible

- Firefox iOS follows a predictable release flow: long-lived `release/vMAJOR`
  branches, tagged as `firefox-vMAJOR.MINOR[.PATCH]`, with Mergify
  auto-backports from `main`. The natural diff for analysis is between two
  consecutive tags.
- TestRail's `Section Hierarchy` column is 100% populated and the top-level
  sections map cleanly to code modules (Toolbar → `BrowserKit/ToolbarKit`,
  Menu redesign → `MenuKit`, Library → `firefox-ios/Client/Frontend/Library`,
  etc.).
- A significant subset of TestRail cases include explicit
  `Automated Test Name(s)` paths to their Swift implementation, enabling
  direct code↔test mapping without LLM inference.

### Constraints we work around

- TestRail's `Labels` column is empty, and `Priority` is effectively flat
  (nearly all Medium, only a handful High). `Section Hierarchy` is the only
  useful structural signal — the system relies on it.
- Major release diffs touch ~300 files / ~12k LOC — too large to feed raw
  to an LLM. The pipeline summarizes by module before reasoning.
- PR labels are inconsistently applied. The system relies on file paths and
  on the strong `<Verb> FXIOS-NNNNN [Area] description` PR title convention.
- Nimbus feature flags can change behaviour server-side without a code diff
  in the product. The pipeline always flags changes to `nimbus-features/` or
  `initial_experiments.json` as a separate risk.

---

## Architecture

```
                ┌─────────────────────────────┐
                │  TestRail export (.xlsx)    │  refreshed when QA lead
                │  manual + automated cases   │  re-exports from TestRail
                └──────────────┬──────────────┘
                               │
                               ▼
   ┌───────────────────────────────────────────────────┐
   │  section_to_module_mapping.yaml                    │  human-curated config:
   │  TestRail sections ↔ firefox-ios code modules      │  the "Rosetta stone"
   │  + drift_detection rules                           │
   │  + special_rules (Nimbus, dependencies, strings,   │
   │    Mergify backports)                              │
   └──────────────────────┬────────────────────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼
┌───────────────────┐               ┌────────────────────┐
│  align.py         │               │  recommend.py      │
│  (planned)        │               │  (batch)           │
│                   │               │                    │
│  Run on demand    │               │  Run per release   │
│  when TestRail or │               │  by QA lead        │
│  the repo changes │               │                    │
│  structurally     │               │                    │
└─────────┬─────────┘               └──────────┬─────────┘
          │                                    │
          ▼                                    ▼
  ┌────────────────────────────┐    ┌──────────────────────────┐
  │ pending_mapping_review.yaml│    │ release_report_<tag>.md  │
  │ (LLM proposals for humans  │    │ (the deliverable for QA) │
  │  to accept/edit/reject)    │    │                          │
  └────────────────────────────┘    └──────────────────────────┘
```

### Components

| File | Type | Edited by | Read by |
|---|---|---|---|
| `section_to_module_mapping.yaml` | Config (human-curated) | QA lead | `recommend.py`, `align.py` |
| `testrail_export_ios.xlsx` | TestRail export | TestRail admin | `recommend.py`, `align.py` |
| `recommend.py` | Script (working) | Engineering | Run per release |
| `align.py` | Interactive CLI (planned) | Engineering | Run when drift is detected |
| `pending_mapping_review.yaml` | Output (planned) | `align.py` will write it, humans will review | `align.py` (planned) |
| `release_report_<tag>.md` | Output | Generated each run | QA team (the deliverable) |

### Why two scripts, not one

`recommend.py` and `align.py` have different cadences and different stakes:

- **`recommend.py`** runs every release (weekly). It must never block a
  release report on a mapping gap — it surfaces drift as a visible warning
  at the top of the report and produces the recommendations with whatever
  mapping is available.
- **`align.py`** (planned) will run on demand when TestRail or the repo
  changes structurally. It will be interactive (CLI prompts) and update
  the mapping YAML directly. Curating a mapping needs a human in the loop;
  recommendation generation does not.

Both will share the same drift-detection logic. Until `align.py` ships,
`recommend.py`'s inline drift detection is the only mechanism surfacing
gaps.

---

## How `recommend.py` works

```
INPUT: prev_tag, new_tag, testrail_export.xlsx, mapping.yaml
  │
  ├─ 1. Diff via `gh api compare prev_tag...new_tag`
  │       → list of PRs, files changed, authors, sizes, commit list
  │
  ├─ 2. Filter low-impact PRs:
  │       · string imports (weekly l10n PRs)
  │       · Mergify backports already shipped on main
  │       · mechanical Rust component bumps
  │
  ├─ 3. Light risk heuristics (no LLM, deterministic):
  │       Per PR:
  │         · LOC, # files, tests added or not
  │         · concurrency keywords (async/await/actor/DispatchQueue) in
  │           added lines
  │         · force-unwrap / try! / fatalError introduced
  │         · error-handling changes (catch/throw/Result)
  │         · last-minute merge timing
  │       Per file:
  │         · hotspot (precomputed: bug-fix frequency in git log)
  │         · author churn last 90 days
  │       Per release:
  │         · dependency files changed (Package.swift, Podfile.lock,
  │           MozillaRustComponents/)
  │         · Nimbus feature flags changed (nimbus-features/,
  │           initial_experiments.json)
  │
  ├─ 4. Drift detection (cheap, fail-loud, non-blocking):
  │       · TestRail sections in export but not in YAML → LLM proposes
  │         mapping → written to pending_mapping_review.yaml
  │       · Modules touched in diff but not in YAML → same treatment
  │       · YAML entries whose section name or module path no longer
  │         exists → flagged stale
  │       Test files and noise paths (.xcodeproj, .plist, Assets/, .lproj/)
  │       are excluded from this check.
  │
  ├─ 5. Group changed product-code files by code module
  │       (BrowserKit/Sources/<Kit>, firefox-ios/Client/Frontend/<area>, …)
  │       Test files and noise are excluded from module-touched counting;
  │       test files are used only for exact match in step 6.
  │
  ├─ 6. Exact match: changed `.swift` test files → cross-reference
  │       TestRail cases with explicit `Automated Test Name(s)` paths.
  │       → "these TestRail tests are directly affected by code changes"
  │
  ├─ 7. Section match: code modules → TestRail sections, via mapping.yaml.
  │       → candidate test set (typically ~989 after dedup + Smoke filter).
  │
  ├─ 8. Compute test budget (deterministic, no LLM):
  │       · detect release type from tag names: patch / minor / major
  │       · base range per type: patch 25-40, minor 40-70, major 100-160
  │       · additive bumps: +15 if total LOC > 15k, +10 if any PR > 2k LOC,
  │         +10 if ≥3 high-severity risk signals
  │       · clamp to [15, 200]
  │       · used both to configure the LLM's target and to cap its output
  │
  ├─ 9. Pre-filter candidates (deterministic score, no LLM):
  │       Score each candidate: +50 exact-match, +30 section maps to
  │       top-quartile-LOC module, +20 section has risk signal, +10 manual
  │       only, -20 CI-Completed. Sort by score, keep top budget_hi × 4
  │       (typically ~280). This 3-4× reduction in pool size drops rerank
  │       token cost and improves inter-run stability.
  │
  ├─ 10. LLM rerank (Sonnet 4.6 by default, structured JSON output):
  │       Inputs: module diff summary + risk signals + drift findings +
  │       filtered candidate list including each candidate's score.
  │       Output: ranked subset of budget_lo-budget_hi tests with
  │       priority (P0/P1/P2) and per-test reasons; plus narrative notes.
  │       Temperature: 0 (for Sonnet 4.6). Prompt cached.
  │
  ├─ 11. LLM synthesize (Sonnet 5 by default, streaming):
  │       Produces the final 7-section Markdown report:
  │         · Executive summary
  │         · Suggested manual tests (P0/P1/P2)
  │         · Coverage gaps — manual tests to add
  │         · Suggested automated regression
  │         · Risks
  │         · Exploratory testing focus
  │         · High-risk PRs to review more deeply
  │       Effort: medium. Thinking: disabled. Prompt cached.
  │       Report header includes the computed budget as an auditable line.
  │
  └─ OUTPUT: release_report_<new_tag>.md (English)
```

See `metrics_baseline.md` for measured cost, latency, and inter-run overlap
across each phase of pipeline evolution.

---

## Setup

### Prerequisites

- macOS or Linux
- Python 3.9+ (tested on 3.9.6 and 3.11)
- `gh` CLI authenticated against `github.com/mozilla-mobile/firefox-ios`
- An Anthropic API key (Tier 1 minimum — 30k TPM; Tier 2 recommended for
  comfort: 80k TPM)

### Install dependencies

```bash
pip3 install --user -r requirements.txt
```

Pinned minimums: `openpyxl>=3.1.5`, `pyyaml>=6.0.3`, `anthropic>=0.109.1`. See
`requirements.txt` for the source of truth. Newer versions usually work but
the Anthropic SDK's messages API evolves — the code has model-specific
handling for `effort`, `temperature`, and `thinking` and may need adjustment
if you jump many SDK versions.

### Configure your API key

The safest option for personal use on macOS is to export the key from
`~/.zshrc` so it lives outside the repo and is never committed:

```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-api03-..."' >> ~/.zshrc
chmod 600 ~/.zshrc
source ~/.zshrc
```

Verify (truncated for safety):

```bash
echo "${ANTHROPIC_API_KEY:0:15}..."
```

If you are on Tier 1 (30k TPM), the pipeline still works — the SDK retries
with backoff on rate-limit responses. For frictionless runs deposit credits
to reach Tier 2 ($40 cumulative purchases → 80k TPM for Sonnet 4.6). See
https://console.anthropic.com/settings/limits for your current tier.

If the API key is not set, `recommend.py` falls back to a deterministic
ranker and writer — the script still runs end-to-end.

### Optional environment variables

All three are optional. Use them to override defaults for experiments or
emergency rollback without touching code.

| Variable | Default | Purpose |
|---|---|---|
| `RECOMMEND_MODEL_RERANK` | `claude-sonnet-4-6` | Model used for the rerank stage. Sonnet 4.6 was selected empirically (see `metrics_baseline.md`) over Haiku 4.5 and Sonnet 5 — the alternatives had lower inter-run stability. |
| `RECOMMEND_MODEL_SYNTHESIZE` | `claude-sonnet-5` | Model used to write the narrative report. Sonnet 5 gives slightly better prose than 4.6 at similar cost. |
| `RECOMMEND_RERANK_EFFORT` | `low` | Effort level for rerank on models that support it (Sonnet/Opus). Ignored for Haiku. Increasing it does NOT improve stability empirically; kept configurable for future models. |

Example — try Opus 4.7 for synthesize on a specific release:

```bash
RECOMMEND_MODEL_SYNTHESIZE=claude-opus-4-7 python3 recommend.py --from ... --to ...
```

### Refresh the TestRail export

The TestRail catalogue evolves. Re-export `testrail_export_ios.xlsx`
from TestRail before each release run to keep the mapping current. The
file is **not versioned in this repo** — export it from your TestRail
instance and place it at the project root (or anywhere else and pass
the path via `--testrail`). The expected columns are documented at the
top of `section_to_module_mapping.yaml`.

---

## Usage

### Generate a release report

```bash
cd test-recommender

python3 recommend.py \
  --from firefox-v151.2 \
  --to firefox-v151.3 \
  --testrail ./testrail_export_ios.xlsx \
  --mapping ./section_to_module_mapping.yaml \
  --output ./release_report_firefox-v151.3.md \
  --verbose
```

Arguments:

| Flag | Required | Notes |
|---|---|---|
| `--from` | yes | Previous release tag, e.g. `firefox-v151.2` |
| `--to` | yes | New release tag, e.g. `firefox-v151.3` |
| `--testrail` | yes | Path to a TestRail `.xlsx` export |
| `--mapping` | yes | Path to `section_to_module_mapping.yaml` |
| `--output` | no | Output Markdown path. Default: `release_report_<to_tag>.md` |
| `--verbose` / `-v` | no | Stream pipeline progress and token usage to stderr |

**Note on branch names in `--to`**: The default output path
(`release_report_<to_tag>.md`) is a direct string substitution. If `--to`
is a branch name like `release/v153.0` (rather than a tag like
`firefox-v153.0`), the default becomes `release_report_release/v153.0.md`
— which Python treats as a subdirectory `release_report_release/` plus a
file, and the write fails because the directory doesn't exist. When
running against a branch, pass `--output` explicitly, e.g.
`--output ./release_report_firefox-v153.0.md`.

Typical wall-clock time: 30-90 seconds. Typical cost: ~$0.30 per release
with Sonnet 4.6.

### Interpret the output

The report has seven sections in this order:

1. **Executive summary** — 2-4 bullets. The two or three things QA should
   know first.
2. **Suggested manual tests** — divided into P0 (must run), P1 (should
   run), P2 (if time). Each test has a one-line reason specific to this
   release.
3. **Coverage gaps — manual tests to add** — areas where the diff suggests
   behaviour that the existing catalogue does not cover.
4. **Suggested automated regression** — critical flows that touched
   manual-only tests and would benefit from automation.
5. **Risks** — concurrency changes, force-unwraps, dependency bumps,
   Nimbus changes, large PRs, hotspot files, in plain prose ranked by
   severity.
6. **Exploratory testing focus** — 3-6 specific areas to poke at, each
   tied to a concrete change in the diff.
7. **High-risk PRs to review more deeply** — PRs that warrant code review
   beyond QA.

If the system detects mapping drift (new sections in TestRail or new
modules in the repo without YAML mapping), a `⚠️ Mapping drift detected`
warning appears at the very top of the report. Until `align.py` ships,
curate the mapping YAML by hand to resolve.

### Verbose output

With `--verbose`, the script prints token telemetry per LLM call:

```
[recommend] rerank usage: input=43228 cache_write=1087 cache_read=0 output=2101
[recommend]   49 tests ranked (P0=21, P1=25, P2=3)
[recommend] synth usage: input=9426 cache_write=0 cache_read=0 output=6348
```

`cache_read` will be 0 on the first run with a given system prompt. On
subsequent runs (within the 5-minute cache TTL, or 1-hour with explicit
TTL configuration), `cache_read` will populate and you'll pay ~0.1× input
cost for the cached portion.

If `cache_write` stays at 0 across multiple runs, the system prompt is
below Anthropic's ≥1024-token minimum for prompt caching — a silent
failure with no error, only a ~20% cost bump. After editing either
system prompt in `recommend.py`, run
`python3 scripts/count_prompt_tokens.py` to verify the prompts still
meet the threshold.

---

## Configuration: `section_to_module_mapping.yaml`

The mapping YAML is the most important human-curated artifact in the
project. It has four top-level blocks:

- `sections:` — one entry per top-level TestRail section, listing the
  code modules that map to it. Confidence is annotated (high / medium /
  low) for manual review.
- `modules_without_clear_section:` — code modules that don't have a
  TestRail section. These are coverage blind spots and the recommender
  flags changes to them explicitly.
- `special_rules:` — **descriptive documentation** of how the pipeline
  handles Nimbus changes, dependency bumps, string imports, and Mergify
  backports. The actual behaviour is hardcoded in `recommend.py` (see
  `LOW_IMPACT_TITLE_KEYWORDS`, `DEPENDENCY_PATHS`, `NIMBUS_PATHS`); this
  block is NOT parsed at runtime, it exists as a reference for readers.
- `drift_detection:` — **descriptive documentation** of the drift-detection
  design. `recommend.py` implements the basic checks (TestRail sections
  and repo modules not in the YAML); the rest of the block describes
  goals for `align.py` (not yet implemented).

When TestRail adds a new section, or the repo adds a new module, the
mapping needs to be updated. The drift-detection logic in `recommend.py`
will surface this as a warning; you should then either edit the YAML
directly or run `align.py` once it exists.

---

## Cost estimate

Per release run with the default models (rerank on Sonnet 4.6, synthesize on
Sonnet 5):

| Stage | Model (default) | Notes |
|---|---|---|
| Rerank | Sonnet 4.6 | Structured JSON output, prompt-cached |
| Synthesize | Sonnet 5 | Streaming Markdown, prompt-cached |
| **Total** | | **~$0.24–0.38 per run** |

Measured range across recent runs — see `metrics_baseline.md` for the
per-phase evolution. A weekly cadence yields ~$15–20/year. A major release
(12k LOC diff) stays under $1. With prompt caching on the second run onward
(within the 5-minute TTL), rerank input costs drop ~20%.

Override the models via `RECOMMEND_MODEL_RERANK` / `RECOMMEND_MODEL_SYNTHESIZE`
env vars if you want to run cheaper (e.g. Sonnet 4.6 on both) or more expensive
(e.g. Opus 4.7 on synthesize for the highest prose quality). See the
"Optional environment variables" table in the Setup section above.

If you run on the deterministic fallback only (no API key), cost is zero
but the report is materially less useful — the P0/P1/P2 distribution
collapses, and the narrative sections become boilerplate.

---

## Limitations and known issues

- **Section-match candidate sets are coarse.** A single touched file in a
  given area pulls in every TestRail test in that section. The LLM rerank
  trims this from ~900 candidates down to 25-50, but the candidate pool
  is broader than ideal. A future iteration could weight candidates by
  the LOC touched in the corresponding module.
- **TestRail Section ID is not currently exported.** Section renames
  break the mapping by name. The TestRail admin should add Section ID to
  the export to make rename detection robust. Until then, `align.py`
  will fall back to fuzzy name match and case-ID set overlap.
- **Nimbus feature flag state in production is opaque to this system.**
  A change in `nimbus-features/` is flagged as a risk, but the recommender
  doesn't know whether the affected flag is on or off in production. The
  QA team should cross-check Nimbus rollout status manually.
- **`align.py` is not yet implemented.** Drift findings are surfaced in
  the report and to `pending_mapping_review.yaml` (in the recommender's
  inline drift check), but the interactive curation tool is still to be
  built.
- **The deterministic fallback ranker is intentionally crude.** It exists
  to keep the pipeline from failing closed, not to replace the LLM. When
  the LLM is unavailable, the fallback sorts candidates by sub-suite and
  automation status, truncates to the release-specific budget ceiling,
  and assigns P1 to manual-only tests and P2 to the rest. No release-
  specific reasoning, no narrative sections — just a ranked list.

---

## Project layout

```
test-recommender/
├── README.md                              ← this file
├── requirements.txt                       ← pinned deps
├── section_to_module_mapping.yaml         ← human-curated config
├── recommend.py                           ← release pipeline (working)
├── budget_calculator.py                   ← per-release test budget (Phase 2)
├── candidate_scorer.py                    ← deterministic pre-filter (Phase 3)
├── git_pr_extractor.py                    ← git-first PR resolver (ready for CI)
├── (align.py — planned, not yet in repo)  ← interactive curation
├── metrics_baseline.md                    ← measured cost/latency/overlap
├── tests/                                 ← unit tests (78 tests across 3 modules)
│   ├── test_budget_calculator.py
│   ├── test_candidate_scorer.py
│   └── test_git_pr_extractor.py
├── scripts/
│   └── count_prompt_tokens.py             ← Anthropic count_tokens helper
├── .gitignore                             ← excludes secrets, outputs, backups
└── release_report_<tag>.md                ← generated per run (gitignored)
```

External inputs:

- TestRail export: `testrail_export_ios.xlsx` (not versioned — supplied by
  the operator; refresh from your TestRail instance before each release run).
- GitHub: `mozilla-mobile/firefox-ios`, accessed via `gh` CLI.
- Anthropic API: models are configurable via env vars (see the Setup
  section); defaults are Sonnet 4.6 for rerank and Sonnet 5 for synthesize.

---

## Roadmap

1. **Now**: move `recommend.py` into a GitHub Action triggered by
   `workflow_dispatch(from_tag, to_tag)`. The Action clones `firefox-ios`
   locally and uses `git diff` / `git log` (instead of the truncated
   GitHub compare API), and integrates `git_pr_extractor.py` for
   API-free PR resolution. This removes the 300-file hard cap on the
   compare endpoint and eliminates ~281 API calls per major release.
2. **Then**: validate the recommender against 2-3 historical releases.
   Compare the system's `Suggested manual tests` list against what QA
   actually executed and the bugs found after the release. Feed findings
   back into the rerank prompt.
3. **Then**: implement `align.py` — the interactive mapping-curation
   tool. Target design:

   ```
   INPUT: testrail_export.xlsx, mapping.yaml
     │
     ├─ 1. Diff TestRail sections vs YAML sections.
     │     · For each new section: LLM proposes mapping using the section
     │       name, a sample of 5 random test titles + steps from that
     │       section, and the current repo module list.
     │     · For each stale YAML section: attempt rename detection in
     │       this order — fuzzy name match, then case-ID set overlap,
     │       then Section ID once TestRail exports it.
     │
     ├─ 2. Diff repo modules vs YAML references.
     │     · For each new module not referenced: LLM proposes a section.
     │     · For each YAML path that no longer exists: mark stale.
     │
     ├─ 3. Interactive review (CLI prompts):
     │       For each proposal:
     │         [a] accept   [e] edit   [r] reject   [s] skip
     │       Accepted changes are written into mapping.yaml directly
     │       (with a .bak backup); rejected go to
     │       pending_mapping_review.yaml.
     │
     └─ OUTPUT: updated mapping.yaml + pending_mapping_review.yaml
   ```
4. **Then**: ask the TestRail admin to add Section ID to the export.
   Use it as the stable mapping key once available.
5. **Later**: integrate Jira (`FXIOS-NNNNN` enrichment from PR titles)
   and Sentry (recent crashes weight on priority).
6. **Out of MVP scope**: web UI for the QA team to consume reports,
   integration with the release-management workflow, feedback loop
   from executed tests back into ranking.

---
