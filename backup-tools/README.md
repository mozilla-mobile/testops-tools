# TestRail Backup Tool

This directory holds the source code for backing up selected test suites to the designated
Google Cloud bucket on a regular basis.

## Recover from backup

1. Download the CSV file from the Google Cloud bucket.
1. Download the .cfg file from this directory.
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
   * (Configure the mapping for custom fields)
1. Click *Import* and then *Close*.

## Todo and Limitations

* No custom fields in .cfg file.
  * [Administrator instructions](https://support.testrail.com/hc/en-us/articles/7373850291220-Configuring-custom-fields) for setting custom fields