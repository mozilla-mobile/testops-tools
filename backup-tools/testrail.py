import os
from lib.testrail_conn import APIClient

'''
export TESTRAIL_HOST=https://mozilla.testrail.io
export TESTRAIL_USERNAME=firefox-test-engineering@mozilla.com
export TESTRAIL_API_KEY=firefox-test-engineering@mozilla.com:dPqhLgYkaLY.65v25.BJ-iLape1Sh1B8OBDXyH5NX
'''

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
    '''
if __name__ == "__main__":
    testrail = TestRail()

    PROJECT = {
        'Fenix Browser': {
            'id': 59,
            'suite': {
                'Full Functional Tests Suite': 3192
            }
        },
        'Firefox for iOS': {
            'id': 14,
            'suite': {
                'Full Functional Tests Suite': 45443,
                'iOS Performance Test Suite': 1298
            }
        },
        'Focus for iOS': {
            'id': 27,
            'suite': {
                'Full Functional Test Suite': 5291
            }
        },
        'Firefox for Android': {
            'id': 13,
            'suite': {
                'Smoke Tests': 142,
                'L10N Test suite': 186
            }
        },
        'Focus for Android': {
            'id': 49,
            'suite': {
                'Full Functional Tests Suite': 1028
            }
        }
    }

    project = 'Firefox for iOS'
    suite = 'Full Functional Tests Suite'
    PROJECT_ID = PROJECT.get(project).get('id')
    SUITE_ID = PROJECT.get(project).get('suite').get(suite)

    response = testrail.test_cases(PROJECT_ID, SUITE_ID)
    # Get only the cases only
    test_case = response['cases']
    
    filename = "data-{project}-{suite}.json".format(project=project, suite=suite)
    with open(filename, 'w') as output:
        json.dump(test_case, output, indent=2)
        '''