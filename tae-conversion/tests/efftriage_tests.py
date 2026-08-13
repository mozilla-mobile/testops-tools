#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for efftriage — the failed-run -> gotcha mapper (MTE-5827).

No device, no Firefox checkout, no network: the rule tests run against REAL
labelled conversion runs checked in under tests/fixtures/corpus, and the
edge-case tests against synthetic batch dirs in temp dirs.

Why the fixtures are real runs and not hand-written traces. efftriage is only
worth having if it can be trusted, because a confidently WRONG diagnosis is
worse than none: it sends the reader down the wrong path, which is the exact
failure mode the tool exists to prevent. Hand-written traces test the shapes the
author imagined, so they can pass while the tool mismatches real output --- a
false green in the very suite meant to prevent false greens. The corpus was
previously implicit: labelled batch dirs sitting in one person's conversion-runs/,
unversioned and unrunnable in CI.

    python -m unittest discover -s tae-conversion/tests -p '*tests.py'
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOL_ROOT = os.path.dirname(TESTS_DIR)
TOOLS = os.path.join(TOOL_ROOT, "tools")
CORPUS = os.path.join(TESTS_DIR, "fixtures", "corpus")
sys.path.insert(0, TOOLS)

import efftriage  # noqa: E402

with open(os.path.join(CORPUS, "labels.json")) as _fh:
    LABELS = json.load(_fh)

# Rules with no labelled example anywhere in the 53-run corpus they were written
# against. They are unvalidated, not known-good: a rule that has never fired on a
# real failure may not match the shape it was written for at all. Delete an entry
# here as soon as a real run exercises it.
UNVALIDATED_RULES = {"T3", "T4", "T5"}


class CorpusTests(unittest.TestCase):
    """Every labelled real run must still be diagnosed the way it was labelled."""

    def triage(self, name):
        return efftriage.triage(os.path.join(CORPUS, name))

    def test_outcome_matches_status_json(self):
        for name, want in LABELS.items():
            with self.subTest(run=name):
                self.assertEqual(self.triage(name)["outcome"], want["outcome"])

    def test_expected_rules_still_fire(self):
        for name, want in LABELS.items():
            if want["known_gap"]:
                continue
            with self.subTest(run=name):
                got = [f["rule"] for f in self.triage(name)["findings"]]
                self.assertEqual(
                    got, want["expected_rules"],
                    f"{name} ({want['source_batch']}) changed diagnosis",
                )

    def test_known_gaps_are_still_gaps(self):
        # A tripwire, not an endorsement: these are real failures efftriage cannot
        # explain. If you add a rule that covers one, this test fails --- that is the
        # reminder to move it out of the gap list and give it expected_rules.
        for name, want in LABELS.items():
            if not want["known_gap"]:
                continue
            with self.subTest(run=name):
                self.assertEqual(
                    self.triage(name)["findings"], [],
                    f"{name} is now diagnosed --- update labels.json to record the win",
                )

    def test_retry_detection_matches_labels(self):
        for name, want in LABELS.items():
            with self.subTest(run=name):
                self.assertEqual(bool(self.triage(name).get("retried")), want["retried"])

    def has_skips(self, name):
        with open(os.path.join(CORPUS, name, "status.json")) as fh:
            status = json.load(fh)
        return any(r.get("status") == "skipped" for r in status.get("results", []))

    def test_passing_nonretried_runs_are_never_triaged(self):
        # The invariant that a false positive violated: non-fatal [ERR] lines
        # (nav-graph polling, tolerated absence checks) made the rules invent a cause
        # for a green run.
        #
        # "outcome == pass" is NOT the same as genuinely green, so runs containing a skip
        # are excluded: for those, `pass` is itself the bug (gotcha A44) and a finding is
        # the correct output, not a false positive.
        for name, want in LABELS.items():
            if want["outcome"] != "pass" or want["retried"] or self.has_skips(name):
                continue
            with self.subTest(run=name):
                self.assertEqual(self.triage(name)["findings"], [])

    def test_every_finding_is_wellformed(self):
        for name in LABELS:
            for f in self.triage(name)["findings"]:
                with self.subTest(run=name, rule=f.get("rule")):
                    for key in ("rule", "gotcha", "line", "cause", "fix"):
                        self.assertIn(key, f)
                    self.assertTrue(f["cause"], "a finding must say what happened")
                    self.assertTrue(f["fix"], "a finding must say what to do")
                    self.assertTrue(f["gotcha"], "a finding must cite a gotcha id")

    def test_no_corpus_run_raises(self):
        for name in LABELS:
            with self.subTest(run=name):
                efftriage.triage(os.path.join(CORPUS, name))


class RuleInventoryTests(unittest.TestCase):
    """Keep the gap between 'rules that exist' and 'rules proven to work' visible."""

    def rule_ids(self):
        return {r[0] for r in efftriage.RULES}

    def test_every_rule_has_a_labelled_example_or_is_listed_unvalidated(self):
        exercised = {
            f["rule"]
            for name in LABELS
            for f in efftriage.triage(os.path.join(CORPUS, name))["findings"]
        }
        unproven = self.rule_ids() - exercised - UNVALIDATED_RULES
        self.assertEqual(
            unproven, set(),
            "new rules need a labelled corpus run, or an entry in UNVALIDATED_RULES "
            "explaining that they are unproven",
        )

    def test_unvalidated_list_does_not_go_stale(self):
        exercised = {
            f["rule"]
            for name in LABELS
            for f in efftriage.triage(os.path.join(CORPUS, name))["findings"]
        }
        self.assertEqual(
            UNVALIDATED_RULES & exercised, set(),
            "a rule listed as unvalidated now has a real example --- remove it from "
            "UNVALIDATED_RULES",
        )

    def test_rule_ids_are_unique(self):
        ids = [r[0] for r in efftriage.RULES]
        self.assertEqual(len(ids), len(set(ids)))


class SyntheticBatch:
    """Builds throwaway batch dirs; shapes the real corpus happens not to contain."""

    def batch(self, report=None, status=None, exists=True):
        td = tempfile.TemporaryDirectory(prefix="efftriage-test-")
        self.addCleanup(td.cleanup)
        if not exists:
            return os.path.join(td.name, "no-such-batch")
        if report is not None:
            with open(os.path.join(td.name, "run-report.txt"), "w") as fh:
                fh.write(report)
        if status is not None:
            with open(os.path.join(td.name, "status.json"), "w") as fh:
                json.dump(status, fh)
        return td.name


class BadInputTests(SyntheticBatch, unittest.TestCase):
    def test_nonexistent_dir_is_not_diagnosed_as_a_harness_problem(self):
        res = efftriage.triage(self.batch(exists=False))
        self.assertEqual(res["outcome"], "no-such-batch")
        self.assertEqual(res["findings"], [])
        joined = " ".join(res["notes"])
        self.assertIn("no such batch directory", joined)
        # Previously fell through to A24 and sent the reader off to check effpretty
        # resolution and pull dumps off a device --- for a mistyped path.
        self.assertNotIn("A24", joined)
        self.assertNotIn("effpretty", joined)

    def test_real_dir_with_empty_report_still_reports_A24(self):
        res = efftriage.triage(self.batch(report="", status={"outcome": "unknown"}))
        self.assertIn("A24", " ".join(res["notes"]))

    def test_missing_status_json_does_not_crash(self):
        res = efftriage.triage(self.batch(report="run finished: 1 tests, 1 failed\n"))
        self.assertEqual(res["outcome"], "unknown")

    def test_malformed_status_json_does_not_crash(self):
        d = self.batch(report="run finished: 1 tests, 1 failed\n")
        with open(os.path.join(d, "status.json"), "w") as fh:
            fh.write("{not json")
        self.assertEqual(efftriage.triage(d)["outcome"], "unknown")


class CrashModeTests(SyntheticBatch, unittest.TestCase):
    """Crash mode is where `outcome: pass` is itself the lie (MTE-5822)."""

    def test_crash_finding_survives_a_pass_outcome(self):
        report = "CRASH: java.lang.NullPointerException at Foo.bar\nrun finished: 1 tests, 0 failed\n"
        res = efftriage.triage(self.batch(report=report, status={"outcome": "pass"}))
        self.assertTrue(
            res["findings"], "the pass-gate must not swallow a crash: pass is the lie here"
        )
        self.assertEqual(res["findings"][0]["rule"], "T10")

    def test_retry_pass_is_labelled_flaky_and_still_explained(self):
        report = (
            "[ERR] x 'Foo' appeared before 3000ms elapsed\nrun finished: 1 tests, 1 failed\n"
            "Started try #2\nrun finished: 1 tests, 0 failed\n"
        )
        res = efftriage.triage(self.batch(report=report, status={"outcome": "pass"}))
        self.assertTrue(res["retried"])
        self.assertIn("ONLY ON RETRY", " ".join(res["notes"]))


class SkippedRunTests(SyntheticBatch, unittest.TestCase):
    """A skip asserts nothing, so it must never read as green (gotcha A44).

    This was the campaign's fifth false-green shape: effloop scored `outcome: pass` whenever
    `failures == 0 and tests > 0`, which an @Ignore'd or Assume()-gated test satisfies without
    running. effverify got it right (`passed: false`); efftriage trusted the outcome and said
    "nothing to triage".
    """

    def test_all_skipped_is_diagnosed_even_when_outcome_claims_pass(self):
        # The load-bearing case: the field that should raise the alarm is the one that lied, so the
        # diagnosis must come from the per-test statuses instead.
        res = efftriage.triage(self.batch(
            report="run finished: 1 tests, 0 failed, 0 ignored\n",
            status={"outcome": "pass", "tests": 1, "failures": 0, "skipped": 1,
                    "results": [{"name": "someTest", "status": "skipped"}]},
        ))
        self.assertEqual([f["rule"] for f in res["findings"]], ["T11"])
        self.assertEqual(res["findings"][0]["gotcha"], "A44")
        self.assertIn("nothing was verified", res["findings"][0]["cause"])
        self.assertIn("someTest", res["findings"][0]["cause"])

    def test_skipped_test_names_are_reported(self):
        res = efftriage.triage(self.batch(
            report="x\n",
            status={"outcome": "skipped",
                    "results": [{"name": "aTest", "status": "skipped"},
                                {"name": "bTest", "status": "skipped"}]},
        ))
        self.assertEqual(res["skipped"], ["aTest", "bTest"])

    def test_partial_skip_alongside_a_pass_is_still_flagged(self):
        res = efftriage.triage(self.batch(
            report="x\n",
            status={"outcome": "partial",
                    "results": [{"name": "ranTest", "status": "pass"},
                                {"name": "gatedTest", "status": "skipped"}]},
        ))
        self.assertEqual([f["rule"] for f in res["findings"]], ["T11"])
        self.assertIn("incomplete", res["findings"][0]["cause"])
        self.assertIn("gatedTest", res["findings"][0]["cause"])

    def test_a_genuine_pass_is_not_flagged_as_skipped(self):
        res = efftriage.triage(self.batch(
            report="run finished: 1 tests, 0 failed, 0 ignored\n",
            status={"outcome": "pass", "skipped": 0,
                    "results": [{"name": "someTest", "status": "pass"}]},
        ))
        self.assertEqual(res["findings"], [])
        self.assertEqual(res.get("skipped", []), [])


class CliTests(unittest.TestCase):
    """The CLI contract, measured on the process. Piping a tool through `head`
    reports the pager's exit status, not the tool's --- an easy way to convince
    yourself a broken exit code is fine."""

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(TOOLS, "efftriage.py"), *args],
            capture_output=True, text=True, timeout=60,
        )

    def test_no_args_is_a_usage_error(self):
        p = self.run_cli()
        self.assertEqual(p.returncode, 2)
        self.assertIn("usage:", p.stdout + p.stderr)

    def test_version_resolves_and_exits_zero(self):
        p = self.run_cli("--version")
        self.assertEqual(p.returncode, 0)
        self.assertIn("efftriage.py", p.stdout)
        self.assertNotIn("unknown", p.stdout, "VERSION must resolve, even through a symlink")

    def test_json_output_is_valid_json(self):
        p = self.run_cli(os.path.join(CORPUS, "T10-crash"), "--json")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout)["tool"], "efftriage")

    def test_nonexistent_batch_does_not_traceback(self):
        p = self.run_cli(os.path.join(tempfile.gettempdir(), "definitely-not-a-batch"))
        self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main()
