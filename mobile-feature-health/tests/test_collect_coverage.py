# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for collect_coverage.py on a synthetic xccov report and a faked Bitrise API. No network, needs PyYAML."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import collect_coverage  # noqa: E402
from feature_map import FeatureMap  # noqa: E402

MAP = """\
platform: ios
repo: example/firefox-ios
base: ""
extensions: [".swift"]
roots:
  - App
rules:
  - {path: "App/**", feature: SHARED.SHELL}
  - {path: "App/Library/Bookmarks/**", feature: LIB.BMK}
  - {path: "App/Library/History/**", feature: LIB.HIST}
  - {path: "App/Logins/**", feature: CRED}
"""
REPORT = {"targets": [{"name": "Client.app", "files": [
    {"path": "/Users/vagrant/git/App/Library/Bookmarks/Panel.swift", "executableLines": 10, "coveredLines": 5},
    {"path": "/Users/vagrant/git/App/Library/History/Panel.swift", "executableLines": 30, "coveredLines": 3},
    {"path": "/Users/vagrant/git/App/Logins/List.swift", "executableLines": 10, "coveredLines": 2},
    {"path": "/Users/vagrant/git/App/AppDelegate.swift", "executableLines": 50, "coveredLines": 25},
]}]}
SECRET_URL = "https://storage.example/unit-test-coverage.json?X-Signature=secret"


def build(n, slug, finished=True):
    return {"build_number": n, "slug": slug, "branch": "main", "commit_hash": "0123456789abcdef",
            "finished_at": "2026-11-24T10:40:00Z" if finished else None, "stack_identifier": "osx-xcode-27.1.x",
            "status_text": "error"}


class FakeBitrise:
    """builds: newest first; artifacts: {build slug: [titles]}; broken: build slugs whose artifacts can't be read."""

    def __init__(self, builds, artifacts, broken=()):
        self.builds, self.artifacts, self.broken, self.calls = builds, artifacts, broken, []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)
        if any(f"/builds/{slug}/" in url for slug in self.broken):
            raise collect_coverage.requests.ConnectionError("gone")
        r = mock.Mock()
        r.raise_for_status = lambda: None
        if url == SECRET_URL:
            r.json = lambda: REPORT
        elif url.endswith("/builds"):
            r.json = lambda: {"data": self.builds}
        elif url.endswith("/artifacts"):
            slug = url.split("/builds/")[1].split("/")[0]
            r.json = lambda: {"data": [{"title": t, "slug": f"a-{t}"} for t in self.artifacts.get(slug, [])]}
        else:
            r.json = lambda: {"data": {"expiring_download_url": SECRET_URL}}
        return r


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        path = os.path.join(self.dir, "feature-map.yml")
        with open(path, "w") as f:
            f.write(MAP)
        self.fm = FeatureMap("ios", None, map_path=path)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_totals_are_feature_code_only(self):
        out = collect_coverage.collect(REPORT, {"number": 1}, self.fm)["platforms"]["ios"]
        self.assertEqual(out["features"]["L1:LIB"], {"executable": 40, "covered": 8})
        self.assertEqual(out["features"]["L1:CRED"], {"executable": 10, "covered": 2})
        # Areas (features and area-only code), not the shared browser shell.
        self.assertEqual(out["totals"]["features"], {"executable": 50, "covered": 10})
        self.assertEqual(out["totals"]["shared"], {"executable": 50, "covered": 25})
        self.assertEqual(out["unmapped"], [])

    def test_files_are_listed_by_feature_most_uncovered_first(self):
        out = collect_coverage.collect(REPORT, {"number": 1}, self.fm)["platforms"]["ios"]
        self.assertEqual([(e["feature"], e["path"]) for e in out["by_file"]],
                         [("CRED", "App/Logins/List.swift"), ("LIB.BMK", "App/Library/Bookmarks/Panel.swift"),
                          ("LIB.HIST", "App/Library/History/Panel.swift"), ("SHARED.SHELL", "App/AppDelegate.swift")])
        self.assertEqual(out["by_file"][0]["target"], "Client.app")

    def test_uses_the_newest_finished_build_that_has_the_artifact(self):
        api = FakeBitrise([build(3, "running", finished=False), build(2, "no-artifact"), build(1, "good")],
                          {"no-artifact": ["raw-xcodebuild-output.log"], "good": ["unit-test-coverage.json"]})
        with mock.patch.object(collect_coverage.requests, "get", api.get):
            report, meta = collect_coverage.fetch_report("token", "app", "main")
        self.assertEqual(report, REPORT)
        self.assertEqual((meta["number"], meta["status"], meta["commit"]), (1, "error", "0123456789ab"))
        self.assertEqual(meta["url"], "https://app.bitrise.io/build/good")

    def test_history_has_the_earlier_runs_newest_first(self):
        api = FakeBitrise([build(4, "new"), build(3, "no-artifact"), build(2, "gone"), build(1, "old")],
                          {"new": [collect_coverage.ARTIFACT], "gone": [collect_coverage.ARTIFACT],
                           "old": [collect_coverage.ARTIFACT]}, broken={"gone"})
        with mock.patch.object(collect_coverage.requests, "get", api.get):
            runs = collect_coverage.fetch_reports("token", "app", "main")
        self.assertEqual([b["number"] for _, b in runs], [4, 1])   # an unreadable older run is skipped
        (report, meta), previous = runs[0], runs[1:]
        out = collect_coverage.collect(report, meta, self.fm, previous)["platforms"]["ios"]
        self.assertEqual([h["build"]["number"] for h in out["history"]], [4, 1])
        self.assertEqual(out["history"][0]["totals"], out["totals"])
        self.assertEqual(out["history"][1]["features"]["L1:LIB"], [40, 8])
        self.assertNotIn("X-Signature", json.dumps(out))

    def test_the_newest_run_must_be_readable(self):
        api = FakeBitrise([build(2, "gone"), build(1, "old")],
                          {"gone": [collect_coverage.ARTIFACT], "old": [collect_coverage.ARTIFACT]}, broken={"gone"})
        with mock.patch.object(collect_coverage.requests, "get", api.get), \
                self.assertRaises(collect_coverage.requests.RequestException):
            collect_coverage.fetch_reports("token", "app", "main")

    def test_a_run_the_map_cant_read_is_left_out_of_the_trend(self):
        bad = {"targets": [{"name": "Client.app", "files": [
            {"path": "/Users/vagrant/git/App/Logins/List.swift", "executableLines": 1, "coveredLines": 1,
             "functions": [{"name": "f()", "executableLines": 5, "coveredLines": 5}]}]}]}
        symbols = MAP.replace('{path: "App/Logins/**", feature: CRED}',
                              '{path: "App/Logins/**", feature: CRED, symbols: [{match: "f", feature: LIB.BMK}]}')
        path = os.path.join(self.dir, "symbols.yml")
        with open(path, "w") as f:
            f.write(symbols)
        fm = FeatureMap("ios", None, map_path=path)
        out = collect_coverage.collect(REPORT, {"number": 2}, fm, [(bad, {"number": 1})])["platforms"]["ios"]
        self.assertEqual([h["build"]["number"] for h in out["history"]], [2])

    def test_no_build_with_the_artifact_is_an_error(self):
        api = FakeBitrise([build(1, "old")], {"old": []})
        with mock.patch.object(collect_coverage.requests, "get", api.get), self.assertRaises(LookupError):
            collect_coverage.fetch_report("token", "app", "main")

    def test_the_signed_download_url_never_reaches_the_output(self):
        api = FakeBitrise([build(1, "good")], {"good": ["unit-test-coverage.json"]})
        env = {"BITRISE_TOKEN": "token", "BITRISE_APP_SLUG": "app"}
        with mock.patch.object(collect_coverage.requests, "get", api.get), mock.patch.dict(os.environ, env), \
                mock.patch.object(collect_coverage, "FeatureMap", lambda *a, **k: self.fm):
            out = collect_coverage.build()
        text = json.dumps(out) + "\n".join(collect_coverage.summary(out))
        self.assertNotIn("X-Signature", text)
        self.assertNotIn("token", json.dumps(out["platforms"]["ios"]["build"]))

    def test_needs_bitrise_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(RuntimeError):
            collect_coverage.build()


if __name__ == "__main__":
    unittest.main()
