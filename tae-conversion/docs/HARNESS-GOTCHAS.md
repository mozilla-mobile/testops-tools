# ui/efficiency harness gotchas & authoring checklist

A running catalog of bugs we've hit in the harness core / helpers / primitives, plus the checks that
catch them. Use it two ways: (1) a **review checklist** against new page objects, selectors, and verbs;
(2) a **triage list** when a test fails weirdly — scan here before assuming a product bug.

Each entry: **symptom → cause → check**. Add new ones as we find them; link the Jira/bug where relevant.

Last updated: 2026-08-04.

> The distilled, landed subset of this catalog lives in-tree at
> `<fenix>/app/src/androidTest/java/org/mozilla/fenix/ui/efficiency/docs/gotchas.md`.
> This file runs ahead of it: entries land here first and are folded in-tree once confirmed.
> At the time of writing, in-tree carries A1–A8 and B1–B8; A9–A19 and B9–B13 are here only.

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

### A16. A disabled Compose button accepts the click and drops it (2026-08-03, translations sheet)
- **Symptom:** `mozClick`/`mozClickIfPresent` reports success, nothing happens, and the test fails much
  later at whatever was supposed to follow — e.g. `'Translation bottom sheet translate button' was expected
  to disappear after 25000ms`.
- **Cause:** a Compose button rendered with `enabled = false` still receives the click gesture; only
  `onClick` is skipped. `mozClick` resolves and clicks — it never asserts actionability — so "clicked" in
  the report means "the gesture was delivered", not "the app acted on it".
- **Check:** for any control whose enabled state is driven by async work (a fetch, a detection), gate on
  enabled before clicking. Confirm the gate actually blocks: a real gate takes measurable time. See A17 for
  why the obvious gate silently does not.

### A17. An enabled-check on a COMPOSE_BY_TEXT selector is a no-op (2026-08-03)
- **Symptom:** a wait-until-enabled gate returns in ~30 ms and the click is still dropped (A16).
- **Cause:** `COMPOSE_BY_TEXT` resolves on the unmerged tree, which yields the *text node inside* the
  button. Disabled semantics live on the button, so the text node reports enabled while the button is not.
- **Check:** use `COMPOSE_BY_TEXT_MERGED` for anything you interact with rather than merely read —
  it resolves the button itself. A gate that returns in tens of milliseconds is the tell.

### A18. A failed attempt's HomeActivity blocks the retry's launch (2026-08-03, bug 2060347)
- **Symptom:** the retry never runs its steps; it dies after 45 s with
  `Could not launch intent … HomeActivity within 45000 milliseconds`, naming HomeActivity instead of
  whatever actually failed.
- **Cause:** the previous attempt's `HomeActivity` is still RESUMED when the retry rule relaunches (the
  activity rule's teardown has not finished it). `HomeActivity` is `launchMode="singleTask"`, so the intent
  goes to the existing instance and `MonitoringInstrumentation` never sees a new activity reach RESUMED.
- **Check:** `BaseTest` now finishes every non-destroyed activity between attempts. When a retry dies at
  activity launch, log `ActivityLifecycleMonitorRegistry.getActivitiesInStage()` for every `Stage` in the
  catch block before theorising — it names the resident activity in one run. Note a leftover *custom tab*
  is harmless; the next test launches over one fine.

### A19. ESPRESSO_BY_ID cannot address framework ids (2026-08-03)
- **Symptom:** `IllegalArgumentException` (not "element not found") the moment a selector resolves, e.g. on
  the "Later" button of the secure-your-cards system dialog.
- **Cause:** `ESPRESSO_BY_ID` looks the name up in the *app's* `R.id`, so `android:id/button2` cannot
  resolve at all.
- **Check:** for platform/system-UI ids use `UIAUTOMATOR_WITH_RAW_RES_ID` with the fully-qualified id
  (`android:id/button2`, `com.android.systemui:id/notification_stack_scroller`).

### B12. Compose's waitUntil raises a Throwable, so `catch (e: Exception)` misses it (2026-08-03)
- **Symptom:** a helper with a retry loop does not retry; the first timeout escapes.
- **Cause:** `ComposeTimeoutException` extends `Throwable` directly, not `Exception`.
- **Check:** retry loops around `composeRule.waitUntil` must catch `Throwable`.

### B13. A helper that opens a system window must close it on the failure path (2026-08-03, bug 2060345)
- **Symptom:** one failure inside the notification shade turns every later step — and the retry — into an
  unrelated error; Espresso cannot even dump (`has-window-focus=false`).
- **Cause:** the shade holds window focus, and `openNotificationTray()` left it open when its verify threw.
- **Check:** wrap the post-open verification, close on the failure path, then rethrow the original error.
  Confirm the close rather than assuming it: `pressBack()` does dismiss the shade, but a close helper should
  re-probe and escalate (`pressHome()`) rather than trust it.

---

## A. Known harness bugs (continued — 2026-08-04, DownloadFileTypesTest conversion)

### A20. A click can resolve, report success, and do nothing (inert text twin) (2026-08-04)
- **Symptom:** `mozClick` logs `[OK] ✔ Clicked '<x>'` in ~100 ms and the UI does not change. No exception —
  the failure surfaces later as a timeout on whatever should have appeared. Same shape as A16, different
  cause.
- **Cause:** the text you matched sits on a different node than the click action, and the node you hit is
  not merely disabled — it is not interactive at all. Each link on the downloads test page is a clickable
  node with `desc="Download <file>"` PLUS a sibling text node carrying the same string and no click action;
  a `textContains` match lands on the twin. A17 is the Compose-side instance of this (unmerged text node
  inside a button); this entry is the device-side one, in web content.
- **Check:** for a CLICK target prefer a handle owned by the interactive node — testTag, then
  content-description. The on-failure ScreenDump marks interactive nodes `[clickable]`: if your target
  prints without it, you are aiming at the twin. Watch the dump's `(N nodes with a handle, of M total)`
  line too — the interactive parent is often among the hidden ones, having no text of its own.

### A21. A Compose click can resolve the right node and still not actuate it (2026-08-04)
- **Symptom:** an on-screen Compose button does not respond to `mozClick`, whichever text strategy is used.
  Seen on the download dialog's confirm button (a `FilledButton` with no testTag in
  `RenameAndChangeLocationDialogContent.DialogActionButtons`).
- **Cause:** NOT root-caused. What is established: `COMPOSE_BY_TEXT`, a purpose-built
  `hasText and hasClickAction`, and `COMPOSE_BY_TEXT_MERGED` all resolved a node and reported a successful
  click while the dialog stayed open; a device-level `UiObject2` tap worked immediately. Given A16/A17 the
  leading explanation is timing rather than injection path — the button is briefly disabled while the
  dialog settles, Compose resolves and clicks within ~150 ms and the gesture is dropped, whereas the
  device-level query is slower and lands after it is enabled. That was not verified: no enabled-state
  gate was tried on this dialog.
- **Check:** before reaching for a different injection path, gate on enabled per A16 — a real gate takes
  measurable time. If gating fixes it, fold this entry into A16 and delete it.

### A22. `UiObject.click()` returns false for SLOW controls, not just missed ones (2026-08-04)
- **Symptom:** `AssertionError: Failed to click UiObject` on an element that is present and was tapped.
- **Cause:** `UiObject.click()` is `clickAndSync`, which reports failure when no window update arrives
  within ~5.5 s. Anything triggering a network round-trip (starting a download) can exceed that. A dump at
  one such failure showed the target holding input focus — the tap had landed, and the surrounding retry
  then reloaded the page and discarded a dialog that was on its way.
- **Check:** use a `UIAUTOMATOR2_*` strategy for slow-reacting controls; `UiObject2.click()` injects the
  gesture and lets the caller wait. Read `Failed to click UiObject` as "no window update in time", not as
  proof the click missed.

### A23. `mozSwipeTo` cannot scroll to a `UiObject` (2026-08-04)
- **Symptom:** `mozSwipeTo` returns immediately without swiping, and the following click fails anyway.
- **Cause:** its visibility test for a `UiObject` is `element.exists()`, already true for a node that is in
  the hierarchy but scrolled off-screen — so it "succeeds" on attempt 0. The Compose and Espresso branches
  check actual display; the UiObject branch does not.
- **Check:** don't rely on `mozSwipeTo` for UiObject-based selectors. Worth fixing to check visible bounds.

### A24. effloop can finish without a `run-report.txt`, silently disabling effverify (2026-08-04)
- **Symptom:** `effverify` returns `{"ok": false, "error": "no run-report.txt (did it compile/run?)"}` for a
  run that plainly executed, and `status.json` says `"ran": false` while listing per-test results.
- **Cause (root cause FIXED 2026-08-12):** the `effpretty capture` step produced no report. `effloop.sh`
  invoked it as `$TOOLS/effpretty.py`, but effpretty lives **in-tree** under
  `ui/efficiency/devtools/effpretty/` — so it only ever resolved for checkouts that happened to have a local
  copy or symlink beside the script, and silently did nothing everywhere else. effloop now resolves it under
  `$REPO` (override with `EFFPRETTY=`), falls back to `$TOOLS`, and exits 2 with a named error if neither
  exists rather than producing an empty report. The consequence beyond effverify was worse: the
  on-failure ScreenDumps never reach `raw-run.log` either, so diagnostics look absent when they are merely
  unrouted. This is what led me to conclude "mozClick does not dump on click failure" — it does,
  `BasePage.kt:478`.
- **Check:** if `run-report.txt` is missing, take the verdict from `status.json` (the folded JUnit XML) and
  read dumps straight off the device with `adb logcat -d -s EffScreenDump:I`. logcat rotates — grep the
  whole buffer rather than tailing it.

## B. Authoring / review checklist (continued — 2026-08-04)

### B14. Serving a page from mockWebServer can change which dialog the app shows (2026-08-04)
- **Why:** replacing the remote downloads page with the local `downloadPageAsset` made localhost return a
  `content-length`, so Fenix rendered the KNOWN-SIZE download dialog —
  `RenameAndChangeLocationDialogContent`, with a rename field and a differently-composed confirm button —
  instead of the unknown-size variant. The test went from 5/9 to 0/9 on that change alone, and four device
  runs went into debugging a failure the change had introduced.
- **Check:** switching a test from a remote page to a local asset changes the system under test, not just
  its reliability. Re-run immediately and compare against the previous baseline; if results get worse,
  suspect the switch before suspecting the code under test. Both dialog variants ship in the product, so a
  selector verified against one is not verified against the other.

### A25. Re-loading a *different* URL on `BrowserPage` needs `forceNavigation = true` (2026-08)
- **Symptom:** a second `on.browserPage.navigateToPage(otherUrl)` silently does nothing; you stay on the
  previous page and a later content assertion fails confusingly.
- **Cause:** `navigateToPage` early-returns when `mozIsOnPageNow()` is true, and BrowserPage's arrival anchor
  is `ENGINE_VIEW`, which is present for ANY loaded page.
- **Check:** every browser navigation after the first passes `forceNavigation = true`. Only the first load
  from Home/AppEntry can omit it. (`verifyPageContentWithReload` / `clickDownloadLink` already do this.)

### A26. `mozVerifyElementIsChecked` / `IsNotChecked` are single-shot — they race a data bind (2026-08)
- **Symptom:** ~1/50 on Firebase, "expected checked, got unchecked" on a checkbox the fragment does check.
- **Cause:** unlike `mozVerify`, these do ONE read with no polling. Native `MaterialCheckBox` rows inflate
  unchecked and get their real state a beat later; `navigateToPage` can confirm arrival on a bottom-of-screen
  anchor before the rows above finish binding.
- **Check:** poll any state a UI action or bind updates asynchronously (checked/selected/enabled/text).
  Prefer a page-object-local retry wrapper (`verifyCheckBox(selector, checked)`, deadline 5s / poll 250ms)
  over hardening the shared BasePage verb — a framework-primitive change used by 20+ call sites needs its own
  justification, not a drive-by inside a conversion.
- **Triage:** classify a Firebase failure by DURATION first — a "failure" far faster than the test's real
  runtime (20-30s vs 45-70s) is infra (device offline, install), not your assertion.

### A27. `UiObject.click()` also returns false for a DISMISS tap with no window change (augments A22)
- **Symptom:** "Stay in Firefox" on the applinks sheet throws `Failed to click UiObject`, while "Open in App"
  on the SAME sheet passes.
- **Cause:** `UiObject.click()` is `clickAndSync` — it reports false when no window-content-update arrives.
  Dismissing a sheet and staying put produces no new window; launching another app does.
- **Check:** for any button whose only effect is closing an in-app dialog/sheet, use a `UIAUTOMATOR2_*`
  (UiObject2) strategy — its click injects the gesture without gating on the sync. Never read
  `Failed to click UiObject` as proof the tap missed.

### A28. Chaining breaks at the FIRST `moz*` verb, even with the covariant override (2026-08)
- **Symptom:** `navigateToPage().mozVerifyElementIsNotEnabled(...).myHelper()` fails with
  `Unresolved reference`, although the page DOES declare the covariant `navigateToPage` override.
- **Cause:** every `moz*` verb returns `BasePage`, so a page-specific helper after one is off a `BasePage`
  receiver. The override only fixes the first hop.
- **Check:** bind a local val when interleaving — `val p = on.page.navigateToPage(); p.mozVerify...(); p.myHelper()`.
  effcheck passes on this; only effbuild catches it.

### A29. `navigateToPage` self-corrects a stale `PageStateTracker` — use it to re-anchor (2026-08)
- After an imperative page-object helper that changes screens without touching the tracker (e.g. a save that
  `popBackStack()`es to a different fragment), call `on.<actualScreen>.navigateToPage()`: it checks
  `mozIsOnPageNow()` FIRST and, if already there, re-syncs the tracker with zero navigation instead of trying
  to BFS from the stale origin. Subsequent `navigateToPage`s then route correctly.

### A30. BFS can pick a DESTRUCTIVE equal-length edge out of an edit surface (2026-08)
- **Symptom:** navigating to Settings from the search bar opened a browser tab and corrupted the back-stack,
  so a later "Navigate up" chain landed on GeckoView instead of Home.
- **Cause:** BFS chose `SearchBarComponent -> BrowserPage` (steps `EnterText(url) + PressEnter`); the box still
  held the typed term, so PressEnter SUBMITTED it. A stateful edge is a landmine when the field has residual text.
- **Check:** hop through a neutral page first (`on.home.navigateToPage()`) rather than letting BFS route out of
  an edit surface. Structurally: give edit surfaces an explicit non-destructive outbound edge —
  `SearchBarComponent -> HomePage` via `NavigationStep.PressBack` was added for this and makes the route
  length-1, so BFS prefers it.

### A31. Awesomebar suggestions are asserted as a COLLECTION by tag (2026-08)
- Each row carries testTag `mozac.awesomebar.suggestion` (singular; the container is plural `...suggestions`).
  Displayed: `mozVerifyAnyContainsText(COMPOSE_BY_TAG "mozac.awesomebar.suggestion", term)`. Absent:
  `mozVerifyNoneContainText(same, term)` — note it passes VACUOUSLY when there are zero suggestion nodes, which
  is exactly the "suggestions off" case, so pair it with a positive control.
- effcheck's "literal testTag not found in app source" WARN is a false positive for tags defined in
  android-components (outside `--app-root`).

### A32. Below-the-fold Settings entries need a `Swipe` nav step, and `mozSwipeTo` to assert (2026-08)
- Preference screens are RecyclerViews that recycle off-screen rows out of the hierarchy, so `mozVerify` alone
  (it does not scroll) fails on an entry below the fold. Use
  `on.settings.navigateToPage().mozSwipeTo(BTN).mozVerify(BTN)`, and put a `NavigationStep.Swipe(BTN)` before
  the `Click` on the `Settings -> sub-page` edge.

### A33. Compose sliders: drive with `mozSetSliderValue`, not a swipe (2026-08)
- New `BasePage.mozSetSliderValue(selector, value)` uses `performSemanticsAction(SemanticsActions.SetProgress)`.
  A synthetic swipe can only land on whatever step the gesture geometry hits; SetProgress asks for the exact
  value. Compose-tag selectors only.

### A34. Espresso `Intents` works in efficiency tests for free (2026-08)
- `BaseTest` runs on `HomeActivityIntentTestRule`, which extends `IntentsTestRule` (auto `init()/release()`),
  so a page object can assert `intended(hasAction(...))` with no per-test setup. This unblocks converting any
  legacy test that used `intended(...)` — e.g. the default-browser role request
  (`"android.app.role.action.REQUEST_ROLE"`).

### A35. `SwitchPreferenceCompat` state is NOT readable with `mozVerifyElementIsChecked` (2026-08)
- The Switch is a *cousin* of the title text, not the title node. Keep the legacy Espresso
  `hasCousin(allOf(withClassName(endsWith("Switch")), isChecked()))` in a page-object helper. Two flavours:
  toggles with no stable id (match by class) and ones with `R.id.switch_widget` (match by id). Page objects
  legitimately hold Espresso here.
- Corollary: do not trust pre-existing stub selectors. `USE_SYSTEM_FONT_SIZE_TOGGLE` referenced an espresso id
  that does not exist on the real `SwitchPreferenceCompat` screen — effcheck's B-check had flagged it and it was
  never verified.

### A36. A Compose Checkbox with no tag or content-description leaves only a sibling index (2026-08)
- The Manage Shortcuts `LazyColumn` renders each engine row with a bare `Checkbox`. No `SelectorStrategy`
  expresses "checkbox that is a sibling of text X", so the faithful port is the legacy device call:
  `mDevice.findObject(UiSelector().text(name)).getFromParent(UiSelector().index(i)).click()`.
- **Check:** keep index-fragile device interactions as page-object helpers, NEVER as a shared BasePage verb.

### A37. effverify scored a CRASH-mode failure as passed — a false green (2026-08-12, FIXED)
- **Symptom:** a class run whose `status.json` said `outcome=fail, failures=1` came back from
  `effverify --json` as `{"ok": true, "clean": true, "failed_total": 0}`, with the failed test listed as
  `"passed"`. `effloop_exit` was correctly `1`. The failing test was
  `scanQRCodeToOpenAWebpageTest`, killed by `IllegalArgumentException: CaptureRequest contains unconfigured
  Input/Output Surface!` from `QrFragment`.
- **Cause:** the test died from an uncaught exception rather than a failed assertion, so the report contains
  **no `failed:` marker** and the gradle log line does not say `FAILED`. effverify built its failed-set from
  those two signals only and fell through to "appeared in `started:` and not otherwise flagged -> passed".
  The tell in the JSON is `"gradle": null` on a test reported as passed. This is the same fall-through the
  2026-08-03 fix closed for assertion failures; crashes survived it.
- **Fix:** effverify now also reads the report's own `FAILURES (n of m)` header (which names each failed test)
  and any `CRASH:` line inside a single-test block, and adds an `unattributed_failures` backstop: if the
  declared failure count exceeds what it can pin to a name, it reports NOT DONE instead of guessing. Verified
  against 7 real batches with no regressions.
- **Check:** never take effverify alone as the done-gate. Read `status.json` (`outcome`, `failures`) next to it,
  and if `effloop_exit` is non-zero while effverify says clean, believe the exit code.

### A38. `mach lint` and every Gradle task serialize on one lockfile, and a killed run leaves it stale (2026-08-12)
- **Symptom:** `A failure occurred in the android-format linter` with
  `filelock._error.Timeout: The file lock 'objdir-frontend/gradle/mach_android.lockfile' could not be
  acquired`, and `0 fixed` — which reads like a linter bug but is pure contention. Two concurrent
  `mach lint` runs, or a lint started while an effwatch test run is building, will do this to each other.
- **Cause:** `tools/lint/android/lints.py` wraps every gradle invocation in a `SoftFileLock` on
  `mach_android.lockfile`. Being a *soft* lock, the file's existence IS the lock, so SIGTERM-ing a lint leaves
  it behind and every later run waits out the timeout for nothing.
- **Check:** run one at a time; never lint while a queued conversion run is in flight. After killing a lint,
  `rm -f objdir-frontend/gradle/mach_android.lockfile`.
- **Also:** `./mach lint <path>` on Kotlin selects `android-lint` too, which runs `:fenix:lintDebug` over the
  whole module and takes ~10+ minutes; the path argument cannot narrow it, because the Android linters are
  wired per Gradle module rather than per file. Use `-l android-format` (ktlint + detekt only), or skip mozlint
  altogether with `./mach gradle :fenix:ktlint :fenix:detekt`. Note gradle caches those tasks — an `UP-TO-DATE`
  run prints nothing and looks clean; add `--rerun-tasks` when you need certainty. `./mach format` (spotless)
  does NOT catch the ktlint rules that fail the gate, e.g. `no-consecutive-blank-lines` and `standard:kdoc`.

### A39. An arrival check can be satisfied by an element BEHIND an overlay (2026-08-12)
- **Symptom:** `navigateToPage` reports arrival on a page the test never reached, and the run fails several
  steps later somewhere unrelated. Cost 5 device cycles on one conversion before the test was parked, then
  landed in 2 once the dumps were read.
- **Cause:** `requiredForPage` selectors resolve on nodes that are still in the tree underneath a modal
  surface. Two confirmed cases: `BrowserPage`'s `ENGINE_VIEW` resolves under the addressbar's edit-mode
  overlay, and `HomeSelectors.HOMEPAGE_VIEW` resolves under the search overlay while the toolbar is covered.
- **Check:** after any query submit, `mozWaitUntilAbsent(SearchBarSelectors.TOOLBAR_IN_EDIT_MODE)` before the
  next hop. When backing out to a page, anchor on something that is genuinely occluded — `MAIN_MENU_BUTTON`,
  not `HOMEPAGE_VIEW` — or the loop returns while you are still covered and the next `navigateToPage` takes a
  destructive edge (for HomePage that is the "New tab" click).

### A40. `mozLongClick` is not held long enough for a View-based list row (2026-08-12)
- **Symptom:** a long press on a history row silently behaves as a TAP: the item opens in the browser, and the
  next step's "More options" click then hits the browser's main menu instead of a multi-select toolbar. The
  dump gives it away — the Compose tree starts at `ADDRESSBAR_URL_BOX`.
- **Cause:** `UiObject.longClick()` uses UiAutomator's default press duration, which this row treats as a tap.
- **Check:** select the row with an **Espresso** strategy (e.g. `ESPRESSO_BY_TEXT`) so `mozLongClick` goes
  through Espresso's `longClick()`, which honours the platform long-press timeout. This is what the legacy
  robots rely on.

### A41. `COMPOSE_BY_TEXT` reports an AMBIGUOUS match as "not found" (2026-08-12)
- **Symptom:** `mozVerify` fails with "not found after 5000ms" for text that is plainly on screen.
- **Cause:** the strategy resolves through the singular `onNodeWithText`, which throws when more than one node
  matches; `mozVerifyElement` swallows that and degrades to `false`. Two sponsored tiles, two identical
  captions, and the verb says the text is absent.
- **Check:** use `COMPOSE_BY_TEXT_SUBSTRING` (`onAllNodesWithText(...).onFirst()`) when duplicates are
  possible, or scope to a container with `COMPOSE_ON_ALL_NODES_BY_TAG_WITH_CHILD_TEXT_ON_FIRST`.

### A42. A caption is not unique to the surface you are testing (2026-08-12)
- **Symptom:** an absence assertion for the "Sponsored" label can never come true on the homepage, even with
  sponsored top sites disabled and visibly gone.
- **Cause:** the Pocket sponsored *story* further down the homepage carries its own "Sponsored" identifier
  (`pocket.sponsoredContent.identifier`). A bare text match hits it.
- **Check:** scope the selector to the tile
  (`COMPOSE_ON_ALL_NODES_BY_TAG_WITH_CHILD_TEXT_ON_FIRST` on `top_sites_list.top_site_item` + the caption).
  Note the tile root is a plain `Box` that does not merge descendants, so a tag-only text query cannot see the
  caption either.

### A43. Revoking a runtime permission is not enough to reset a "don't ask again" (2026-08-12)
- **Symptom:** a permission-dialog test passes on the first attempt and fails on BaseTest's retry, looking for
  a Deny button that never appears — because the OS auto-denies with no dialog at all.
- **Cause:** "Deny and don't ask again" sets `FLAG_PERMISSION_USER_FIXED`, which `pm revoke` leaves in place.
  Legacy gets away with it only because the orchestrator wipes package data between test *methods*; a retry
  runs in the same process.
- **Check:** in the test, `pm clear-permission-flags <pkg> <permission> user-fixed user-set` **and**
  `pm revoke <pkg> <permission>`. Do **not** use the device-wide `pm reset-permissions` — it strips permissions
  the instrumentation itself relies on and crashes the test process.
