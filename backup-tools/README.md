# TestRail Backup Tool

This directory holds the source code for backing up selected test suites to the designated
Google Cloud bucket on a regular basis.

The following projects are included in the backup:

* Fenix Browser
* Firefox for iOS
* Focus for Android
* Focus for iOS

## Recover from backup

1. Download the CSV tarfile from the Google Cloud bucket. A link to the `.tgz` file is available through the
   [Github Actions job summary page](https://github.com/mozilla-mobile/testops-tools/actions/workflows/testrail-backup.yml).
1. Download [testrail-import.cfg](https://github.com/mozilla-mobile/testops-tools/blob/main/backup-tools/testrail-import.cfg).
1. Navigate to TestRail project's *TestSuites & Cases* tab and open to an empty test suite.
1. Select *Import Cases* icon ➡️ *Import From CSV*.
1. From the *Import from CSV* modal:
   * File
     * Select the CSV file from step 1.
   * Format & Mapping
     * Select *Load mapping from configuration file* and select the .cfg file from step 1.
   * Advanced Options
     * Select *UTF-8* as *File Encoding*.
     * Select *Test Case (Steps)* as the *Template*
   * Click *Next*
1. From the 2nd *Import from CSV* modal:
   * Row Layout
     * Select *Test cases use multiple rows*
     * Select *Title* as the *Column to detect new test cases*
   * From "CSV Column ➡️ TestRail Field"
     * Examine each mapping. Select an appropriate "TestRail Field" if such a mapping has not been selected
   * Click *Next*
1. From the 3rd *Import from CSV* modal:
   * Review the values of each field to be imported
   * Click *Next*
1. From the 4th *Import from CSV* modal:
   * Preview Import
     * Review the first few cases
   * If all looks good, click "Import"
   * If some fields are missing or wrong, go back to the 2nd modal and review the mapping
1. From the last *Import from CSV* modal:
   * Click *Close* if there are no errors

## Limitations

* Some test cases (max 5%) are not exported for unknown reasons.
* Not all custom fields are captured in [testrail-import.cfg](https://github.com/mozilla-mobile/testops-tools/blob/main/backup-tools/testrail-import.cfg).
  * The following fields are known to be not imported: Automation, Automation Coverage, Sub Test Suite(s), Automated Test Name(s), Notes.
  * The following fields may not be imported properly: Type, Priority, AssignedTo, Estimate, References.
  * See [Configuring custom fields](https://support.testrail.com/hc/en-us/articles/7373850291220-Configuring-custom-fields) for setting TestRail test suite custom fields for the test cases.
* An import does not detect duplicate test cases. An import to a non-empty test suite adds test cases to the test suite. Duplicated test cases may be added.
* An import does not restore the test cases' original IDs. The imported cases have new IDs.
* An import does not restore the folder structure from test suites. Instead, all test cases are dumped into the same big folder.
* An import does not restore the original order of the test cases. Instead, the test cases are ordered alphabetically.
* Attachments to the test cases are not included in the backups.