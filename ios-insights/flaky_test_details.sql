WITH target_date AS (
  SELECT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) AS rpt_date
),
yesterday_failures AS (
  SELECT DISTINCT
    branch,
    device,
    test_suite,
    test_case
  FROM `${GCP_SA_IOS_TESTS_INSIGHTS_TABLE}`
  WHERE DATE(timestamp) = (SELECT rpt_date FROM target_date)
    AND result = 'failed'
),
historical_ranked AS (
  SELECT
    branch,
    device,
    test_suite,
    test_case,
    result,
    timestamp,
    ROW_NUMBER() OVER (
      PARTITION BY branch, device, test_suite, test_case
      ORDER BY timestamp DESC
    ) AS rn
  FROM `${GCP_SA_IOS_TESTS_INSIGHTS_TABLE}`
  WHERE DATE(timestamp) < (SELECT rpt_date FROM target_date)
),
last_3_runs AS (
  SELECT *
  FROM historical_ranked
  WHERE rn <= 3
),
flagged AS (
  SELECT
    y.branch,
    y.device,
    y.test_suite,
    y.test_case,
    CASE
      WHEN EXISTS (
        SELECT 1
        FROM last_3_runs h
        WHERE h.branch = y.branch
          AND h.device = y.device
          AND h.test_suite = y.test_suite
          AND h.test_case = y.test_case
          AND h.result = 'succeeded'
      )
      THEN TRUE
      ELSE FALSE
    END AS is_flaky
  FROM yesterday_failures y
),
combined AS (
  SELECT 
    branch,
    device,
    test_case,
    MAX(CASE WHEN is_flaky THEN 1 ELSE 0 END) AS is_flaky
  FROM flagged
  GROUP BY branch, device, test_case
),
totals AS (
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