# TestRail Backup Tool

This directory holds the source code for backing up selected test suites to the designated
Google Cloud bucket on a regular basis.

## Recover from backup

1. Download the encrypted CSV file from the Google Cloud bucket. A link to the `.tgz.gpg` file is available through the
   [Github Actions job summary page](https://github.com/mozilla-mobile/testops-tools/actions/workflows/testrail-backup.yml).
1. Download [testrail-import.cfg](https://github.com/mozilla-mobile/testops-tools/blob/main/backup-tools/testrail-import.cfg).
1. Navigate to TestRail project's *TestSuites & Cases* tab and open to an empty test suite.
1. Select *Import Cases* icon ➡️ *Import From CSV*.
1. From the *Import from CSV* modal:
   * Select the CSV file from step 1.
   * Select *Load mapping from configuration file* and select the .cfg file from step 1.
   * Select *UTF-8* as *File Encoding*.
   * Select *Test Case (Steps)* as the *Template* 
   * Click *Next*
1. From the 2nd *Import from CSV* modal:
   * Select *Test cases use multiple rows*
   * Select *Title* as the *Column to detect new test cases*
   * Click *Next* until the *Preview Import* screen
   * Configure the mapping for custom fields if necessary
1. Click *Import* and then *Close*.

## Limitations

* Not all custom fields are captured in [testrail-import.cfg](https://github.com/mozilla-mobile/testops-tools/blob/main/backup-tools/testrail-import.cfg).
  * See [Configuring custom fields](https://support.testrail.com/hc/en-us/articles/7373850291220-Configuring-custom-fields) for setting TestRail test suite custom fields for the test cases.
* An import to a non-empty test suite adds test cases to the test suite. Duplicated test cases may be added: An import does not check for duplicate titles.
* An import does not restore the test cases' original IDs. The imported cases have new IDs.
* An import does not restore the sections from test suites.
* An import does not detect duplicate test cases.
* Attachments to the test cases are not included in the backups.