WITH overall AS (
    SELECT 
        COUNT(*) AS total_tests,
        COUNTIF(result = 'failed') AS failed_tests,
        ROUND((COUNTIF(result = 'failed') / COUNT(*)) * 100, 2) AS failure_rate
    FROM `${GCP_SA_IOS_TESTS_INSIGHTS_TABLE}`
    WHERE DATE(timestamp) = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),
test_comparisons AS (
    SELECT
        branch,
        device,
        test_case,
        timestamp,
        result,
        LAG(result, 1) OVER (PARTITION BY test_case, branch, device ORDER BY timestamp) AS prev_result1,
        LAG(result, 2) OVER (PARTITION BY test_case, branch, device ORDER BY timestamp) AS prev_result2,
        LAG(result, 3) OVER (PARTITION BY test_case, branch, device ORDER BY timestamp) AS prev_result3
    FROM `${GCP_SA_IOS_TESTS_INSIGHTS_TABLE}`
),
yesterday_tests AS (
    SELECT *
    FROM test_comparisons
    WHERE DATE(timestamp) = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),
flagged_tests AS (
    SELECT
        branch,
        device,
        test_case,
        result,
        CASE
            WHEN prev_result1 IS NULL OR prev_result2 IS NULL OR prev_result3 IS NULL THEN FALSE
            WHEN (result = prev_result1 AND result = prev_result2 AND result = prev_result3) THEN FALSE
            ELSE TRUE
        END AS is_flaky
    FROM yesterday_tests
),
flaky_agg AS (
    SELECT
        SUM(flaky_tests_count) AS flaky_tests,
        SAFE_DIVIDE(SUM(flaky_tests_count), SUM(total_tests)) AS flaky_rate
    FROM (
        SELECT
            branch,
            device,
            COUNT(*) AS total_tests,
            COUNTIF(is_flaky) AS flaky_tests_count
        FROM flagged_tests
        GROUP BY branch, device
    )
)
SELECT
    overall.total_tests,
    overall.failed_tests,
    overall.failure_rate,
    flaky_agg.flaky_tests,
    ROUND(flaky_agg.flaky_rate * 100, 2) AS flaky_rate
FROM overall CROSS JOIN flaky_agg;