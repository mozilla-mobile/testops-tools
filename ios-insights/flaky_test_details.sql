WITH test_comparisons AS (
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
)
    SELECT
	    branch,
        device,
        COUNT(*) AS total_tests,
        COUNTIF(is_flaky) AS flaky_tests_count,
        SAFE_DIVIDE(COUNTIF(is_flaky), COUNT(*)) AS flaky_tests_ratio,
        ARRAY_TO_STRING(ARRAY_AGG(CASE WHEN is_flaky THEN test_case END IGNORE NULLS), ', ') AS flaky_tests_details
    FROM flagged_tests
    GROUP BY branch, device
    ORDER BY branch, device;