# mobile-testing-assessment-charts

Charts from the Firefox Mobile Testing Assessment, rebuilt from live data instead
of one-off screenshots. Publishes a staff-only site to Quick at
https://mte-mobile-testing-assessment-charts.quick.mozilla.cloud/.

It shows:

- Test methods per layer in the iOS and Android (Fenix) code, side by side.
- Per platform: tests by layer, test pyramid, unit tests by module, E2E tests by feature.
- TestRail Full Functional cases per feature and automation status, for both platforms.

## How it runs

`.github/workflows/mobile-testing-assessment-charts.yml` runs every Monday, or on demand
from the Actions tab ("Run workflow"; the site's **Refresh data** button links there):

1. Sparse, shallow clones of the test folders in `mozilla-mobile/firefox-ios`
   and `mozilla-firefox/firefox`.
2. `collect_code_tests.py` counts test methods → `site/data/code.json`.
3. `collect_testrail.py` counts cases per feature and status → `site/data/testrail.json`.
4. Deploys `site/` to Quick. `index.html` loads the two JSON files and draws the
   charts with Plotly.

The data files only exist on the site, which is behind Mozilla SSO. They are not
committed here because this repo is public. They hold aggregate counts only:
`collect_testrail.py` reads section names and titles to classify each case, then
drops them, so no titles, steps, section names or case IDs reach the output or
the Actions log.

## What counts

Counts are volume, not coverage. Commented-out tests are not counted.

- **iOS**: `func test…` methods in `firefox-ios/firefox-ios-tests/Tests` and
  `BrowserKit/Tests`.
  - Smoketest: XCUITests annotated `// Smoketest`.
  - Performance: `PerformanceTests` (an XCUITest file) plus `StoragePerfTests`.
    They are left out of the XCUI numbers so they aren't counted twice.
  - Storage/Sync/Account: SharedTests, StorageTests, SyncTests, AccountTests,
    SyncTelemetryTests.
  - L10n: `snapshot()` calls, not test methods.
  - Integration: pytest functions in ExperimentIntegrationTests and SyncIntegrationTests.
  - XCUITests by feature: mapped from the test file name (`XCUI_FEATURES`).
    Files that match nothing show up as "Other".
- **Android**: `@Test` methods in Fenix only (`mobile/android/fenix/app/src`).
  android-components is not counted.
  - `src/test`: Robolectric when the class runs with `AndroidJUnit4` or a
    Robolectric runner, JUnit otherwise.
  - `src/androidTest`: `ui/` is E2E, split into Espresso/UIAutomator and the
    TAE framework's `ui/efficiency/tests`. The rest of `ui/efficiency` tests
    the TAE framework itself and is not counted as E2E. `experimentintegration/`
    and `syncintegration/` are integration, `perf/` is performance, a Compose
    test rule anywhere else is component.
  - Unit tests by module: top-level package under `org.mozilla.fenix`.
  - E2E by feature: mapped from the test file name (`ANDROID_E2E_FEATURES`).
- **TestRail**: Full Functional Tests Suite (Android 3192, iOS 45443).
  Automated = Completed, To automate = Suitable, Manual only = Unsuitable,
  Untriaged = anything else (Untriaged, Disabled, blank). Features come from
  `feature_taxonomy.py`, matched on the leaf section name and title.

## First deploy

The Quick site is created on the first run: run the workflow manually once.
