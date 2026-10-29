import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from googleapiclient.errors import HttpError  # noqa: E402

import fetch_metrics  # noqa: E402
import run_queries  # noqa: E402


def http_error(status):
    return HttpError(mock.Mock(status=status, reason="x"), b"{}")


def body(end=(2026, 10, 29)):
    return {
        "timelineSpec": {
            "aggregationPeriod": "DAILY",
            "startTime": {"year": 2026, "month": 10, "day": 1},
            "endTime": {"year": end[0], "month": end[1], "day": end[2]},
        }
    }


def endpoint_with(latest):
    ep = mock.Mock()
    ep.get.return_value.execute.return_value = {
        "freshnessInfo": {
            "freshnesses": [
                {
                    "aggregationPeriod": "DAILY",
                    "latestEndTime": {"year": latest[0], "month": latest[1], "day": latest[2]},
                }
            ]
        }
    }
    return ep


class ExplainStaleRequest(unittest.TestCase):
    def test_range_past_latest_is_stale(self):
        msg = fetch_metrics.explain_stale_request(endpoint_with((2026, 10, 25)), "m", body())
        self.assertIn("2026-10-25", msg)

    def test_start_equal_to_latest_is_stale(self):
        b = body(end=(2026, 10, 19))
        b["timelineSpec"]["startTime"] = {"year": 2026, "month": 10, "day": 19}
        msg = fetch_metrics.explain_stale_request(endpoint_with((2026, 10, 19)), "m", b)
        self.assertIsNotNone(msg)

    def test_range_within_latest_is_not_stale(self):
        self.assertIsNone(
            fetch_metrics.explain_stale_request(endpoint_with((2026, 10, 29)), "m", body())
        )

    def test_freshness_lookup_failure_returns_none(self):
        ep = mock.Mock()
        ep.get.return_value.execute.side_effect = Exception("boom")
        self.assertIsNone(fetch_metrics.explain_stale_request(ep, "m", body()))


class QueryVitals(unittest.TestCase):
    CONFIG = {"metric_set_suffix": "crashRateMetricSet", "endpoint": "crashrate"}

    def _service(self, endpoint):
        service = mock.Mock()
        service.vitals.return_value.crashrate.return_value = endpoint
        return service

    def test_400_with_stale_data_raises_not_fresh(self):
        ep = endpoint_with((2026, 10, 25))
        ep.query.return_value.execute.side_effect = http_error(400)
        with self.assertRaises(fetch_metrics.DataNotFreshError):
            fetch_metrics.query_vitals(self._service(ep), "pkg", self.CONFIG, body())

    def test_persistent_freshness_400_raises_not_fresh_after_retries(self):
        ep = endpoint_with((2026, 10, 19))
        err = HttpError(
            mock.Mock(status=400, reason="start_date should be before the current freshness 2026-10-19"),
            b"{}",
        )
        ep.query.return_value.execute.side_effect = err
        with self.assertRaises(fetch_metrics.DataNotFreshError):
            fetch_metrics.query_vitals(
                self._service(ep), "pkg", self.CONFIG, body(end=(2026, 10, 28))
            )
        self.assertEqual(ep.query.call_count, 10)

    def test_400_with_fresh_data_reraises_http_error(self):
        ep = endpoint_with((2026, 10, 29))
        ep.query.return_value.execute.side_effect = http_error(400)
        with self.assertRaises(HttpError):
            fetch_metrics.query_vitals(self._service(ep), "pkg", self.CONFIG, body())


class RunQueriesStale(unittest.TestCase):
    def _run(self, returncode):
        manifest = Path(tempfile.mkdtemp()) / "q.toml"
        manifest.write_text('[[queries]]\nname = "q"\npackage = "p"\nmetric_set = "crashrate"\n')
        out = Path(tempfile.mkdtemp())
        proc = mock.Mock(returncode=returncode, stdout="", stderr="stale!")
        argv = ["run_queries", "--manifest", str(manifest), "--output-dir", str(out)]
        with mock.patch.object(run_queries.subprocess, "run", return_value=proc), \
                mock.patch.object(sys, "argv", argv):
            try:
                run_queries.main()
                exited = None
            except SystemExit as e:
                exited = e.code
        return exited, json.loads((out / "summary.json").read_text())

    def test_stale_exit_code_does_not_fail_run(self):
        exited, summary = self._run(fetch_metrics.EXIT_DATA_STALE)
        self.assertIsNone(exited)
        self.assertEqual(summary["q"]["status"], "stale")

    def test_other_failure_still_fails_run(self):
        exited, _ = self._run(1)
        self.assertEqual(exited, 1)


if __name__ == "__main__":
    unittest.main()
