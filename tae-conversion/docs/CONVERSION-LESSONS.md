# Conversion lessons — assumption-corrections that should become tooling/skills

Every time a conversion *didn't work first try* and taught me something, it lands here as: **what I
assumed → what was actually true → the reusable rule → tooling status**. The point is to turn each
one-off failure into a heuristic an authoring skill (or a static check) can enforce, so the *next*
conversion is right the first time. Companion to HARNESS-GOTCHAS.md (harness bug catalog); the
chronological run log stays in the working knowledge base and is not published here.

Legend for **Tooling status**: ✅ enforced by a tool · 🛠️ candidate for a tool/skill · 📖 authoring rule (judgment).

---

## A. Candidate selection

**A1. Line count ≠ complexity.**
- Assumed: shortest legacy tests (by LOC) are the easiest conversions.
- Reality: the top "cheap" MainMenu items needed new page objects, a long-press primitive, or app-exit
  to external apps. LOC hides capability cost.
- Rule: rank by *existing coverage × expressibility with existing primitives*, not LOC. Read the body +
  check which screens are already modeled before committing to a candidate.
- Tooling: 🛠️ `effscaffold` surfaces the body/coverage; a coverage-aware scorer could rank the P0 pool.

**A2. "Not converted" means not converted *on main*, not absent from your tree (2026-08-04).**
- Assumed: if the efficiency package in your checkout has no such test, it needs converting.
- Reality: a branch that predates someone else's landing cannot see their work. Bug 2060292 converted
  `AddressAutofillTest.deleteSavedAddressTest` while bug 2060174 had already landed the same test from
  someone else — the duplicate only surfaced as a rebase conflict, after review and submission.
- Rule: fetch and check main before picking, not just the working tree. `effnext`'s tree check and
  `effscaffold`'s already-converted check both read your checkout, so both are blind to this.
- Tooling: 🛠️ the tree check could compare against `origin/main` rather than the working tree.

## B. Authoring (compile-time — cheap to catch statically)

**B1. `mockWebServer` isn't on BaseTest.**
- Assumed: `mockWebServer` is inherited.
- Reality: each test class needs `private val mockWebServer get() = fenixTestRule.mockWebServer`.
- Tooling: ✅ effcheck `MWS`.

**B2. TestAssetHelper members need importing even on a receiver.**
- Assumed: `mockWebServer.getGenericAsset(...)` resolves without an import.
- Reality: `getGenericAsset` / `enhancedTrackingProtectionAsset` etc. are extensions — import each.
- Tooling: ✅ effcheck `IMP`.

**B3. `navigateToPage()` returns `BasePage`.**
- Assumed: I can chain any page method off `navigateToPage()`.
- Reality: only `moz*`/BasePage methods chain; page-specific methods need their own line — UNLESS the page
  overrides `navigateToPage` with a covariant return (e.g. BrowserPage).
- Tooling: 📖 (compile error catches it; too many false positives to lint — see dropped CHAIN check).

**B4. effdump/args: `InstrumentationRegistry.getArguments()`, not `getInstrumentation().arguments`.**
- Tooling: 📖 one-off.

## C. Selectors (the biggest recurring category)

**C1. Prefer the unique testTag over text — text collides (gotcha A7).**
- Assumed: matching the trust-panel website by its visible title text is fine.
- Reality: the page title + host ALSO render in the address bar → `COMPOSE_BY_TEXT` matched multiple nodes
  → ambiguous failure. The element had a unique `testTag` (`unified.trust.panel.website`).
- Rule: tag → id → content-desc → text, in that order (authoring priority B5). If a tag exists, use it even
  when text "looks" fine.
- Tooling: 🛠️ effdump shows the tag; a check could flag COMPOSE_BY_TEXT when a nearby node has a testTag.

**C2. Pre-stubbed page objects carry STALE locators — never trust a stub.**
- Assumed: the existing (stubbed) CustomTabsPage menu-button res-id was correct.
- Reality: it was the OLD Android-view res-id (`mozac_browser_toolbar_menu`); the redesigned toolbar uses a
  content-desc ("More options" = `R.string.content_description_menu`).
- Rule: verify every stub locator against the live UI before relying on it.
- Tooling: ✅ effdump (dump the screen, read the real handles).

**C3. Nav entry / arrival selectors must cover EVERY runtime state (gotcha B7).**
- Assumed: one arrival signal / entry button per screen.
- Reality (twice): RecentlyClosed's `requiredForPage` was the empty-state view (gone once populated);
  the trust-panel site-info button's tag depends on page security (SECURE/UNSECURE/UNKNOWN).
- Rule: `requiredForPage` = an element present in ALL states; a state-dependent entry control →
  `ClickIfPresent` every variant.
- Tooling: 📖 (can't see at static time); standing check when building nav.

**C4. The Compose dump can't see View screens — you need Espresso + UIAutomator too.**
- Assumed: the on-failure Compose ScreenDump shows what's on screen.
- Reality: legacy View screens (RecyclerViews, res-id widgets) dump 0 Compose nodes; recently-closed's
  res-ids only appear in the UIAutomator/Espresso trees.
- Rule: for View screens, author from the Espresso (in-process) dump first (framework prefers ESPRESSO_BY_ID),
  then UIAutomator for cross-process/system/GeckoView.
- Tooling: ✅ effdump now emits all three (Compose / Espresso / UIAutomator).

## D. Navigation & app model

**D1. Close-last-tab lands on Home → re-sync before routing.**
- Rule: after `on.tabDrawer.closeTabWithTitle(...)`, call `on.home.navigateToPage()` to re-sync page state.
- Tooling: 📖 idiom.

**D2. Custom tabs are LAUNCH-reached, not graph-navigated.**
- Assumed: a nav edge (click path) reaches a custom tab.
- Reality: custom tabs run in a separate activity started by an intent (IntentReceiverActivity). No click
  path from HomePage.
- Rule: model as `launchCustomTab()` (fire the intent, set page state); no NavigationRegistry edge. Use
  device-level (UIAutomator) selectors — they survive the activity switch; Compose/global-semantics also work.
- Tooling: 📖 pattern; the launch capability now exists.

## E. Runtime behavior

**E1. Slow ≠ flaky.** UIAutomator list rendering can take ~3s; `mozVerify`'s poll-until-present handles it
(logs "not found" retries, then finds it). Don't add retries or call it flaky — check it eventually passed on try #1.

**E2. "Green + 0 failed" hides SKIPPED tests.** A conversion is done only when the *named* test shows
`started:`, is NOT in `ignored:`, and its run is 0-failed. Tooling: ✅ `effverify`.

**E3. Shared-selector/edge changes touch every test that uses them (gotcha A4).** After editing a shared
selector (e.g. the trust-panel website tag), re-verify the WHOLE class, not just the one test.

---

## Distilled heuristics for an authoring skill (the payoff)
1. Before picking a candidate: `effscaffold` it; confirm the screens are modeled and no app-exit/new-primitive is needed.
2. Before writing selectors for any screen whose handles you're unsure of: `effdump` it (all 3 layers) and author from ground truth. Prefer tag → ESPRESSO_BY_ID → content-desc → text.
3. Never trust a stubbed page object's locators; dump and verify.
4. For nav: `requiredForPage` must be state-invariant; state-dependent entry buttons → ClickIfPresent all variants.
5. Test-class boilerplate: mockWebServer accessor + TestAssetHelper imports (effcheck catches these).
6. Done = `effverify` green (named test ran, not skipped, 0-failed); shared changes → re-verify the class.

## C5. Web DOM resource-ids need the RAW-resourceId strategy.
- Assumed: UIAUTOMATOR_WITH_RES_ID matches a web form's id (e.g. "submit").
- Reality: it prepends `packageName:id/` (right for APP views, wrong for WEB ids). Web/GeckoView ids surface
  as RAW resource-ids. UIAUTOMATOR_WITH_COMPOSE_TAG matches the raw resourceId (no prefix) and works for them.
- Rule: app View res-id -> UIAUTOMATOR_WITH_RES_ID; web DOM id (submit/username/password) -> the raw-resid strategy.
- MTE-5722 note: a raw-resid strategy MUST survive selector consolidation (it is NOT dead — web ids need it).

## E1. Gate 6 reads the JSON verdict only — never the raw run log. (token discipline)
- Assumed: to confirm a run you read `run-report.txt` / `effpretty` output.
- Reality: that's the loop's single biggest per-run token spike (reports run 200–2000+ lines). The verdict
  already exists structured: `effbuild --json` (compile) + `effverify --json` (run). effverify is now scoped
  to the LAST run (no stale-buffer false negatives) and carries a capped `failure_excerpt` on failure.
- Rule: at gate 6 read `effbuild --json` then `effverify --json`, nothing else. Never `cat` run-report.txt /
  raw-run.log; never read `effpretty` output (it's a human-facing renderer). Trust `clean`=false as flaky.

## E2. Pick the next test locally with `effnext` — never the Google Sheet.
- Assumed: choosing the next test means consulting the project tracker Sheet.
- Reality: the Sheet is systems-of-record for status, but round-tripping it to *pick* is slow and burns tokens.
  The working queue is local: `testrail_smoke_pool.txt` (prioritized) minus `converted_rows.csv` (done).
- Rule: `effnext --json` for the next candidate; reconcile the Sheet in a batch after landing, not per-pick.
- Correction (2026-08-03): `converted_rows.csv` lags the tree badly — it proposed a test that was already
  converted and committed, and 11 of its top 30 candidates were already in-tree. `effnext` now greps the
  efficiency tests package itself and drops those (`--no-tree-check` opts out). Note `effscaffold`'s
  `already_converted` does NOT cover this: it lists matching *files*, not methods.
- Rule (2026-08-03): a candidate you decide not to take — too complex for whoever is picking it up, blocked
  on a harness gap, deliberately deferred — gets recorded with `effnext --skip Class.method --reason "…"`
  rather than mentally stepped over, so the next caller gets a different pick and the reason survives.
  Skips are advisory and reversible (`--unskip`, `--skips`); they never mark a test converted.

## D3. Settings sub-pages need a back-edge to Home to load a URL after a settings change.
- Assumed: navigateToPage(BrowserPage) works from any page.
- Reality: no path from a deep settings page to BrowserPage; legacy "exits the menu" first.
- Rule: give a settings page a ->HomePage back-edge (ClickIfPresent GO_BACK_BUTTON "Navigate up" chain);
  then navigateToPage(browser,url) routes settings->home->browser.

## F. Environment overlays & observability (AddressAutofill, 2026-07-27)

**F1. A "not found" can mean "covered by a system overlay", not "absent".**
- Assumed: if a `moz*` step reports element-not-found, the element isn't on screen (selector or nav is wrong).
- Reality: a separate-window OEM overlay can cover it. Focusing a text field on a stylus-enabled device pops
  "Try out your stylus", which suppressed the address-autofill prompt and hid web content from the tree.
- Rule: treat unexpected not-founds on web/field interactions as possible overlays. Handling is centralized:
  `OverlayRegistry` + `BasePage.dismissKnownOverlaysIfPresent()` (auto-fired on a locate miss, retries once).
  For web-form autofill also set `stylus_handwriting_enabled 0`. Tooling: 🛠️ registry-driven; extend the list.

**F2. On-failure diagnostics must cover ALL layers + windows/focus, not just Compose.**
- Assumed: the Compose ScreenDump on failure shows what's on screen.
- Reality: it's blind to system dialogs, legacy Views, and the IME — exactly the things that cause the
  failure. I burned a run guessing a dismiss handle because the popup wasn't in the dump.
- Rule: `ScreenDump.dump()` now emits Compose + `[windows]` (titles/types, IME/overlay flags, focused input)
  + UIAutomator + Espresso on every failure. Read the `[windows]` block first to tell "covered/focus-stolen"
  from "genuinely absent". Tooling: ✅ wired into the BasePage failure path.

**F3. RetryTestRule attempts share persistent app state the cleanup didn't reset.**
- Assumed: each retry attempt starts clean (BaseTest recreates the compose rule + clears bookmarks/session/tabs).
- Reality: saved autofill addresses persisted across attempts, so a first-attempt failure changed the Autofill
  screen for the retry and it failed differently — a retry-pass/​retry-fail that misrepresents the real result.
- Rule: clear the storage a test mutates in the per-attempt cleanup. Added autofill-address deletion to
  `BaseTest`. Tooling: 🛠️ generalize — cleanup should cover each storage a converted test touches.

## G. Review & verification (2026-07-28, 20-commit stack review)

**G1. A dropped assertion does not fail — it passes for the wrong reason.**
Reviewing 13 conversions found 17 legacy assertions silently missing. None caused a failure, because what
gets dropped is the *payload* check (`verifyPageContent`, `verifyUrl` after reopening, `verifyTabCounter`,
the five blocked-tracker checks) rather than the navigation. The test still proves it reached a screen; it
stops proving the screen is right. Green is not evidence of parity — only a line-by-line diff against the
legacy body is. Tooling: 🛠️ a conversion checker could diff legacy `verify*` calls against the port.

**G2. Switching a selector to a tag can silently delete the content assertion.**
`WEBSITE_TITLE`/`WEBSITE_URL` were moved from text matching to tag-only to fix a real ambiguity (the host
renders in both the trust panel and the address bar). That made `verifyUnifiedTrustPanelItems`' `webSite`
and `webSiteURL` **dead parameters** across all five trust-panel tests — every caller passed them, nothing
read them, and "an element with this tag exists" is nearly always true once the panel opens. When a tag
replaces text, ask what the text was *asserting*; if it was content, match both
(`COMPOSE_BY_TAG_AND_TEXT`). Related: gotcha A11 — wire a new strategy into BOTH resolution paths.

**G3. Verify the fix landed where you think it did.**
Two fixes this pass produced byte-identical failures because the code that actually ran was somewhere else:
a duplicate nav edge in another file (gotcha A13), and a strategy added to `resolveComposeNode` but not
`mozGetElement` (A11). If a fix changes nothing, suspect a second definition before suspecting the
diagnosis.

**G4. Read the legacy ROBOT, not just the legacy test.**
Retry/refresh semantics, per-assertion waits and fallback behaviour live in the robot helper. The
tracking-protection assertions look like plain text checks in the test body; the refresh-on-retry that makes
them reliable is in `BrowserRobot`. Porting the body alone produces a test that is correct-looking and
flaky.

**G5. Gradle's JUnit XML is authoritative; the logcat trace explains WHY.**
`status.json` said `ran: true` and nothing else, so pass/fail had to come from
`.../androidTest-results/connected/debug/TEST-*.xml`. Also: the Test Orchestrator runs each test in its own
process, so one `run finished: 1 tests` per test plus a suite summary is NORMAL — it is not a stale buffer
(I misread it as one and briefly chased the wrong thing). effloop now folds the XML into `status.json`.

**G6. "All green" needs the class list attached, and must say WHOSE runs it covers.**
Reported "39 tests green across 6 classes" for a stack containing **7** converted classes. The seventh
(`AddressAutofillTest`) had in fact been run and resolved separately by the engineer — but the summary did
not say the count covered only the agent's own runs, so it read as full-stack coverage with one class
silently missing. State the inventory and the provenance: an agent's verification and a human's are
separate sets, and neither is visible to the other unless recorded.

## C. Selectors (continued)

**C6. In the expanded-toolbar layout, prefer a device-level content-description over a testTag.**
Controls MOVE between surfaces and change the handles they expose — the tab counter has no tag at all in
the bottom navigation bar, only a content-description. A Compose exact/merged content-description lookup
also fails where the device-level one succeeds. Three of four test failures debugged on 2026-07-28 were
this single pattern. See gotcha A12.


## H. Acting on a control vs. finding it (2026-08-03, translations sheet + credit cards)

**H1. "Clicked" in the report does not mean the app acted.**
- Assumed: if `mozClick` reports success, the click did something.
- Reality: a Compose button rendered `enabled = false` still accepts the gesture and silently skips
  `onClick`. The failure then surfaces wherever the effect was expected — 25s and several steps away from
  the cause.
- Rule: when a control's enabled state depends on async work, wait for enabled before clicking, and make
  sure the gate really blocks (a gate returning in tens of ms is not gating). See gotchas A16/A17.
- Tooling: 🛠️ `mozWaitUntilEnabled` was written for this and is not landed yet; a check that flags
  `mozClick` on a `COMPOSE_BY_TEXT` selector would catch the no-op-gate variant statically.

**H2. Selector strategy decides whether you can even observe actionability.**
- Assumed: text selectors are interchangeable for reading and for clicking.
- Reality: `COMPOSE_BY_TEXT` resolves the text node inside the button (unmerged tree), which reports
  enabled while the button is disabled. `COMPOSE_BY_TEXT_MERGED` resolves the button.
- Rule: read with `COMPOSE_BY_TEXT`, act with `COMPOSE_BY_TEXT_MERGED`.

**H3. A default 5s locate is not a synchronisation primitive.**
- Reality: three separate defects found in one 2026-08-03 sweep (bugs 2060405, 2060414, 2060415) were all a
  default `mozVerify` timeout standing in for a readiness signal that never came.
- Rule: gate on the thing that means "ready" (the detected language rendered, the sheet gone, the toolbar
  usable again), and prefer a positive assertion over waiting for something to disappear — absence cannot
  distinguish "it worked" from "the click was dropped".

## I. Paperwork that is part of the conversion, not after it (2026-08-03)

**I1. The `@Converted` annotation belongs in the conversion commit.**
- Reality: the burndown keys off that marker, so a conversion that lands without it reads as unconverted.
  Two conversions in one stack were caught missing it during a pre-submit audit, requiring a mid-stack
  rewrite that would have been free if written at the time.
- Rule: annotate the legacy method in the same commit; use `notes` for any deliberate deviation (e.g. local
  mockWebServer asset instead of an external URL).
- Tooling: 🛠️ a pre-submit check ("every conversion commit touches a legacy test and adds `@Converted`")
  would make this mechanical.

**I2. Conversion bugs must block the tracking meta; harness bugs must not.**
- Reality: the meta (bug 2030727) tracks the campaign through `depends_on`. A conversion bug that is never
  linked is invisible in the burndown; a tooling/harness bug that *is* linked pollutes it.
- Rule: set `blocks` at filing time, and only for test-conversion bugs.

**I3. Bugzilla descriptions cannot be edited via the API.**
- Reality: `PUT /rest/bug/comment/<id>` returns 404 (code 32614); only comment *tags* are writable. A wrong
  comment 0 can only be corrected by a human in the web UI.
- Rule: get the mechanism right before filing, or expect to hand a human the corrected text. Prefer filing
  after the diagnosis is confirmed, not while it is still a theory.

**I4. Rebasing a submitted stack: dropping a commit leaves its revision in the graph (2026-08-04).**
- Reality: abandoning a revision does not remove it from the stack's dependency graph. After dropping a
  duplicate commit mid-stack, the next revision still recorded the abandoned one as its parent, and its
  diff still pointed at the dropped commit's hash as its base.
- Rule: resubmit the **whole** range, not just the commits whose content changed — the re-parenting is
  what clears the stale edge. Expect every revision to get a new diff (the rebase changed every hash),
  and expect already-accepted revisions to reset to needs-review; tell the reviewers why before they see
  it. If avoiding a resubmit matters more, leave commit messages alone — editing one forces the upload
  you were trying to avoid.

## J. Interaction diagnosis and re-baselining (DownloadFileTypesTest, 2026-08-04, 8 device runs)

Section H covers the same family from the translations sheet; these are the additions from a conversion
where the click problem appeared twice in one test, on two different layers.

**J1. A text selector can resolve a non-interactive TWIN of the target.**
- Assumed: if a selector resolves an element and the click reports success, the click landed.
- Reality: hit twice in one conversion. Each download link renders as a PAIR — a clickable node carrying
  `desc="Download <file>"` and a sibling text node with the same string and no click action. Same shape for
  the dialog's confirm button (`Button { Text("Download") }`). H1 is the disabled-button version of this;
  here the node was not disabled, it was never interactive.
- Rule: for anything you CLICK rather than merely read, the handle must belong to the node owning the click
  action. A text match is the likeliest to pick the twin, because the text lives on the child and the action
  on the parent. Gotchas A17 (Compose side) and A20 (device side).
- Tooling: 🛠️ a check could flag text strategies used as click targets.

**J2. `UiObject.click()` returning false does NOT mean the click failed.**
- Assumed: `Failed to click UiObject` means the tap missed.
- Reality: it is `clickAndSync`, which returns false when no window update arrives inside ~5.5 s — routinely
  exceeded by a click that starts a network download. A dump at one such "failure" showed the link holding
  input focus; the tap had worked, and the retry then reloaded the page and threw away a dialog that was
  on its way.
- Rule: for a control whose reaction is slow, use a UiObject2 strategy — it injects the gesture and leaves
  the waiting to the caller. Gotcha A22.
- Tooling: ✅ `UIAUTOMATOR2_BY_DESCRIPTION_CONTAINS` added for this.

**J3. Two identical failures mean the variable you are changing is the wrong one.**
- Assumed: a click that resolves but does nothing is a selector problem, so try another strategy.
- Reality: `COMPOSE_BY_TEXT`, a purpose-built `hasText and hasClickAction`, and `COMPOSE_BY_TEXT_MERGED`
  all resolved a node, reported success, and left the dialog open. Three runs, one hypothesis, no new
  information. The first run designed to DISCRIMINATE between hypotheses (Compose injection vs. the app not
  acting) settled it immediately.
- Rule: after the second identical failure, stop varying the same dimension and design a run whose possible
  outcomes point at different causes. Write down what each outcome would mean before starting it.
- Tooling: 📖 judgment.

**J4. Swapping a remote page for a local asset is a change to the system under test.**
- Assumed: serving the same page from mockWebServer only removes network flakiness.
- Reality: localhost returns a `content-length`, so Fenix rendered the known-size download dialog (with a
  rename field) instead of the unknown-size one — a dialog carrying the J1 confirm-button problem, which
  the remote page never surfaced. A run that was 5/9 green went to 0/9, and four runs went into debugging a
  failure the change itself had introduced.
- Rule: re-baseline immediately after a determinism change. If results get worse, suspect the change before
  suspecting the code under test. Gotcha B14.
- Tooling: 📖 judgment.

## K. Harness-first authoring, and distrusting the legacy assertion (2026-08-07..12 smoke batches)

From the SettingsDeleteBrowsingData, SettingsOpenLinksInApps, SettingsGeneral, PageSummaries, addons and
SettingsSearch conversions. Sections A-J cover selectors and interaction; these are about where a fix belongs
and which assertion to trust.

**K1. When a `moz*` verb cannot express a case, extend the primitive — do not wrap or inline a workaround.**
- Assumed: a screen-specific page-object helper is the cheap fix.
- Reality: a raw `mDevice` wait or ad-hoc loop is a smell even when it works and even when it faithfully mirrors
  the legacy robot. Concretely: instead of a bespoke `swipeToSwitchToTab`, add a `steps` param to
  `mozSwipeElement`; instead of inlining a wait, add the smallest general `BasePage` primitive.
- Rule: at the interaction gate, first ask "can I make the existing primitive flexible?" A general extension is
  inherited by every later conversion; a wrapper helps one test and hides the capability. Cover all element
  backends (ViewInteraction / UiObject / UiObject2 / SemanticsNodeInteraction), modelled on an existing verb.

**K2. Collapse near-duplicate legacy helpers into one helper with a variant flag.**
- Legacy `installAddon` vs `installAddonInPrivateMode` differ by one checkbox. The port is ONE
  `installAddon(title, allowInPrivateBrowsing: Boolean = false)`, not two public methods over a shared private one.
- Rule: mirror the legacy *behavior*, not its method shape or count. Default the flag to the common case and pass
  it by name at call sites. Collapse unless the two paths diverge in more than one step.

**K3. Name a `SelectorStrategy` after the matchers it calls, not where its value came from.**
- A `UiSelector().resourceId(v).descriptionContains(s)` lookup is `UIAUTOMATOR_WITH_RES_ID_AND_DESCRIPTION_CONTAINS`
  — NOT `..._WITH_COMPOSE_TAG_AND_...`, even when the res-id string originates from a Compose `testTag` surfaced
  via `testTagsAsResourceId`. That origin is a property of one selector's value, not of the strategy.
- Rule: strategy name == the matchers it runs, consistent with its siblings (`..._WITH_TEXT`, `..._WITH_RES_ID_AND_TEXT`).
  Value origin and res-id prefixing behaviour go in the doc comment. A Compose strategy that really calls
  `hasTestTag(...) and hasContentDescription(...)` IS correctly named `COMPOSE_BY_TAG_AND_CONTENT_DESCRIPTION_SUBSTRING`.

**K4. Audit every legacy `verify*` before porting it — they fail in both directions.**
- Vacuous-by-construction: `swipeNavBar*` asserted `itemWithText(fullHttpUrl)` was gone, but the toolbar strips the
  scheme so that object never existed — the assert passed trivially and the REAL check was the following `verifyUrl`.
- Dead-by-swallowing: legacy `BrowserRobot.verifyUrl` wraps its wait in `catch (ComposeTimeoutException) { Log.i }`
  — it logs and returns, asserting nothing. Ported onto the efficiency `verifyUrl` (which THROWS) the test failed,
  which looks like a conversion regression and is the opposite: the dead assertion finally firing.
- Rule: at the parity gate, open the legacy robot helper for each `verify*` and determine whether it THROWS or
  SWALLOWS, and what it actually checks against the live UI. If it swallows, re-derive the real observable behaviour
  from the device and assert THAT, keyed on a fixed app-string handle rather than a locale/env-dependent one.
- Pairs with G-section triage: legacy-RED + converted-GREEN on one build => legacy harness flake (product fine);
  legacy-GREEN + converted-RED => the legacy assertion was already dead. Both say "trust the product path,
  distrust the legacy assertion."

**K5. A launch-flag-gated page needs `LaunchConfig` plumbing in THREE places — and is often already on.**
- Add the field to the `LaunchConfig` data class, the `BaseTest` constructor (+ `defaultLaunchConfig`), AND the
  `HomeActivityIntentTestRule(...)` construction inside `BaseTest.retryWithCompose`. A test then opts in with
  `: BaseTest(flag = true)`. Default it to mirror the app's normal launch so `LaunchConfig()` stays == normal.
- But check `nimbus.fml.yaml` first: FML defaults are compiled in and always applied in instrumented tests, so a
  feature "behind a flag" (e.g. `shake-to-summarize`, `default: true`) may already be reachable under a plain
  launch. The plumbing then makes the dependency EXPLICIT (robust if the default flips), not strictly necessary.

**K6. Link every conversion bug to the tracking meta bug.**
- Each Bugzilla ticket filed for a legacy-test conversion should block
  [Bug 2030727 — [meta] TAE - Migrate and remove legacy tests](https://bugzilla.mozilla.org/show_bug.cgi?id=2030727)
  so the campaign stays trackable in one place. `effbug` does not set it on `create`; use
  `{ "bug":"update", "ids":[NNNNN], "blocks":[2030727] }` via the bridge, or the Bugzilla UI.

**K7. The committed reachability case list is a STATIC generated file — new pages are not covered until it is regenerated.**
- `NavigationReachabilityParameterizedTest.kt`'s `data()` is a hand-pasted `listOf(Case(...))` produced by
  `devtools/NavigationCaseGeneratorTest#logPresenceCases` (it logs boilerplate to logcat; a human pastes it).
  Registering a page in `PageContext` enrols it in the factory but does NOT add it here.
- Observed stale: the committed list was missing two new search sub-pages AND the pre-existing
  `SettingsSearchDefaultSearchEnginePage`. Adding just your own `Case(...)` entries by hand avoids pulling in
  unrelated stale-missing pages; a full regen is a separate cleanup (good-first-bug).

**K8. Tool verdicts: duration is the first triage signal (the RED-run crash is FIXED).**
- ~~`effverify`'s `failure_excerpt` path throws `NameError: name 'txt' is not defined`~~ — **fixed 2026-08-12**
  (`txt` should have been `full`; it only ever triggered when there was no `raw-run.log` to read). effverify now
  returns a verdict on a failing run, with a capped `failure_excerpt`, so the JUnit-XML fallback below is no
  longer needed for the common case. It is still the right move when `run-report.txt` is missing entirely (A24).
- **Cross-check `status.json` anyway.** A green effverify next to a non-zero `effloop_exit` means believe the exit
  code: see A37 for the crash-mode false green that motivated this rule.
- `effloop_exit:2` in ~45s = COMPILE failure, not a run — read `effbuild --json` for the Kotlin error.
  `effloop_exit:0` in ~50s = warm incremental build + quick run; still confirm `clean:true`, `failed_total:0`,
  `retried:false` (green alone hides a skip or a retry-pass).
- When `effbuild` says "build-infra, not test code", believe it: `mergeLibDexDebug` `NoSuchFileException` = corrupt
  incremental dex (`rm -rf` those intermediates, not a full clean); `machStagePackage` "Required Gecko binaries are
  missing" = run `./mach build`. Fix the objdir, not the port.

**K9. `effwatch` is a blocking bridge with no `--help`, and needs its env pinned per checkout.**
- `effwatch --help` / `--status` do not exist — they silently enter the poll loop with the WRONG default REPO and
  burn a slot (`pkill -f effwatch.sh` to clean up strays). Start it ONCE in the background.
- Override `REPO` when the checkout is not `$HOME/Workspace/firefox`, and `ANDROID_SERIAL` whenever more than one
  device is attached (otherwise gradle `connectedDebugAndroidTest` fans out to a physical phone too).
- Protocol: drop `conversion-runs/_queue/<id>.request.json` = `{"test_class":"Class#method","batch":"x"}`, poll for
  `<id>.done.json`, then `effverify conversion-runs/<batch> <method> --json`. Budget ~7 min for one method.
- A LEGACY test can be run through the same bridge by passing its fully-qualified `Class#method` — effloop treats
  any `test_class` containing a dot as an FQN. That is how you establish legacy ground truth (K4).
- When a nav failure saved no logcat, pull it live: `adb logcat -d -s PageNavigation:I EffScreenDump:I`.
  `PageNavigation` prints the exact BFS path chosen; `EffScreenDump` shows the screen actually landed on.

**K10. Cross-hierarchy return navigation is free — if every return edge is registered.**
- `on.searchBar.navigateToPage()` from a deep Settings sub-page BFS-routes
  ManageShortcuts -> SettingsSearch -> Settings -> Home -> SearchBar automatically, replacing legacy
  `exitMenu()` + `openSearch()`. That only works because each back edge exists.
- Rule: register the return edge on a new page even when your test only needs the forward one — the graph reuses it.
  Prefer decomposed per-screen edges (`SettingsPage -> subpage`) over one Home-anchored mega-edge, so the page is
  reachable from any entry the graph already knows.

**K11. One Settings area can mix View and Compose surfaces — pick the strategy per surface.**
- The SettingsSearch preferences screen is View-based (`ESPRESSO_BY_TEXT` keyed off string resources) while the
  Manage Shortcuts screen it opens is Compose (`COMPOSE_BY_TEXT` on the arrival header). Do not choose one strategy
  per settings-area.
- View forms: set fields with `mDevice.findObject(By.res("$pkg:id/edit_engine_name")).text = v` (fires the
  TextWatcher that enables Save), assert the Save button with `mozVerifyElementIsEnabled` on an `ESPRESSO_BY_ID`
  selector (Espresso needs no visibility, so it works with the keyboard up), and `closeSoftKeyboard()` before
  clicking a button below the fields in a ScrollView.
- effcheck warns "R.id/x not obviously present in app source" for ids declared only in `res/layout/*.xml` — it
  scans `values/`, not layouts. Benign; confirm with a grep of the layout.

**K12. Do not assume a legacy mock-server dependency is real.**
- Adding a custom search engine needs NO reachable URL: `SaveSearchEngineFragment.createCustomEngine` validates
  locally (name non-empty + search string contains `%s`); `SearchStringValidator` (which does a network fetch) is
  not wired into the add flow and the favicon fetch is best-effort. The legacy test's
  `searchMockServerRule.server.port` URL is vestigial, so the efficiency test needs no mock-server rule.
- Rule: check the fragment before inheriting a rule.

## Open gaps (unresolved — pick up on next attempt)

- **Address-autofill suggestion not offered on-device.** With the stylus overlay removed AND stylus disabled,
  the "Select address" prompt still did not appear for AddressAutofillTest#verifyAddressAutofillTest. The
  address saves (Manage addresses confirms), so the remaining suspect is the Country/State dropdown helper
  saving an address Gecko won't match to the US form, vs. a genuine prompt trigger/timing issue. Next step:
  one instrumented run dumping Manage Addresses (now that all-layer dumps are in) to confirm the saved values
  before deciding between "fix the dropdown" and "fix the trigger". Test + harness are built and compile-clean.
