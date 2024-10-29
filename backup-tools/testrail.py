import os
from testrail_conn import APIClient

class TestRail():
    
    def __init__(self):
        try:
            TESTRAIL_HOST = os.environ['TESTRAIL_HOST']
            self.client = APIClient(TESTRAIL_HOST)
            self.client.user = os.environ['TESTRAIL_USERNAME']
            self.client.password = os.environ['TESTRAIL_PASSWORD']
        except KeyError as e:
            raise ValueError(f"ERROR: Missing Testrail Env Var: {e}")
    
    # Public Methods


    # API: Projects
    def projects(self):
        return self.client.send_get('get_projects')

    def project(self, testrail_project_id):
        return self.client.send_get(
            'get_project/{0}'.format(testrail_project_id))

    # API: Cases
    def test_cases(self, testrail_project_id, testrail_test_suite_id):
        return self.client.send_get(
            'get_cases/{0}&suite_id={1}'
            .format(testrail_project_id, testrail_test_suite_id))

    def test_case(self, testrail_test_case_id):
        return self.client.send_get(
            'get_case/{0}'.format(testrail_test_case_id))

    # API: Case Fields
    def test_case_fields(self):
        return self.client.send_get(
            'get_case_fields')

    # API: Suites
    def test_suites(self, testrail_project_id):
        return self.client \
                   .send_get('get_suites/{0}'.format(testrail_project_id))

    def test_suite(self, testrail_test_suite_id):
        return self.client \
                   .send_get('get_suite/{0}'.format(testrail_test_suite_id))