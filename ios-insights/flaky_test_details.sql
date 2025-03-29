WITH test_comparisons AS (
    SELECT
    	branch,
        device,
        test_case,
        test_suite,
        timestamp,
        result,
        LAG(result, 1) OVER (PARTITION BY test_case, branch, device ORDER BY timestamp) AS prev_result1,
        LAG(result, 2) OVER (PARTITION BY test_case, branch, device ORDER BY timestamp) AS prev_result2,
        LAG(result, 3) OVER (PARTITION BY test_case, branch, device ORDER BY timestamp) AS prev_result3
    FROM `${GCP_SA_IOS_TESTS_INSIGHTS_TABLE}`
),
yesterday_failed AS (
  SELECT DISTINCT 
    branch, 
    device, 
    test_suite,
    test_case, 
    result, 
    prev_result1, 
    prev_result2, 
    prev_result3
  FROM test_comparisons
  WHERE DATE(timestamp) = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND result = 'failed'
),
flagged_tests AS (
  SELECT
    branch,
    device,
    test_suite,
    test_case,
    CASE
      WHEN prev_result1 IS NULL OR prev_result2 IS NULL OR prev_result3 IS NULL THEN FALSE
      WHEN (prev_result1 = 'failed' AND prev_result2 = 'failed' AND prev_result3 = 'failed') THEN FALSE
      ELSE TRUE
    END AS is_flaky
  FROM yesterday_failed
)
SELECT
  branch,
  device,
  COUNT(DISTINCT test_case) AS total_failed_tests,
  COUNT(DISTINCT CASE WHEN is_flaky THEN test_case END) AS flaky_tests_count,
  ROUND(
    SAFE_DIVIDE(
      COUNT(DISTINCT CASE WHEN is_flaky THEN test_case END),
      COUNT(DISTINCT test_case)
    ),
    4
  ) AS flaky_tests_ratio,
  ARRAY_TO_STRING(
    ARRAY_AGG(DISTINCT CASE WHEN is_flaky THEN test_case END IGNORE NULLS),
    ', '
  ) AS flaky_tests_details,
  DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) AS report_date,
  test_suite
FROM flagged_tests
GROUP BY branch, device, test_suite
HAVING COUNT(DISTINCT CASE WHEN is_flaky THEN test_case END) > 0
ORDER BY branch, device, test_suite;
