---
name: xcuitest-review
description: Pre-commit / pre-PR review of XCUITest UI automation work in the firefox-ios repo. Checks Page Object compliance, selector reuse, test plan inclusion, pbxproj wiring, diff hygiene and PR template. Use before `git add`/commit or before opening the PR.
---

Review the pending XCUITest work against the checklist below. This is a **review**, not a fix:
report findings and let the user decide. Do not edit any file without explicit authorization.

## 0. Establish the diff

```bash
git status --short
git diff
git diff --stat
```

Untracked test files won't show in `git diff` — read them in full. Cover every changed file,
including ones the user added themselves (test plans, `project.pbxproj`).

**When the argument is a PR URL/number**, review the PR head, not the working tree:

```bash
gh pr view <N> --json title,body,files,statusCheckRollup
git fetch -q origin pull/<N>/head:pr-<N> && git fetch -q origin main
git diff origin/main...pr-<N>
git show pr-<N>:<path>        # read a file as it is on the PR head, for line numbers
```

Don't check out the PR branch; read files with `git show pr-<N>:<path>` so the user's working tree
is untouched.

## 1. Page Object compliance

- No raw element lookups (`app.buttons[...]`, `app.staticTexts[...]`, `app.tables[...]`) in the
  test file. Elements belong in `XCUITests/PageScreens/<Name>Screen.swift`, addressed through a
  selector.
- Every new selector lives in `XCUITests/Selectors/<Name>Selectors.swift` as: an entry in the
  `...SelectorsSet` protocol, the `let` in the struct, and **an entry in the `all` array**
  (easy to forget — the `all` array is what tooling iterates).
- Literal IDs/labels go in the private `IDs` enum, not inline in the `Selector` call.
- Screen objects are constructed in `setUp()`, not per test.

## 2. Selector reuse and correctness

- Search before adding: `grep -rn "SELECTOR_NAME\|<the label>" firefox-ios/firefox-ios-tests/Tests/XCUITests/Selectors/`.
  A selector that already exists must be reused rather than duplicated under a new name.
- **Collision risk on fragment matchers.** `staticTextLabelContains` matches substrings, so a
  selector for `"Mozilla"` also matches `"The Book of Mozilla"` and would make a tab-switching or
  navigation test pass for the wrong reason. Flag any `labelContains` whose fragment could match a
  different page in the same test.
- **Web view selectors must target visible content.** The accessibility tree only exposes the
  visible part of a web page. Text below the fold (e.g. a heading further down the page) does not
  exist for the test. Prefer text known to be on screen at the moment of the assertion.
- Prefer accessibility identifiers over user-facing labels; labels break under localization.

### Always go through a selector shortcut

`Selectors/SelectorShortcuts.swift` holds ~44 `static func` factories on `Selector`
(`buttonId`, `staticTextByExactLabel`, `staticTextLabelContains`, `tableIdOrLabel`, …). A selector
in a `*Selectors.swift` file must be built with one of them.

- A raw `Selector(strategy: .someCase(...), value:, description:, groups:)` written inline in a
  `*Selectors.swift` file is a finding. Check whether a shortcut already covers it:
  `grep -n "static func" firefox-ios/firefox-ios-tests/Tests/XCUITests/Selectors/SelectorShortcuts.swift`
- **If no shortcut fits, create it** rather than inlining the strategy — the shortcut is the shared
  vocabulary, and skipping it hides the new matcher from everyone else.
- If the underlying **strategy** doesn't exist either, it goes in `Selectors/SelectorHelper.swift`:
  a case in the `SelectorStrategy` enum, plus handling in **both** switches, `element(in:)` and
  `query(in:)`. Missing the second is a compile error, so it won't ship — but it is easy to
  half-write.
- Reach for the `.predicate` escape hatch only when the matcher is genuinely one-off; a matcher that
  a second test will want belongs in a shortcut.

**Watch the duplicate-name trap.** A `SelectorStrategy` case and a shortcut can share a name and
**not** behave the same. `staticTextLabelContains` exists as both, and they resolve differently:

| Form | Resolves to |
|---|---|
| shortcut `Selector.staticTextLabelContains(_:description:groups:)` | `.predicate(elementType == staticText AND label CONTAINS x)` |
| raw case `strategy: .staticTextLabelContains(x)` | `app.staticTexts.containing(predicate)` |

`.containing()` matches elements that have a *descendant* satisfying the predicate, which is broader
and usually not what was meant. The shortcut is the correct path. Distinguish them by the argument
labels at the call site: `description:`/`groups:` means the shortcut.

## 3. Shared code must be additive

- Existing `assert*` helpers in page objects are used by other test files. **Never rewrite one**
  to change its waiting or failure behaviour. If a caller needs to branch on the result, add a new
  non-failing variant (`-> Bool`, `failOnTimeout: false`) alongside it and leave the original
  untouched.
- Check the blast radius before accepting any change to a shared page object:
  `grep -rn "methodName" firefox-ios/firefox-ios-tests/Tests/XCUITests/`
- Deleting or renaming a shared helper needs the same check plus the user's authorization.

## 4. Duplication inside the new tests

- Is the same retry/wait/setup block repeated per test? It should be one private helper.
  Quick smell test: `grep -c "for _ in 0..<" <testfile>` should be 1, not N.
- Shared multi-step preambles (open page → bookmark it, open N tabs → select one) belong in a
  named private helper whose name states what it leaves behind.

## 5. Test integrity — would this test fail if the app broke?

The most common defect in UI automation is a test that is green for the wrong reason.

- Does the assertion actually distinguish success from failure? (A tab counter that stays `"1"`
  in private mode proves nothing about a private tab having opened.)
- If two shortcuts/actions are symmetric and both wrap around, does the fixture have enough state
  that swapping them would fail? (Three tabs starting at index 0, not two.)
- Do retries risk applying the action twice? A retry is only safe if it fires exclusively when the
  previous attempt had **no** effect. Where the action is not idempotent (bookmarking, adding an
  entry), assert the resulting count, not just existence.
- Any hardcoded `sleep`/`Thread.sleep` is a finding — use the `mozWaitFor*` helpers.

## 6. Test metadata

- TestRail case link as a comment above each test:
  `// https://mozilla.testrail.io/index.php?/cases/view/<id>`
- Sub-suite label on the next line (`// Smoketest`, `// Regression`) matching what TestRail says.
  The label is not decoration — it determines which test plan the test runs in, so a wrong or
  missing label and a mismatched plan entry are the same defect. Cross-check against §7.
- Test name describes the behaviour under test and matches the case. Check for typos and
  singular/plural drift against the run log if one exists.

## 7. Test plans

Plans live in `firefox-ios/firefox-ios-tests/Tests/*.xctestplan`.

- **The sub-suite label decides the plan, and the two main plans partition the suite.** Every test
  runs in exactly one of `Smoketest` / `FullFunctionalTestPlan`. Both use `skippedTests`, so
  membership is expressed by listing the test in the *other* plan's skip list:

  | Label in the test file | `Smoketest.xctestplan` | `FullFunctionalTestPlan.xctestplan` |
  |---|---|---|
  | `// Smoketest`  | not listed (runs) | **listed as skipped** |
  | `// Regression` | **listed as skipped** | not listed (runs) |

  Listed in neither → the test runs twice. Listed in both → it never runs. Check both plans, not
  one, and check them against the label rather than against each other.
- **Only `// Smoketest` tests are exercised by PR CI.** A `// Regression` test is not run by any
  PR check, so a green Bitrise run says nothing about it — it needs a local run (see §11).
- The remaining plans (`PerformanceTestPlan`, `AccessibilityTestPlan`, `SyncIntegrationTestPlan`,
  `ExperimentIntegrationTests`) need the new tests listed as skipped regardless of label. Verify
  each plan the user edited actually lists **every** new test method — a missing entry means the
  test runs in a plan whose launch arguments it was never designed for (`AccessibilityTestPlan`
  passes no launch arguments; `FullFunctionalTestPlan` passes `FIREFOX_CLEAR_PROFILE` and
  `FIREFOX_TEST`).
- **A new test class is not covered by an existing class-name skip.** Plans skip whole classes with
  a bare `"SomeTestClass"` entry. Splitting a test out into a new class silently opts it into every
  plan that skipped the original class — each one needs its own entry for the new name.
- Cross-check names: `grep -rn "<TestClassName>" firefox-ios/firefox-ios-tests/Tests/*.xctestplan`
  and diff that set against the `func test...` names in the file. Renaming a test after editing the
  plans silently orphans the skip entry.

## 8. Xcode project wiring

Only `Selectors/` and `PageScreens/` are `fileSystemSynchronizedGroups` in the XCUITests target.

- A **new file at the root of `XCUITests/`** needs 4 explicit entries in
  `firefox-ios/Client.xcodeproj/project.pbxproj`: `PBXBuildFile`, `PBXFileReference`, the group's
  `children`, and the target's `Sources` build phase. Verify all four exist and reference the
  XCUITests target (not Client):
  `grep -n "<FileName>.swift" firefox-ios/Client.xcodeproj/project.pbxproj`
- A new file inside `Selectors/` or `PageScreens/` needs **no** pbxproj change.
- Adding the file via Xcode is the reliable way to get these entries; hand-editing the pbxproj is a
  last resort and needs authorization.

## 9. Lint and style

- SwiftLint runs on build and on push. Limits that bite: `line_length` warning at **125**,
  `function_body_length` error at **108**.
- MPL license header on every new file (3-line form used across the repo).
- Comments to a strict minimum per `AGENTS.md`: keep them only where the code is non-obvious
  (why a retry exists, why a selector targets an unexpected string). Delete narration of what the
  code plainly does. Never delete a pre-existing comment unrelated to the change.

## 10. Diff hygiene

- Leftover diagnostics: `grep -n "print(\|NSLog\|XCTContext\|debugPrint" <changed files>`
- Commented-out code, `TODO`, temp files, `.xcresult`, logs in the repo.
- Unrelated churn in `project.pbxproj` (Xcode alphabetically reorders pre-existing entries when a
  file is added). Report it as cosmetic, not as something that must be fixed.
- Nothing outside the ticket's scope. App/product source changes in a test-automation ticket are a
  finding unless the ticket asked for them.

## 11. Verification status

Ask/confirm rather than assume:

- Have all the new tests passed, in the same run, after the **last** code change? A refactor that
  touched every test invalidates any earlier green run.
- Both iPhone **and** iPad, since layout differs.
- **A green PR CI run does not cover a `// Regression` test** — Bitrise runs `Smoketest`, which
  lists Regression tests as skipped. Never cite passing checks as evidence for one; ask for the
  local run. The same applies to any pre-existing test the change affects but the plan skips.
- If the tests use hardware keyboard shortcuts, the simulator needs "Connect Hardware Keyboard"
  enabled, and CI parity should be called out in the PR description.

Report which tests were verified where, and say plainly if something is unverified.

## 12. PR readiness (when opening the PR)

- Use `PULL_REQUEST_TEMPLATE` from the repo root, filling in the relevant sections and deleting
  unused markup.
- Jira ticket number, and the **GitHub issue number from the bottom of the JIRA ticket**.
- PR name follows the repo's PR naming guide.
- Description explains any non-obvious mechanism a reviewer will question (e.g. why a retry loop
  exists at all).

## Output

Report findings grouped as:

- **Blocking** — would break the build, break CI, or make a test pass for the wrong reason.
- **Should fix** — duplication, scope creep in shared code, missing metadata.
- **Optional** — cosmetic diff noise, style nits.

### Location and comment text for every finding

Each finding goes in the chat with its exact location and a comment the user can paste themselves:

- `path/File.swift:LINE` (or `:START-END`), with line numbers taken from the **PR head / working
  tree** (`git show pr-<N>:<path> | grep -n ...`), never from `main` or from diff hunk offsets.
- **Where the comment belongs**, so the user knows where to paste it:
  - **On `File.swift:LINE`** when that line is in the diff (GitHub only accepts line comments on
    changed lines and the few context lines around them).
  - **On a nearby changed line, mentioning the real line** when the problem is in unchanged code
    next to the change (e.g. the same race in another test of the same file).
  - **General PR comment** for the title, description, verification requests and anything not
    tied to a line.
- A ready-to-paste comment in English: short, stating the problem and the suggested fix.

End the report with a table: `# | Severity | File:line | Where to comment`.

Before reporting how a helper behaves (fails on timeout, retries, is idempotent), read its body on
the PR head. Don't infer it from its name or from a partial read.

**Never write to GitHub from this skill**: no PR comments, reviews, approvals, labels or edits, and
don't offer to post them. Read-only `gh`/`git fetch` to get the diff is fine. All findings and
comment texts are delivered in the chat only.

State explicitly what you checked and found clean. If nothing is blocking, say so. Then stop —
propose the fixes and wait for authorization before editing anything.
