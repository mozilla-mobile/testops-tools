# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for bugs_map.py and android/bugs-map.yml. No network, needs PyYAML only."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import bugs_map  # noqa: E402
from feature_map import load_taxonomy  # noqa: E402

TAXONOMY = load_taxonomy()
MAP = {
    "product": "Example", "escaped": {"team_email_domains": ["example.com"], "bot_email_suffixes": ["@bots.tld"],
                                      "bot_emails": ["filer@example.org"]},
    "not_counted_resolutions": ["DUPLICATE", "INVALID"],
    "components": {
        "Tabs": {"feature": "TABS.TRAY", "titles": [{"match": "tab group", "feature": "TABS.GRP"}]},
        "Autofill": {"feature": "CRED"},
        "Performance": {"feature": "X.PERF"},
        "General": {"untriaged": True},
        "Tooling": {"excluded": True},
    },
}


def bug(i, component, summary="", creator="someone@gmail.com", resolution="", created="2026-03-01T10:00:00Z"):
    return {"id": i, "component": component, "summary": summary, "creator": creator, "resolution": resolution,
            "creation_time": created}


class RealMapTest(unittest.TestCase):
    def test_android_map_is_valid(self):
        m = bugs_map.BugsMap.load("android")
        self.assertEqual(m.errors, [])
        self.assertIn("Browser Engine", m.components)


class MapValidationTest(unittest.TestCase):
    def test_errors(self):
        bad = dict(MAP, components={
            "A": {"feature": "NOPE.ID"},
            "B": {"feature": "LIB.BMK", "untriaged": True},
            "C": {"feature": "LIB.BMK", "titles": [{"match": "(", "feature": "LIB.BMK"}]},
            "D": {"untriaged": True, "titles": [{"match": "x", "feature": "LIB.BMK"}]},
            "E": {"feature": "SHARED.SHELL"},
        })
        errors = bugs_map.BugsMap(bad, TAXONOMY).errors
        self.assertEqual(len(errors), 5, errors)


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        self.m = bugs_map.BugsMap(MAP, TAXONOMY)

    def test_component_and_title(self):
        self.assertEqual(self.m.classify(bug(1, "Tabs", "Crash in tab groups")), ("feature", "TABS.GRP"))
        self.assertEqual(self.m.classify(bug(2, "Tabs", "Tab tray is empty")), ("feature", "TABS.TRAY"))
        self.assertEqual(self.m.classify(bug(3, "General")), ("untriaged", ""))
        self.assertEqual(self.m.classify(bug(4, "Tooling")), ("excluded", ""))
        self.assertEqual(self.m.classify(bug(5, "Brand new")), ("unknown component", ""))

    def test_escaped(self):
        self.assertTrue(self.m.is_escaped(bug(1, "Tabs")))
        self.assertFalse(self.m.is_escaped(bug(1, "Tabs", creator="dev@example.com")))
        self.assertFalse(self.m.is_escaped(bug(1, "Tabs", creator="sheriff@bots.tld")))
        self.assertFalse(self.m.is_escaped(bug(1, "Tabs", creator="Filer@example.org")))

    def test_attribute_and_count(self):
        bugs = [bug(1, "Tabs", "tab group"), bug(2, "Tabs"), bug(3, "Autofill"), bug(4, "Performance"),
                bug(5, "General"), bug(6, "Tooling"), bug(7, "Tabs", resolution="DUPLICATE"),
                bug(8, "Tabs", creator="dev@example.com")]
        counts = bugs_map.count(bugs_map.attribute(bugs, self.m))
        self.assertEqual(counts["L1:TABS"], 2)
        self.assertEqual(counts["TABS.GRP"], 1)
        self.assertEqual(counts["L1:CRED"], 1)
        self.assertEqual(counts["X.PERF"], 1)
        self.assertNotIn("L1:X", counts)
        self.assertEqual(counts[bugs_map.UNTRIAGED_KEY], 1)
        self.assertEqual(sum(counts[k] for k in counts if k.startswith("L1:")), 3)
        self.assertEqual(len(bugs_map.attribute(bugs, self.m, escaped_only=False)), 6)


class CommandTest(unittest.TestCase):
    def run_cli(self, bugs, *args, mapping=MAP):
        with tempfile.TemporaryDirectory() as tmp:
            cache, path = os.path.join(tmp, "bugs.json"), os.path.join(tmp, "map.yml")
            with open(cache, "w") as f:
                json.dump(bugs, f)
            with open(path, "w") as f:
                json.dump(mapping, f)  # JSON is valid YAML
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = bugs_map.main(["android", "--cache", cache, "--map", path, "--since", "2026-01-01",
                                      "--until", "2026-12-31", *args])
        return code, out.getvalue()

    def test_check_fails_on_unknown_component(self):
        code, out = self.run_cli([bug(1, "Tabs"), bug(2, "Brand new")], "check")
        self.assertEqual(code, 1)
        self.assertIn("Brand new: 1 bugs", out)

    def test_counts_csv_and_window(self):
        bugs = [bug(1, "Tabs"), bug(2, "Performance"), bug(3, "Tabs", created="2025-12-31T23:00:00Z")]
        code, out = self.run_cli(bugs, "counts", "--csv")
        self.assertEqual(code, 0)
        self.assertIn("L2,TABS.TRAY,Tab tray & tab management,1", out)
        self.assertIn("axis,X.PERF,", out)


if __name__ == "__main__":
    unittest.main()
