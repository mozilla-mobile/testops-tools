import sys
import json
import csv
from datetime import datetime
from testrail import TestRail
from pathvalidate import sanitize_filename

def create_csv(project_id, project_name, suite_id, suite_name):
    print("Fetching {project}: {suite}".format(project=project_name, suite=suite_name))
    
    now = datetime.now()
    testrail = TestRail()
    
    # TestRail API limits 250 test cases to be fetched at a time.
    # We repeatedly fetch test cases until there's no more left.
    offset_count = 0
    cases = []
    more_cases = [{}]
    while len(more_cases) > 0:
        response = testrail.test_cases(project_id, suite_id, offset_count)
        more_cases = response['cases']
        cases += more_cases
        offset_count = len(cases)
    print("TOTAL: {0} cases fetched".format(len(cases)))
    
    # Do not create backup for empty suites
    if len(cases) == 0:
        print("No backup file is created because the test suite is empty.")
        return

    output_json_file = "backup_{project}_{suite}_{year}-{month}-{day}.json".format(
        project=project_name, 
        suite=suite_name,
        year=now.year,
        month=now.month,
        day=now.day
    )
    output_json_file = sanitize_filename(output_json_file)
    
    # Write test cases to json file (For debugging)
    with open(output_json_file, 'w') as output:
        json.dump(cases, output, indent=2)
   
    # write test cases to CSV file
    output_csv_file = output_json_file.replace(".json", ".csv")
    with open(output_csv_file, 'w') as csv_file:
        csv_writer = csv.writer(csv_file)
        csv.writer(csv_file)

        # Print header
        # Rearrange the multi-line steps and expected result to be at the rightmost
        backup_fields = [*cases[0].keys()]
        backup_fields.remove('custom_steps_separated')
        backup_fields.append('Steps')
        backup_fields.append('Expected Result')
        csv_writer.writerow(backup_fields) 

        # Print rows (including unravel the Steps and Expected Results)
        for case in cases:
            first_row = [case.get(field, '') for field in backup_fields[:-2]] # need treatment for steps
            steps = case['custom_steps_separated']
            if steps:
                first_row.append(steps[0].get('content', ''))
                first_row.append(steps[0].get('expected', ''))
            else:
                first_row.append('')
                first_row.append('')
                steps = []
            csv_writer.writerow(first_row)
            
            for step in steps[1:]:
                row = ["" for field in backup_fields[:-2]]
                row.append(step['content'])
                row.append(step['expected'])
                csv_writer.writerow(row)

if __name__ == "__main__":
    testrail = TestRail()
    
    if len(sys.argv) == 1:
        print("Usage: python backup_testrail.py <project id...>")
        sys.exit(1)
        
    project_ids = sys.argv[1:]
    for project_id in project_ids:
        project = testrail.project(project_id)
        project_name = project.get('name')
        # Starting v9.3.2, get_suites returns a pagination containing a list of
        # suites instead of just a list of suites.
        suites = testrail.test_suites(project_id).get('suites')
        
        for suite in suites:
            suite_id = suite.get('id')
            suite_name = suite.get('name')
            create_csv(project_id, project_name, suite_id, suite_name)