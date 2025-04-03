WITH target_date AS (
  -- Define yesterday as the target date.
  SELECT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) AS rpt_date
),
yesterday_failures AS (
  -- Select distinct test records that failed on target_date, at the granularity of branch/device/test_suite/test_case.
  SELECT DISTINCT
    branch,
    device,
    test_suite,
    test_case
  FROM `${GCP_SA_IOS_TESTS_INSIGHTS_TABLE}`
  WHERE DATE(timestamp) = (SELECT rpt_date FROM target_date)
    AND result = 'failed'
),
historical AS (
  -- Select distinct historical records for the same tests in the 3 days before target_date.
  SELECT DISTINCT
    branch,
    device,
    test_suite,
    test_case,
    result
  FROM `${GCP_SA_IOS_TESTS_INSIGHTS_TABLE}`
  WHERE DATE(timestamp) BETWEEN DATE_SUB((SELECT rpt_date FROM target_date), INTERVAL 3 DAY)
                            AND DATE_SUB((SELECT rpt_date FROM target_date), INTERVAL 1 DAY)
),
flagged AS (
  -- For each test (branch, device, test_suite, test_case) that failed yesterday,
  -- flag it as flaky if there is at least one historical record that is not 'failed'.
  SELECT
    y.branch,
    y.device,
    y.test_suite,
    y.test_case,
    CASE
      WHEN EXISTS (
        SELECT 1 FROM historical h
        WHERE h.branch = y.branch
          AND h.device = y.device
          AND h.test_suite = y.test_suite
          AND h.test_case = y.test_case
          AND h.result <> 'failed'
      )
      THEN TRUE
      ELSE FALSE
    END AS is_flaky
  FROM yesterday_failures y
),
combined AS (
  -- Now collapse flagged results by branch, device, and test_case (ignoring test_suite).
  -- If the same test_case appears in multiple suites, we count it as flaky if any occurrence is flaky.
  SELECT 
    branch,
    device,
    test_case,
    MAX(CASE WHEN is_flaky THEN 1 ELSE 0 END) AS is_flaky
  FROM flagged
  GROUP BY branch, device, test_case
),
totals AS (
  -- Aggregate totals by branch and device:
  -- total_failed_tests: distinct test_case count (ignoring test_suite)
  -- flaky_tests_count: distinct test_case count flagged as flaky
  SELECT 
    branch,
    device,
    COUNT(DISTINCT test_case) AS total_failed_tests,
    COUNT(DISTINCT CASE WHEN is_flaky = 1 THEN test_case END) AS flaky_tests_count,
    ARRAY_TO_STRING(ARRAY_AGG(DISTINCT CASE WHEN is_flaky = 1 THEN test_case END), ', ') AS flaky_tests_details
  FROM combined
  GROUP BY branch, device
)
SELECT
  branch,
  device,
  total_failed_tests,
  flaky_tests_count,
  ROUND(SAFE_DIVIDE(flaky_tests_count, total_failed_tests), 4) AS flaky_tests_ratio,
  flaky_tests_details,
  (SELECT rpt_date FROM target_date) AS report_date
FROM totals
ORDER BY branch, device;