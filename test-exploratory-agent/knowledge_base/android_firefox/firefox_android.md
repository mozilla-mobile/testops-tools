---
app: Firefox for Android (Fenix / Firefox / Firefox Beta)
package: org.mozilla.fenix | org.mozilla.firefox | org.mozilla.firefox_beta
main_activity: org.mozilla.firefox.App
last_verified: 2026-08-05
verified_by: manual observation
notes: |
  Knowledge base is intentionally minimal — populate after real Android
  sessions expose accessibility IDs. No CI captures a specific build.
---

# Firefox for Android — App Knowledge Base

## App overview
- Package: `org.mozilla.firefox` (Release) / `org.mozilla.fenix` (Nightly) / `org.mozilla.firefox_beta` (Beta)
- Main activity: `org.mozilla.firefox.App`
- Main surfaces: Browser tabs, URL bar, Tab tray, Menu, Settings, Private browsing

---

## Feature map (use this to navigate)

### URL Bar / Navigation
- Tap URL bar to enter edit mode → keyboard appears
- Accepts URLs and search queries
- Back/Forward buttons in toolbar
- Reload button in URL bar

### Tab management
- Tab counter button → opens Tab tray
- Tab tray shows all open tabs
- Swipe tab to close
- Private tabs are completely separate from normal tabs

### Private browsing
- Toggle via Tab tray → private mode button
- Visual indicator: dark/purple theme when active
- History is NOT saved in private mode
- Cookies and cache cleared when private session ends

### Menu (three-dot)
- Bookmarks
- History
- Downloads
- Add to home screen
- Find in page
- Desktop site
- Settings

### Settings
- Search engine selection
- Tracking protection
- Privacy settings
- Sync (Firefox account)
- Notifications
- Theme: Light / Dark / System

### Downloads
- Tap downloadable link → download prompt
- Files saved to device Downloads folder
- In private mode: files deleted on session close

---

## Business rules by feature

### Private browsing rules (HIGH PRIORITY)
1. History MUST NOT persist after closing private session
2. Cookies from private session MUST NOT be visible in normal mode
3. Tab counter for private and normal tabs must be separate and accurate

### Tab management rules
1. Tab counter MUST match actual number of open tabs
2. Closing last tab should not crash — should show empty state

### Navigation rules
1. Back button must be disabled on first page of a new tab
2. Loading indicator must appear for slow pages and disappear on completion
3. HTTPS padlock must show for secure sites

### Search rules
1. URL input field must differentiate between URL and search query
2. Search suggestions must appear after 2+ characters
3. Private mode search must not leak to normal history

---

## Known fragile areas (explore carefully)
- Tab counter after rapid open/close sequences
- Private mode after app backgrounding + foregrounding
- PDF rendering
- Rotation in tab tray

---

## Accessibility identifiers
TODO: fill in real accessibility IDs observed from the live accessibility tree.
Run the agent once and check the logs to capture real element names.

*Note: accessibility IDs can change between builds. Always verify from the live accessibility tree.*
