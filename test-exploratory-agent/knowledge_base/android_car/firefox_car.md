---
app: Firefox for Android Automotive (pilot)
package: org.mozilla.firefox
last_verified: 2026-08-05
verified_by: manual observation (pilot)
notes: |
  Pilot build — main surfaces still being explored. Not automatically
  selected: --knowledge android_car is required to load this file.
---

# Firefox for Android Car — App Knowledge Base

## App overview
- Package: `org.mozilla.firefox` (same as Android release — distinguish via --knowledge android_car)
- Pilot build optimized for Android Automotive OS
- Main surfaces: differ from standard Android Firefox — update after initial exploration

---

## Important differences from Firefox Android

- To navigate to a URL use the `type_url` action — it handles focus, typing, and submitting in one step. Do NOT use `type_text` + Enter to navigate
- No standard keyboard may be available — do NOT rely on typing URLs directly
- Voice search button is present in the URL bar but opens a system dialog you cannot dismiss by tapping or swiping — use the `press_back` action (not swipe) to dismiss it
- Some features may be intentionally disabled for driver safety (e.g. text input while driving)
- Tab management and private browsing availability: unknown — verify on first run

---

## Known constraints (automotive context)
- Screen is a car display — interaction model differs significantly from phones
- If a system dialog appears (e.g. voice, permissions), always use the `press_back` action to dismiss it — do NOT use swipe or tap

---

## Business rules
TODO: fill in after initial exploration sessions.

---

## Accessibility identifiers
TODO: fill in real accessibility IDs observed from the live accessibility tree.
Run the agent once with --knowledge android_car and check the logs.
