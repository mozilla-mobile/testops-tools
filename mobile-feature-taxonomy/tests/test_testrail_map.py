# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for testrail_map.py on synthetic sections and cases. No network, needs PyYAML only."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import testrail_map  # noqa: E402
from feature_map import load_taxonomy  # noqa: E402

IDS = testrail_map.valid_ids(load_taxonomy())

SECTIONS = [
    {"id": 1, "name": "Library", "parent_id": None, "description": "<p>LIB<br>Swipe down closes the panel.</p>"},
    {"id": 2, "name": "Bookmarks", "parent_id": 1, "description": "<p>LIB.BMK</p>"},
    {"id": 3, "name": "Edit", "parent_id": 2, "description": None},
    {"id": 4, "name": "Misc", "parent_id": 1, "description": ""},
    {"id": 5, "name": "Update", "parent_id": None, "description": "<p>APP.UDP</p>"},
    {"id": 6, "name": "Toolbar", "parent_id": None, "description": "Make the middle button configurable."},
]
CASES = [
    {"id": "C1", "section_id": 2, "automation": "Completed"},
    {"id": "C2", "section_id": 3, "automation": "Suitable"},
    {"id": "C3", "section_id": 4, "automation": "Completed"},
    {"id": "C4", "section_id": 5, "automation": ""},
    {"id": "C5", "section_id": 6, "automation": "Unsuitable"},
]


class DescriptionIdTest(unittest.TestCase):
    def test_first_word_is_the_id(self):
        self.assertEqual(testrail_map.description_id("<p>LIB.BMK</p>", IDS), ("LIB.BMK", None))
        self.assertEqual(testrail_map.description_id('<p data-pasted="true">CRED.CC</p><p><br></p>', IDS),
                         ("CRED.CC", None))
        self.assertEqual(testrail_map.description_id("<p>SRCH.URL<br>Design docs: …</p>", IDS), ("SRCH.URL", None))

    def test_l1_area_is_valid(self):
        self.assertEqual(testrail_map.description_id("<p>CRED</p>", IDS), ("CRED", None))

    def test_typo_is_reported(self):
        self.assertEqual(testrail_map.description_id("<p>APP.UDP</p>", IDS), (None, "APP.UDP"))

    def test_free_text_is_not_an_id(self):
        self.assertEqual(testrail_map.description_id("Make middle navigation toolbar button configurable.", IDS),
                         (None, None))
        self.assertEqual(testrail_map.description_id("<p>PDF files larger than 50 MB</p>", IDS), (None, None))
        self.assertEqual(testrail_map.description_id(None, IDS), (None, None))

    def test_code_buckets_are_not_testrail_features(self):
        self.assertEqual(testrail_map.description_id("SHARED.SHELL", IDS), (None, "SHARED.SHELL"))


class AttributeTest(unittest.TestCase):
    def setUp(self):
        self.attributed, self.tree = testrail_map.attribute(SECTIONS, CASES, IDS)

    def test_nearest_ancestor_wins(self):
        self.assertEqual(self.attributed["C1"], ("LIB.BMK", True))
        self.assertEqual(self.attributed["C2"], ("LIB.BMK", False))
        self.assertEqual(self.attributed["C3"], ("LIB", True))

    def test_unmapped(self):
        self.assertEqual(self.attributed["C4"][0], "")
        self.assertEqual(self.attributed["C5"][0], "")
        self.assertEqual(self.tree.unknown, {5: "APP.UDP"})

    def test_path(self):
        self.assertEqual(self.tree.path(3), "Library > Bookmarks > Edit")

    def test_counts_include_l1_only_cases_in_the_area(self):
        counts = testrail_map.count(self.attributed)
        self.assertEqual(counts["LIB.BMK"], {"total": 2, "automated": 1})
        self.assertEqual(counts["L1:LIB"], {"total": 3, "automated": 2})
        self.assertEqual(counts[""]["total"], 2)


class CommandTest(unittest.TestCase):
    def run_cli(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "cache.json")
            with open(cache, "w") as f:
                json.dump({"suite_id": 1, "sections": SECTIONS, "cases": CASES}, f)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = testrail_map.main(["ios", "--cache", cache, *args])
        return code, out.getvalue()

    def test_check_fails_on_unmapped_and_unknown(self):
        code, out = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("`APP.UDP` in Update", out)
        self.assertIn("Toolbar", out)
        self.assertIn("`LIB`  Library > Misc", out)

    def test_counts_csv(self):
        code, out = self.run_cli("counts", "--csv")
        self.assertEqual(code, 0)
        self.assertIn("L2,LIB.BMK,Bookmarks,2,1,50.0", out)
        self.assertIn("L1,LIB,Library (saved content),3,2,66.7", out)
        self.assertIn(",,No feature,2,0,0.0", out)


if __name__ == "__main__":
    unittest.main()
