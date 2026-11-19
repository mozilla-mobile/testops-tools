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
import unittest.mock

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
        self.assertEqual(self.m.classify(bug(5, "Brand new")), ("needs a decision", ""))

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


IOS_MAP = {
    "source": "github", "repo": "example/firefox-ios", "bug_labels": ["Bug"],
    "escaped": {"team_associations": ["MEMBER", "OWNER"]}, "spam_phrases": ["please ignore"],
    "title_hints": [{"match": "\\bpdfs?\\b", "feature": "BRW.PDF"}],
    "issues": {101: "LIB.BMK", 102: {"excluded": "macOS, not iOS"}, 103: "APP"},
}


def issue(n, title="Something is broken", assoc="NONE", created="2026-03-01T10:00:00Z"):
    return {"id": n, "summary": title, "assoc": assoc, "creation_time": created, "creator": "x",
            "component": "", "resolution": "", "labels": ["Bug"]}


class IosTest(unittest.TestCase):
    def setUp(self):
        self.m = bugs_map.BugsMap(IOS_MAP, TAXONOMY)

    def test_real_ios_map_is_valid(self):
        m = bugs_map.BugsMap.load("ios")
        self.assertEqual(m.errors, [])
        self.assertGreater(len(m.issues), 100)

    def test_decisions(self):
        self.assertEqual(self.m.classify(issue(101)), ("feature", "LIB.BMK"))
        self.assertEqual(self.m.classify(issue(102)), ("excluded", ""))
        self.assertEqual(self.m.classify(issue(999)), ("needs a decision", ""))
        self.assertEqual(self.m.suggest(issue(999, "PDFs not opening")), "BRW.PDF")

    def test_escaped_and_spam(self):
        self.assertTrue(self.m.is_escaped(issue(1, assoc="CONTRIBUTOR")))
        self.assertFalse(self.m.is_escaped(issue(1, assoc="MEMBER")))
        self.assertFalse(self.m.is_escaped(issue(1, "Please ignore this test")))
        self.assertFalse(self.m.is_escaped(issue(1, "bugs")))

    def test_bad_decision(self):
        bad = dict(IOS_MAP, issues={1: "NOPE.ID", 2: {"excluded": ""}})
        self.assertEqual(len(bugs_map.BugsMap(bad, TAXONOMY).errors), 2)

    def test_undecided_count_as_untriaged(self):
        bugs = [issue(101), issue(102), issue(103), issue(999), issue(104, assoc="MEMBER")]
        counts = bugs_map.count(bugs_map.attribute(bugs, self.m))
        self.assertEqual(counts["LIB.BMK"], 1)
        self.assertEqual(counts["L1:APP"], 1)
        self.assertEqual(counts[bugs_map.UNTRIAGED_KEY], 1)


class CacheWindowTest(unittest.TestCase):
    def test_cache_reused_only_for_a_covered_window(self):
        m = bugs_map.BugsMap(MAP, TAXONOMY)
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "bugs.json")
            with open(cache, "w") as f:
                json.dump({"schema": bugs_map.CACHE_SCHEMA, "since": "2026-01-01", "until": "2026-03-31",
                           "bugs": [bug(1, "Tabs", created="2026-02-01T00:00:00Z"),
                                    bug(2, "Tabs", created="2026-03-15T00:00:00Z")]}, f)
            got = bugs_map.load_bugs(m, "2026-01-01", "2026-02-28", cache)
            self.assertEqual([b["id"] for b in got], [1])
            with unittest.mock.patch.object(bugs_map, "fetch", return_value=[]) as fetch:
                bugs_map.load_bugs(m, "2026-01-01", "2026-04-30", cache)   # later "today": refetch
            fetch.assert_called_once()
            with open(cache) as f:
                self.assertEqual(json.load(f)["until"], "2026-04-30")


class RetryTest(unittest.TestCase):
    def test_retries_5xx_then_succeeds(self):
        bad, good = unittest.mock.Mock(status_code=502, headers={}), unittest.mock.Mock(status_code=200, headers={})
        session = unittest.mock.Mock()
        session.get.side_effect = [bad, good]
        with unittest.mock.patch.object(bugs_map.time, "sleep"):
            self.assertIs(bugs_map.get_with_retry(session, "https://x"), good)
        self.assertEqual(session.get.call_count, 2)


TARGETS = bugs_map.valid_targets(TAXONOMY)


class IosTeamTest(unittest.TestCase):
    MAP = dict(IOS_MAP, escaped={"team_org": "example", "team_teams": ["ios-eng"], "bot_logins": ["sync-bot"],
                                 "tag_associations": ["MEMBER"]})

    def test_team_membership_decides(self):
        m = bugs_map.BugsMap(self.MAP, TAXONOMY)
        insider = dict(issue(1, assoc="MEMBER"), team=True)
        mozillian = dict(issue(2, assoc="MEMBER"), team=False)    # org member outside the iOS teams: escaped
        community = dict(issue(3, assoc="CONTRIBUTOR"), team=False)
        bot = dict(issue(4, assoc="COLLABORATOR"), team=False, creator="Sync-Bot")
        self.assertEqual([m.is_escaped(b) for b in (insider, mozillian, community, bot)], [False, True, True, False])

    def test_members_are_read_and_failures_are_explicit(self):
        m = bugs_map.BugsMap(self.MAP, TAXONOMY)
        ok = unittest.mock.Mock(status_code=200, links={}, json=lambda: [{"login": "Alice"}, {"login": "bob"}])
        session = unittest.mock.Mock(); session.get.return_value = ok
        self.assertEqual(bugs_map.team_members(m, session), {"alice", "bob"})
        session.get.return_value = unittest.mock.Mock(status_code=404, links={})
        with self.assertRaisesRegex(RuntimeError, "read:org"):
            bugs_map.team_members(m, session)


class AssignedByTest(unittest.TestCase):
    def test_ios(self):
        m = bugs_map.BugsMap(IOS_MAP, TAXONOMY)
        self.assertEqual(m.assigned_by(issue(101)), "decision")
        self.assertEqual(m.assigned_by(issue(900)), "waiting for a decision")
        b = issue(901)
        b["tag_text"] = "Main menu (UI.MENU)"
        self.assertEqual(m.assigned_by(b), "tag")

    def test_android(self):
        m = bugs_map.BugsMap(MAP, TAXONOMY)
        self.assertEqual(m.assigned_by(bug(1, "Tabs", "tab group crash")), "title rule")
        self.assertEqual(m.assigned_by(bug(2, "Tabs", "tray empty")), "component")
        self.assertEqual(m.assigned_by(bug(3, "General")), "untriaged")


class TagTest(unittest.TestCase):
    def test_parse(self):
        p = lambda t: bugs_map.parse_tag(t, TARGETS)
        self.assertEqual(p("Toolbar & address bar layout (UI.TB)"), ("feature", "UI.TB"))
        self.assertEqual(p("UI.TB"), ("feature", "UI.TB"))
        self.assertEqual(p("AI controls (AI.CTRL)"), ("feature", "AI.CTRL"))      # "AI" alone is an L1 too
        self.assertEqual(p("Performance (X.PERF)"), ("feature", "X.PERF"))
        self.assertEqual(p("Passwords & autofill (CRED)"), ("feature", "CRED"))
        self.assertEqual(p("excluded (Focus, not Firefox)"), ("excluded", ""))
        self.assertEqual(p("Toolbar (UI.TOOLBAR)"), ("invalid tag", "UI.TOOLBAR"))
        self.assertIsNone(p("it works for me now"))
        self.assertIsNone(p(""))

    def test_comment_line(self):
        body = "Thanks!\nFeature affected: Page translation (TRANS.PAGE)\nWIP-Comment added by QA/Test Eng team"
        self.assertEqual(bugs_map.comment_tag(body), "Page translation (TRANS.PAGE)")
        self.assertEqual(bugs_map.comment_tag("**Feature:** UI.TB"), "UI.TB")
        self.assertIsNone(bugs_map.comment_tag("There's also a different feature planned for next week"))

    def test_tag_wins(self):
        ios = bugs_map.BugsMap(IOS_MAP, TAXONOMY)
        b = issue(101)                                          # decided LIB.BMK in the map
        b["tag_text"] = "Main menu (UI.MENU)"
        self.assertEqual(ios.classify(b), ("feature", "UI.MENU"))
        b["tag_text"] = "excluded (macOS)"
        self.assertEqual(ios.classify(b), ("excluded", ""))
        b["tag_text"] = "Main menu (UI.MNU)"                     # typo: falls back to the decision, reported
        self.assertEqual(ios.classify(b), ("feature", "LIB.BMK"))
        android = bugs_map.BugsMap(MAP, TAXONOMY)
        tb = bug(1, "Tabs")
        tb["tag_text"] = "BRW.FIND"
        self.assertEqual(android.classify(tb), ("feature", "BRW.FIND"))

    def test_bugzilla_whiteboard_and_team_comments(self):
        m = bugs_map.BugsMap(MAP, TAXONOMY)
        b1, b2, b3 = bug(1, "Tabs"), bug(2, "Tabs"), bug(3, "Tabs")
        b1["whiteboard"] = "[fxdroid] [feature:BRW.FIND]"
        comments = {"bugs": {
            "2": {"comments": [{"creator": "dev@example.com", "creation_time": "2026-03-02T00:00:00Z",
                                "text": "Feature affected: Tab groups & collections (TABS.GRP)"}]},
            "3": {"comments": [{"creator": "someone@gmail.com", "creation_time": "2026-03-02T00:00:00Z",
                                "text": "Feature affected: Main menu (UI.MENU)"}]}}}
        session = unittest.mock.Mock()
        session.get.return_value = unittest.mock.Mock(status_code=200, headers={}, json=lambda: comments)
        bugs_map.add_bugzilla_tags(m, [b1, b2, b3], session)
        self.assertEqual((b1["tag_text"], b1["tag_source"]), ("BRW.FIND", "whiteboard"))
        self.assertEqual((b2["tag_text"], b2["tag_source"]), ("Tab groups & collections (TABS.GRP)", "comment"))
        self.assertNotIn("tag_text", b3)                         # not from the team: ignored
        url, params = session.get.call_args[0][0], session.get.call_args[1]["params"]
        self.assertTrue(url.endswith("/2/comment"))
        self.assertEqual(params, [("ids", "3")])


class CommandTest(unittest.TestCase):
    def run_cli(self, bugs, *args, mapping=MAP, platform="android"):
        with tempfile.TemporaryDirectory() as tmp:
            cache, path = os.path.join(tmp, "bugs.json"), os.path.join(tmp, "map.yml")
            with open(cache, "w") as f:
                json.dump(bugs, f)
            with open(path, "w") as f:
                json.dump(mapping, f)  # JSON is valid YAML
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = bugs_map.main([platform, "--cache", cache, "--map", path, "--since", "2026-01-01",
                                      "--until", "2026-12-31", *args])
        return code, out.getvalue()

    def test_check_fails_on_unknown_component(self):
        code, out = self.run_cli([bug(1, "Tabs"), bug(2, "Brand new")], "check")
        self.assertEqual(code, 1)
        self.assertIn("Brand new: 1 bugs", out)

    def test_ios_check_lists_undecided_with_suggestion(self):
        code, out = self.run_cli([issue(101), issue(555, "PDFs not opening")], "check", mapping=IOS_MAP,
                                 platform="ios")
        self.assertEqual(code, 1)
        self.assertIn("#555 PDFs not opening", out)
        self.assertIn("Feature affected: PDFs, documents & printing (BRW.PDF)", out)

    def test_check_reports_invalid_tags(self):
        b = issue(101)
        b["tag_text"], b["tag_source"] = "Main menu (UI.MNU)", "comment"
        code, out = self.run_cli([b], "check", mapping=IOS_MAP, platform="ios")
        self.assertEqual(code, 1)
        self.assertIn("`UI.MNU`", out)

    def test_counts_csv_and_window(self):
        bugs = [bug(1, "Tabs"), bug(2, "Performance"), bug(3, "Tabs", created="2025-12-31T23:00:00Z")]
        code, out = self.run_cli(bugs, "counts", "--csv")
        self.assertEqual(code, 0)
        self.assertIn("L2,TABS.TRAY,Tab tray & tab management,1", out)
        self.assertIn("axis,X.PERF,", out)


if __name__ == "__main__":
    unittest.main()
