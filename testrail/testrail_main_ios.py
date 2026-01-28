#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
This Python script automates creating milestones and test runs in TestRail and updating
test cases based on the results of automated smoke tests for different product releases.

Functionality includes:
- Reading TestRail credentials and environment variables.
- Building milestone names and descriptions.
- Interacting with the TestRail API to create milestones, test runs, and update test cases.
- Sending notifications to a specified Slack channel.
"""

import os
import re
import sys

from testrail_api import TestRail

from testrail_utils import (
    build_milestone_description_ios,
    build_milestone_name,
    get_release_type,
    get_release_version_ios,
    load_testrail_credentials
)

from slack_notifier import (
    send_error_notification_ios,
    send_success_notification_ios
)

# Constants
SUCCESS_CHANNEL_ID = "C07HUFVU2UD"  # mobile-testeng-releases
ERROR_CHANNEL_ID = "CAFC45W5A"  # mobile-alerts-ios

SLACK_MOBILE_TESTENG_RELEASE_CHANNEL = os.environ.get("SLACK_MOBILE_TESTENG_RELEASE_CHANNEL")
SLACK_MOBILE_ALERTS_IOS_CHANNEL = os.environ.get("SLACK_MOBILE_ALERTS_IOS_CHANNEL")

if not SLACK_MOBILE_TESTENG_RELEASE_CHANNEL:
    raise ValueError("SLACK_MOBILE_TESTENG_RELEASE_CHANNEL not defined in the environment variable.")

if not SLACK_MOBILE_ALERTS_IOS_CHANNEL:
    raise ValueError("SLACK_MOBILE_ALERTS_IOS_CHANNEL not defined in the environment variable.")


def main():
    # Load TestRail credentials
    credentials = load_testrail_credentials(".testrail_credentials.json")
    testrail = TestRail(
        credentials["host"], credentials["username"], credentials["password"]
    )

    # Read task environment variables
    try:
        release_tag = os.environ["RELEASE_TAG"]
        release_name = os.environ["RELEASE_NAME"]
        # Try to extract "build N" from RELEASE_NAME, e.g.
        # "Build Validation sign-off - Firefox RC 145.3 build 4"
        build_number = None
        m = re.search(r"\bbuild\s+(\d+)\b", release_name, re.IGNORECASE)
        if m:
            build_number = int(m.group(1))
        print(f"Parsed build_number: {build_number!r}")
    except KeyError as e:
        raise ValueError(f"ERROR: Missing Environment Variable: {e}")
    
    if any(keyword in release_name.lower() for keyword in ("focus", "klar")) \
            or any(keyword in release_tag.lower() for keyword in ("focus", "klar")):
        shipping_product = "focus"
        testrail_product_type = "Focus"
        testrail_project_id = "27"
        testrail_test_suite_id = "5291"
    elif release_name.lower().startswith("firefox") or release_tag.lower().startswith("firefox-"):
        shipping_product = "firefox"
        testrail_product_type = "Firefox"
        testrail_project_id = "14"
        testrail_test_suite_id = "45443"
    else:
        raise Exception(f"Unrecognized release name: {release_name} or tag: {release_tag}")


    # Release information
    release_version = get_release_version_ios(release_tag)
    release_type = get_release_type(release_version)

    # Build milestone information
    milestone_name = build_milestone_name(
        testrail_product_type, release_type, release_version
    )
    # If this is RC2/RC3/... and we detected a build number, append it
    if build_number and build_number > 1:
        milestone_name = f"{milestone_name} build {build_number}"

    print(f"Final milestone_name: {milestone_name!r}")
    milestone_description = build_milestone_description_ios(milestone_name)

    try:
        # Check if milestone exists
        if testrail.does_milestone_exist(testrail_project_id, milestone_name):
            print(f"Milestone for {milestone_name} already exists. Exiting script...")
            # Exit with code 2 to indicate milestone already exists (not an error, but should skip tests)
            sys.exit(2)
        print(f"Create Milestone for {milestone_name}")

        # Create milestone and test runs
        devices = ["iPhone 17 (iOS 26.2)", "iPad mini (6th generation) (iOS 26.2)"]
        smoke_filters = {
            "custom_automation_status": 4, # Automation = Completed
            "custom_automation_coverage": 3, # Automation Coverage = Full
            "custom_sub_test_suites": lambda v: set(v or []) == {1, 2} # Suite Functional & Smoke&Sanity
        }

        smoke_case_ids = testrail.get_case_ids_by_multiple_custom_fields(
            testrail_project_id,
            testrail_test_suite_id,
            smoke_filters
        )

        # Filters for Full Functional Tests Suite (Functional only)
        functional_filters = {
            "custom_automation_status": 4, # Automation = Completed
            "custom_automation_coverage": 3, # Automation Coverage = Full
            "custom_sub_test_suites": lambda v: set(v or []) == {1} # Suite Functional only
        }

        functional_case_ids = testrail.get_case_ids_by_multiple_custom_fields(
            testrail_project_id,
            testrail_test_suite_id,
            functional_filters
        )

        milestone = testrail.create_milestone(
            testrail_project_id, milestone_name, milestone_description
        )

        for device in devices:
            # Create Smoke Tests Suite test runs     
            testrail.create_paginated_test_runs(
                project_id=testrail_project_id,
                suite_id=testrail_test_suite_id,
                release_version_id = release_version,
                milestone_id=milestone["id"],
                base_run_name="Smoke Tests Suite",
                device_name=device,
                case_ids=smoke_case_ids
            )

            # Create Full Functional Tests Suite test runs
            testrail.create_paginated_test_runs(
                project_id=testrail_project_id,
                suite_id=testrail_test_suite_id,
                release_version_id = release_version,
                milestone_id=milestone["id"],
                base_run_name="Full Functional Tests Suite",
                device_name=device,
                case_ids=functional_case_ids
            )

        if build_number and build_number > 1:
            slack_release_version = f"{release_version} build {build_number}"
        else:
            slack_release_version = release_version

        # Send success notification
        success_values = {
            "RELEASE_TYPE": release_type,
            "RELEASE_VERSION": slack_release_version,
            "SHIPPING_PRODUCT": shipping_product,
            "TESTRAIL_PROJECT_ID": testrail_project_id,
            "TESTRAIL_PRODUCT_TYPE": testrail_product_type,
        }
        send_success_notification_ios(success_values, SLACK_MOBILE_TESTENG_RELEASE_CHANNEL)
    except Exception as error_message:
        send_error_notification_ios(str(error_message), SLACK_MOBILE_ALERTS_IOS_CHANNEL)

if __name__ == "__main__":
    main()
