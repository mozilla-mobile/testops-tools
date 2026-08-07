// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at http://mozilla.org/MPL/2.0/

import XCTest

class SampleFeatureTests: BaseTestCase {
    override func setUp() async throws {
        try await super.setUp()
    }

    // https://mozilla.testrail.io/index.php?/cases/view/1000001
    func testBookmarkCanBeAdded() {
        navigator.nowAt(NewTabScreen)
        navigator.goto(LibraryPanel_Bookmarks)
        navigator.performAction(Action.AddNewBookmark)
    }

    // https://mozilla.testrail.io/index.php?/cases/view/1000002
    func testHistoryListShows() throws {
        navigator.goto(LibraryPanel_History)
    }

    // A test that reports success having asserted nothing on older OSes - the
    // same shape as an all-@Ignore'd Android class.
    // https://mozilla.testrail.io/index.php?/cases/view/1000003
    func testNewToolbarOnly() throws {
        guard #available(iOS 17.0, *), !skipPlatform else { return }
        navigator.goto(ToolbarSettings)
    }

    // https://mozilla.testrail.io/index.php?/cases/view/1000004
    func testExplicitlySkipped() throws {
        throw XCTSkip("blocked on FXIOS-1234")
    }

    func testWithoutATestRailCase() {
        navigator.goto(SettingsScreen)
    }

    // Not a test: no `test` prefix, so XCTest ignores it and so must we.
    func helperThatLooksLikeATest() {
        navigator.goto(SettingsScreen)
    }
}
