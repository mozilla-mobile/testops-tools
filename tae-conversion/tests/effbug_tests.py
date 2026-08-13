#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for effbug's request building.

No network and no API key: the one function that talks to Bugzilla (`_req`) is stubbed, so these assert
what effbug *would* send. That is the part worth pinning — a wrong field silently writes the wrong thing
to a public bug, and unlike a test failure there is no undo.

    python -m unittest discover -s tae-conversion/tests -p '*tests.py'
"""

import os
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(TESTS_DIR), "tools")
sys.path.insert(0, TOOLS)

import effbug  # noqa: E402


class EffbugCase(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake_req(method, path, body=None):
            self.calls.append((method, path, body))
            return {"bugs": [{"id": 1}], "id": 1}

        self.patch(effbug, "_req", fake_req)
        self.patch(effbug, "API_KEY", "fake-key-for-tests")

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, old)

    def sent_fields(self):
        puts = [c for c in self.calls if c[0] == "PUT"]
        self.assertTrue(puts, "expected a PUT")
        return puts[-1][2]


class UpdateCommentTests(EffbugCase):
    """`comment` on update must post a NEW comment.

    Comment 0 cannot be edited through the Bugzilla API, so without this there is nowhere for a
    correction to go — which is exactly what was needed after a bug was filed with a wrong TestRail id.
    """

    def test_comment_is_sent_as_a_new_comment(self):
        effbug.run({"bug": "update", "id": 2063232, "comment": "a correction"})
        self.assertEqual(self.sent_fields()["comment"], {"body": "a correction"})

    def test_comment_is_trimmed_and_blank_is_ignored(self):
        # A blank comment must not create an empty comment, and must not count as "something to change".
        with self.assertRaises(RuntimeError):
            effbug.run({"bug": "update", "id": 1, "comment": "   ", "self_assign": False})

    def test_comment_travels_alongside_other_fields(self):
        effbug.run({"bug": "update", "id": 1, "comment": "note", "priority": "P3"})
        fields = self.sent_fields()
        self.assertEqual(fields["priority"], "P3")
        self.assertEqual(fields["comment"], {"body": "note"})

    def test_update_requires_a_numeric_id(self):
        with self.assertRaises(RuntimeError):
            effbug.run({"bug": "update", "id": "not-a-number", "comment": "x"})

    def test_update_with_nothing_to_change_is_an_error(self):
        with self.assertRaises(RuntimeError):
            effbug.run({"bug": "update", "id": 1, "self_assign": False})


class ActionTests(EffbugCase):
    def test_unknown_action_is_rejected_by_name(self):
        with self.assertRaises(RuntimeError) as ctx:
            effbug.run({"bug": "frobnicate", "id": 1})
        self.assertIn("frobnicate", str(ctx.exception))

    def test_relations_are_wrapped_as_add_not_replaced(self):
        # A bare list REPLACES the set, which on a meta bug would silently drop every other bug it tracks.
        effbug.run({"bug": "update", "id": 1, "blocks": [2030727]})
        self.assertEqual(self.sent_fields()["blocks"], {"add": [2030727]})


class DescriptionTests(unittest.TestCase):
    """The description composer is pure, so it needs no stubbing."""

    def test_testrail_id_is_appended(self):
        body = effbug._compose_description(
            {"comment": "what", "why": "because", "kind": "conversion", "testrail": "249659"},
        )
        self.assertIn("TestRail: 249659", body)
        self.assertIn("Why: because", body)

    def test_multiple_testrail_ids_are_joined(self):
        body = effbug._compose_description({"comment": "x", "testrail": ["1", "2"]})
        self.assertIn("TestRail: 1, 2", body)

    def test_context_footer_can_be_suppressed(self):
        with_footer = effbug._compose_description({"comment": "x"})
        without = effbug._compose_description({"comment": "x", "no_context_footer": True})
        self.assertLess(len(without), len(with_footer))


if __name__ == "__main__":
    unittest.main()
