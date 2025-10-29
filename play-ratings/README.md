# Google Play Store Rating Monitor

Monitors Firefox and Focus Android apps Play Store ratings every few hours and sends Slack notifications when ratings drop.

## Monitored Apps

- Firefox Release (`org.mozilla.firefox`)
- Firefox Beta (`org.mozilla.firefox_beta`)
- Firefox Nightly (`org.mozilla.fenix`)
- Firefox Focus (`org.mozilla.focus`)

## Files

- `.github/workflows/monitor-ratings.yml` - Main workflow with matrix
- `check_ratings.py` - Fetches and compares ratings from Google Play
- `post_slack.py` - Sends Slack notifications

## Behavior

| Scenario | Action |
|----------|--------|
| Rating drops (4.6 → 4.5) | Send Slack notification |
| Rating increases (4.5 → 4.6) | Silent, update cache |
| Rating unchanged | Silent, update cache |
| First run | Store initial rating |
