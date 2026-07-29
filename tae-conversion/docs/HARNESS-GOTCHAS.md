# ui/efficiency harness gotchas & authoring checklist

A running catalog of bugs we've hit in the harness core / helpers / primitives, plus the checks that
catch them. Use it two ways: (1) a **review checklist** against new page objects, selectors, and verbs;
(2) a **triage list** when a test fails weirdly — scan here before assuming a product bug.

Each entry: **symptom → cause → check**. Add new ones as we find them; link the Jira/bug where relevant.

Last updated: 2026-07-28.

> The distilled, landed subset of this catalog lives in-tree at
> `<fenix>/app/src/androidTest/java/org/mozilla/fenix/ui/efficiency/docs/gotchas.md`.
> This file runs ahead of it: entries land here first and are folded in-tree once confirmed.
> At the time of writing, in-tree carries A1–A8 and B1–B8; A9–A15 and B9–B11 are here only.

---

## A. Known harness bugs (things that have actually bitten us)

### A1. Local-only opaque crash / StrictMode penaltyDeath on any failure
- **Symptom:** a test that should report a clean assertion failure instead dies with an opaque
  StrictMode `penaltyDeath` crash — but only locally on a real device; passes on Firebase.
- **Cause:** Espresso's `DefaultFailureHandler` captures a screenshot on failure; that bitmap copy trips
  Fenix's StrictMode `penaltyDeath` and kills the process before the real error surfaces.
- **Check:** `BaseTest.setUp()` installs `Espresso.setFailureHandler(DefaultFailureHandler(appContext, false))`
  (screenshot capture off). Never swap this for a broad `StrictMode.setVmPolicy` relaxation.

### A2. A presence/verify probe that throws feeds the crash path
- **Symptom:** navigation polling or an "is this present?" check crashes instead of returning false;
  can also trigger A1.
- **Cause:** a presence primitive threw instead of degrading to `false`.
- **Check:** `mozVerifyElement` and every presence probe used by `mozIsOnPageNow`/`mozWaitForPageToLoad`
  are wrapped try/catch → return `false`, never throw. Any NEW verb built on `resolve()` must keep this.

### A3. Compose merged-vs-unmerged tree trap (regressed twice)
- **Symptom:** a text/content-desc selector suddenly finds 0 nodes → "element not found" → many tests
  navigating via that label fail at once (e.g. all Bookmarks tests via the "Bookmarks" menu item).
- **Cause:** querying the wrong Compose semantics tree. Many labels exist only in the UNMERGED tree;
  `onNodeWithText(value)` defaults to merged and returns nothing. Both regressions were this.
- **Check:** when migrating a verb onto `resolve()`, PRESERVE each strategy's proven primary tree exactly
  (text = unmerged; tag/content-desc = merged) and add the other tree only as fallback. `resolve()` now
  tries both and picks the *displayed* match — keep that behavior.

### A4. Any shared-resolution change touches all ~185 tests
- **Symptom:** a small tweak to `resolve()`/`mozGetElement` breaks a large, uniform swath of tests.
- **Cause:** every verb funnels through shared resolution.
- **Check:** full efficiency-suite run before trusting ANY shared-resolution change. Reading the shape of
  the failure tells you the class: a systematic selector break fails hundreds *uniformly*; flakiness is
  *scattered* across unrelated pages. Don't re-tune shared resolution on an unconfirmed hypothesis.

### A5. `BaseTest.isRetryable()` is too broad (MTE-5729)
- **Symptom:** a genuinely failing test shows "0 failed" because the 1 retry passed, or a real bug is
  masked as flakiness.
- **Cause:** `isRetryable()` retries `AssertionError`/`RuntimeException`/`NullPointerException` — nearly
  everything.
- **Check:** when diagnosing, remember 1 retry can turn a real red into green. Tightening the retry scope
  is tracked as MTE-5729.

### A6. Page-arrival timeouts are the most common failure shape
- **Symptom:** `navigateToPage` → `mozWaitForPageToLoad` can't find a page's `requiredForPage` anchor
  within 10s.
- **Cause:** usually timing/flakiness (slow arrival), sometimes a wrong/absent anchor selector,
  sometimes the screen genuinely isn't there (wrong launch/state — see A8).
- **Check:** `ScreenDump` now fires on `navigateToPage` failure. Use it to separate "selector wrong
  (element is in the dump)" from "screen wrong (element absent / wrong page)". Capture with
  `adb logcat -c` then `adb logcat -d -s EffScreenDump:I`.

### A7. Duplicate/pager node matches ("expected 1, found N")
- **Symptom:** a click/verify by text throws because several composed nodes share the label.
- **Cause:** a `HorizontalPager` (e.g. onboarding cards) composes adjacent pages at once, so shared button
  text ("Not now"/"Continue") matches multiple nodes.
- **Check:** for text shared across simultaneously-composed nodes, use a per-instance `testTag`, or rely
  on `resolve()`'s displayed-match pick. Prefer stable handles over shared text.

### A8. An overridable config hook whose resolved value isn't actually used
- **Symptom:** you add a per-case/per-run config override (e.g. `BaseTest.launchConfig()`) and it looks
  wired, but behavior never changes — the run uses the default.
- **Cause:** the construction site computed the resolved config (`val cfg = launchConfig()`) but still
  passed the original fixed fields to the thing being configured —
  `HomeActivityIntentTestRule(skipOnboarding = skipOnboarding, …)` instead of `cfg.skipOnboarding`. The
  override is dead code.
- **Check:** when you introduce an overridable hook, grep the construction site and confirm *every*
  argument reads from the resolved value, not the old field. (Hit 2026-07-22 wiring the reachability
  `LaunchConfig`; onboarding kept launching with `skipOnboarding=true` until the args were switched to
  `cfg.*`.)

---

## B. Authoring & review checks for new code

### B1. A new page object can NEVER have an empty navigation path  ← onboarding bug, 2026-07-22
- **Why:** the Reachability factory **auto-registers every page object** (it discovers them by reflection
  over `PageContext` via `PageCatalog`) and generates a "can I reach this page?" case for each. A page
  with no reachable path — empty/absent `NavigationRegistry` steps AND no handling for a special launch —
  produces a reachability case that always fails.
- **What happened:** `OnboardingPage` registered `AppEntry → OnboardingPage` with `steps = listOf()`. The
  reachability run launches with the harness default (`skipOnboarding = true`), so onboarding never shows,
  so the `requiredForPage` anchor (ToU card title) is never found → the generated case fails.
- **Check for every new page object:**
  - It registers at least one `NavigationRegistry` edge with real steps that reach it from `AppEntry`
    (directly or transitively), **or**
  - if it only exists under a special app launch (e.g. onboarding), it declares a `LaunchConfig` on its
    `AppEntry` edge. The Reachability factory now threads that config per case and launches the activity
    with it, so the page is genuinely reached — not skipped.
  - Never leave `steps = listOf()` on the only edge into a page without one of the above.
  - Note: Pairs can't vary launch per case, so special-launch pages are excluded from Pairs only.

### B2. Selectors live in the catalog, not in page objects
- **Why:** a `Selector(...)` defined inline in a `pageObjects/*.kt` escapes the `selectors/*Selectors.kt`
  catalog and the migration ledger, and won't be found by tooling that scans the catalog.
- **Check:** `grep -rn "SelectorStrategy\." pageObjects/` returns nothing. Selectors that need a runtime
  value become a parameterized catalog function `fun NAME(x): Selector` (see B4). (Fixed 2 instances as
  PW-2, MTE-5722.)

### B3. A selector `value` must not be blank
- **Why:** `resolve()` returns `null` for a blank value. Parameterized selectors with a default `""` used
  for group registration can silently resolve to nothing when accidentally called without an argument.
- **Check:** don't conflate group registration with matching via a blank-valued call; a selector used to
  match must always receive a real value.

### B4. Parameterized selector functions stay pure (no presentation logic)
- **Why:** a `fun NAME(s: String) = Selector(value = s, …)` is the idiomatic Kotlin "template" and is
  fine. The smell is functions that rebuild the app's rendered text (plurals, `HtmlCompat`, hardcoded
  English like `"$count selected"`) — that couples the catalog to i18n/formatting and is fragile.
- **Check:** a parameterized selector fun should be a single `Selector(...)` expression whose `value` is
  the parameter. If it computes a resource/plural/HTML string, prefer a stable handle (tag/res-id) instead,
  or move the string derivation to a labels layer. Track such funcs to tech-debt, not the migration.

### B5. Selector authoring priority (stable handles over text)
- **Why:** text matches break on localization and duplicate nodes (A7).
- **Check (in order):** Compose `testTag` → resource id → content-description → text (only as last resort,
  always via `getStringResource(...)`). Derive the handle from the app UI source, not from how a legacy
  robot happened to match.

### B6. New verbs go through `resolve()` and keep the guarantees above
- **Check:** a new interaction/verification verb resolves via `resolve()` (not a fresh `when(strategy)`
  block), preserves per-strategy tree semantics (A3), never throws from a presence check (A2), and is
  validated with a full-suite run (A4).

### B7. Nav entry/arrival selectors must cover EVERY runtime state (2026-07-23, bit us twice)
- **Why:** a screen's arrival signal or entry control can change with app state. (1) RecentlyClosed's
  `requiredForPage` was the empty-state view — absent once the list is populated, so populated tests
  couldn't confirm arrival. (2) The UnifiedTrustPanel entry button's testTag depends on page security:
  `SITE_INFO_SECURE` vs `SITE_INFO_UNSECURE` vs `SITE_INFO_UNKNOWN` — the secure-only edge never opened
  the panel on an http page.
- **Check:** `requiredForPage` must be an element present in ALL states (e.g. a toolbar title, never an
  empty-list placeholder). A nav edge whose entry control is state-dependent must `ClickIfPresent` every
  variant. effcheck can't see this — verify by hand whenever you build/modify nav.

### B8. Test-class boilerplate (now enforced by effcheck MWS/IMP)
- A test class using `mockWebServer` must declare `private val mockWebServer get() = fenixTestRule.mockWebServer`
  — `BaseTest` does not expose it. (effcheck: MWS)
- `TestAssetHelper` members (`getGenericAsset`, `enhancedTrackingProtectionAsset`, …) must be imported even
  when called on a receiver (`mockWebServer.getGenericAsset(...)`). (effcheck: IMP)
- `navigateToPage()` returns `BasePage`: chain only `moz*`/BasePage methods off it. Call a page-specific
  method on the page object on its own line — UNLESS that page overrides `navigateToPage` with a covariant
  return type (e.g. BrowserPage), in which case chaining its own methods is fine. (compile error otherwise)

## A. Known harness bugs (continued)

### A9. A blocking system overlay masquerades as "element not found" (stylus-handwriting prompt) (2026-07-27, AddressAutofill)
- **Symptom:** a `moz*` step fails with "element not found" even though the target is on screen; often the
  web content nodes also "vanish" from the tree at the same moment. Seen converting AddressAutofillTest:
  after tapping the `streetAddress` web field the autofill "Select address" prompt never appeared.
- **Cause:** on devices with stylus handwriting enabled (Android 14+), focusing a text field raises an OEM
  dialog **"Try out your stylus"** in a SEPARATE window that covers the page and suppresses the app's own
  prompt. Its dismiss control is res-id `closeButton` with text/desc "Cancel" (its `button2` is *"Next"* —
  a wrong guess to dismiss). It is NOT in the app's Compose tree, so the Compose ScreenDump can't see it.
- **Check:** blocking overlays are handled centrally — `OverlayRegistry` lists them (presence + dismiss
  selectors) and `BasePage.dismissKnownOverlaysIfPresent()` clears them; `mozClick`/`mozVerify` now call it
  automatically on a locate miss and retry once. For web-form tests, also disable the prompt deterministically:
  `settings put secure stylus_handwriting_enabled 0` before touching a field. Add new overlays to the registry.

### A10. On-failure dump was Compose-only — blind to the overlay that caused the failure (2026-07-27)
- **Symptom:** the auto ScreenDump on a failed step showed only app chrome / Compose nodes, so an overlay,
  system dialog, or soft keyboard sitting ON TOP (the actual cause) was invisible — you couldn't tell
  "selector wrong" from "target covered/focus stolen" without a second, hand-driven run.
- **Cause:** `BasePage` only called the Compose `ScreenDump.dump()`; the app is mixed-layer (Compose +
  legacy Views + system windows), and Compose semantics see none of the latter.
- **Check:** `ScreenDump.dump()` now emits ALL layers on failure — Compose, a **window/focus summary**
  (`dumpWindows`: window titles/types, IME/overlay flags, and the currently focused input), UIAutomator, and
  Espresso. When a locate fails, scan the `[windows]` block first: a non-APPLICATION window on top ⇒ overlay/
  popup/keyboard covered the target (see A9); focused-input elsewhere ⇒ focus was stolen.

## B. Authoring / review checklist (continued)

### B9. Web-form autofill tests need stylus disabled + autofill state cleared between retries
- **Why:** (1) the stylus prompt (A9) blocks the field tap that triggers autofill; (2) saved autofill data
  persists across the RetryTestRule's attempts (only bookmarks/session/tabs were cleared), so a first-attempt
  failure leaves an address that changes the Autofill settings layout and makes the *retry* fail differently
  (e.g. "Add address" pushed off-screen) — masking the real result.
- **Check:** `BaseTest` now deletes all saved autofill addresses in the per-attempt cleanup. Web-form-autofill
  page helpers disable stylus handwriting before focusing a field. OPEN: even with both, the address-autofill
  *suggestion* did not surface on the test device — see CONVERSION-LESSONS "Open gaps" (autofill-not-offered);
  root-cause (dropdown-set country/state vs a genuine trigger/timing issue) still to be confirmed.

---

## A. Known harness bugs (continued — 2026-07-28, stack review pass)

### A11. `mozVerify` and `mozClick` do not resolve selectors the same way (2026-07-28)
- **Symptom:** a selector that works with one verb fails with the other, on the same screen, with no
  indication why. Cost a full debug cycle on the trust-panel and search-placeholder selectors.
- **Cause:** two different resolution paths. `mozClick` → `resolve()` → `resolveComposeNode()`, which tries
  the **merged tree, then falls back to unmerged**. `mozVerify` → `mozVerifyElement()` → `mozGetElement()`,
  which searches **only the tree the strategy's branch happens to name** — for Compose
  content-description that is the merged tree, with no fallback. Adding a strategy to one path and not the
  other compiles fine and fails at runtime (this is how COMPOSE_BY_TAG_AND_TEXT shipped half-wired; the
  exhaustive-`when` compile error in `mozGetElement` is what caught it).
- **Check:** when adding a `SelectorStrategy`, wire it into BOTH `resolveComposeNode()`'s `candidates()` and
  `mozGetElement()`'s `when`. There are three `when (selector.strategy)` blocks in BasePage; two have an
  `else` and will silently ignore a new value. Only `mozGetElement`'s is exhaustive.

### A12. `shouldUseExpandedToolbar` RELOCATES controls — a working selector can become unfindable (2026-07-28)
- **Symptom:** three ToolbarTest failures, all "element not found", all in tests that had passed before the
  launch flag was enabled for that class.
- **Cause:** the expanded toolbar is not a restyle, it moves controls between surfaces and changes what
  handles they expose. Confirmed from a `dumpAll` of the browser view:
  - **tab counter** → moves into the bottom `navigation_bar` and exposes **no testTag at all**, only
    `desc="Non-private Tabs Open: N. Tap to switch tabs."` So `TABS_COUNTER`-tag selectors cannot match.
  - **Bookmark page** → moves OUT of the main menu into the nav bar, so a Compose content-description
    lookup inside the menu finds nothing (legacy's `itemWithDescription` still resolves it device-wide).
  - **search placeholder** → in edit mode the hint is a **text node**; `ADDRESSBAR_SEARCH_BOX` carries no
    content-description whatsoever.
- **Check:** any selector used by a class that sets `shouldUseExpandedToolbar = true` must be verified in
  THAT layout, not assumed from the default one. Prefer a device-level content-description
  (`UIAUTOMATOR_WITH_DESCRIPTION_CONTAINS`) for controls that move — it resolves in both layouts, which a
  testTag cannot when the tag does not exist. See `ToolbarSelectors.TAB_COUNTER_ANY_LAYOUT`.

### A13. Duplicate NavigationRegistry edges are silent, and the loser is invisible (2026-07-28)
- **Symptom:** fixed the selector on a `BrowserPage -> TabDrawerPage` edge, re-ran, got a **byte-identical**
  failure naming the selector I had just replaced.
- **Cause:** that edge is registered TWICE — in `BrowserPage.kt` and in `TabDrawerPage.kt`. Nothing warns at
  registration, and the failure output does not say which registration supplied the step, so a "fix" to the
  wrong one looks like the fix simply didn't work.
- **Check:** before editing a nav edge, grep for `to = "<TargetPage>"` across `pageObjects/` — do not assume
  the edge lives in the page it targets. Filed on MTE-5688: `register()` should reject or loudly log a
  duplicate from->to pair.

### A14. Group verification short-circuits, so it names only the FIRST missing element (2026-07-28)
- **Symptom:** `Not all elements in group 'browserViewMainMenuItems' are present` — and after fixing the one
  element the per-selector log named, the same error returned for a different element.
- **Cause:** `mozVerifyElementsByGroup` is an `all {}`, which stops at the first `false`. The remaining group
  members are never probed, so one run tells you about exactly one missing element.
- **Check:** expect to iterate once per missing member, or read the ScreenDump (now emitted — A15) and check
  the whole group against it in one pass.

### A15. A dev tool in `efficiency.devtools` runs on Firebase (2026-07-28)
- **Symptom:** none visible — the tests passed. `InteractiveInspectTest#inspect` polls a trigger file for
  **30 minutes** and then passes, so it consumed a Firebase device slot on every TAE run silently.
- **Cause:** `mobile/android/test_infra/flank-configs/fenix/arm-tae-tests.yml` lists
  `- package org.mozilla.fenix.ui.efficiency.devtools` as a test target. Anything with an `@Test` in that
  package runs in CI, regardless of intent — a `// DEV ONLY — do not add to CI shards` comment enforces
  nothing.
- **Check:** gate dev-only methods on `assumeFalse("dev tool, not a CI test", isTestLab())`. Do NOT use
  `@Ignore`: it also blocks running them by hand from Android Studio or `-P…class=…#method`, which is the
  only way these tools are meant to be used.

---

## B. Authoring / review checklist (continued — 2026-07-28)

### B10. Carry over EVERY legacy assertion explicitly — implicit checks do not count (2026-07-28)
- **Why:** `navigateToPage()` silently asserts the `requiredForPage` group, which makes it tempting to drop a
  legacy `verifyPageContent`/`verifyUrl` as redundant. A review of the smoke-conversion stack found **17**
  assertions dropped this way across 6 of 13 conversions. The tests still passed — what gets dropped is
  usually the *payload* assertion (does the right page/content/count appear), not the navigation, so the
  test keeps verifying that it got somewhere without verifying what.
- **Check:** diff the legacy body against the port and list every legacy verification; anything missing gets
  added back explicitly, even if it duplicates an implicit check. If the harness genuinely cannot express it,
  document the gap in the test AND the commit message — do not leave it silently absent.

### B11. Content that appears only after async work needs a RELOAD retry, not a longer wait (2026-07-28)
- **Symptom:** `verifyPageContent("social blocked")` fails on the tracking-protection page no matter the
  timeout.
- **Cause:** the page writes its blocked-tracker report once trackers have been processed; if the check runs
  before that, waiting longer on the *current* document never helps. Legacy's
  `verifyTrackingProtectionWebContent` retried each assertion **with a page refresh** for exactly this reason
  — a detail easy to miss when porting, because it lives in the robot, not the test.
- **Check:** use `BrowserPage.verifyPageContentWithReload(url, text)`. When porting, read the legacy *robot*
  helper, not just the test body — retry/refresh semantics hide there.
