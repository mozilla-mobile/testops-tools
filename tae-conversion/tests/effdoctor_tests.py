#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Tests for effdoctor — the session preflight and toolchain map (MTE-5766).

No device, no live effwatch, no Firefox checkout: each case builds a fake
checkout in a temp dir and stubs the one function that shells out, so `ps`,
`lsof`, `adb` and `git` are all scripted.

Why this file exists. effdoctor's entire job is to answer "which queue is the
live watcher actually reading", because a request dropped in the wrong queue is
never consumed and never errors --- it just hangs. Its first live run got that
answer WRONG: effwatch had been launched as `./tae-conversion/tools/effwatch.sh`
and the relative path was resolved with os.path.abspath, i.e. against
effdoctor's own cwd rather than the watcher's, so it named a directory that had
never existed and advised queueing into it. Same class as the bug it exists to
catch. The cwd-invariance test below is the regression guard.

    python -m unittest discover -s tae-conversion/tests -p '*tests.py'
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOL_ROOT = os.path.dirname(TESTS_DIR)
TOOLS = os.path.join(TOOL_ROOT, "tools")
sys.path.insert(0, TOOLS)

import effdoctor  # noqa: E402

EFFPRETTY_REL = effdoctor.EFFPRETTY_REL


class DoctorCase(unittest.TestCase):
    """A fake world: canonical tools dir, canonical queue, a repo with effpretty,
    one adb device. Findings therefore come only from what a test sets up."""

    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix="effdoctor-test-")
        self.addCleanup(td.cleanup)
        self.root = td.name

        self.canon_tools = os.path.join(self.root, "testops-tools", "tae-conversion", "tools")
        self.canon_queue = os.path.join(
            self.root, "testops-tools", "tae-conversion", "conversion-runs", "_queue"
        )
        os.makedirs(self.canon_tools)
        os.makedirs(self.canon_queue)

        self.repo = os.path.join(self.root, "firefox")
        effpretty = os.path.join(self.repo, EFFPRETTY_REL)
        os.makedirs(os.path.dirname(effpretty))
        open(effpretty, "w").close()

        self.patch(effdoctor, "CANON_TOOLS", self.canon_tools)
        self.patch(effdoctor, "CANON_ROOT", os.path.dirname(self.canon_tools))
        self.patch(effdoctor, "REPO", self.repo)
        # No alt checkout by default, so the divergence check stays quiet.
        self.patch(effdoctor, "ALT_TOOLS", os.path.join(self.root, "nonexistent-alt"))

        self.watchers = []      # (pid, launch_path_as_in_ps, cwd_or_None)
        self.devices = ["emulator-5554\tdevice"]

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, old)

    def fake_sh(self, cmd):
        if cmd.startswith("ps "):
            return "\n".join(f"  {pid} bash {path}" for pid, path, _ in self.watchers)
        if cmd.startswith("lsof "):
            pid = cmd.split("-p ")[1].split()[0]
            for wpid, _, cwd in self.watchers:
                if str(wpid) == pid:
                    return f"p{pid}\nn{cwd}" if cwd else ""
            return ""
        if cmd.startswith("adb devices"):
            return "List of devices attached\n" + "\n".join(self.devices)
        if cmd.startswith("pgrep"):
            return ""
        if cmd.startswith("git "):
            return "some-branch"
        return ""

    def check(self):
        self.patch(effdoctor, "sh", self.fake_sh)
        return effdoctor.check()

    def levels(self, res, level):
        return [f for f in res["findings"] if f["level"] == level]

    def text(self, res):
        return " ".join(
            (f["message"] or "") + " " + (f["fix"] or "") for f in res["findings"]
        )


class QueueResolutionTests(DoctorCase):
    """Resolving the watched queue is the whole point of the tool."""

    def test_relative_launch_path_resolves_against_the_watcher_cwd(self):
        # The original bug: resolved against effdoctor's cwd instead, naming a queue
        # under whatever directory effdoctor happened to be run from.
        self.watchers = [(4242, "./tae-conversion/tools/effwatch.sh",
                          os.path.join(self.root, "testops-tools"))]
        res = self.check()
        w = res["watchers"][0]
        self.assertEqual(w["watching_queue"], self.canon_queue)
        self.assertTrue(w["canonical"])
        self.assertTrue(w["exists"])
        self.assertTrue(res["ok"], self.text(res))

    def test_answer_does_not_depend_on_effdoctors_own_cwd(self):
        # The regression guard proper: same fake world, three different cwds, and the
        # reported queue must be identical. This is what silently broke before.
        self.watchers = [(4242, "./tae-conversion/tools/effwatch.sh",
                          os.path.join(self.root, "testops-tools"))]
        answers = set()
        original = os.getcwd()
        self.addCleanup(os.chdir, original)
        for cwd in (self.root, self.repo, tempfile.gettempdir()):
            os.chdir(cwd)
            answers.add(self.check()["watchers"][0]["watching_queue"])
        self.assertEqual(answers, {self.canon_queue})

    def test_absolute_launch_path_is_used_as_is(self):
        self.watchers = [(4242, os.path.join(self.canon_tools, "effwatch.sh"), "/some/other/place")]
        res = self.check()
        self.assertEqual(res["watchers"][0]["watching_queue"], self.canon_queue)
        self.assertTrue(res["ok"], self.text(res))

    def test_noncanonical_but_existing_queue_is_a_warning_naming_that_queue(self):
        alt_tools = os.path.join(self.root, "ui-test-modernization", "tools")
        alt_queue = os.path.join(self.root, "ui-test-modernization", "conversion-runs", "_queue")
        os.makedirs(alt_tools)
        os.makedirs(alt_queue)
        self.watchers = [(4242, os.path.join(alt_tools, "effwatch.sh"), self.root)]
        res = self.check()
        w = res["watchers"][0]
        self.assertEqual(w["watching_queue"], alt_queue)
        self.assertFalse(w["canonical"])
        self.assertTrue(w["exists"])
        self.assertTrue(self.levels(res, "WARN"))
        self.assertIn(alt_queue, self.text(res))


class WrongAnswerTests(DoctorCase):
    """Declining to answer beats answering wrongly: a queue path that does not
    exist sends the reader somewhere permanently silent."""

    def test_nonexistent_computed_queue_is_a_failure(self):
        self.watchers = [(4242, "./faketools/effwatch.sh", os.path.join(self.root, "elsewhere"))]
        res = self.check()
        w = res["watchers"][0]
        self.assertFalse(w["exists"])
        self.assertTrue(self.levels(res, "FAIL"))
        self.assertIn("DOES NOT EXIST", self.text(res))
        self.assertFalse(res["ok"])

    def test_nonexistent_queue_is_not_advertised_as_somewhere_to_queue_into(self):
        self.watchers = [(4242, "./faketools/effwatch.sh", os.path.join(self.root, "elsewhere"))]
        text = self.text(self.check())
        self.assertNotIn("Queue requests into the WATCHED path", text)

    def test_unreadable_cwd_reports_undetermined_rather_than_guessing(self):
        self.watchers = [(4242, "./tae-conversion/tools/effwatch.sh", None)]
        res = self.check()
        w = res["watchers"][0]
        self.assertIsNone(w["watching_queue"])
        self.assertIn("cannot be determined", self.text(res))
        self.assertIn("lsof", self.text(res))
        self.assertFalse(res["ok"])

    def test_unreadable_cwd_does_not_invent_a_canonical_answer(self):
        self.watchers = [(4242, "./tae-conversion/tools/effwatch.sh", None)]
        self.assertFalse(self.check()["watchers"][0]["canonical"])


class WatcherCountTests(DoctorCase):
    def test_no_watcher_is_reported(self):
        self.watchers = []
        res = self.check()
        self.assertEqual(res["watchers"], [])
        self.assertIn("no effwatch running", self.text(res))

    def test_two_watchers_warn_about_concurrent_gradle_builds(self):
        # Two builds against one device read as test flakiness (MTE-5768).
        cwd = os.path.join(self.root, "testops-tools")
        self.watchers = [(1, "./tae-conversion/tools/effwatch.sh", cwd),
                         (2, "./tae-conversion/tools/effwatch.sh", cwd)]
        res = self.check()
        self.assertEqual(len(res["watchers"]), 2)
        self.assertIn("2 effwatch processes", self.text(res))
        self.assertFalse(res["ok"])

    def test_effdoctor_does_not_count_itself_as_a_watcher(self):
        self.watchers = [(4242, "./tae-conversion/tools/effwatch.sh",
                          os.path.join(self.root, "testops-tools"))]
        real_sh = self.fake_sh

        def sh_with_self(cmd):
            if cmd.startswith("ps "):
                return real_sh(cmd) + "\n  9999 python3 effdoctor.py --json effwatch.sh"
            return real_sh(cmd)

        self.patch(effdoctor, "sh", sh_with_self)
        self.assertEqual(len(effdoctor.check()["watchers"]), 1)


class EnvironmentCheckTests(DoctorCase):
    def test_missing_effpretty_is_a_failure(self):
        os.remove(os.path.join(self.repo, EFFPRETTY_REL))
        res = self.check()
        self.assertFalse(res["effpretty"]["found"])
        self.assertTrue(self.levels(res, "FAIL"))
        self.assertIn("A24", self.text(res))

    def test_no_adb_device_is_a_failure(self):
        self.devices = []
        res = self.check()
        self.assertTrue(self.levels(res, "FAIL"))
        self.assertIn("no adb device", self.text(res))

    def test_stale_gradle_lock_with_no_holder_warns(self):
        lock = os.path.join(self.repo, "objdir-frontend/gradle/mach_android.lockfile")
        os.makedirs(os.path.dirname(lock))
        open(lock, "w").close()
        res = self.check()
        self.assertTrue(res["gradle_lock"]["present"])
        self.assertFalse(res["gradle_lock"]["held"])
        self.assertIn("A38", self.text(res))

    def test_alt_checkout_holding_a_real_copy_is_flagged_as_divergent(self):
        # A separate copy drifts silently; a symlink cannot.
        alt = os.path.join(self.root, "alt-tools")
        os.makedirs(alt)
        open(os.path.join(self.canon_tools, "effloop.sh"), "w").close()
        open(os.path.join(alt, "effloop.sh"), "w").close()
        self.patch(effdoctor, "ALT_TOOLS", alt)
        res = self.check()
        self.assertTrue(res["alt_tools"]["divergent"])
        self.assertIn("SEPARATE copy", self.text(res))

    def test_alt_checkout_of_symlinks_is_not_divergent(self):
        alt = os.path.join(self.root, "alt-tools")
        os.makedirs(alt)
        real = os.path.join(self.canon_tools, "effloop.sh")
        open(real, "w").close()
        os.symlink(real, os.path.join(alt, "effloop.sh"))
        self.patch(effdoctor, "ALT_TOOLS", alt)
        self.assertEqual(self.check()["alt_tools"]["divergent"], [])


class OkFlagTests(DoctorCase):
    def test_clean_world_exits_ok(self):
        self.watchers = [(4242, os.path.join(self.canon_tools, "effwatch.sh"), self.root)]
        res = self.check()
        self.assertTrue(res["ok"], self.text(res))

    def test_info_only_findings_do_not_flip_ok(self):
        # "no watcher running" is INFO: it is worth saying, but it is not a fault in
        # the toolchain, and it must not make a healthy checkout look broken.
        self.watchers = []
        res = self.check()
        self.assertEqual(self.levels(res, "INFO"), res["findings"])
        self.assertTrue(res["ok"])


def _can_read_proc_cwd():
    """Whether this machine can read another process's cwd at all (/proc or lsof).
    Skipping beats failing: a red CI job for a missing utility teaches people to
    ignore the suite, which is the habit these tests exist to prevent."""
    if os.path.isdir("/proc/self"):
        return True
    return bool(shutil.which("lsof"))


class ProcCwdTests(unittest.TestCase):
    """proc_cwd reads another process's cwd for real, so it has to work against
    the actual OS, not a stub."""

    @unittest.skipUnless(_can_read_proc_cwd(), "neither /proc nor lsof available")
    def test_reads_the_cwd_of_a_live_process(self):
        d = tempfile.TemporaryDirectory(prefix="effdoctor-cwd-")
        self.addCleanup(d.cleanup)
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=d.name)
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        got = effdoctor.proc_cwd(p.pid)
        self.assertIsNotNone(got, "cwd could not be read")
        self.assertEqual(os.path.realpath(got), os.path.realpath(d.name))

    def test_returns_none_for_a_pid_that_is_not_running(self):
        self.assertIsNone(effdoctor.proc_cwd(999999))


class CliTests(unittest.TestCase):
    """Measured on the process. Piping through `head` reports the pager's exit
    status, not the tool's."""

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(TOOLS, "effdoctor.py"), *args],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "REPO": tempfile.gettempdir()},
        )

    def test_version_resolves_and_exits_zero(self):
        p = self.run_cli("--version")
        self.assertEqual(p.returncode, 0)
        self.assertIn("effdoctor.py", p.stdout)
        self.assertNotIn("unknown", p.stdout)

    def test_json_is_valid_and_carries_the_watcher_fields(self):
        p = self.run_cli("--json")
        parsed = json.loads(p.stdout)
        self.assertEqual(parsed["tool"], "effdoctor")
        for w in parsed["watchers"]:
            for key in ("pid", "launched_from", "proc_cwd", "watching_queue", "exists", "canonical"):
                self.assertIn(key, w)

    def test_exit_code_tracks_the_ok_flag(self):
        p = self.run_cli("--json")
        self.assertEqual(p.returncode, 0 if json.loads(p.stdout)["ok"] else 1)

    def test_human_output_does_not_traceback(self):
        p = self.run_cli()
        self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main()
