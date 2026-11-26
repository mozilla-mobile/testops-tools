# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for collect.py: every data file from one command, and a failing source doesn't stop the others."""

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

import collect  # noqa: E402


class FakeSource:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def build(self, cache_dir=None):
        if self.error:
            raise self.error
        return self.result

    def summary(self, out):
        return ["ok"]


class CollectTest(unittest.TestCase):
    def run_collect(self, sources, *args, pre=None):
        with tempfile.TemporaryDirectory() as tmp:
            for name in pre or []:
                with open(os.path.join(tmp, f"{name}.json"), "w") as f:
                    f.write("{}")
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(collect.SOURCES, sources, clear=True), mock.patch.dict(os.environ, {}, clear=True), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = collect.main(["--out-dir", tmp, *args])
            files = {f: json.load(open(os.path.join(tmp, f))) for f in os.listdir(tmp)}
        return code, files, err.getvalue()

    def test_features_file(self):
        rows = collect.feature_rows()
        self.assertEqual(rows["features"][0], {"type": "l1", "id": "BRW", "name": "Browsing & page content"})
        self.assertIn({"type": "l2", "id": "LIB.BMK", "l1": "LIB", "name": "Bookmarks"}, rows["features"])
        self.assertIn("X.PERF", [x["id"] for x in rows["crosscutting"]])
        self.assertIn("SHARED.SHELL", [x["id"] for x in rows["shared"]])
        self.assertEqual([x["id"] for x in rows["excluded"]], ["EXCLUDED"])

    def test_all_sources(self):
        code, files, _ = self.run_collect({"a": FakeSource({"n": 1}), "b": FakeSource({"n": 2})})
        self.assertEqual(code, 0)
        self.assertEqual(sorted(files), ["a.json", "b.json", "features.json", "status.json"])
        self.assertEqual(files["status.json"]["sources"], {"a": {"ok": True}, "b": {"ok": True}})

    def test_one_source_fails(self):
        secret = RuntimeError("https://user:token@example.testrail.io failed")
        code, files, err = self.run_collect({"a": FakeSource(error=secret), "b": FakeSource({"n": 2})}, pre=["a"])
        self.assertEqual(code, 1)
        self.assertNotIn("a.json", files)            # last run's file is removed, not shown as today's
        self.assertEqual(files["b.json"], {"n": 2})
        self.assertEqual(files["status.json"]["sources"]["a"], {"ok": False, "error": "RuntimeError"})
        self.assertNotIn("token", err)              # only the error type is logged

    def test_allow_partial(self):
        code, _, _ = self.run_collect({"a": FakeSource(error=ValueError())}, "--allow-partial")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
