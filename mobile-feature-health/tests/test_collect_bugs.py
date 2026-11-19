# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for collect_bugs.py on synthetic bugs. No network, needs PyYAML only."""

import os
import sys
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import collect_bugs  # noqa: E402
from collect_bugs import bugs_map  # noqa: E402
from feature_map import load_taxonomy  # noqa: E402

TAXONOMY = load_taxonomy()
ANDROID = bugs_map.BugsMap({
    "product": "Firefox for Android",
    "escaped": {"team_email_domains": ["mozilla.com"], "bot_email_suffixes": ["@mozilla.tld"], "bot_emails": []},
    "not_counted_resolutions": ["DUPLICATE"],
    "components": {"Tabs": {"feature": "TABS.TRAY"}, "Performance": {"feature": "X.PERF"},
                   "General": {"untriaged": True}, "Tooling": {"excluded": True}},
}, TAXONOMY)
IOS = bugs_map.BugsMap({
    "source": "github", "repo": "mozilla-mobile/firefox-ios", "bug_labels": ["Bug"],
    "escaped": {"team_associations": ["MEMBER"]}, "issues": {10: "LIB.BMK"},
}, TAXONOMY)


def bz(i, component, status="NEW", creator="someone@example.org", resolution=""):
    return {"id": i, "summary": f"bug {i}", "component": component, "status": status, "resolution": resolution,
            "creator": creator, "creation_time": "2026-03-01T00:00:00Z"}


def gh(n, state="open", assoc="NONE"):
    return {"id": n, "summary": f"issue {n}", "state": state, "assoc": assoc, "creator": "x", "component": "",
            "resolution": "", "creation_time": "2026-03-01T00:00:00Z"}


class AndroidTest(unittest.TestCase):
    def setUp(self):
        bugs = [bz(1, "Tabs"), bz(2, "Tabs", status="RESOLVED", resolution="FIXED"), bz(3, "Performance"),
                bz(4, "General"), bz(5, "Tooling"), bz(6, "Tabs", resolution="DUPLICATE", status="RESOLVED"),
                bz(7, "Tabs", creator="dev@mozilla.com")]
        self.out = collect_bugs.platform_bugs(ANDROID, bugs, "2026-01-01")

    def test_rows_and_lists(self):
        self.assertEqual(self.out["features"]["TABS.TRAY"], ["1", "2"])
        self.assertEqual(self.out["features"]["L1:TABS"], ["1", "2"])
        self.assertEqual(self.out["features"]["X.PERF"], ["3"])
        self.assertEqual(self.out["features"]["UNTRIAGED"], ["4"])
        self.assertEqual(self.out["escaped"], 4)
        self.assertEqual(sorted(self.out["bugs"]), ["1", "2", "3", "4"])

    def test_open_closed_and_links(self):
        self.assertTrue(self.out["bugs"]["1"]["open"])
        self.assertFalse(self.out["bugs"]["2"]["open"])
        self.assertEqual(self.out["bugs"]["1"]["url"], "https://bugzilla.mozilla.org/show_bug.cgi?id=1")
        self.assertEqual(self.out["list_url"], "https://bugzilla.mozilla.org/buglist.cgi?bug_id=")

    def test_feature_and_how_per_bug(self):
        self.assertEqual((self.out["bugs"]["1"]["feature"], self.out["bugs"]["1"]["how"]), ("TABS.TRAY", "component"))
        self.assertEqual((self.out["bugs"]["4"]["feature"], self.out["bugs"]["4"]["how"]), ("", "untriaged"))

    def test_tag_is_reported(self):
        b = bz(8, "Tabs")
        b["tag_text"] = "Find in page (BRW.FIND)"
        out = collect_bugs.platform_bugs(ANDROID, [b], "2026-01-01")
        self.assertEqual((out["bugs"]["8"]["feature"], out["bugs"]["8"]["how"]), ("BRW.FIND", "tag"))

    def test_title_rule_is_reported(self):
        m = bugs_map.BugsMap(dict(ANDROID.data, components={
            "Tabs": {"feature": "TABS.TRAY", "titles": [{"match": "group", "feature": "TABS.GRP"}]}}), TAXONOMY)
        b = bz(9, "Tabs")
        b["summary"] = "Tab group lost"
        out = collect_bugs.platform_bugs(m, [b], "2026-01-01")
        self.assertEqual((out["bugs"]["9"]["feature"], out["bugs"]["9"]["how"]), ("TABS.GRP", "title rule"))

    def test_query_url_mirrors_the_filters(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.out["query_url"]).query)
        self.assertEqual(q["product"], ["Firefox for Android"])
        self.assertEqual(q["chfieldfrom"], ["2026-01-01"])
        self.assertIn("@mozilla.com", q["v1"])
        self.assertIn("Tooling", [v[0] for k, v in q.items() if k.startswith("v")])


class IosTest(unittest.TestCase):
    def test_issues(self):
        out = collect_bugs.platform_bugs(IOS, [gh(10, state="closed"), gh(11), gh(12, assoc="MEMBER")], "2026-01-01")
        self.assertEqual(out["features"]["LIB.BMK"], ["10"])
        self.assertEqual(out["features"]["UNTRIAGED"], ["11"])
        self.assertEqual(out["undecided"], 1)
        self.assertFalse(out["bugs"]["10"]["open"])
        self.assertEqual(out["bugs"]["10"]["how"], "decision")
        self.assertEqual(out["bugs"]["11"]["how"], "waiting for a decision")
        self.assertEqual(out["bugs"]["10"]["url"], "https://github.com/mozilla-mobile/firefox-ios/issues/10")
        self.assertIsNone(out["list_url"])
        self.assertIn("created%3A%3E%3D2026-01-01", out["query_url"])


if __name__ == "__main__":
    unittest.main()
