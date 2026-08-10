---
name: testcase-generator
description: Analyzes mobile feature requirements and structures a TestRail-importable 8-column CSV document. Triggers when the user asks to generate, create, or write manual test cases for a mobile feature.
argument-hint: "[folder name inside work/inputs/, or custom path to requirements file]"
---

# Generate mobile test cases

Produces a TestRail-importable CSV from requirements provided in
`work/inputs/<feature>/`, written to `work/outputs/<feature>/`. It acts as the
upstream analyzer before spawning the core runner. Obeys
[`standards.md`](../../standards.md).

**Contents**

| Section | Purpose |
|---|---|
| [Critical references](#critical-references) | Files you must read before writing anything |
| [Input & output paths](#input--output-paths) | Where requirements come from, what you must produce |
| [Session reset & context isolation](#session-reset--context-isolation) | Every run starts from scratch |
| [Checkpoint](#checkpoint-runs-inline-before-spawning-the-agent) | Inline gate before the agent is spawned |
| [Generation playbook](#generation-playbook-the-subagent-follows-this) | Steps 1–5, executed by the subagent |

---

## Critical references

> **You must ALWAYS read** `.claude/assets/templates/fifa.csv` as your single
> source of truth for folder hierarchy, naming conventions, writing style, and
> level of detail.
>
> **You must also analyze** any reference screenshots in
> `.claude/assets/templates/layout.png` to understand the expected formatting
> for the layout tests structure.

---

## Input & output paths

Resolve every path from `<feature>` — the folder name given as the argument.
Use the same slug for the output folder and the CSV filename.

**Read (inputs) — never modified:**

| Path | Contents |
|---|---|
| `work/inputs/<feature>/` | The requirements: specs, PRDs, Figma exports, ticket screenshots, telemetry tables. Read **every** file in the folder. |

**Write (outputs) — exactly these two files:**

| Path | Contents |
|---|---|
| `work/outputs/<feature>/<feature>-testcases.csv` | The 8-column TestRail CSV ([Step 5](#step-5--formatting--testrail-best-practices)). |
| `work/outputs/<feature>/manifest.md` | The companion record (below). |

Create `work/outputs/<feature>/` if it does not exist. Use lowercase-hyphenated
slugs for the feature folder and filename (e.g. `tracker-blocking-module` →
`tracker-blocking-module-testcases.csv`).

### What the manifest must contain

`manifest.md` is where everything that is **not** a test case goes. It must
record, at minimum:

- **Requirement → case traceability** — which requirement each case derives
  from, so coverage is auditable.
- **Test design techniques used** — which of the [Step 2 techniques](#2b--test-design-techniques)
  you applied and why they fit this feature, so the coverage rationale is
  auditable.
- **"Example test data (tester aids, not from spec)"** — a section under exactly
  that title listing every suggested value you embedded, flagged as swappable
  for the team's official QA/test-data list
  ([Step 2](#2f--test-data)).
- **Gaps and assumptions** — anything the requirements do not settle, any value
  you could not clarify, and any question that went unanswered or was postponed.
- **Out-of-scope flag behaviour** — feature-flag rules described in the
  requirements, recorded here instead of becoming cases
  ([4.1](#41--never-test-these-at-all)).
- **Justification for a third Accessibility case**, if you added one
  ([4.2](#42--accessibility-exactly-two-cases)).
- **Evidence for each iPad case**, if the folder exists
  ([4.4](#44--ipad-device-agnostic-by-default)).
- **Contradictions found in the sources** — documented, not resolved.

---

## Session reset & context isolation

Run from scratch, every time.

- **Zero-Context Policy:** Every single run of this agent must be treated as a
  completely isolated, stateless session.
- **Forget Prior Context:** Do not persist, carry over, or reference any
  requirements, variables, features, or UI screens analyzed in previous
  executions or chats.
- **No Assumptions:** If a variable, base URL, or requirement is not explicitly
  provided in the *current* input path or prompt, do not guess or reuse old
  ones. Prompt the user or fail gracefully.
- **Fresh State:** Purge all internal memory/cache of previous test scenarios
  before compiling the new CSV.

---

## Checkpoint (runs inline before spawning the agent)

1. **Parse the argument** — Identify the requirements or input path. If empty,
   ask the user for the feature description.
2. **Resolve the feature name** — Extract the feature name to organize output
   paths.
3. **Classify + restate the plan** — Summarize the feature name, platforms in
   scope (iOS/Android), and target paths.
4. **STOP AND WAIT** — Wait for an explicit confirmation ("go") from the user
   before executing.
5. **On confirmation, spawn `testcase-generator`** to execute the playbook
   below.

---

## Generation playbook (the subagent follows this)

### Step 1 — Structure & Hierarchy

Organize the tests into logical folders (`Section` column). Whenever
appropriate, separate tests into categories such as:

| Folder | Constraint |
|---|---|
| Functional | — |
| UI / Layout | — |
| Error handling | — |
| Permissions | if applicable |
| Accessibility | **exactly two cases: one Dynamic Text, one VoiceOver** (see [Step 4](#42--accessibility-exactly-two-cases)) |
| Telemetry | **1 case, 2 at the absolute most** (see [Step 4](#43--telemetry-one-case-one-step-per-event)) |
| iPad specific | **only if the feature behaves differently on tablets** (see [Step 4](#44--ipad-device-agnostic-by-default)). If iPhone and iPad behaviour is identical, do NOT create this folder. |

> **Step 4 caps the size of the Accessibility, Telemetry and iPad folders and
> lists what must never be tested at all. Read it before deciding the
> structure.**

---

### Step 2 — Functional Test Design (Deep Coverage)

Create complete functional coverage including, where applicable.

#### 2.a — Scenario coverage

- **Positive scenarios:** happy path, normal user flows, expected user
  behavior.
- **Negative scenarios:** invalid inputs, interrupted flows, network issues,
  permissions denied, unsupported configurations, edge cases. (Never "feature
  disabled" — see [Step 4's exclusions](#41--never-test-these-at-all).)
- **Consider regression impact:** Fresh install, Existing user, App upgrade,
  App relaunch, Background / Foreground, Kill and relaunch, Device restart.
- **State persistence:** Whenever the feature contains preferences or toggles,
  always verify that the state persists after app restart, browser restart, and
  device restart.
- **Think beyond the specification:** Proactively include test cases for
  unexpected user interactions, interruption scenarios, error handling, and
  recovery flows. If a behavior is reasonably expected from a production-quality
  mobile app, include it. For **functional** coverage, prioritize quality and
  coverage over reducing suite size — but never at the cost of duplication, and
  never in the folders Step 4 caps (Accessibility, Telemetry, iPad).

#### 2.b — Test design techniques

Do not invent cases ad hoc. Derive them with the recognised techniques below,
and **pick the ones that fit the feature** — a settings toggle needs different
techniques from a form or a multi-step wizard. Most features need three or four,
not all nine.

| Technique | What it does | Reach for it when |
|---|---|---|
| **Happy Path Testing** | Tests the expected, successful user flow. *E.g. user logs in with valid credentials and reaches the dashboard.* | Always — every feature gets at least one. |
| **Boundary Value Analysis (BVA)** | Tests values at the edges of allowed input ranges. *E.g. if a password must be 8–20 characters, test 7, 8, 20, and 21.* | Any numeric range, length limit, count threshold, or timeout. |
| **Equivalence Partitioning (EP)** | Groups inputs into valid and invalid classes and tests one representative of each. *E.g. for an age field (18–65), test 25 (valid), 17 and 66 (invalid).* | Inputs with classes of behaviour — pair it with BVA rather than testing every value. |
| **Negative Testing** | Verifies behaviour with invalid or unexpected input. *E.g. invalid email formats, empty required fields.* | Any user-supplied input or externally-supplied data. |
| **Decision Table Testing** | Tests combinations of conditions against expected outcomes. *E.g. discount eligibility by membership type and purchase amount.* | Business rules driven by two or more inputs. |
| **State Transition Testing** | Verifies behaviour as an object changes state. *E.g. Draft → Submitted → Approved → Shipped → Delivered.* | Anything with a lifecycle: toggles, downloads, sessions, order/report status. |
| **Use Case / Scenario Testing** | Builds cases from real user workflows. *E.g. purchase an item, cancel an order, reset a password.* | End-to-end journeys; the backbone of the Functional folder. |
| **Error Guessing** | Uses tester experience to predict likely failure points. *E.g. rapid double-taps, special characters, switching network mid-action.* | Always, as a final sweep — this is where interruption and race conditions come from. |
| **Pairwise (Combinatorial) Testing** | Covers all pairs of input combinations instead of the full matrix. | Many configuration axes (device, OS, language, permissions) where the full cross-product is impractical. |

Name the techniques you used in the manifest, so the coverage rationale is
auditable.

#### 2.c — Testing levels

Cover the pyramid from the bottom up, expressed as a **manual** tester can
execute it:

| Level | In a manual suite this means |
|---|---|
| **Unit** | A single control, field, or element validated in isolation — one toggle, one input's validation, one label. |
| **Integration** | Two or more components working together — a setting that changes another screen, a UI action that produces a network request, data passed between screens. |
| **System** | The feature working end to end inside the whole app, alongside neighbouring features, across app lifecycle and device state. |
| **Acceptance (UAT)** | The real user workflow the requirement describes, validated against the requirement's own wording. |

**Do not duplicate a validation across levels to tick boxes.** Each level exists
to catch a failure the others cannot. If a check is already covered at one
level, do not restate it at another — assert it once, at the lowest level where
it can fail, and let the higher-level case exercise the flow around it. A case
whose only justification is "this level needs coverage too" is redundant and
must not be written.

#### 2.d — Consolidation

- **Group related failures into one case.** Errors that share a trigger and an
  expected outcome belong in the SAME case, as separate indexed steps — not one
  case each. For example, HTTP `404` and `402` (or `500` / `503`) are verified
  in a single "Server error responses" case with one step per code, provided the
  expected UI is the same. Split into separate cases only when the expected
  behaviour genuinely differs (e.g., offline shows a retry affordance but `500`
  does not).

#### 2.e — Technical Recommendations (API, Postman, Proxyman & Mockoon)

For features relying on API interactions or backend integrations, the generated
test cases must contain a highly actionable, beginner-friendly technical
validation section. The instructions must guide the tester step-by-step using
primary free tools (if not available free tools ask for permissions to use other
useful tools):

- **Environment Setup:** Instruct the tester on how to set up the chosen tool.
  For **Postman**, detail environment variable configurations (e.g.,
  `{{baseUrl}}`, auth tokens). For **Proxyman**, provide step-by-step
  instructions to install and trust the SSL certificate on the test device
  (iOS/Android) to decrypt HTTPS traffic. For **Mockoon**, guide the tester on
  setting up a new local environment (port and base route) and starting the
  server.
- **API Client Validation (Postman):** Provide explicit, step-by-step execution
  instructions (e.g., *"Step 1: Open request X. Step 2: In the 'Body' tab,
  replace Y with Z. Step 3: Click 'Send'"*). Include concrete JSON payload
  examples for both successful runs and edge cases (empty fields, special
  characters, invalid tokens), specifying the exact expected response codes
  (e.g., `200 OK`, `201 Created`, `400 Bad Request`) and key schema properties
  to verify.
- **Network Traffic Interception (Proxyman / Charles Proxy):** Guide the tester
  on how to use Proxyman to isolate target traffic (e.g., filtering for
  `api.domain.com`). Write explicit inspection instructions (e.g., *"Check
  'Request -> JSON Text' to verify the `device_type` payload is set to
  `iOS`"*). Provide concrete steps on how to use *Map Local* or *Breakpoints*
  to modify server responses on-the-fly to validate UI error states.
- **Simulating Backend Failures & Mocking (Mockoon):** Instruct the tester on
  how to mock hard-to-reach backend errors (e.g., `500 Internal Server Error`,
  `403 Forbidden`, `504 Gateway Timeout`) or corrupt payloads. Provide the exact
  mock structures or JSON configurations to copy-paste directly into
  **Mockoon**. Explain how to configure route delays (e.g., 15 seconds) to test
  mobile UI resilience, and how to redirect mobile traffic from the staging
  environment to the local Mockoon port.

#### 2.f — Test data

- **Public Testing & Validation Links:** Whenever a test scenario requires
  interacting with external links or web tools to validate a specific behavior
  (e.g., verifying deep links, validating JWT tokens, testing OAuth redirects,
  or checking payment gateways), the agent must suggest highly reliable,
  industry-standard, and free public testing links. Avoid generic placeholders
  like `http://example.com`. Instead, suggest active tools relevant to the
  domain.
- **Concrete example test data (NEVER leave input abstract):** Any scenario that
  depends on specific input data must embed a concrete, ready-to-use example
  directly in the Preconditions and Steps — never ship abstract phrasing like
  "a URL that returns 404 is available" or "a page with an archived version."
  Always give a real value marked as a suggestion, e.g.
  `(e.g., https://httpstat.us/404)`. This applies to URLs, accounts, files,
  search queries, payloads, and any other required data.
  - **Prefer the mockups' own data:** When the scenario relates to a
    screen/flow shown in the provided screenshots, reuse the exact
    domain(s)/values visible there (e.g., if the mock shows `ableton.com`, use
    it) before inventing anything.
  - **Standard free utilities for error/state triggers:** HTTP status & errors →
    `https://httpstat.us/<code>` (`/404`, `/500`, `/503`) with delay via
    `?sleep=<ms>`; TLS/certificate errors → `https://expired.badssl.com`,
    `https://self-signed.badssl.com`, `https://wrong.host.badssl.com`;
    DNS/host-not-found → a non-resolving `.invalid` domain. For domain-specific
    states (e.g., "URL with an archived snapshot"), give a concrete URL plus how
    to confirm it qualifies.
  - **Consistency with evidence-over-invention:** These are explicitly labeled
    *suggested* tester aids, not fabricated requirements — so they do not
    violate the No-Assumptions policy. Record every example value in the
    manifest under a section titled "Example test data (tester aids, not from
    spec)", flagged as swappable for the team's official QA/test-data list.

---

### Step 3 — UI / Layout Test Design (Checklist Mode)

Whenever possible, create dedicated UI/Layout test cases instead of mixing
visual validation into functional tests.

- **UI Checklist:** Explicitly state in the test title that the scope is layout
  validation.
- **UI Checklist:** Each layout test must list all expected UI elements
  explicitly (e.g., Header: AI Controls, Back button, Toggles, Links, Footer
  description, Icons). Never write vague results like "The UI is displayed
  correctly".
- **Matrix Validation:** Include steps that validate the same screen across:
  Light Mode (default) → Dark Mode → Portrait → Landscape → Normal Browsing →
  Private Browsing. (Assume initial precondition is Portrait + Light Mode +
  Normal Browsing.)

---

### Step 4 — Coverage caps & scope exclusions (HARD LIMITS)

These are not suggestions. They override the "prioritize coverage over suite
size" instinct in Step 2. **Exceeding a cap, or writing an excluded case, is a
defect in the suite.**

| Area | Hard limit |
|---|---|
| Feature flags / secret settings | **0 cases** — never tested ([4.1](#41--never-test-these-at-all)) |
| Accessibility | **2 cases** — 1 Dynamic Text + 1 VoiceOver ([4.2](#42--accessibility-exactly-two-cases)) |
| Telemetry | **1 case**, 2 at most ([4.3](#43--telemetry-one-case-one-step-per-event)) |
| iPad specific | **0 cases** unless tablet behaviour differs ([4.4](#44--ipad-device-agnostic-by-default)) |
| Error handling | Grouped, never one case per status code ([4.5](#45--consolidate-error-handling)) |

#### 4.1 — Never test these at all

Assume the feature **is enabled and correctly configured** in the environment
under test. Never write a case for:

- **Feature flag values** — flag ON, flag OFF, flag default, Nimbus/experiment
  variants, or what a user sees when a flag changes.
- **Enabling the feature from secret/debug settings**, developer menus, or any
  internal toggle used to switch the feature on.
- **"Feature disabled"** states of any kind.

Enabling the feature belongs in the **Preconditions** ("the feature is enabled
in the build under test"), never in a test case of its own. If the requirements
describe flag behaviour, note it in the manifest as out of scope — do not turn
it into cases.

#### 4.2 — Accessibility: exactly two cases

- **One case for Dynamic Text** and **one case for VoiceOver**. That is the
  whole folder.
- **Happy path only.** No a11y error states, no edge cases, no per-screen
  variants.
- Each case walks the feature's main flow once with that accessibility setting
  active, asserting the specific expectations (text scales without
  truncation/overlap; elements are announced in the correct order with the
  correct labels/traits).
- Add a third case **only** when the happy path genuinely cannot be completed in
  a single flow — for example the feature has two independent entry points that
  cannot be reached in one pass. If you add one, justify it in the manifest.
- If the requirements supply an explicit a11y spec (reading order, traits,
  presentational elements), fold it into these two cases — do not spawn a case
  per rule.

#### 4.3 — Telemetry: one case, one step per event

- **One test case.** Two only if a single case genuinely cannot express it (for
  example, consent-gated events that require a different app state).
- **Each telemetry entry gets its own indexed step inside that one case** — one
  step per event/metric/field, with the expected result naming exactly what must
  be recorded.
- Never create a case per event, per bucket, or per field.
- Keep the folder small; telemetry breadth belongs in steps, not in row count.

#### 4.4 — iPad: device-agnostic by default

- Tests are **device-agnostic by default** — the same case should pass on iPhone
  and iPad. Write them so nothing in the steps assumes a phone.
- Create the "iPad specific" folder and `[iPad]` cases **only for genuine,
  evidenced exceptions** — a different presentation (e.g., a centred modal
  instead of a bottom sheet), a different layout threshold, or tablet-only
  behaviour.
- If iPhone and iPad behave the same, there is **no** iPad folder and **no**
  `[iPad]` cases. Do not re-run the phone suite on tablet "for completeness".
- When only a detail differs, prefer a note on the existing case over a
  duplicate tablet case.

#### 4.5 — Consolidate error handling

Follow [Step 2's grouping rule](#2d--consolidation): related failures with the
same expected outcome share one case, one step per variant. Do not emit a case
per status code.

---

### Step 5 — Formatting & TestRail Best Practices

When compiling the final rows, strictly adhere to these constraints:

1. **Output Format:** Generate the final output strictly as a Comma-Separated
   Values (CSV) document. Use one row per TestRail test case. Any field that
   contains a comma, double-quote, or line break MUST be wrapped in double
   quotes, with internal quotes doubled (`""`). Adding an example like
   `(e.g., ...)` to a field introduces a comma — re-check that field is quoted.

2. **CSV Columns:** Exactly include these **8** columns, in this order:
   `Section (Folder)`, `Title`, `Preconditions`, `Steps`, `Expected Results`,
   `Priority`, `Type`, `Sub Test Suite(s)`.

3. **Step-by-Step Pairing:** Steps should be concise. Every single step must
   have its own matching Expected Result using clear line indices.

4. **Avoid vague expected results:** Never write "Works correctly", "Screen is
   displayed correctly", or "Everything is visible". Describe exactly what
   should happen.

5. **Reuse navigation:** Avoid repeating unnecessary navigation. Prefer
   "Navigate to Settings > AI Controls" instead of repetitive step paths.

6. **Consistent wording:** Strictly use approved QA verbs: `Tap`, `Long press`,
   `Observe`, `Verify`, `Navigate to`, `Enable`, `Disable`, `Close`, `Reopen`.
   Avoid mixing with click or press.

7. **Test priorities:** Assign one of four priorities, using this definition of
   severity (what happens if the test fails):

   | Priority | If this test fails |
   |---|---|
   | `Critical` | the change **cannot be merged** into the project (merge-blocking) |
   | `High` | it may be a **release blocker** |
   | `Medium` | a "we can live with it for now" issue (non-blocking, should be fixed) |
   | `Low` | cosmetic with no user impact, or an uncommon edge-case scenario |

8. **Scenario grouping:** Test cases should represent complete user scenarios.
   Group related validations into a logical end-to-end scenario whenever it
   makes sense (e.g., onboarding validation, dismissal, and persistence grouped
   together).

9. **No abstract test data:** Every precondition or step that references
   required input (a URL, account, file, query, or payload) must include a
   concrete example value inline, marked `(e.g., …)`. Never deliver a case that
   says "a URL that … is available" without the example (see
   [Step 2 — Concrete example test data](#2f--test-data)).

10. **Sub Test Suite(s):** Every case must populate the `Sub Test Suite(s)`
    column. Combine ALL applicable tags below into one cell, comma-separated
    (quote the cell — it contains commas). Order: base, then priority tag, then
    folder tag(s).

    | Source | Tag |
    |---|---|
    | **Base** (every case) | `Special Case` |
    | Priority `Critical` | also `Smoke & Sanity` |
    | Priority `High` | also `Regression` |
    | Priority `Medium` | also `Functional` |
    | Priority `Low` | also `Exploratory` |
    | **Accessibility** folder | also `Accessibility` |
    | **Localization** folder | also `L10n` |
    | **Telemetry** folder | also `Telemetry` |

    Examples: a High-priority Telemetry case → `Special Case, Regression,
    Telemetry`; a Critical Functional case → `Special Case, Smoke & Sanity`; a
    Low-priority Accessibility case → `Special Case, Exploratory,
    Accessibility`.

11. **Validate before delivering:** After writing the CSV, parse it (e.g.,
    `python3 -c "import csv,sys; rows=list(csv.reader(open(sys.argv[1]))); assert all(len(r)==8 for r in rows), [i for i,r in enumerate(rows) if len(r)!=8]"`)
    and confirm every row has exactly 8 columns. Fix any row that fails before
    reporting the suite as complete.

12. **Verify the Step 4 caps before delivering.** Count the rows per section and
    check every one of these. Fix violations — do not report them as acceptable:

    - **Accessibility = 2 cases** (one Dynamic Text, one VoiceOver). A third
      requires a written justification in the manifest.
    - **Telemetry ≤ 2 cases**, with each telemetry entry as its own step inside
      a case — not as its own case.
    - **iPad specific = 0 cases** unless a tablet-only difference is evidenced
      in the requirements. If the folder exists, the manifest must name the
      evidence for each case.
    - **Zero cases** about feature flags, Nimbus variants, secret/debug
      settings, or "feature disabled" states.
    - **No case-per-status-code** in Error handling — related failures with the
      same expected outcome are grouped.

    Report the per-section counts when you deliver, so the caps are visible.
