# TestRail URL Scanner

Automated tool to detect test functions missing TestRail URLs in both iOS (Swift) and Android (Kotlin) test suites.

## Overview

This tool scans test files to ensure every test function has an associated TestRail case URL documented above it. It runs automatically via GitHub Actions every Monday and sends Slack notifications when missing URLs are detected.

**Supported Platforms:**
- **iOS**: Swift XCUITests in `mozilla-mobile/firefox-ios`
- **Android**: Kotlin UI tests in `mozilla-firefox/firefox` (Mozilla Central mirror)

## How It Works

### iOS (Swift)

The scanner looks for test functions matching the pattern `func test...()` and validates that a TestRail URL appears above them.

#### Valid Patterns

**Pattern 1: Direct URL**
```swift
// https://mozilla.testrail.io/index.php?/cases/view/2307058
func testImageOff() {
    // test code
}
```

**Pattern 2: URL + Smoke Test marker**
```swift
// https://mozilla.testrail.io/index.php?/cases/view/2307058
// Smoke TAE
func testLogin() {
    // test code
}
```

**Pattern 3: URL + intermediate comments + Smoke Test**
```swift
// https://mozilla.testrail.io/index.php?/cases/view/2307058
// Functionality is tested by UITests/NoImageModeTests
// SmokeTest TAE
func testImageOff() {
    // test code
}
```

**Pattern 4: URL + multi-line docstring**
```swift
// https://mozilla.testrail.io/index.php?/cases/view/2344428
/**
 * Tests landscape page navigation with tab switching.
 */
func testLandscapeNavigationWithTabSwitch() {
    // test code
}
```

**Pattern 5: URL + docstring + Smoke Test**
```swift
// https://mozilla.testrail.io/index.php?/cases/view/2307058
/**
 * Description of test
 */
// SmokeTest TAE
func testFeature() {
    // test code
}
```

#### Detection Algorithm (iOS)

The scanner searches upward from the test function declaration:

1. **Check immediate previous line**
   - If it's a TestRail URL → ✅ Linked
   - If it's empty → ❌ Missing
   - Otherwise, continue to step 2

2. **Check for Smoke markers or comments**
   - If previous line is `// Smoke` or `// SmokeTest`:
     - Start searching upward from the line before the Smoke marker
   - If previous line ends with `*/` (multi-line comment close):
     - Mark as inside multi-line comment block
   - If previous line starts with `*` (inside multi-line comment):
     - Mark as inside multi-line comment block

3. **Skip over comment blocks**
   - Skip empty lines
   - Skip single-line comments (`//`)
   - Skip multi-line comment blocks:
     - Continue until finding `/**` or `/*` (start of block)
     - Exit multi-line mode

4. **Find TestRail URL**
   - First non-comment line encountered must be TestRail URL → ✅ Linked
   - If encounter non-comment, non-URL line → ❌ Missing

#### Ignored Files (iOS)

The scanner automatically ignores:
- **Directories**: `ExperimentIntegrationTests/`, `PerformanceTests/`
- **File prefixes**: `A11y*`, `PerformanceTests*`, `ExperimentIntegrationTests*`
- **Specific files**: `ScreenGraphTest.swift`, `SiteLoadTest.swift`

### Android (Kotlin)

The scanner looks for functions annotated with `@Test` (any function name) and validates that a TestRail URL appears above the annotations.

#### Valid Patterns

**Pattern 1: Direct URL**
```kotlin
// TestRail link: https://mozilla.testrail.io/index.php?/cases/view/2833690
@Test
fun openURL() {
    // test code
}
```

**Pattern 2: URL + multiple annotations**
```kotlin
// TestRail link: https://mozilla.testrail.io/index.php?/cases/view/2833690
@SmokeTest
@Test
fun loginFlow() {
    // test code
}
```

**Pattern 3: URL + comments + annotations**
```kotlin
// TestRail link: https://mozilla.testrail.io/index.php?/cases/view/2833690
// Additional context about the test
@SmokeTest
@Test
fun verifySettings() {
    // test code
}
```

#### Detection Algorithm (Android)

The scanner processes files line-by-line:

1. **Find `@Test` annotation**
   - Mark `pending_test_annotation = True`
   - This indicates the next function should be validated

2. **Find function declaration**
   - Match any function: `fun functionName()`
   - **Important**: Function name doesn't need to start with "test"
   - Only process if `pending_test_annotation == True`

3. **Search upward for TestRail URL**
   - Start from line before the function
   - Skip upward through:
     - Empty lines
     - Annotations (lines starting with `@`)
     - Comments (lines starting with `//`)

4. **Validate TestRail URL**
   - First non-annotation, non-comment line must contain TestRail URL
   - If TestRail URL found → ✅ Linked
   - If encounter non-comment line without URL → ❌ Missing

#### Key Differences from iOS

- **Function naming**: Android tests can have any function name (`openURL()`, `verifyLogin()`), not just `test*`
- **Detection trigger**: Uses `@Test` annotation instead of function name prefix
- **Comment format**: Typically includes "TestRail link:" prefix in comment

#### Ignored Files (Android)

Currently no specific files are ignored for Android. Directories can be added to `ANDROID_IGNORED_DIRS` if needed.

## GitHub Action Workflow

The scanner runs automatically via GitHub Actions:

**Schedule**: Every Monday at 8:00 AM UTC
**Manual trigger**: Available via `workflow_dispatch`

### Workflow Features

- **Matrix strategy**: Runs iOS and Android scans in parallel
- **Independent execution**: iOS failure doesn't block Android (and vice versa)
- **Sparse checkout**: For Android, only clones necessary test directories
- **Slack notifications**: Sends alerts when missing URLs are detected (with platform-specific titles)
- **GitHub Summary**: Detailed report visible in Actions UI

### Repositories Scanned

**iOS**: `mozilla-mobile/firefox-ios` (main branch)
- Auto-discovers XCUITests directory using pattern: `*XCUITests*`
- Uses direct Git clone

**Android**: `mozilla-firefox/firefox` (GitHub mirror of Mozilla Central)
- Path: `mobile/android/fenix/app/src/androidTest/java/org/mozilla/fenix/ui`
- Uses sparse checkout for efficiency
- Downloads files from GitHub raw mirror when using searchfox URLs

### Workflow Configuration

The workflow uses a matrix strategy for parallel execution:

```yaml
matrix:
  include:
    - platform: ios
      repo: mozilla-mobile/firefox-ios
      repo_path: firefox-ios
      test_path_pattern: "*XCUITests*"
      platform_name: "iOS/Swift (XCUITests)"

    - platform: android
      repo: mozilla-firefox/firefox
      repo_path: firefox
      test_path: "mobile/android/fenix/app/src/androidTest/java/org/mozilla/fenix/ui"
      platform_name: "Android/Kotlin"
```

## Usage

### Run Locally

**iOS:**
```bash
python testrail_scan_missing_urls.py \
  --platform ios \
  --root /path/to/firefox-ios/XCUITests \
  --testrail-domain mozilla.testrail.io
```

**Android (local directory):**
```bash
python testrail_scan_missing_urls.py \
  --platform android \
  --root /path/to/fenix/ui/tests \
  --testrail-domain mozilla.testrail.io
```

**Android (with searchfox URL):**
```bash
python testrail_scan_missing_urls.py \
  --platform android \
  --root "https://searchfox.org/firefox-main/source/mobile/android/fenix/app/src/androidTest/java/org/mozilla/fenix/ui"
```

### Command Line Options

- `--platform`: **Required**. Must be `ios` or `android`
- `--root`: **Required**. Local file path or searchfox URL (Android only)
- `--testrail-domain`: **Optional**. Defaults to `mozilla.testrail.io` for Android, accepts any for iOS
- `--fail`: **Optional**. Exit with error code if missing URLs found (useful for CI)
- `--debug`: **Optional**. Print detailed debug information for each test

### Debug Mode

Use `--debug` to see detailed information about each test:

```bash
python testrail_scan_missing_urls.py \
  --platform ios \
  --root /path/to/tests \
  --debug
```

Output example:
```
[LINKED] TestFile.swift:42 testLogin
  prev1: // Smoke TAE
  prev2: // https://mozilla.testrail.io/...

[MISSING] TestFile.swift:67 testFeature
  prev1: <empty>
  prev2: }
```

## Dependencies

```bash
pip install requests
```

**Required for**:
- Fetching files from searchfox/GitHub mirror (Android)
- Also imported by iOS script (even though not used for local files)

## Implementation Details

### Regular Expressions

**iOS Swift:**
```python
SWIFT_TEST_FUNC_RE = re.compile(r"^\s*func\s+(test[A-Za-z0-9_]+)\s*\(")
```
- Matches functions starting with "test"

**Android Kotlin:**
```python
KOTLIN_TEST_FUNC_RE = re.compile(r"^\s*fun\s+([A-Za-z0-9_]+)\s*\(")
KOTLIN_TEST_ANNOTATION_RE = re.compile(r"^\s*@Test\b")
```
- Matches any function name
- Requires `@Test` annotation to identify as test

**Smoke Test marker:**
```python
SMOKE_RE = re.compile(r"^\s*//\s*smoke(test)?\b.*$", re.IGNORECASE)
```
- Matches both `// Smoke` and `// Smoketest`
- Case-insensitive

**TestRail URL detection:**
```python
def is_testrail_url_line(line: str, testrail_domain: str | None) -> bool:
    has_url = "http://" in line or "https://" in line
    if testrail_domain:
        return testrail_domain in line
    return "testrail" in line.lower()
```

### Searchfox Integration (Android)

When a searchfox URL is provided as `--root`:

1. **Parse searchfox URL** to extract path
2. **Fetch file list** from searchfox HTML
3. **Extract filenames** matching pattern (`*Test.kt`)
4. **Download each file** from GitHub mirror:
   - Converts: `searchfox.org/firefox-main/source/...`
   - To: `raw.githubusercontent.com/mozilla-firefox/firefox/main/...`
5. **Analyze in memory** (no temporary files created)

## Future Improvements

### Standardize iOS Format

Currently the scanner handles legacy formats with intermediate comments and multi-line docstrings. For better maintainability, consider standardizing to:

**Recommended format:**
```swift
// https://mozilla.testrail.io/index.php?/cases/view/XXXXXX
func testName() {
    // test code
}
```

**With Smoke marker:**
```swift
// https://mozilla.testrail.io/index.php?/cases/view/XXXXXX
// Smoke TAE
func testName() {
    // test code
}
```

**Best practice:** Move docstrings inside the function body rather than between the TestRail URL and function declaration.

### Android Improvements

Consider adding:
- Support for other test directories beyond `/ui`
- Specific file/directory ignore patterns as needed
- Detection of other test annotation types if needed

## Troubleshooting

### "Module 'requests' not found"

**Solution**: Install dependencies:
```bash
pip install requests
```

### "Found 0 files matching pattern"

**Android with searchfox**:
- Verify the searchfox URL is correct
- Check that the URL contains `/source/` in the path
- Ensure GitHub mirror is accessible

**iOS**:
- Verify the root path exists
- Check that path contains Swift files matching `*.swift`

### Tests not being detected

**iOS**:
- Verify function starts with `func test`
- Check that file is not in ignore list

**Android**:
- Verify function has `@Test` annotation above it
- Function name can be anything (doesn't need to start with "test")

### False positives (test marked as missing but has URL)

Check the format and position of the TestRail URL:
- **iOS**: URL must be in comment line above test (or above Smoke marker)
- **Android**: URL must be above all annotations (`@Test`, `@SmokeTest`, etc.)

Use `--debug` flag to see exactly what the scanner sees for each test.

## Files

- **`testrail_scan_missing_urls.py`**: Main scanner script
- **`.github/workflows/testrail-missing-links-slack.yml`**: GitHub Action workflow
- **`.github/slack/testrail-missing-links.json`**: Slack notification template
