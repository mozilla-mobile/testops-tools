# test-exploratory-agent — Claude Code guidance

Context for **Claude Code** (the CLI assistant) when working on this codebase.

**This is not the system prompt for the runtime agent.** The runtime
agent's prompt is *composed per platform* by `_build_system_prompt()` in
`agent/loop.py`. If you're changing what the agent *does at runtime* —
action schema, JSON output contract, decision heuristics — edit that
function (and `AgentDecision`), not this file. See
[Where the runtime agent's rules live](#where-the-runtime-agents-rules-live).

For end-user documentation (how to run the agent, CLI options, platforms
supported), see `README.md`.

---

## What this project is

Autonomous exploratory QA agent for Firefox mobile (iOS + Android).
Uses Anthropic Claude for reasoning and Appium for device control.

Single supported entry point: `python agent/loop.py --objective "..."`.

---

## Architecture

`agent/` — runtime modules:

| Module | Purpose |
|---|---|
| `loop.py` | Main perception → reason → act loop. Entry point. Owns the prompt builder, the `AgentDecision` schema and the CLI. |
| `perception.py` | Screenshot + accessibility tree parsing (handles iOS and Android formats) |
| `actions.py` | Appium interactions: tap, swipe, type, rotate, background, etc. |
| `reporter.py` | Session JSON, per-session `bugs_<id>.md` and `coverage_<id>.json`, crash-safe flush every 5 steps |
| `memory.py` | Cross-session persistence (features tested, bugs confirmed, patterns) |
| `knowledge.py` | Platform-specific rules injected into LLM prompt (zero-cost, file reads) |
| `cost.py` | `CostTracker` + `TrackedClient` — every LLM call auto-recorded with a `purpose` tag. Tracks **tokens only**; USD isn't tracked here (see the module docstring). |

Supporting:

- `config/appium_caps.py` — device capabilities, iOS/Android auto-detection
- `setup_check.py` — preflight environment check (Python deps, Appium, API key, Xcode/adb). Run before the agent.
- `scripts/analyze_costs.py` — CLI aggregation over past sessions
- `scripts/build_dashboard.py` — self-contained interactive HTML dashboard
- `tests/` — 118 pytest tests over the pure modules (`actions`, `appium_caps`, `cost`, `knowledge`, `loop`, `memory`, `perception`, `reporter`). No device or network needed.
- `knowledge_base/{ios_firefox,android_firefox,android_car}/` — per-platform Firefox rules

---

## Conventions

- **Language**: code, inline comments, and documentation in English.
- **Tests**: run `pytest tests/` before committing changes to `agent/`. All 118 must pass.
- **LLM calls MUST go through `TrackedClient.messages_create(purpose=..., ...)`** — never construct a raw `anthropic.Anthropic()` client. This is what keeps token tracking accurate and complete.
- **Exception handling**: prefer specific exceptions (`WebDriverException`, `anthropic.APIError`, `NoSuchElementException`, `ET.ParseError`). Broad `except Exception:` is acceptable only in best-effort cleanup blocks (screen recording, video save, memory update in `finally`).
- **Timeouts**: `TrackedClient` sets `timeout=30s` on the Anthropic client. Do not raise this without a documented reason.

---

## Gotchas — read before editing

- **Session artifacts contain PII**. `reports/session_*.mp4`, `reports/session_*.json`, `reports/bugs_*.md`, `reports/coverage_*.json`, `reports/dashboard.html*`, and `reports/screenshots/` are gitignored on purpose. Do not `git add reports/` blindly.
- **Nothing under `reports/` is tracked, including `agent_memory.json`** — it accumulates one operator's session history and unverified bug titles against specific app builds. This closes H2 from the security review and makes the README's "every installation starts with empty memory" claim true. The whole directory is created at runtime (`reporter.py:67`, `memory.py:130`, `perception.py:61`), so a fresh clone has no `reports/` at all and `memory.load()` returns an empty structure. Don't re-add a seed file: "first run" is the correct state for a new install.
- **Memory is single-writer-safe, not multi-writer-safe.** `memory.save()` uses `tempfile.mkstemp + os.replace` so the on-disk file is never left JSON-corrupt even under concurrent writes. But concurrent sessions read → modify → write can lose updates (last writer wins at the semantic level). Assume sequential usage; for parallel CI, isolate each worker's `reports/` directory.
- **Prompt injection is open on `--objective`**. Safe in CLI-only mode. Any new interface exposing this input to non-operator users (Slack bot, web UI, ticket automation) must sanitize input **at that boundary**, not inside `loop.py`.
- **Navigation is the one injection-resistant boundary.** `--allowed-domains` enforces a host allowlist for `type_url` **in Python**, after the LLM has decided — so injected page content cannot talk the agent into navigating off-list. Keep new navigation paths behind that same check; a rule added only to the prompt is not an enforcement point. Default is unrestricted (exploratory testing needs URL freedom), so CI pipelines should set it explicitly.
- **Exit codes are a CI contract**, even though no pipeline lives in this repo yet:

  | Code | Meaning |
  |---|---|
  | 0 | Session completed; nothing worth failing on under the active `--fail-on` |
  | 1 | Session completed; a **High** bug was recorded (`--fail-on high`) |
  | 2 | Session completed; a **Critical** bug was recorded (`--fail-on critical` or `high`) |
  | 3 | **The agent crashed.** Infrastructure failure, not a finding — fires on any `--fail-on`, including `never` |

  The 1/2/3 split is the point: a crash must never be readable as "found a High bug". Keep `never` as the default (exploratory findings are informational, not blocking) and keep crash reporting outside the `exit_code_for()` range. A consumer should treat 3 as "the run is invalid, ignore the report".
- **Legacy files were deleted** and should not be reintroduced: `main.py`, `agent/explorer.py`, `agent/vision.py`, `config.py` (flat file, distinct from `config/` package), `drivers/appium_driver.py`. Old backup files (`agent/loop_noscreenshot.py`, `agent/loop_screenshots.py`, `agent/loop_old.py`) also removed. Single entry point remains `agent/loop.py` — don't add a parallel copy of the loop "just to try something", it always outlives the experiment.
- **Dashboard is XSS-hardened via DOM API**. When adding a column to `scripts/build_dashboard.py:renderTable`, the `render()` callback must return a DOM `Node` built via `document.createElement()` + `.textContent` — never an HTML string with interpolated values. See existing `sevBadge()` and `sessionLink()` helpers.
- **The agent has a budget cap** (`--max-tokens`, default `2_000_000`). Don't remove this default without discussion — it's the safety net against runaway sessions. USD isn't tracked in-code (see `agent/cost.py` header); for $ billing use the Anthropic console.
- **Android knowledge base is intentionally minimal** (`knowledge_base/android_firefox/firefox_android.md`). Do not treat this as complete — H5 is pending. Contributions welcome.
- **Knowledge base files carry YAML frontmatter** (`app`, `bundle_id`/`package`, `last_verified` date). It's manual + best-effort — no CI captures the specific build/commit, and there's no staleness warning. The frontmatter is *documentation for humans*: not parsed by `agent/knowledge.py`, not consumed programmatically. When editing a knowledge file, bump `last_verified` to today's date and add a `notes:` line if something material changed (menu layout drift, new accessibility IDs, etc.). `_load_sections` only extracts `##`/`###` headers so the frontmatter never leaks into the LLM prompt.

---

## Where the *runtime agent's* rules live

Everything about what the agent should DO at runtime (action schema, JSON
output, bug reporting format, stuck detection, escape strategies) lives in
one of three places — pick the right one:

| Layer | Where | Use it for |
|---|---|---|
| Prompt | `_build_system_prompt()` in `agent/loop.py` | What the LLM is *told*: heuristics, bug-report format, when to stop. Advisory — the model can ignore it. |
| Schema | `AgentDecision` (pydantic v2) in `agent/loop.py` | What the LLM is *allowed to emit*: field types, coercion, clamping. Rejects malformed output before it reaches Appium. |
| Behavior | the rest of `agent/*.py` | What actually *happens*: allowlists, budget cap, retries, escape strategies. The only real enforcement point. |

Two details that are easy to get wrong:

- **The prompt is per-platform.** `_available_actions(platform)` picks universal + iOS-only or Android-only actions, so the LLM is never offered `press_back` on iOS. Add a new action to the right tuple *and* to `_PARAMS_BLURB`, or it won't appear in the schema.
- **The module-level `SYSTEM_PROMPT` constant is a back-compat snapshot** of the iOS variant, kept for existing imports and tests. The running agent uses `self._system_prompt`, built at connect time. **Editing the constant does not change agent behavior** — edit `_build_system_prompt()`.

A rule that must hold (not just be suggested) belongs in the schema or in
Python, never in the prompt alone.

**This CLAUDE.md file is not read by the runtime agent.** Adding rules
here about "when to report a bug" or "what action to take" has no effect
on agent behavior — those must go into one of the three layers above.
