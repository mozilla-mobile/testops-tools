# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for collect_testrail.py on synthetic TestRail data. No network, needs PyYAML only."""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import collect_testrail  # noqa: E402

SECRET_SECTION = "Secret section name"
SECRET_TITLE = "Secret case title"
DATA = {"suite_id": 1, "sections": [
    {"id": 1, "name": "Library", "parent_id": None, "description": "<p>LIB</p>"},
    {"id": 2, "name": SECRET_SECTION, "parent_id": 1, "description": "<p>LIB.BMK</p>"},
    {"id": 3, "name": "Unmapped", "parent_id": None, "description": None},
], "cases": [
    {"id": "C1", "section_id": 2, "automation": "Completed", "title": SECRET_TITLE},
    {"id": "C2", "section_id": 2, "automation": "Suitable"},
    {"id": "C3", "section_id": 1, "automation": "Completed"},
    {"id": "C4", "section_id": 3, "automation": ""},
]}


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.out = collect_testrail.collect({"ios": DATA, "android": DATA})

    def test_counts(self):
        ios = self.out["platforms"]["ios"]
        self.assertEqual(ios["features"]["LIB.BMK"], {"total": 2, "automated": 1})
        self.assertEqual(ios["features"]["L1:LIB"], {"total": 3, "automated": 2})
        self.assertEqual(ios["cases"], 4)
        self.assertEqual(ios["no_feature"], 1)
        self.assertNotIn("", ios["features"])

    def test_only_aggregates_leave(self):
        text = json.dumps(self.out)
        for secret in (SECRET_SECTION, SECRET_TITLE, "Unmapped", "C1"):
            self.assertNotIn(secret, text)

    def test_main_writes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            for p in collect_testrail.PLATFORMS:
                with open(os.path.join(tmp, f"{p}.json"), "w") as f:
                    json.dump(DATA, f)
            out = os.path.join(tmp, "site", "data", "testrail.json")
            self.assertEqual(collect_testrail.main(["--cache-dir", tmp, "--out", out]), 0)
            with open(out) as f:
                self.assertEqual(json.load(f)["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
