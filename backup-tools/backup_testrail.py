import json
import csv
from datetime import datetime
from testrail import TestRail

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

if __name__ == "__main__":
    
    testrail = TestRail()
    now = datetime.now()
    
    project = 'Firefox for iOS'
    suite = 'Full Functional Tests Suite'
    PROJECT_ID = PROJECT.get(project).get('id')
    SUITE_ID = PROJECT.get(project).get('suite').get(suite)

    response = testrail.test_cases(PROJECT_ID, SUITE_ID)
    # Get only the cases only
    test_case = response['cases']
    
    output_json_file = "data-{project}-{suite}-{year}-{month}-{day}.json".format(
        project=project, 
        suite=suite,
        year=now.year,
        month=now.month,
        day=now.day
    )
    
    # write test cases to json file
    with open(output_json_file, 'w') as output:
        json.dump(test_case, output, indent=2)
   
    # write test cases to CSV file
    output_csv_file = output_json_file.replace(".json", ".csv")
    with open(output_csv_file, 'w') as csv_file:
        csv_writer = csv.writer(csv_file)
        csv.writer(csv_file)

        # Print header
        # Rearrange the multi-line steps and expected result to be at the rightmost
        backup_fields = [*test_case[0].keys()]
        backup_fields.remove('custom_steps_separated')
        backup_fields.append('Steps')
        backup_fields.append('Expected Result')
        csv_writer.writerow(backup_fields) 

        # Print rows (including unravel the Steps and Expected Results)
        for test in test_case[1:-1]:
            first_row = [test[field] for field in backup_fields[:-2]] # need treatment for steps
            first_row.append(test['custom_steps_separated'][0]['content'])
            first_row.append(test['custom_steps_separated'][0]['expected'])
            csv_writer.writerow(first_row)
            for step in test['custom_steps_separated'][1:-1]:
                row = ["" for field in backup_fields[:-2]]
                row.append(step['content'])
                row.append(step['expected'])
                csv_writer.writerow(row)