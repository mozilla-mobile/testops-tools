#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
This module provides a TestRail class for interfacing with the TestRail API, enabling the creation and management of test milestones, test runs, and updating test cases. It facilitates automation and integration of TestRail functionalities into testing workflows, particularly for projects requiring automated test management and reporting.

The TestRail class encapsulates methods to interact with TestRail's API, including creating milestones and test runs, updating test cases, and checking the existence of milestones. It also features a method to retry API calls, enhancing the robustness of network interactions.

Key Components:
- TestRail Class: A class providing methods for interacting with TestRail's API.
  - create_milestone: Create a new milestone in a TestRail project.
  - create_milestone_and_test_runs: Create a milestone and associated test runs for multiple devices in a project.
  - create_test_run: Create a test run within a TestRail project.
  - does_milestone_exist: Check if a milestone already exists in a TestRail project.
  - update_test_cases_to_passed: Update the status of test cases to 'passed' in a test run.
- Private Methods: Utility methods for internal use to fetch test cases, update test run results, and retrieve milestones.
- Retry Mechanism: A method to retry API calls with a specified number of attempts and delay, improving reliability in case of intermittent network issues.

Usage:
This module is intended to be used as part of a larger automated testing system, where integration with TestRail is required for test management and reporting.

"""

import json
import os
import sys
import time

# Ensure the directory containing this script is in Python's search path
script_directory = os.path.dirname(os.path.abspath(__file__))
if script_directory not in sys.path:
    sys.path.append(script_directory)

from testrail_conn import APIClient


class TestRail:
    def __init__(self, host, username, password):
        if not all([host, username, password]):
            raise ValueError("TestRail host, username, and password must be provided.")
        self.client = APIClient(host)
        self.client.user = username
        self.client.password = password

    # Public Methods

    def create_milestone(self, project_id, title, description):
        if not all([project_id, title, description]):
            raise ValueError("Project ID, title, and description must be provided.")
        data = {"name": title, "description": description}
        return self.client.send_post(f"add_milestone/{project_id}", data)

    def create_test_run(
        self,
        project_id,
        milestone_id,
        test_run_name,
        suite_id,
    ):
        if not all([project_id, milestone_id, test_run_name, suite_id]):
            raise ValueError(
                "Project ID, milestone ID, test run name, and suite ID must be provided."
            )
        data = {
            "name": test_run_name,
            "milestone_id": milestone_id,
            "suite_id": suite_id,
        }
        return self.client.send_post(f"add_run/{project_id}", data)

    def does_milestone_exist(self, project_id, milestone_name, num_of_milestones=20):
        """
        Check if a milestone with a specific name exists in the last 'num_of_milestones'
        milestones, paginating through the milestones as needed.

        Args:
            project_id (int): ID of the project.
            milestone_name (str): Name of the milestone to search for.
            num_of_milestones (int): Number of milestones to check (default is 20).

        Returns:
            bool: True if the milestone exists, False otherwise.
        """
        if not all([project_id, milestone_name]):
            raise ValueError("Project ID and milestone name must be provided.")

        limit = 250
        offset = 0

        while True:
            # Fetch the milestones page by page, with a limit and offset
            milestones = self._get_milestones(project_id, limit, offset).get(
                "milestones", []
            )

            # If there are no more milestones, return False
            if not milestones:
                return False

            # Check if the milestone exists in the last 'num_of_milestones' milestones
            if any(
                milestone_name == milestone["name"]
                for milestone in milestones[-num_of_milestones:]
            ):
                return True

            # If there are more milestones, increment the offset to fetch the next page
            offset += limit

            # If the number of milestones returned is less than the limit, it's the last page
            if len(milestones) < limit:
                return False

    def update_test_run_tests(self, test_run_id, test_status):
        if not all([test_run_id, test_status]):
            raise ValueError("Test run ID and test status must be provided.")
        tests = self._get_tests(test_run_id)
        data = {
            "results": [
                {"test_id": test["id"], "status_id": test_status} for test in tests
            ]
        }
        return self.client.send_post(f"add_results/{test_run_id}", data)
    
    def get_case_ids_by_multiple_custom_fields(self, project_id, suite_id, filters):
        filtered_cases = self._get_test_cases_by_multiple_custom_fields(
            project_id, suite_id, filters
        )
        return [case["id"] for case in filtered_cases]
    
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



    # Private Methods

    def _get_test_cases(self, project_id, suite_id):
        if not all([project_id, suite_id]):
            raise ValueError("Project ID and suite ID must be provided.")
        return self.client.send_get(f"get_cases/{project_id}&suite_id={suite_id}")[
            "cases"
        ]

    def _get_test_cases_with_pagination(self, project_id, suite_id):
        if not all([project_id, suite_id]):
            raise ValueError("Project ID and suite ID must be provided.")

        all_cases = []
        limit = 250
        offset = 0

        while True:
            endpoint = f"get_cases/{project_id}&suite_id={suite_id}&limit={limit}&offset={offset}"
            response = self.client.send_get(endpoint)

            if "cases" not in response:
                break

            cases = response["cases"]
            all_cases.extend(cases)

            if len(cases) < limit:
                break  # Last page

            offset += limit

        return all_cases

    def _get_milestone(self, milestone_id):
        if not milestone_id:
            raise ValueError("Milestone ID must be provided.")
        return self.client.send_get(f"get_milestone/{milestone_id}")

    def _get_milestones(self, project_id, limit=250, offset=0):
        """
        Fetches milestones for the given project ID, with pagination support.

        Args:
            project_id (int): ID of the project.
            limit (int): Maximum number of milestones to fetch per request.
            offset (int): Offset to start fetching milestones from.

        Returns:
            dict: The response containing the milestones.
        """
        if not project_id:
            raise ValueError("Project ID must be provided.")

        return self.client.send_get(
            f"get_milestones/{project_id}&limit={limit}&offset={offset}"
        )

    def _get_tests(self, test_run_id):
        if not test_run_id:
            raise ValueError("Test run ID must be provided.")
        return self.client.send_get(f"get_tests/{test_run_id}")["tests"]

    def _get_test_run(self, test_run_id):
        if not test_run_id:
            raise ValueError("Test run ID must be provided.")
        return self.client.send_get(f"get_run/{test_run_id}")

    def _get_test_runs(self, project_id):
        if not project_id:
            raise ValueError("Project ID must be provided.")
        return self.client.send_get(f"get_runs/{project_id}")["runs"]

    def _get_test_run_results(self, test_run_id):
        if not test_run_id:
            raise ValueError("Test run ID must be provided.")
        return self.client.send_get(f"get_results_for_run/{test_run_id}")["results"]

    def _retry_api_call(self, api_call, *args, max_retries=3, delay=5):
        if not all([api_call, args]):
            raise ValueError("API call and arguments must be provided.")
        """
        Retries the given API call up to max_retries times with a delay between attempts.

        :param api_call: The API call method to retry.
        :param args: Arguments to pass to the API call.
        :param max_retries: Maximum number of retries.
        :param delay: Delay between retries in seconds.
        """
        for attempt in range(max_retries):
            try:
                return api_call(*args)
            except Exception:
                if attempt == max_retries - 1:
                    raise  # Reraise the last exception
                time.sleep(delay)

    def _get_test_cases_by_multiple_custom_fields(self, project_id, suite_id, filters):
        """if not all([project_id, suite_id, filters]):
            raise ValueError("Project ID, suite ID y filtros deben ser provistos.")

        all_cases = self._get_test_cases(project_id, suite_id)

        matching_cases = [
            case for case in all_cases
            if all(case.get(field) == expected for field, expected in filters.items())
        ]

        return matching_cases"""
        if not all([project_id, suite_id, filters]):
            raise ValueError("Project ID, suite ID and filters must be provided.")

        all_cases = self._get_test_cases_with_pagination(project_id, suite_id)
        print("************LENGHT****************")
        print(len(all_cases))

        def satisfies_all(case):
            for field, condition in filters.items():
                value = case.get(field)
                if callable(condition):
                    if not condition(value):
                        return False
                else:
                    if value != condition:
                        return False
            return True

        return [case for case in all_cases if satisfies_all(case)]