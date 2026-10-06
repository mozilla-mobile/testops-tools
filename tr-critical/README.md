# tr-critical

Tracks automation of the critical (Regression) test suite for Firefox for
Android and iOS in TestRail, and publishes a staff-only dashboard to Quick at
https://mte-testrail-critical.quick.mozilla.cloud/.

## How it runs

`.github/workflows/tr-critical-dashboard.yml` runs weekday mornings:

1. Restores yesterday's `metrics.csv` and `tr-state.json` from the Quick site.
2. Runs `tr-critical.py`, which adds today's row and writes `latest.json`.
3. Deploys `site/` to Quick.

The history lives on the site, which is staff-only. Nothing is committed back
to this repo because it is public. For the same reason the run keeps the
report, which lists case IDs and titles, out of the Actions log.

If the restore step can't read the history, the run stops before deploying,
so a failed read can't wipe the history. The first deploy is the exception:
run the workflow manually with `bootstrap` ticked.

## Run locally

    export TESTRAIL_HOST=mozilla.testrail.io
    export TESTRAIL_USERNAME=you@mozilla.com
    export TESTRAIL_PASSWORD=<api key>
    pip install requests
    python tr-critical.py

Useful flags: `--csv`, `--json`, `--state`, `--no-state` (an ad-hoc run that
won't become the comparison point), `--show-repeats`, `--discover` (list
TestRail field names).

## What counts

- **Critical**: in the Regression sub-suite, any type.
- **Automatable**: critical minus cases flagged Unsuitable. The denominator.
- **Automated**: Automation field is Completed, in any framework.
- **In TAE**: automated and labelled TAE. Automated without the label is legacy.
