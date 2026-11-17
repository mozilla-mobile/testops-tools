# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for testrail_section_check.py on synthetic data. No network, needs PyYAML only."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import testrail_map  # noqa: E402
import testrail_section_check as check  # noqa: E402
from feature_map import load_taxonomy  # noqa: E402

IDS = testrail_map.valid_ids(load_taxonomy())

GOOD = {"suite_id": 1, "sections": [
    {"id": 1, "name": "Bookmarks", "parent_id": None, "description": "<p>LIB.BMK</p>"},
    {"id": 2, "name": "Import", "parent_id": 1, "description": None},
    {"id": 3, "name": "Library", "parent_id": None, "description": "<p>LIB</p>"},
], "cases": [{"id": "C1", "section_id": 2, "automation": ""}, {"id": "C2", "section_id": 3, "automation": ""}]}

BAD = {"suite_id": 2, "sections": [
    {"id": 10, "name": "Update", "parent_id": None, "description": "<p>APP.UDP</p>"},
    {"id": 11, "name": "New <beta> feature & co", "parent_id": None, "description": "Design doc link"},
], "cases": [{"id": "C10", "section_id": 10, "automation": ""},
             {"id": "C11", "section_id": 11, "automation": ""}, {"id": "C12", "section_id": 11, "automation": ""}]}

ENV = {"TESTRAIL_HOST": "example.testrail.io", "TESTRAIL_USERNAME": "u", "TESTRAIL_PASSWORD": "p"}


class CheckPlatformTest(unittest.TestCase):
    def test_l1_only_is_not_a_problem(self):
        self.assertFalse(check.has_problems(check.check_platform("ios", GOOD, IDS)))

    def test_unknown_and_unmapped(self):
        r = check.check_platform("android", BAD, IDS)
        self.assertEqual(r["unknown"], [(10, "Update", "APP.UDP")])
        self.assertEqual(r["unmapped"], [(11, "New <beta> feature & co", 2), (10, "Update", 1)])

    def test_summary_line_has_no_section_names(self):
        line = check.summary_line(check.check_platform("android", BAD, IDS))
        self.assertNotIn("Update", line)
        self.assertNotIn("beta", line)
        self.assertIn("3 cases in 2 sections with no feature ID", line)


class SlackPayloadTest(unittest.TestCase):
    def test_links_and_escaping(self):
        results = [check.check_platform("ios", GOOD, IDS), check.check_platform("android", BAD, IDS)]
        payload = check.slack_payload(results, "https://example.testrail.io", "https://github.com/run/1")
        text = json.dumps(payload)
        self.assertIn("index.php?/suites/view/2&group_by=cases:section_id&group_id=11", text)
        self.assertIn("New &lt;beta&gt; feature &amp; co", text)
        self.assertIn("`APP.UDP`", text)
        self.assertIn("iOS: all sections OK.", text)
        self.assertEqual(payload["text"], "TestRail sections without a feature ID: Android")

    def test_long_lists_are_cut(self):
        many = {"suite_id": 3, "sections": [{"id": i, "name": f"S{i}", "parent_id": None, "description": ""}
                                            for i in range(100)],
                "cases": [{"id": f"C{i}", "section_id": i, "automation": ""} for i in range(100)]}
        payload = check.slack_payload([check.check_platform("ios", many, IDS)], "https://x")
        text = json.dumps(payload)
        self.assertIn("and 60 more", text)
        self.assertTrue(all(len(b["text"]["text"]) <= 3000 for b in payload["blocks"] if b["type"] == "section"))


class MainTest(unittest.TestCase):
    def run_main(self, data_by_platform, *args, env=None):
        with tempfile.TemporaryDirectory() as tmp:
            for platform, data in data_by_platform.items():
                with open(os.path.join(tmp, f"{platform}.json"), "w") as f:
                    json.dump(data, f)
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, {**ENV, **(env or {})}, clear=True), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = check.main(["--cache-dir", tmp, *args])
        return code, out.getvalue(), err.getvalue()

    def test_all_good(self):
        code, out, _ = self.run_main({"ios": GOOD, "android": GOOD})
        self.assertEqual(code, 0)
        self.assertEqual(out.count(": OK."), 2)

    def test_sends_to_slack(self):
        with mock.patch.object(check, "post_to_slack") as post:
            code, out, _ = self.run_main({"ios": GOOD, "android": BAD}, env={"SLACK_WEBHOOK_URL": "https://hook"})
        self.assertEqual(code, 1)
        post.assert_called_once()
        self.assertNotIn("Update", out)  # names only in the Slack payload, never on stdout

    def test_no_webhook_fails_without_printing_names(self):
        code, out, err = self.run_main({"android": BAD}, "--platform", "android")
        self.assertEqual(code, 1)
        self.assertNotIn("Update", out + err)

    def test_dry_run_prints_payload(self):
        code, out, _ = self.run_main({"android": BAD}, "--platform", "android", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("APP.UDP", out)


if __name__ == "__main__":
    unittest.main()
