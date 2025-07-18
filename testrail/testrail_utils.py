#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
This script contains utility functions designed to support the integration of automated
testing processes with TestRail, a test case management tool. The primary focus is on
creating and managing milestones in TestRail based on automated smoke tests for product
releases. It includes functions for building milestone names and descriptions, determining
release types, and loading TestRail credentials.

Functions:
- build_milestone_name(product_type, release_type, version_number): Constructs a formatted
  milestone name based on the product type, release type, and version number.
- build_milestone_description(milestone_name): Generates a detailed description for the
  milestone, including the release date and placeholders for testing status and QA recommendations.
- get_release_version(): Reads and returns the release version number from a 'version.txt' file.
- get_release_type(version): Determines the release type (e.g., Alpha, Beta, RC) based on
  the version string.
- load_testrail_credentials(json_file_path): Loads TestRail credentials from a JSON file
  and handles potential errors during the loading process.
- get_release_version_ios(release_tag): Reads and returns the release version from the release tag.
"""

import json
import os
import textwrap
from datetime import datetime


def build_milestone_name(product_type, release_type, version_number):
    return f"Build Validation sign-off - {product_type} {release_type} {version_number}"


def build_milestone_description(milestone_name):
    current_date = datetime.now()
    formatted_date = current_date = current_date.strftime("%B %d, %Y")
    return textwrap.dedent(
        f"""
        RELEASE: {milestone_name}\n\n\
        RELEASE_TAG_URL: https://archive.mozilla.org/pub/fenix/releases/\n\n\
        RELEASE_DATE: {formatted_date}\n\n\
        TESTING_STATUS: [ TBD ]\n\n\
        QA_RECOMMENDATION:[ TBD ]\n\n\
        QA_RECOMENTATION_VERBOSE: \n\n\
        TESTING_SUMMARY\n\n\
        Known issues: n/a\n\
        New issue: n/a\n\
        Verified issue:
    """
    )


def get_release_version():
    # Check if version.txt was found
    version_file_path = os.path.join(
        os.environ.get("GECKO_PATH", "."), "mobile", "android", "version.txt"
    )
    if not os.path.isfile(version_file_path):
        raise FileNotFoundError(f"{version_file_path} not found.")

    # Read the version from the file
    with open(version_file_path, "r") as file:
        version = file.readline().strip()

    return version


def get_release_type(version):
    release_map = {"a": "Alpha", "b": "Beta"}
    # use generator expression to check each char for key else default to 'RC'
    product_type = next(
        (release_map[char] for char in version if char in release_map), "RC"
    )
    return product_type


def load_testrail_credentials(json_file_path):
    try:
        with open(json_file_path, "r") as file:
            credentials = json.load(file)
        return credentials
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to load TestRail credentials: {e}")

def get_release_version_ios(release_tag):
    if release_tag and 'v' in release_tag:
        version = release_tag.split('v')[-1]  # e.g., "140.0b2"
    else:
        version = None
    return version

def build_milestone_description_ios(milestone_name):
    current_date = datetime.now()
    formatted_date = current_date = current_date.strftime("%B %d, %Y")
    return textwrap.dedent(
        f"""
        RELEASE: {milestone_name}\n\n\
        RELEASE_TAG_URL: https://github.com/mozilla-mobile/firefox-ios/releases/\n\n\
        RELEASE_DATE: {formatted_date}\n\n\
        TESTING_STATUS: [ TBD ]\n\n\
        QA_RECOMMENDATION: [ TBD ]\n\n\
        QA_RECOMENTATION_VERBOSE: \n\n\
        TESTING_SUMMARY\n\n\
        Known issues: n/a\n\
        New issue: n/a\n\
        Verified issue:
    """
    )

def create_paginated_test_runs(
    self,
    project_id,
    suite_id,
    release_version_id,
    milestone_id,
    base_run_name,
    device_name,
    case_ids,
    status_id=1,  # default to Passed
    max_cases_per_run=250
):
    """
    Crete one or more test runs if the number of test cases is greater than 250 
     (Test rail API limit).

    Args:
        project_id (int): ID of the project.
        suite_id (int): ID of the test suite.
        milestone_id (int): ID of the milestone.
        base_run_name (str): Common Prefix for all the test runs.
        device_name (str): Device name (to include in the name of the test run).
        case_ids (list): List of the IDs of the test cases to include in the test run.
        status_id (int): Result to apply by default to the test cases (default: 1 = Passed).
        max_cases_per_run (int): Límit for the test cases for each run (default: 250).
    """
    def chunk_case_ids(case_ids, size):
        for i in range(0, len(case_ids), size):
            yield case_ids[i:i + size]

    for index, chunk in enumerate(chunk_case_ids(case_ids, max_cases_per_run)):
        run_name = f"{base_run_name} - {release_version_id} - {device_name} (part {index + 1})" if len(case_ids) > max_cases_per_run else f"{base_run_name} - {device_name}"
        
        test_run = self.client.send_post(f"add_run/{project_id}", {
            "name": run_name,
            "milestone_id": milestone_id,
            "suite_id": suite_id,
            "include_all": False,
            "case_ids": chunk
        })

        self.update_test_run_tests(test_run["id"], status_id)
