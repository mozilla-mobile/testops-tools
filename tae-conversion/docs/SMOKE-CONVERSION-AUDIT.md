# Legacy smoke test conversion audit

**Audited 2026-08-19**, against `efficiency-batch-2` (5 commits: Bug 2063223, 2063228, 2063232, 2063252,
2063263 / D319313-D319317) sitting on `main` at `b0bc20aac45f`. Numbers below assume that stack lands.

## Headline

| | Count |
|---|---|
| Legacy `@SmokeTest` methods in `androidTest/.../ui/*Test.kt` | **169** |
| Of those, annotated `@Converted` | **146** |
| **Remaining** | **23** |
| — of the 23, `@Ignore`d | 8 |
| — of the 23, active (not `@Ignore`d) | 15 |

### Why this says 23 and not 20

A raw `grep -c '@Converted'` over the legacy files returns **149**, which is where 169 - 149 = 20 comes from.
Three of those annotations sit on tests that are **not** `@SmokeTest` (verified: each carries only `@Test`):

- `MainMenuTest.verifyTheMainMenuShareButtonFromCustomTabTest`
- `SettingsCustomizeTest.verifyTheToolbarLayoutSectionTest`
- `TabbedBrowsingTest.verifySyncedTabsWhenUserIsNotSignedInTest`

146 converted-smoke + 3 converted-non-smoke = 149, which reconciles exactly against the raw grep. So the smoke
ratio is **146/169**, and the raw `@Converted` count is not a smoke ratio.

## The 8 `@Ignore`d

| Test | `@Ignore` reason |
|---|---|
| `FirefoxSuggestTest.verifyFirefoxSuggestNonSponsoredSearchResultsTest` | Failing, bug 1882035 |
| `FirefoxSuggestTest.verifyFirefoxSuggestSponsoredSearchResultsTest` | Failing, bug 1898435 |
| `MainMenuTest.verifyTheMoreMainMenuSummarizePageButtonTest` | "Will be fixed in bug 2059592" |
| `MainMenuTest.verifyTheMoreMainMenuSummarizePageButtonFunctionalityTest` | "Will be fixed in bug 2059592" |
| `NoNetworkAccessStartupTests.testSignInPageWithNoNetworkConnection` | Failing, bug 1987355 |
| `SettingsDeleteBrowsingDataTest.deleteCachedFilesTest` | Failing, bug 1987355 |
| `MicrosurveyTest.verifyTheSurveyConfirmationSheetTest` | (no reason string) |
| `OnboardingTest.verifyTheSetAsDefaultBrowserOnboardingCardFunctionalityTest` | (no reason string) |

An `@Ignore` is **not** proof the flow is unautomatable — it means the legacy test is currently failing or
parked. Baseline the legacy test on device before trusting any port (see CONVERSION-LESSONS).

## The 15 active, clustered by blocker

**Site permissions - 7 tests, a third of everything left.** System permission dialogs plus real media
playback. Same shape as the `Files`/`Media` chooser divergence, so `SystemPickerCapabilities` (Bug 2063263) is
the groundwork to extend here.

- `SettingsSitePermissionsTest.clearAllSitePermissionsExceptionsTest`
- `SettingsSitePermissionsTest.systemBlockedPermissionsRedirectToSystemAppSettingsTest`
- `SettingsSitePermissionsTest.verifyAutoplayBlockAudioOnlySettingOnMutedVideoTest`
- `SettingsSitePermissionsTest.verifyAutoplayBlockAudioOnlySettingOnNotMutedVideoTest`
- `SitePermissionsTest.allowLocationPermissionsTest`
- `SitePermissionsTest.audioVideoPermissionWithoutRememberingTheDecisionTest`
- `SitePermissionsTest.blockNotificationsPermissionTest`

**Microsurvey - 2.** Needs the survey to trigger.

- `MicrosurveyTest.activationOfThePrintMicrosurveyTest`
- `MicrosurveyTest.verifyTheSurveyRemainsActivatedWhileChangingTabsTest`

**Onboarding - 2.** Requires `BaseTest(skipOnboarding = false)`.

- `OnboardingTest.verifyEdgeToEdgeWallpaperAfterOnboardingTest`
- `OnboardingTest.verifyTheTermsOfUseOnboardingCardTest` - **already converted, see below**

**Top sites - 2.**

- `SponsoredShortcutsTest.verifySponsoredShortcutsListTest` - **ambient server covers this, see below**
- `TopSitesTest.addAndRemoveMostViewedTopSiteTest`

**Translations - 1.** `verifyTheTranslationIsDisplayedAutomaticallyTest`. Needs a real translation model
download, which never completes on the local emulator (see the suite baseline: `MainMenuTest`'s translate
test fails locally for the same reason). Firebase is the only place this can be verified.

**Trust panel - 1.** `UnifiedTrustPanelTest.verifySecurePageConnectionFromQuickSettingsWithTrackersInCustomTabsTest`.
Needs tracker content in a custom tab.

## Two of the 23 are bookkeeping, not conversion work

1. **`OnboardingTest.verifyTheTermsOfUseOnboardingCardTest` is already converted.**
   `ui/efficiency/tests/OnboardingTest.kt` has a test of that exact name, landed by **Bug 2057054**, carrying
   the same TestRail case (3349493). That commit never touched the legacy file, so the `@Converted` annotation
   was simply never added. A one-line annotation takes the count to 147/169.
2. **`SponsoredShortcutsTest.verifySponsoredShortcutsListTest` is functionally covered** by the ambient-server
   work (**Bug 2063541**, commit `f880cf8a82dc` on `ambient-server-sponsored-tiles`, not yet landed). But that
   commit adds a *new* test, `SponsoredShortcutsAmbientServerTest.verifySponsoredShortcutsFromAmbientServerTest`,
   and does not annotate the legacy test - so as written it will not count as a conversion. Decide whether it
   replaces the legacy test and add the `@Converted` mapping if so.

## Set-aside register cross-check

The two `FirefoxSuggestTest` tests were recorded in the register as **resolved** (converted and landed via Bug
2063105), but that was the client-substitution faker work, which was dropped and abandoned along with Bug
2063093. They are therefore **open again** and back in the 23. The ambient server is the replacement path -
it solves the same problem one layer lower (real Rust client and provider, fixture inventory over real https).

## Reproducing this audit

Heuristic but reconciled (146 + 3 = 149 matches the raw grep). Walks back from each `fun x()` over its
contiguous annotation/comment block, and treats a class-level `@SmokeTest` as applying to every test in
the file.

```python
import re, glob, os
L = 'mobile/android/fenix/app/src/androidTest/java/org/mozilla/fenix/ui'
rows = []
for path in sorted(glob.glob(f'{L}/*.kt')):
    lines = open(path).read().splitlines()
    cls_i = next((i for i, l in enumerate(lines)
                  if re.match(r'^(?:@\w+\s+)*(?:open |abstract )?class ', l)), len(lines))
    cls_smoke = '@SmokeTest' in "\n".join(lines[:cls_i + 1])
    for i, l in enumerate(lines):
        m = re.match(r'^\s*fun (\w+)\(\)', l)
        if not m:
            continue
        j, block = i - 1, []
        while j >= 0:
            s = lines[j].strip()
            if s == '' or s == '}' or s.startswith('class ') or re.match(r'^fun ', s):
                break
            block.append(s); j -= 1
        b = "\n".join(reversed(block))
        if '@Test' not in b:
            continue
        rows.append(dict(file=os.path.basename(path), test=m.group(1),
                         smoke='@SmokeTest' in b or cls_smoke,
                         converted='@Converted' in b, ignored='@Ignore' in b))
smoke = [r for r in rows if r['smoke']]
rem = [r for r in smoke if not r['converted']]
print(f"smoke={len(smoke)} converted={len(smoke)-len(rem)} remaining={len(rem)} "
      f"ignored={sum(1 for r in rem if r['ignored'])}")
for r in sorted(rem, key=lambda r: (r['file'], r['test'])):
    print(('IGNORED ' if r['ignored'] else 'active  '), r['file'][:-3] + '.' + r['test'])
```

Cross-check for already-converted-but-unannotated tests (this is what caught the Onboarding one): match each
remaining test name against `fun` names in `ui/efficiency/tests/*.kt`.

---

# Appendix: duplicate/prior-work verification (2026-08-19, second pass)

Run because of a recollection that some of the remaining tests - site permissions in particular - had already
been converted, and to confirm the commits cut from batch-2 as "duplicates" really were duplicates.

## The original batch-2 stack, and what was cut

`backup/efficiency-batch-2-prerebase-20260817-185146` holds the pre-drop stack: **20 commits = 9 search-batch
commits (Bug 2063043-2063102, since landed as `efficiency-search-batch`) + 11 batch-2 candidates.** Of the 11:

**Kept (the current 5):** 2063223, 2063228, 2063232, 2063252, 2063263.

**Cut as duplicates - all 6 verified genuinely present in main:**

| Bug | Conversion | Efficiency test in main | Legacy `@Converted` in main |
|---|---|---|---|
| 2063217 | `SettingsPageSummariesTest.verifyPageSummariesUITest` | present | yes |
| 2063247 | `SettingsAddonsTest.noCrashWithAddonInstalledTest` | present | yes |
| 2063255 | `SettingsGeneralTest.changeDefaultBrowserSetting` | present | yes |
| 2063265 | `SettingsSearchTest.verifySearchShortcutChangesAreReflectedInSearchSelectorMenuTest` | present | yes |
| 2063277 | `SettingsSearchTest.verifyCustomSearchEngineCanBeAddedFromSearchEngineMenuTest` | present | yes |
| 2063301 | `SettingsSearchTest.verifyShowSearchSuggestionsToggleTest` | present | yes |

**None of the 6 were site-permissions tests** - they are Settings (search, addons, general, page summaries).
Where our cut versions asserted *more* than main's landed versions, that delta was salvaged separately as
**Bug 2064267** (`improve-landed-eff-tests`), so nothing was lost by dropping them.

## No prior conversion exists for the 22 others

Two independent checks, both negative:

1. **Diff scan across all 263 commits** on every local branch not in `main`, for all 23 remaining test names.
   Only hits: the two `FirefoxSuggestTest` names and `verifySponsoredShortcutsListTest` in the **dropped faker
   commits** (Bug 2063105, Bug 2063093), and `verifyTheTermsOfUseOnboardingCardTest` in a docs commit
   (Bug 2057959) that merely mentions it. **Zero hits for any of the 7 site-permissions tests.**
2. **TestRail case-id cross-check** (stronger than name matching - this is what caught the Onboarding case):
   all 23 remaining legacy tests carry a TestRail id; compared against the 170 id-carrying tests in the
   efficiency suite, **only `OnboardingTest.verifyTheTermsOfUseOnboardingCardTest` (case 3349493) matches**.

So 22 of the 23 are genuinely unwritten, and no work would be duplicated by converting them.

## Why "we already did site permissions" is a half-memory

The **scaffolding exists and is landed in main**, just not these 7 tests:

- `pageObjects/SitePermissionsPage.kt`
- `pageObjects/SettingsSiteSettingsPermissionsPage.kt`
- `selectors/SitePermissionsSelectors.kt`
- `selectors/SettingsSiteSettingsPermissionsSelectors.kt`
- `tests/SettingsSiteSettingsTest.kt` - covers `verifySiteSettingsSectionTest` and
  `verifySiteSettingsExceptionsSectionTest`, neither of which is one of the 7

So the site-permissions cluster is **additions on existing page objects and selectors, not greenfield** -
which makes it a better first target than the raw count of 7 suggests.

---

# Progress: site-permissions cluster (2026-08-19)

Branch `efficiency-site-permissions`, based directly on main (nothing needed from the pending batch-2 stack,
so no cherry-picks). **6 of the 7 site-permissions tests converted, all green on device with no retry**, via
the documented loop (effcheck -> queue -> effloop -> effverify/efftriage).

| Bug | Tests | Commit |
|---|---|---|
| 2064810 | `verifyAutoplayBlockAudioOnlySettingOnNotMutedVideoTest` (2095125), `verifyAutoplayBlockAudioOnlySettingOnMutedVideoTest` (2286807) | `dc4a0e11d946` |
| 2064815 | `blockNotificationsPermissionTest` (2334074), `allowLocationPermissionsTest` (251385), `audioVideoPermissionWithoutRememberingTheDecisionTest` (2334295) | `48bb9ccfeed6` |
| 2064823 | `clearAllSitePermissionsExceptionsTest` (246976) | tip |

**Still open in this cluster: `systemBlockedPermissionsRedirectToSystemAppSettingsTest`** — the one that drives
the Android system settings app (grant Camera/Location/Microphone, return, assert unblocked), so it needs
capability detection of the settings UI per API level.

**Counts with this branch landed: 152/169 converted, 17 remaining** (8 `@Ignore`d, 9 active).

**Baseline first paid off:** all 7 legacy tests were run on device before any port was written and all 7 passed,
so every failure during conversion was known to be the port's fault, not the flow's.

New harness pieces, all authored from live dumps: `SettingsSiteSettingsAutoplayPage` (+ return edge),
autoplay selectors, permission-prompt selectors that assert button LABELS by res-id+text, web-DOM-id triggers
for the permissions test page, and exceptions-screen selectors. Details in CONVERSION-LESSONS.md.

**Two process notes worth keeping.** TestRail ids: three of six were wrong on the first pass because I read
them from grep context windows instead of the line immediately above each test — a scripted legacy-vs-port
comparison caught all three, and it should be run before filing anything (two filed bugs needed correcting
comments). And efftriage earned a new rule: T19, for "No navigation path found from X to Y", which it
previously misrouted to the selector/dump advice.

## Cluster complete (2026-08-19)

**All 7 site-permissions tests converted and green.** Final piece:

| Bug | Test | Commit |
|---|---|---|
| 2064833 | `systemBlockedPermissionsRedirectToSystemAppSettingsTest` (no TestRail link in legacy) | `505c1b74f63b` |

Branch `efficiency-site-permissions` = **4 commits, all ours, standalone on main.** A cherry-pick of Bug 2063263
was tried first as a base, but its revision (D319317) is CLOSED, so moz-phab refuses to submit a stack containing
it. The dependency turned out to be one function I had written myself, so it was inlined and the borrowed commit
dropped. **Check what you actually need before cherry-picking a base:** main already had
`APP_INFO_PERMISSIONS_ROW`, `APP_PERMISSION_ROW`, `APP_PERMISSION_ALLOW_OPTION`,
`openAppPermissions` and `allowAppPermission` — everything except `SystemPickerCapabilities`, which this test
never needed.

**Counts with this branch landed: 153/169 converted, 16 remaining** (8 `@Ignore`d, 8 active).

The cherry-pick paid for itself: `SystemSettingsSelectors.APP_INFO_PERMISSIONS_ROW`,
`APP_PERMISSION_ROW`, `APP_PERMISSION_ALLOW_OPTION` and `SystemSettingsPage.openAppPermissions/allowAppPermission`
already did what legacy's `switchAppPermissionSystemSetting` chain did.

**The assertion worth stealing for other system-UI tests.** Legacy branched on `Build.VERSION` to decide whether
to assert the granted row's "Only while app is in use" summary (rendered only up to API 30), and above that
asserted only that a row with the permission's title exists — which is true whether the permission is allowed or
denied, so on a modern release that assertion could not fail. The port keeps the row check for parity and adds
`PackageManager.checkSelfPermission` as the real oracle: no version branch, and it cannot pass for a denied
permission. It is inlined in `SystemSettingsPage.verifySystemPermissionGranted` (`appContext.checkSelfPermission`), deliberately
NOT in `SystemPickerCapabilities`: that file does not exist on main yet, and adding it here would collide with Bug
2063263 when that lands.

Also fixed in passing: `SettingsSiteSettingsPermissionsPage` was dead code — never instantiated in `PageContext`,
so its nav registration never ran, and its edge stopped one screen short of its own arrival anchor.
