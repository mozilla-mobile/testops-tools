---
name: testcase-reviewer
description: Audit criteria for reviewing a generated test-case CSV — requirements traceability and gap analysis, redundancy elimination, technical/tooling standards, TestRail formatting, and coverage caps / scope exclusions. Loaded by the testcase-reviewer agent as its core audit engine.
argument-hint: "[feature_name (e.g., onboarding, checkout, etc.)]"
---

# Reviewer Skills & Audit Criteria

This document defines the core cognitive skills and technical standards that the
`testcase-reviewer` must enforce when evaluating test cases.

**Audit dimensions**

| § | Dimension | Question it answers |
|---|---|---|
| [1](#1-requirements-traceability--gap-analysis-functional-audit) | Requirements Traceability & Gap Analysis | Is anything missing? |
| [2](#2-business-sufficiency--de-duplication-optimization-audit) | Business Sufficiency & De-duplication | Is anything redundant? |
| [3](#3-technical-validation--tooling-standards) | Technical Validation & Tooling Standards | Are the technical steps executable? |
| [4](#4-formatting--testrail-best-practices-audit) | Formatting & TestRail Best Practices | Will it import and read correctly? |
| [5](#5-coverage-caps--scope-exclusions-hard-limits) | Coverage Caps & Scope Exclusions | Does it exceed a hard limit, or test something excluded? |

---

## 1. Requirements Traceability & Gap Analysis (Functional Audit)

- **Missing Scenarios:** Identify any missing positive paths, negative paths,
  error handlings, or edge cases by comparing requirements to the CSV.
- **State Persistence & Interruptions:** Ensure there are explicit tests
  verifying state persistence after app kill/relaunch, background/foreground
  transitions, and device restarts where applicable.
- **iPad/Tablet Coverage:** Only expected when the feature behaves differently
  on tablets. If the requirements indicate tablet-specific behavior, verify
  dedicated `[iPad]` tests or notes exist; if the feature is identical on iPhone
  and iPad, an "iPad specific" folder should NOT be present (flag it as
  unnecessary if it is).

---

## 2. Business Sufficiency & De-duplication (Optimization Audit)

- **Coverage Sufficiency:** Validate that the scenarios are business-sufficient,
  covering critical user journeys, target personas, and high-risk business
  logic.
- **Redundancy & Over-testing Elimination:** Actively hunt for and merge
  redundant test cases. If two tests validate the exact same functional outcome
  with minor, non-critical UI variations, combine them or flag the duplicate.
  Keep the test suite lean, high-yield, and focused on unique failure modes.

---

## 3. Technical Validation & Tooling Standards

If the feature interacts with any APIs, network requests, or external web links,
audit the technical steps strictly against these standards.

### A. API Client Validation (Postman)

- Ensure step-by-step execution instructions (e.g., *"Step 1: Open request X,
  Step 2: Replace Y..."*) are provided.
- Verify there are concrete JSON payload examples (for success and edge cases
  like empty fields, special characters, invalid tokens).
- Verify expected response codes (e.g., `200 OK`, `201 Created`,
  `400 Bad Request`) and key schema properties to verify.

### B. Network Traffic Interception (Proxyman / Charles Proxy)

- Verify the test instructs the tester on how to filter traffic (e.g.,
  `api.domain.com`) and exactly which parameters to inspect in the JSON payload
  (e.g., *"Verify that `device_type` payload is set to `iOS`"*).
- Ensure there are clear instructions on using *Map Local* or *Breakpoints* to
  modify responses on-the-fly to validate UI error states.

### C. Simulating Backend Failures & Mocking (Mockoon)

- Ensure mock configurations are provided for hard-to-reach backend errors
  (500, 403, 504 timeouts).
- Verify that the exact mock JSON structures and routing rules are present.
- Provide instructions on how to set route delays (e.g., 15 seconds) and how to
  redirect local device traffic.

### D. Public Testing & Validation Links

Whenever external web tools are needed, suggest actual, industry-standard free
tools instead of generic placeholders.

---

## 4. Formatting & TestRail Best Practices Audit

- **CSV Columns:** Verify the CSV has exactly these 8 columns, in order:
  `Section (Folder)`, `Title`, `Preconditions`, `Steps`, `Expected Results`,
  `Priority`, `Type`, `Sub Test Suite(s)`.

- **Priorities:** Verify every case uses one of `Critical`, `High`, `Medium`,
  `Low`, applied per the severity definitions below. Flag priorities that don't
  match the described risk.

  | Priority | Severity |
  |---|---|
  | `Critical` | merge-blocking |
  | `High` | possible release blocker |
  | `Medium` | "live with it for now" |
  | `Low` | cosmetic / edge case |

- **Sub Test Suite(s):** Verify the column is populated on every case and
  follows the tagging rules below. Flag missing or mismatched tags.

  | Source | Tag |
  |---|---|
  | Base (every case) | `Special Case` |
  | Priority `Critical` | `Smoke & Sanity` |
  | Priority `High` | `Regression` |
  | Priority `Medium` | `Functional` |
  | Priority `Low` | `Exploratory` |
  | `Accessibility` folder | `Accessibility` |
  | `Localization` folder | `L10n` |
  | `Telemetry` folder | `Telemetry` |

- **Step-by-Step Indexing:** Check that every single action step has a perfectly
  matching indexed Expected Result (e.g., Step `1. Tap X` → Expected Result
  `1. Verify Y is shown`).

- **Vague Expectations:** Flag and correct any lazy expected results (e.g.,
  *"Works correctly"*, *"Screen is displayed correctly"*). Replace them with
  precise, observable UI and system behaviors.

- **Approved QA Verbs:** Ensure steps strictly use the approved QA verbs: `Tap`,
  `Long press`, `Observe`, `Verify`, `Navigate to`, `Enable`, `Disable`,
  `Close`, `Reopen`. Flag any instances of "click" or "press".

---

## 5. Coverage Caps & Scope Exclusions (HARD LIMITS)

These mirror the hard limits the `testcase-generator` works to (its **Step 4**).
A suite that exceeds a cap, or contains an excluded case, is defective —
**flag every violation as a proposal**, and say which cap it breaks.

Count the rows per section before judging, and report the counts.

| Area | Hard limit | Flag when |
|---|---|---|
| Feature flags / secret settings | **0 cases** | any case tests a flag value, a Nimbus/experiment variant, activation from secret/debug settings, or a "feature disabled" state |
| Accessibility | **2 cases** | the folder holds more than one Dynamic Text case plus one VoiceOver case, or an a11y case goes beyond the happy path |
| Telemetry | **1 case**, 2 at most | the folder holds more than 2 cases, or events/metrics/fields are split across cases instead of steps |
| iPad specific | **0 cases** unless tablet behaviour differs | the folder exists without evidenced tablet-only behaviour (this is the same rule as §1's iPad/Tablet Coverage) |
| Error handling | grouped | separate cases exist per status code where the expected outcome is identical |

**Detail per area:**

- **Feature flags and secret settings.** The feature is assumed enabled and
  correctly configured in the environment under test; enabling it belongs in
  Preconditions, never in a case. Propose deleting any such case. If the
  requirements describe flag behaviour, it belongs in the manifest as out of
  scope, not in the CSV.
- **Accessibility.** Exactly one Dynamic Text case and one VoiceOver case,
  happy path only — no a11y error states, no edge cases, no per-screen
  variants. A third case is acceptable only when the happy path genuinely
  cannot be completed in one flow **and** the manifest justifies it; if the
  justification is absent, flag it. An explicit a11y spec in the requirements
  (reading order, traits, presentational elements) should be folded into these
  two cases, not spread across a case per rule.
- **Telemetry.** One case, with each telemetry entry as its own indexed step
  and an expected result naming exactly what must be recorded. A second case is
  acceptable only when one genuinely cannot express it (for example
  consent-gated events needing a different app state). Never a case per event,
  per bucket, or per field.
- **iPad.** Cases are device-agnostic by default — the same case should pass on
  iPhone and iPad. `[iPad]` cases and the "iPad specific" folder are warranted
  only for genuine, evidenced exceptions (a different presentation, a different
  layout threshold, tablet-only behaviour). Where only a detail differs, prefer
  a note on the existing case over a duplicate tablet case.
- **Error handling.** Failures that share a trigger and an expected outcome
  belong in one case as separate indexed steps — e.g. `404` and `402` (or
  `500` / `503`) in a single case, one step per code. Separate cases are correct
  only when the expected behaviour genuinely differs (e.g. offline shows a retry
  affordance but `500` does not). This is the consolidation counterpart to §2's
  redundancy audit.
