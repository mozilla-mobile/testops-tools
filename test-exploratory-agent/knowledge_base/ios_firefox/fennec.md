---
app: Firefox iOS Nightly
bundle_id: org.mozilla.ios.Fennec
last_verified: 2026-08-05
verified_by: manual observation
notes: |
  No CI captures a specific build/commit — treat menu layouts and
  accessibility IDs as suggestions. Verify against the live accessibility
  tree if the app has updated since last_verified.
---

# Fennec (Firefox iOS Nightly) — App Knowledge Base

## App overview
- Bundle ID: `org.mozilla.ios.Fennec`
- This is Firefox Nightly for iOS (internal build, not public App Store)
- Main surfaces: Browser tabs, URL bar, Tab tray, Menu, Settings, Private browsing

---

## Feature map (use this to navigate)

### URL Bar / Navigation
- Tap URL bar to enter edit mode → keyboard appears
- Accepts URLs and search queries
- Shows lock icon for HTTPS, warning for HTTP
- Long press → paste & go option
- Back/Forward buttons in toolbar

### Tab management
- Tab counter button (top right) → opens Tab tray
- Tab tray shows thumbnails of all open tabs
- Swipe tab left/right to close
- New tab button in Tab tray
- Private tabs are completely separate from normal tabs

### Private browsing
- Toggle via Menu → "Private Browsing" OR via Tab tray → mask icon
- Visual indicator: dark/purple theme when active
- History is NOT saved in private mode
- Cookies and cache cleared when private session ends
- Private tabs do NOT appear in normal tab tray
- Downloads in private mode: deleted on session close

### CRITICAL: How to enter private mode and navigate to a URL
There is ONE correct flow — use ONLY this:

**Flow A (Tab Tray — the only supported flow):**
1. Tap `TabToolbar.tabsButton` → Tab Tray opens
2. Tap `selectorCell0` (Private) → switches to Private tab section
3. Tap `newTabButtonTabTray` (Add Tab) → creates a new private tab, lands in the private browser
4. You are now in private mode. `PrivateMode.Homepage.MessageCard` is visible.
5. Tap `AddressToolbar.address` → use `type_url` to navigate to a URL

### CRITICAL: Main Menu does NOT have "New Private Tab"
The Main Menu (TabToolbar.menuButton) contains ONLY these items:
- MainMenu.BookmarkPage, MainMenu.FindInPage, MainMenu.DesktopSite
- MainMenu.MoreLess (expands to: Zoom, NightModeOn, AddToShortcuts, SaveAsPDF, Print, Share)
- MainMenu.History, MainMenu.Downloads, MainMenu.Passwords, MainMenu.Bookmarks
- MainMenu.SignIn, MainMenu.Settings
There is NO "New Private Tab" option anywhere in the menu. Do NOT search for it. Do NOT scroll looking for it.

### CRITICAL: How to check history isolation (the actual test)
After navigating to a URL in private mode:
1. Tap `TabToolbar.menuButton` → Main Menu opens
2. Tap `MainMenu.History` → History panel opens
3. Look at the list of visited URLs. The URL you visited in private mode must NOT appear here.
4. If the URL is absent → private browsing isolation is working correctly ✅
5. If the URL is present → this is a bug, report it immediately ❌

### CRITICAL: Common mistakes that cause infinite loops
- ❌ WRONG: Tab Tray → selectorCell0 → doneButtonTabTray → (back to normal browser, NOT private mode)
  - `doneButtonTabTray` with no private tab open returns to NORMAL browser.
  - You MUST tap `newTabButtonTabTray` first to create a private tab.
- ❌ WRONG: Opening the Tab Tray when `AddressToolbar.address` is visible.
  - If `AddressToolbar.address` is in the tree, you are in the browser. Tap it and navigate. Do not open the Tab Tray.
- ❌ WRONG: Thinking you left private mode because the web page has a white/light background.
  - Web page content always looks normal (white background). The dark/purple private theme only applies to Firefox's own UI (homepage, tab tray). After `type_url` succeeds from private mode, you ARE still in private mode.
- ✅ You are in private mode if: `PrivateMode.Homepage.MessageCard` was visible before navigation, OR the Tab Tray shows a tab under `selectorCell0` (Private section).
- ✅ You are in the browser (not Tab Tray) if: `AddressToolbar.address` is visible in the tree.

### Settings
- Search engine selection (Google default)
- Tracking protection: Standard / Strict / Custom
- Privacy settings
- Sync (Firefox account)
- Notifications
- Siri shortcuts
- Theme: Light / Dark / System

### Downloads
- Tap downloadable link → download prompt
- Files saved to iOS Files app
- In private mode: files deleted on session close
- Download indicator in toolbar while in progress

### Reading list / Bookmarks
- Save via Menu → "Add to Reading List"
- Access via Library icon (book icon in toolbar)
- Offline reading supported for saved articles

---

## Business rules by feature

### Private browsing rules (HIGH PRIORITY)
1. History MUST NOT persist after closing private session
2. Cookies from private session MUST NOT be visible in normal mode
3. Tab counter for private and normal tabs must be separate and accurate
4. Purple mask icon MUST always be visible when in private mode
5. Opening a link from another app while in private mode should NOT expose private session content
6. Settings are shared between private and normal mode

### Tab management rules
1. Tab counter MUST match actual number of open tabs (common bug area)
2. Closing last tab should not crash — should show empty state
3. Tab thumbnails must reflect actual page content, not a blank/stale state

### Navigation rules
1. Back button must be disabled on first page of a new tab (no history)
2. Loading indicator must appear for slow pages and disappear on completion
3. HTTPS padlock must show for secure sites, warning for mixed content

### Search rules
1. URL input field must differentiate between URL (navigate) and search query (search engine)
2. Search suggestions must appear after 2+ characters
3. Private mode search must not leak to normal history

---

## Known fragile areas (explore carefully)
- Tab counter after rapid open/close sequences
- Private mode after app backgrounding + foregrounding
- PDF rendering via "Open in Browser"
- Rotation (landscape/portrait) in tab tray
- Deep links from external apps into private mode

---

## Accessibility identifiers (common elements)
These are real accessibility IDs observed in the app:
- URL bar: `url`, `address`, `Search or enter address`
- Tabs button: `Show Tabs`, `TabToolbar.tabsButton`
- New tab: `New Tab`
- Private mode toggle: `Private Browsing`
- Menu: `TabToolbar.menuButton`, `Menu`
- Back: `Back`
- Forward: `Forward`
- Reload: `Reload`

*Note: accessibility IDs can change between builds. Always verify from the live accessibility tree.*
