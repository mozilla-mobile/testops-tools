# Play Developer Reporting API

Fetches Android vitals (crash rate, ANR rate, LMK rate) from Google's Play Developer Reporting API for Firefox Android packages.

## Setup
```bash
uv sync
```

## Auth
```bash
# CI/production — service account JSON key content as env var (preferred)
export GOOGLE_SA_VITALS_JSON='{"type":"service_account",...}'

# Alternative — service account JSON key file path
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa-key.json

# Interactive (local dev)
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/playdeveloperreporting
```

## Usage
```bash
# Crash rate with version resolution (default: last 1 day)
uv run src/fetch_metrics.py --package org.mozilla.firefox --metric-set crashrate --resolve-versions

# ANR rate, last 7 days, top 10 versions
uv run src/fetch_metrics.py --package org.mozilla.firefox --metric-set anrrate --days 7 --top 10 --resolve-versions

# LMK rate for beta
uv run src/fetch_metrics.py --package org.mozilla.firefox_beta --metric-set lmkrate --resolve-versions

# Anomaly detection (Google's 28-day baseline)
uv run src/fetch_metrics.py --package org.mozilla.firefox --anomalies --days 28

# JSON output (includes aggregate summary)
uv run src/fetch_metrics.py --package org.mozilla.firefox --metric-set anrrate --output-format json
```

## Packages

- `org.mozilla.firefox` — Firefox Release
- `org.mozilla.firefox_beta` — Firefox Beta
- `org.mozilla.fenix` — Firefox Nightly

## Metric sets

`crashrate`, `anrrate`, `lmkrate`, `excessivewakeuprate`, `stuckbackgroundwakelockrate`, `slowrenderingrate`, `slowstartrate`, `frozenframerate`

## Key details

- Version resolution maps Play Store version codes to Firefox release versions via Mozilla's release API
- `--resolve-versions` adds `firefoxVersion` and `cpuArch` columns
- Aggregate row uses weighted daily rates; console's headline number uses 28-day rolling averages with higher-precision user counts, so expect ~0.01-0.04% variance
- `distinctUsers` values from the API are rounded/bucketed by Google
- `--anomalies` uses Google's built-in anomaly detection, good for threshold-based Slack alerts
