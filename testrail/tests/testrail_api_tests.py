from datetime import datetime
import os
from typing import Optional
import sys
import unittest


from testrail.testrail_api import TestRail

# Contains tests for the following TestRail API methods:
# - _get_test_cases
#     - verifies the signature of a fetched test case
# - _get_milestones
#     - verifies the signature of a fetched milestone
# - does_milestone_exist
#     - verifies an existing milestone returns true
#     - verifies a non-existent milestone returns false
# - create_milestone
#     - verifies the response signature
#     - verifies the signature of a created milestone
# - create_test_run
#     - verifies the signature of a created test run
# - _update_test_run_tests TBD
# - _retry_api_call TBD
# - _get_tests TBD
# - test_taskcluster_android_workflow


class TestTestRail(unittest.TestCase):
    test_data = {
        "testrail": {
            "host": os.getenv("TESTRAIL_HOST"),
            "username": os.getenv("TESTRAIL_USERNAME"),
            "password": os.getenv("TESTRAIL_PASSWORD"),
        },
        "project": {
            "fenix_browser": {
                "id": 59,
                "test_suite": {
                    "id": 49319,
                    "name": "master",
                },
            },
            "test_project_mobile": {
                "id": 75,
                "test_suite": {
                    "id": 40281,
                    "name": "test_automation_release_miletone_fenix",
                },
            },
        },
        "milestone_name": "Test Milestone" + str(datetime.utcnow()),
        "milestone_description": "Test Milestone Description",
        "devices": ["Device 1", "Device 2"],
        "test_run_name": "Test Run",
    }

    def setUp(self):
        self.testrail = TestRail(
            self.test_data["testrail"]["host"],
            self.test_data["testrail"]["username"],
            self.test_data["testrail"]["password"],
        )
        self.created_test_data = {"milestones": [], "test_runs": []}

    # @unittest.skip("skip")
    def test_get_test_cases_signature(self):
        # test 'cases' signature
        expected_cases_signature = {
            "id": int,
            "title": str,
            "section_id": int,
            "template_id": int,
            "type_id": int,
            "priority_id": int,
            "milestone_id": Optional[int],
            "refs": Optional[str],
            "created_by": int,
            "created_on": int,
            "updated_by": int,
            "updated_on": int,
            "estimate": Optional[str],
            "estimate_forecast": Optional[str],
            "suite_id": int,
            "display_order": int,
            "is_deleted": int,
            "case_assignedto_id": Optional[int],
            "custom_test_case_owner": Optional[str],
            "custom_automation_status": int,
            "custom_automation_coverage": int,
            "custom_test_objective": Optional[str],
            "custom_rotation": Optional[str],
            "custom_preconds": Optional[str],
            "custom_steps": Optional[str],
            "custom_expected": Optional[str],
            "custom_steps_separated": Optional[list],
            "custom_mission": Optional[str],
            "custom_goals": Optional[str],
            "comments": list,
            "custom_sub_test_suites": list,
            "custom_test_area_multi": list,
        }
        project = self.test_data["project"]["test_project_mobile"]
        response = self.testrail._get_test_cases(
            project["id"], project["test_suite"]["id"]
        )

        # test only the first case
        for key, value in response[0].items():
            expected_type = expected_cases_signature.get(key)
            actual_type = type(value)
            print(f"{key}: {value=}, {expected_type=}, {actual_type=}")
            if value is not None:
                self.assertIsInstance(value, expected_type)

    # @unittest.skip("skip")
    def test_get_milestones_signature(self):
        expected_milestones_signature = {
            "id": int,
            "name": str,
            "description": Optional[str],
            "start_on": Optional[int],
            "started_on": Optional[int],
            "is_started": bool,
            "due_on": Optional[int],
            "is_completed": bool,
            "completed_on": Optional[int],
            "project_id": int,
            "parent_id": Optional[int],
            "refs": Optional[str],
            "url": str,
            "milestones": Optional[list],
        }
        project = self.test_data["project"]["test_project_mobile"]
        response = self.testrail._get_milestones(project["id"])

        # test 'milestones' signature
        for key, value in response[0].items():
            expected_type = expected_milestones_signature.get(key)
            actual_type = type(value)
            print(f"{key}: {value=}, {expected_type=}, {actual_type=}")

            if value is not None:
                self.assertIsInstance(value, expected_type)

    # @unittest.skip("skip")
    def test_get_milestone(self):
        milestone_id = 1615
        milestone = self.testrail._get_milestone(milestone_id)
        print(f"{milestone=}")

    # @unittest.skip("skip")
    def test_get_test_runs(self):
        run_id = 85749
        test_run = self.testrail._get_test_run(run_id)
        print(f"{test_run=}")

    # @unittest.skip("skip")
    def test_does_milestone_exist_true(self):
        project = self.test_data["project"]["test_project_mobile"]
        milestone_name = self.test_data["milestone_name"]
        milestone_description = self.test_data["milestone_description"]
        milestone = self.testrail.create_milestone(
            project["id"], milestone_name, milestone_description
        )
        self.created_test_data["milestones"].append(milestone)

        # Test Steps
        milestone_exists = self.testrail.does_milestone_exist(
            project["id"], milestone_name
        )
        print(f"{milestone_exists=}")
        print(f"{self.created_test_data=}")

        # Test Assertion
        self.assertTrue(milestone_exists)

    # @unittest.skip("skip")
    def test_does_milestone_exist_false(self):
        project = self.test_data["project"]["test_project_mobile"]
        milestone_name = "Non-Existent Milestone"
        milestone_exists = self.testrail.does_milestone_exist(
            project["id"], milestone_name
        )
        print(f"{milestone_exists=}")
        print(f"{self.created_test_data=}")

        # Test Assertion
        self.assertFalse(milestone_exists)

    # @unittest.skip("skip")
    def test_create_milestone(self):
        project = self.test_data["project"]["test_project_mobile"]
        milestone = self.testrail.create_milestone(
            project["id"],
            self.test_data["milestone_name"],
            self.test_data["milestone_description"],
        )
        print(f"{milestone=}")
        print(f"{self.created_test_data=}")
        # verify response and milestone is not empty
        self.assertIsInstance(milestone, dict)
        self.assertTrue(bool(milestone))

        # add milestone to created_test_data for caching and cleanup later
        self.created_test_data["milestones"].append(milestone)

    # @unittest.skip("skip")
    def test_create_milestone_signature(self):
        # Milestone Response Signature
        expected_response_signature = {
            "id": int,
            "name": str,
            "description": Optional[str],
            "start_on": Optional[int],
            "started_on": Optional[int],
            "is_started": bool,
            "due_on": Optional[int],
            "is_completed": bool,
            "completed_on": Optional[int],
            "project_id": int,
            "parent_id": Optional[int],
            "url": str,
            "milestones": Optional[list],
        }
        # Test Setup
        project = self.test_data["project"]["test_project_mobile"]
        # Test Steps
        milestone = self.testrail.create_milestone(
            project["id"],
            self.test_data["milestone_name"],
            self.test_data["milestone_description"],
        )
        # add milestone to created_test_data for caching and cleanup later
        self.created_test_data["milestones"].append(milestone)
        print(f"{milestone=}")
        print(f"{self.created_test_data=}")

        # Test Assertion
        for key, value in milestone.items():
            expected_type = expected_response_signature.get(key)
            actual_type = type(value)
            if value is not None:
                print(f"{key}: {value=}, {expected_type=}, {actual_type=}")
                self.assertIsInstance(value, expected_type)

    # @unittest.skip("skip")
    def test_create_test_run_signature(self):
        # Test Run Response Signature
        expected_response_signature = {
            "id": int,
            "suite_id": int,
            "name": str,
            "description": Optional[str],
            "milestone_id": int,
            "assignedto_id": Optional[int],
            "include_all": bool,
            "is_completed": bool,
            "completed_on": Optional[int],
            "config": Optional[str],
            "config_ids": list,
            "passed_count": int,
            "blocked_count": int,
            "untested_count": int,
            "retest_count": int,
            "failed_count": int,
            "custom_status1_count": int,
            "custom_status2_count": int,
            "custom_status3_count": int,
            "custom_status4_count": int,
            "custom_status5_count": int,
            "custom_status6_count": int,
            "custom_status7_count": int,
            "project_id": int,
            "plan_id": Optional[int],
            "created_on": int,
            "updated_on": int,
            "refs": Optional[str],
            "created_by": int,
            "url": str,
        }
        # Test Setup
        project = self.test_data["project"]["test_project_mobile"]
        test_suite = project["test_suite"]
        # test runs require a milestone to be created first
        # check if we have a cached milstone to use before creating a new one
        if len(self.created_test_data["milestones"]) > 0:
            milestone = self.created_test_data["milestones"][0]
        else:
            project = self.test_data["project"]["test_project_mobile"]
            milestone = self.testrail.create_milestone(
                project["id"],
                self.test_data["milestone_name"],
                self.test_data["milestone_description"],
            )
            self.created_test_data["milestones"].append(milestone)

        # Test Steps
        test_run = self.testrail.create_test_run(
            project["id"],
            milestone["id"],
            self.test_data["test_run_name"],
            test_suite["id"],
        )
        # add test_run to created_test_data for cleanup later
        self.created_test_data["test_runs"].append(test_run)
        print(f"{test_run=}")
        print(f"{self.created_test_data=}")

        # Test Assertion
        # verify response and test_run is not empty
        self.assertIsInstance(test_run, dict)
        self.assertTrue(bool(test_run))
        for key, value in test_run.items():
            expected_type = expected_response_signature.get(key)
            actual_type = type(value)
            if value is not None:
                print(f"{key}: {value=}, {expected_type=}, {actual_type=}")
                self.assertIsInstance(value, expected_type)

    # @unittest.skip("skip")
    def test_update_test_run_tests(self):
        test_run = 85749
        test_status = 1  # Passed
        tests = self.testrail._get_tests(test_run)
        for test in tests:
            print(f"{test['id']=} {test['status_id']=}")

        response = self.testrail.update_test_run_tests(test_run, test_status)
        for updated_test in response:
            print(f"{updated_test=}, {updated_test['status_id']=}")

        tests_after_update = self.testrail._get_tests(test_run)

        for test in tests_after_update:
            print(f"{test['id']=} {test['status_id']=}")

    # @unittest.skip("skip")
    def test_taskcluster_android_workflow(self):
        # Test Setup
        project = self.test_data["project"]["test_project_mobile"]
        test_suite = project["test_suite"]

        # Test Steps
        # load TestRail credentials
        tr_host = os.getenv("TESTRAIL_HOST")
        tr_username = os.getenv("TESTRAIL_USERNAME")
        tr_password = os.getenv("TESTRAIL_PASSWORD")
        # initialize TestRail client
        testrail = TestRail(tr_host, tr_username, tr_password)
        # get release version
        release_version = "124.11"
        # get release type
        release_type = "Beta"
        # build milestone name
        product_type = "Fenix"
        milestone_name = f"Build Validation sign-off - {product_type} {release_type} {release_version} {datetime.utcnow()}"
        # build milestone description
        milestone_description = f"RELEASE: {milestone_name}..."
        # check if milestone exists
        milestone_exists = testrail.does_milestone_exist(project["id"], milestone_name)
        print(f"{milestone_exists=}")
        # if true exit script
        if milestone_exists:
            print(f"Milestone for {milestone_name} already exists. Exiting script...")
            sys.exit()
        # create milestone
        milestone = testrail.create_milestone(
            project["id"], milestone_name, milestone_description
        )
        print(f"{milestone=}")
        devices = ["Google Pixel 3(Android11)", "Google Pixel 2(Android11)"]
        # store test runs for testing
        test_runs = []
        # for each device:
        for device in devices:
            # create test run
            test_run_name = f"{device} - {release_type} {release_version}"
            test_run = testrail.create_test_run(
                project["id"],
                milestone["id"],
                test_run_name,
                test_suite["id"],
            )
            test_runs.append(test_run)
            # update test run tests
            test_status = 1  # Passed
            test_run_results = testrail.update_test_run_tests(
                test_run["id"], test_status
            )
            print(f"{test_run_results=}")
        print(f"TEST_RUNS: {test_runs=}")

        # Test Assertion
        # verify milestone exists in project milestones
        project_milestone = testrail._get_milestone(milestone["id"])
        print(f"{project_milestone=}")
        self.assertEqual(project_milestone["name"], milestone["name"])
        # verify test runs exist in project milestone
        for test_run in test_runs:
            project_test_run = testrail._get_test_run(test_run["id"])
            print(f"{project_test_run=}")
            self.assertEqual(project_test_run["name"], test_run["name"])
            self.assertEqual(project_test_run["milestone_id"], test_run["milestone_id"])
        # verify test run tests are updated
        for test_run in test_runs:
            tests = testrail._get_tests(test_run["id"])
            for test in tests:
                self.assertEqual(test["status_id"], 1)


if __name__ == "__main__":
    unittest.main()
