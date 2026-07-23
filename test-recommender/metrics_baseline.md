# Metrics: baseline and phased optimization

> **Snapshot from 2026-07-13.** Concrete numbers below reflect the Anthropic
> SDK, model, and prompt state at the time of measurement. Ratios and
> qualitative findings are more durable; specific token counts and cost
> figures will drift with model / pricing / prompt changes. Treat as a
> historical reference for the design decisions, not a live benchmark.

This document captures two things:

1. The **baseline** measurements of the system before the Phase 1-3
   optimizations (sections 0.1–0.3 below).
2. The **actual results** after each phase, alongside the original targets
   (see "Original targets and actual results" and "Phase-by-phase evolution"
   further down).

The baseline was measured against the `firefox-v151.2 → firefox-v151.3`
release (minor, 282 files, 48 commits, 47 PRs kept after low-impact
filtering). Every optimization was validated against this same release
pair on the same day, three runs each for statistical stability.

---

## 0.1 — System prompt sizes vs cache threshold

Anthropic ephemeral prompt caching requires ≥1024 tokens in the cached block.
Measured with `client.messages.count_tokens(...)` on `claude-sonnet-4-6`.

| Prompt | Tokens (count_tokens) | Actual behavior in production log | Cacheable in production? |
|---|---:|---|---|
| `SYSTEM_PROMPT_RERANK` | 785 | `cache_write=1087` (protocol overhead pushes it over) | YES (by accident) |
| `SYSTEM_PROMPT_SYNTHESIZE` | 954 | `cache_write=0` | **NO** |

**Finding:** synthesize prompt is 70 tokens short of the effective cache
threshold in production. Rerank is under the count_tokens number too, but wire
protocol overhead (~300 tokens for tool/schema metadata) accidentally pushes it
over 1024, so it does cache.

**Action item for Phase 1.4 — RESOLVED:** Extended `SYSTEM_PROMPT_SYNTHESIZE`
with concrete section examples and style samples. Now cacheable in production
(see the "Synthesize prompt cacheable" row of the results table further down).

---

## 0.2 — Variability across identical runs

Three independent runs of `recommend.py` with identical inputs
(v151.2 → v151.3, same TestRail export, same mapping, same model, same day).
Each returns 47 ranked test IDs.

### Pairwise overlap of returned test IDs

| Pair | Intersection | Union | Jaccard | Overlap-of-smaller |
|---|---:|---:|---:|---:|
| run1 vs run2 | 28 | 66 | **42.4%** | 59.6% |
| run1 vs run3 | 27 | 67 | **40.3%** | 57.4% |
| run2 vs run3 | 29 | 65 | **44.6%** | 61.7% |

### Consensus and spread

| Metric | Value |
|---|---:|
| Tests common to all 3 runs | **23** (49% of any single run's output) |
| Tests that appeared in ≥1 run | **80** |
| Tests that appeared in only 1 run | ~30 |

**Finding:** the LLM oscillates significantly between runs. Only ~49% of the
returned set is stable. This means:

- QA sees a substantially different set of "recommended tests" on each run.
- Trust erodes ("why is C3897624 P0 today but not last release?").
- ~30 of the 47 tests per run are effectively "coin-flip picks" from a wider
  pool of near-equivalent candidates.

**Action items — RESOLVED (with partial success on the overlap target):**
- Phase 1.1 (`temperature=0`) applied. Combined with Phase 3, the actual
  overlap reached 64% Jaccard, not the 95% originally targeted. Cloud LLM
  residual non-determinism sets a ceiling well below 95%; see the
  phase-by-phase table further down.
- Phase 3 (pre-filter deterministic top-K) applied as planned. Candidate
  pool shrunk from ~999 to ~280 via a deterministic score field embedded
  in the prompt.

---

## 0.3 — Cost per run

Pricing model (Sonnet 4.6, as of run date):

| Rate | $/million tokens |
|---|---:|
| Regular input | 3.00 |
| Cache write (1.25×) | 3.75 |
| Cache read (0.1×) | 0.30 |
| Output | 15.00 |

### Token usage per run

| Stage | Metric | Run 1 | Run 2 | Run 3 |
|---|---|---:|---:|---:|
| Rerank | input | 43226 | 43229 | 43211 |
| Rerank | cache_write | 1087 | 1087 | 0 |
| Rerank | cache_read | 0 | 0 | **1087** |
| Rerank | output | 2047 | 2024 | 2009 |
| Synth | input | 9447 | 9345 | 9276 |
| Synth | cache_write | 0 | 0 | 0 |
| Synth | cache_read | 0 | 0 | 0 |
| Synth | output | 6259 | 5753 | 5681 |

Run 3 saw cache_read on rerank because it fired within 5 minutes of run 2 —
the ephemeral cache window. This confirms caching works in principle, but the
5-min TTL is too short for the weekly release cadence (releases are days
apart, cache always expires between them).

### Cost per run

| Run | Rerank | Synth | Total |
|---|---:|---:|---:|
| Run 1 | $0.164 | $0.122 | **$0.287** |
| Run 2 | $0.164 | $0.115 | **$0.279** |
| Run 3 | $0.160 (cache hit) | $0.113 | **$0.273** |

**Average: ~$0.28 per release report.**

The cache-read saving on Run 3 was only ~$0.004 because the cached block is
tiny (1087 tokens). Even if we made caching work perfectly, the ceiling of
savings from *this* cache mechanism is ~1% of run cost. Real cost reduction
must come from Phase 3 (pre-filter reduces input tokens by ~30k) and Phase 1.3
(Haiku instead of Sonnet for rerank).

---

## Original targets and actual results

Targets set optimistically before implementation. Actuals measured after each
phase on the same v151.2 → v151.3 minor release (3 runs each, same day).

| Metric | Baseline | Target | Actual after Phase 3b |
|---|---:|---:|---:|
| Cost per run | $0.28 | ~$0.05 | ~$0.24 (14% cheaper) |
| Overlap between identical runs (Jaccard) | 42% | ≥95% | **64%** |
| Tests common to N runs | 23 (49% of run) | ≥45 (≥95%) | **46 (70% of run)** |
| Rerank input tokens | 43k | ~10k | **15k** (65% smaller) |
| Synthesize prompt cacheable | No | Yes | **Yes** |

**Honest reflection:** the 95% overlap target was unreachable with cloud LLMs.
The 64% we hit reflects the ceiling imposed by Anthropic's residual
non-determinism. The 46 stable tests (out of 67) is a substantive improvement
over baseline's 23 — QA trust should be measurably better.

The single biggest lever was Phase 3b's prompt instruction on how to use the
`score` field: +9.4pp Jaccard from one prompt change. This was found only
because the user asked "shouldn't we re-measure after changing the prompt?"
after the initial Phase 3 measurement was declared done. **Every prompt
change is a behavior change and must be validated with fresh runs** — added
as a project principle.

## Phase-by-phase evolution (Jaccard, common tests)

| Phase | Config | Jaccard | Common | Counts |
|---|---|---:|---:|---:|
| Baseline | Sonnet 4.6, no temp, budget 25-50 | 42.4% | 23 | 47/47/47 |
| Phase 1 | + temp=0 | 48.5% | 25 | 48/49/47 |
| Phase 2 | + budget 40-70 (adaptive) | 52.4% | 37 | 65/67/63 |
| Phase 3 | + pre-filter 989→280, score in payload | 54.7% | 38 | 63/67/67 |
| Phase 3b | + prompt instruction on how to use score | **64.1%** | **46** | 65/67/69 |

---

## Reproducing these measurements

The individual report files from the runs above are gitignored and not
included in this repo. To reproduce the measurements:

- **Section 0.1** (system prompt sizes vs cache threshold):
  run `python3 scripts/count_prompt_tokens.py`. The script imports the
  prompts from `recommend.py` and asks Anthropic's `count_tokens` endpoint
  for the authoritative token count.

- **Sections 0.2 and 0.3** (variability + cost):
  run `python3 recommend.py --verbose ...` three consecutive times against
  the same release pair on the same day with identical inputs. Extract
  token usage from the stderr telemetry (see README "Verbose output"
  section) and compute Jaccard overlap between the three ranked test-ID
  sets. The reports themselves are not versioned; only their contents
  matter.

- **Phase-by-phase table**: reproducing this requires running the pipeline
  against the same release pair after each incremental code change
  (temperature, budget, pre-filter, prompt tuning). The commit history of
  `recommend.py` shows the sequence of changes.
