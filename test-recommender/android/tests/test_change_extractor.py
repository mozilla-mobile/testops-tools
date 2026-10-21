"""Tests for android/change_extractor.py — the deterministic layer.

Covered: tag parsing and resolution (including the respin and b10-vs-b9
ordering traps), path classification, commit trailer parsing, and the
diff/log reconciliation that drops promotion-merge phantoms.

Not covered: the real `git` and Bugzilla calls. `extract_range()` is exercised
through a fake git runner so the suite needs no checkout and no network.
"""

from __future__ import annotations

import unittest

from android import change_extractor as ce


# =============================================================================
# Tag parsing
# =============================================================================


class TestParseTag(unittest.TestCase):
    def test_beta_release(self):
        t = ce.parse_tag("FIREFOX-ANDROID_154_0b10_RELEASE")
        self.assertEqual((t.major, t.kind, t.beta), (154, "beta", 10))
        self.assertTrue(t.shipped)
        self.assertIsNone(t.build)

    def test_beta_build(self):
        t = ce.parse_tag("FIREFOX-ANDROID_154_0b1_BUILD2")
        self.assertEqual((t.major, t.kind, t.beta, t.build), (154, "beta", 1, 2))
        self.assertFalse(t.shipped)

    def test_release_candidate(self):
        t = ce.parse_tag("FIREFOX-ANDROID_154_0_BUILD1")
        self.assertEqual((t.major, t.kind, t.build), (154, "rc", 1))
        self.assertIsNone(t.beta)

    def test_shipped_release(self):
        t = ce.parse_tag("FIREFOX-ANDROID_154_0_RELEASE")
        self.assertEqual(t.kind, "rc")
        self.assertTrue(t.shipped)

    def test_dot_release(self):
        t = ce.parse_tag("FIREFOX-ANDROID_153_0_2_RELEASE")
        self.assertEqual((t.major, t.kind, t.patch), (153, "dot", 2))

    def test_rejects_desktop_and_thunderbird_tags(self):
        for raw in ("FIREFOX_99_0_RELEASE", "THUNDERBIRD_45_0b1_RELEASE",
                    "UPDATE_PACKAGING_R10", "last-mozilla-central"):
            self.assertIsNone(ce.parse_tag(raw), raw)

    def test_beta_ordering_is_numeric_not_lexical(self):
        """b10 must outrank b9 — the trap that lexical sorting falls into."""
        b9 = ce.parse_tag("FIREFOX-ANDROID_154_0b9_RELEASE")
        b10 = ce.parse_tag("FIREFOX-ANDROID_154_0b10_RELEASE")
        self.assertLess(b9.sort_key, b10.sort_key)


class TestPreferred(unittest.TestCase):
    def test_shipped_wins_over_any_build(self):
        tags = [
            ce.parse_tag("FIREFOX-ANDROID_154_0_BUILD1"),
            ce.parse_tag("FIREFOX-ANDROID_154_0_BUILD2"),
            ce.parse_tag("FIREFOX-ANDROID_154_0_RELEASE"),
        ]
        self.assertTrue(ce._preferred(tags).shipped)

    def test_respin_picks_highest_build_when_nothing_shipped(self):
        """Mid-validation RC: BUILD2 supersedes BUILD1."""
        tags = [
            ce.parse_tag("FIREFOX-ANDROID_155_0_BUILD1"),
            ce.parse_tag("FIREFOX-ANDROID_155_0_BUILD2"),
        ]
        self.assertEqual(ce._preferred(tags).build, 2)

    def test_empty(self):
        self.assertIsNone(ce._preferred([]))


class TestTagResolution(unittest.TestCase):
    """Resolution helpers against a stubbed tag list."""

    TAGS = "\n".join([
        "FIREFOX-ANDROID_154_0b1_BUILD1",
        "FIREFOX-ANDROID_154_0b1_RELEASE",
        "FIREFOX-ANDROID_154_0b9_RELEASE",
        "FIREFOX-ANDROID_154_0b10_RELEASE",
        "FIREFOX-ANDROID_154_0_BUILD1",
        "FIREFOX-ANDROID_154_0_BUILD2",
        "FIREFOX_99_0_RELEASE",
    ])

    def setUp(self):
        self._real_git = ce._git
        ce._git = lambda repo, args: self.TAGS

    def tearDown(self):
        ce._git = self._real_git

    def test_latest_beta(self):
        self.assertEqual(ce.latest_beta("r", 154).beta, 10)

    def test_resolve_beta_prefers_shipped_build(self):
        t = ce.resolve_beta("r", 154, 1)
        self.assertTrue(t.shipped)

    def test_resolve_rc_picks_highest_build(self):
        self.assertEqual(ce.resolve_rc("r", 154).build, 2)

    def test_beta_pairs_are_consecutive(self):
        pairs = ce.beta_pairs("r", 154)
        self.assertEqual(
            [(a.beta, b.beta) for a, b in pairs], [(1, 9), (9, 10)]
        )

    def test_unknown_cycle_resolves_to_none(self):
        self.assertIsNone(ce.latest_beta("r", 999))
        self.assertIsNone(ce.resolve_rc("r", 999))


# =============================================================================
# Path classification
# =============================================================================


class TestClassifyPath(unittest.TestCase):
    FENIX = "mobile/android/fenix/app/src"

    def test_locale_strings_are_translation_noise(self):
        p = f"{self.FENIX}/main/res/values-es-rES/strings.xml"
        self.assertEqual(ce.classify_path(p), "translation")
        self.assertTrue(ce.ChangedFile(p, 1, 1, "translation").is_noise)

    def test_bcp47_locale_qualifier(self):
        p = f"{self.FENIX}/main/res/values-b+sr+Latn/strings.xml"
        self.assertEqual(ce.classify_path(p), "translation")

    def test_unqualified_strings_are_source_not_noise(self):
        """`res/values/strings.xml` is the en-US source: new UI copy, a real
        signal. Only locale-qualified variants are translation imports."""
        p = f"{self.FENIX}/main/res/values/strings.xml"
        self.assertEqual(ce.classify_path(p), "source_strings")
        self.assertFalse(ce.ChangedFile(p, 1, 1, "source_strings").is_noise)

    def test_ui_and_unit_tests_are_distinguished(self):
        """Only `androidTest/` carries `// TestRail link:` comments, so only it
        can yield an exact match. On the beta branch nearly every test change
        is a unit test, which would otherwise read as a TestRail signal."""
        self.assertEqual(
            ce.classify_path(f"{self.FENIX}/androidTest/java/org/x/FooTest.kt"),
            "test_ui")
        self.assertEqual(
            ce.classify_path(f"{self.FENIX}/test/java/org/x/BarTest.kt"),
            "test_unit")

    def test_neither_test_kind_is_product_code(self):
        for cat in ("test_ui", "test_unit"):
            self.assertIn(cat, ce.TEST_CATEGORIES)

    def test_product_code(self):
        self.assertEqual(
            ce.classify_path(f"{self.FENIX}/main/java/org/mozilla/fenix/A.kt"), "code")

    def test_nimbus_and_telemetry(self):
        self.assertEqual(
            ce.classify_path("mobile/android/fenix/app/nimbus.fml.yaml"), "nimbus")
        self.assertEqual(
            ce.classify_path("mobile/android/fenix/app/metrics.yaml"), "telemetry")

    def test_dependency_pin(self):
        p = ("mobile/android/android-components/plugins/dependencies/src/main/"
             "java/ApplicationServices.kt")
        self.assertEqual(ce.classify_path(p), "dependency")

    def test_docs_and_assets_are_noise(self):
        self.assertTrue(ce.ChangedFile("a/docs/x.md", 1, 0, ce.classify_path("a/docs/x.md")).is_noise)
        self.assertTrue(ce.ChangedFile("a/ic.webp", 1, 0, ce.classify_path("a/ic.webp")).is_noise)


# =============================================================================
# Commit parsing
# =============================================================================


def commit(subject="", body="", sha="a" * 40, stats=None):
    return ce.MozCommit(
        sha=sha, subject=subject, body=body, author="dev",
        date="2026-08-01T00:00:00Z", stats=stats or {},
    )


class TestMozCommit(unittest.TestCase):
    def test_bug_id_from_subject(self):
        c = commit("Bug 2062457 - Refactor Recommended location r=android-reviewers")
        self.assertEqual(c.bug_id, 2062457)

    def test_bug_id_falls_back_to_body(self):
        c = commit("Follow-up fix", body="Part of Bug 2043198 work.")
        self.assertEqual(c.bug_id, 2043198)

    def test_no_bug(self):
        self.assertIsNone(commit("No Bug - Import translations").bug_id)

    def test_phabricator_revision(self):
        c = commit(body="Differential Revision: "
                        "https://phabricator.services.mozilla.com/D316959")
        self.assertEqual(c.phab_revision, "D316959")

    def test_reviewers(self):
        c = commit("Bug 1 - x r=android-reviewers,jonalmeida,Roger")
        self.assertEqual(c.reviewers, ["android-reviewers", "jonalmeida", "Roger"])

    def test_approver_marks_uplift(self):
        c = commit("Bug 2056198 - Fix Sports Widget r=skhan a=dsmith")
        self.assertEqual(c.approver, "dsmith")

    def test_no_approver_on_normal_landing(self):
        self.assertIsNone(commit("Bug 1 - x r=someone").approver)

    def test_backout_detection(self):
        self.assertTrue(commit("Backed out changeset abc for failures").is_backout)
        self.assertTrue(commit('Revert "Bug 1 - x"').is_backout)
        self.assertFalse(commit("Bug 1 - x").is_backout)

    def test_plumbing_detection(self):
        for s in ("No Bug - Import translations from beta",
                  "Automatic version bump NO BUG a=release",
                  "Promote beta to release",
                  "Merge firefox-autoland to firefox-main"):
            self.assertTrue(commit(s).is_plumbing, s)
        self.assertFalse(commit("Bug 1 - real change").is_plumbing)

    def test_line_counts_come_from_per_commit_stats(self):
        c = commit(stats={"a.kt": (10, 3), "b.kt": (1, 1)})
        self.assertEqual((c.additions, c.deletions), (11, 4))
        self.assertEqual(c.files, ["a.kt", "b.kt"])


class TestCleanSubject(unittest.TestCase):
    def test_strips_bug_prefix_and_trailers(self):
        self.assertEqual(
            ce._clean_subject("Bug 2056198 - Fix Sports Widget r=skhan a=dsmith"),
            "Fix Sports Widget",
        )

    def test_handles_colon_separator(self):
        self.assertEqual(
            ce._clean_subject("Bug 2056728:  Replace placeholder strings"),
            "Replace placeholder strings",
        )


# =============================================================================
# Reconciliation
# =============================================================================


class FakeGit:
    """Replays canned `git diff`/`git log` output for extract_range()."""

    def __init__(self, numstat: str, log: str):
        self.numstat = numstat
        self.log = log

    def __call__(self, repo, args):
        if args[0] == "diff":
            return self.numstat
        if args[0] == "log":
            return self.log
        raise AssertionError(f"unexpected git call: {args}")


def log_record(sha, subject, body, stats):
    """Build one record in the format log_commits() parses."""
    rows = "\n".join(f"{a}\t{d}\t{p}" for p, (a, d) in stats.items())
    fields = ce._FIELD_SEP.join(
        [sha, subject, body, "dev", "2026-08-01T00:00:00Z\n" + rows]
    )
    return ce._REC_SEP + fields


class TestExtractRange(unittest.TestCase):
    FENIX = "mobile/android/fenix/app/src/main/java/org/mozilla/fenix"

    def setUp(self):
        self._real_git = ce._git

    def tearDown(self):
        ce._git = self._real_git

    def test_groups_commits_by_bug(self):
        a = f"{self.FENIX}/settings/A.kt"
        b = f"{self.FENIX}/home/B.kt"
        ce._git = FakeGit(
            numstat=f"10\t2\t{a}\n5\t1\t{b}\n",
            log=(
                log_record("s1", "Bug 111111 - first r=x", "", {a: (6, 1)})
                + log_record("s2", "Bug 111111 - second r=x", "", {a: (4, 1)})
                + log_record("s3", "Bug 222222 - other r=x", "", {b: (5, 1)})
            ),
        )
        r = ce.extract_range("repo", "base", "head")
        self.assertEqual([bug.bug_id for bug in r.bugs], [111111, 222222])
        first = r.bugs[0]
        self.assertEqual(len(first.commits), 2)
        # Per-commit sums, not the file's net diff counted twice.
        self.assertEqual((first.additions, first.deletions), (10, 2))

    def test_two_bugs_touching_one_file_do_not_double_count(self):
        """The cycle-151 case: both Adjust bugs touched the same files. Each
        bug must report only its own commit's churn."""
        f = f"{self.FENIX}/components/metrics/AdjustMetricsService.kt"
        ce._git = FakeGit(
            numstat=f"206\t0\t{f}\n",
            log=(
                log_record("s1", "Bug 2038776 - add glean events a=x", "", {f: (230, 0)})
                + log_record("s2", "Bug 2039032 - don't trigger ping a=x", "", {f: (0, 24)})
            ),
        )
        r = ce.extract_range("repo", "base", "head")
        sizes = {b.bug_id: (b.additions, b.deletions) for b in r.bugs}
        self.assertEqual(sizes[2038776], (230, 0))
        self.assertEqual(sizes[2039032], (0, 24))
        # And the per-bug figures reconcile with the net diff.
        net = sum(x.additions - x.deletions for x in r.files)
        self.assertEqual(sum(a - d for a, d in sizes.values()), net)

    def test_phantom_commit_is_excluded_and_reported(self):
        """A promotion-merge artifact touches a file absent from the net diff."""
        real = f"{self.FENIX}/settings/A.kt"
        ghost = f"{self.FENIX}/home/Ghost.kt"
        ce._git = FakeGit(
            numstat=f"1\t1\t{real}\n",
            log=(
                log_record("s1", "Bug 111111 - real r=x", "", {real: (1, 1)})
                + log_record("s2", "Bug 999999 - already in base r=x", "", {ghost: (50, 50)})
            ),
        )
        r = ce.extract_range("repo", "base", "head")
        self.assertEqual([b.bug_id for b in r.bugs], [111111])
        self.assertEqual([c.bug_id for c in r.phantom_commits], [999999])
        self.assertTrue(any("phantom" in w or "net" in w for w in r.warnings))

    def test_noise_only_commit_is_not_a_phantom(self):
        """An l10n import touches files that *are* in the diff but filtered
        out as noise. It must not be misreported as a phantom."""
        tr = "mobile/android/fenix/app/src/main/res/values-es/strings.xml"
        ce._git = FakeGit(
            numstat=f"3\t3\t{tr}\n",
            log=log_record("s1", "No Bug - Import translations from beta", "", {tr: (3, 3)}),
        )
        r = ce.extract_range("repo", "base", "head")
        self.assertEqual(r.bugs, [])
        self.assertEqual(r.phantom_commits, [])
        self.assertEqual(len(r.files), 1)
        self.assertEqual(r.signal_files, [])

    def test_dependency_bump_lands_in_the_no_bug_bucket(self):
        """"No Bug - Bump Application Services" is plumbing by subject but a
        real risk signal, so it must be kept, not dropped as unattributed."""
        dep = ("mobile/android/android-components/plugins/dependencies/src/main/"
               "java/ApplicationServices.kt")
        ce._git = FakeGit(
            numstat=f"1\t1\t{dep}\n",
            log=log_record("s1", "No bug - Bump Application Services to 154.0.1.", "", {dep: (1, 1)}),
        )
        r = ce.extract_range("repo", "base", "head")
        self.assertEqual([b.bug_id for b in r.bugs], [None])
        self.assertEqual(r.unattributed, [])
        self.assertEqual(r.files[0].category, "dependency")

    def test_empty_range(self):
        ce._git = FakeGit(numstat="", log="")
        r = ce.extract_range("repo", "base", "head")
        self.assertEqual((r.files, r.bugs, r.warnings), ([], [], []))

    def test_binary_file_counts_are_zeroed(self):
        ce._git = FakeGit(numstat="-\t-\tmobile/android/fenix/app/src/main/res/ic.webp\n", log="")
        r = ce.extract_range("repo", "base", "head")
        self.assertEqual((r.files[0].additions, r.files[0].deletions), (0, 0))

    def test_include_noise_widens_the_considered_set(self):
        tr = "mobile/android/fenix/app/src/main/res/values-fr/strings.xml"
        ce._git = FakeGit(
            numstat=f"2\t2\t{tr}\n",
            log=log_record("s1", "Bug 333333 - tweak fr copy r=x", "", {tr: (2, 2)}),
        )
        self.assertEqual(ce.extract_range("repo", "b", "h").bugs, [])
        widened = ce.extract_range("repo", "b", "h", include_noise=True)
        self.assertEqual([b.bug_id for b in widened.bugs], [333333])


class TestBugChange(unittest.TestCase):
    def test_uplift_and_test_flags(self):
        code = ce.ChangedFile("a/main/A.kt", 5, 0, "code")
        test = ce.ChangedFile("a/androidTest/ATest.kt", 3, 0, "test_ui")
        bug = ce.BugChange(
            bug_id=1, title="x",
            commits=[commit("Bug 1 - x r=y a=release")],
            files=[code, test],
        )
        self.assertTrue(bug.is_uplift)
        self.assertTrue(bug.touches_tests)
        self.assertTrue(bug.touches_ui_tests)
        self.assertEqual(bug.product_files, [code])


# =============================================================================
# Bugzilla enrichment
# =============================================================================


class TestEnrichWithBugzilla(unittest.TestCase):
    def _result(self, *bug_ids):
        return ce.ExtractionResult(
            base="b", head="h", files=[],
            bugs=[ce.BugChange(bug_id=i, title=f"local {i}") for i in bug_ids],
        )

    def test_attaches_component_and_overrides_title(self):
        r = self._result(111111)
        ce.enrich_with_bugzilla(r, fetcher=lambda ids: {
            111111: {"id": 111111, "product": "Fenix", "component": "Settings",
                     "severity": "S2", "keywords": ["regression"],
                     "summary": "canonical summary"},
        })
        bug = r.bugs[0]
        self.assertEqual(bug.component, "Fenix::Settings")
        self.assertEqual(bug.severity, "S2")
        self.assertEqual(bug.keywords, ["regression"])
        self.assertEqual(bug.title, "canonical summary")

    def test_missing_bugs_are_warned_not_fatal(self):
        """Security-restricted bugs return nothing; the pipeline must continue."""
        r = self._result(111111, 222222)
        ce.enrich_with_bugzilla(r, fetcher=lambda ids: {
            111111: {"id": 111111, "product": "Fenix", "component": "Settings"},
        })
        self.assertEqual(r.bugs[0].component, "Fenix::Settings")
        self.assertIsNone(r.bugs[1].component)
        self.assertTrue(any("unavailable for 1" in w for w in r.warnings))

    def test_api_failure_degrades_gracefully(self):
        r = self._result(111111)
        ce.enrich_with_bugzilla(r, fetcher=lambda ids: {})
        self.assertEqual(r.bugs[0].title, "local 111111")
        self.assertTrue(r.warnings)

    def test_batches_large_bug_lists(self):
        seen: list[int] = []

        def fetcher(ids):
            seen.append(len(ids))
            return {}

        r = self._result(*range(100000, 100250))
        ce.enrich_with_bugzilla(r, fetcher=fetcher, batch_size=100)
        self.assertEqual(seen, [100, 100, 50])

    def test_no_bug_bucket_is_skipped(self):
        r = ce.ExtractionResult(
            base="b", head="h", files=[],
            bugs=[ce.BugChange(bug_id=None, title="No bug - bump")],
        )
        ce.enrich_with_bugzilla(r, fetcher=lambda ids: {1: {}})
        self.assertEqual(r.warnings, [])


if __name__ == "__main__":
    unittest.main()


class TestNimbusExtraction(unittest.TestCase):
    """The manifest is parsed as JSON, not grepped: `slug` appears at three
    nesting levels (experiment, branch, per-branch feature) and a line scan
    reported `control`, `awesomebar` and `pocket` as experiments."""

    MANIFEST = """{"data": [
      {"slug": "exp-one", "featureIds": ["homescreen"],
       "branches": [{"slug": "control", "features": [{"featureId": "awesomebar"}]},
                    {"slug": "treatment-a", "features": [{"featureId": "pocket"}]}]},
      {"slug": "exp-unchanged", "featureIds": ["search"], "branches": []}
    ]}"""

    BASE = """{"data": [
      {"slug": "exp-unchanged", "featureIds": ["search"], "branches": []}
    ]}"""

    def setUp(self):
        self._real_git = ce._git

    def tearDown(self):
        ce._git = self._real_git

    def _git_for(self, base_body, head_body):
        def fake(repo, args):
            if args[0] != "show":
                return ""
            return base_body if args[1].startswith("BASE") else head_body
        return fake

    def test_only_changed_experiments_are_reported(self):
        ce._git = self._git_for(self.BASE, self.MANIFEST)
        features, slugs = ce.nimbus_features_changed("r", "BASE", "HEAD")
        self.assertEqual(slugs, ["exp-one"])
        self.assertEqual(features, ["homescreen"])

    def test_branch_and_feature_slugs_are_not_experiments(self):
        ce._git = self._git_for(self.BASE, self.MANIFEST)
        _, slugs = ce.nimbus_features_changed("r", "BASE", "HEAD")
        for noise in ("control", "treatment-a", "awesomebar", "pocket"):
            self.assertNotIn(noise, slugs)

    def test_placeholder_features_are_ignored(self):
        head = """{"data": [{"slug": "e", "featureIds":
          ["this-is-included-for-mobile-pre-96-support", "homescreen"]}]}"""
        ce._git = self._git_for('{"data": []}', head)
        features, _ = ce.nimbus_features_changed("r", "BASE", "HEAD")
        self.assertEqual(features, ["homescreen"])

    def test_unchanged_manifest_yields_nothing(self):
        ce._git = self._git_for(self.MANIFEST, self.MANIFEST)
        self.assertEqual(ce.nimbus_features_changed("r", "BASE", "HEAD"), ([], []))

    def test_missing_manifest_degrades_to_a_line_scan(self):
        def fake(repo, args):
            if args[0] == "show":
                raise RuntimeError("no such path")
            return '+  "featureId": "translations"\n'
        ce._git = fake
        features, slugs = ce.nimbus_features_changed("r", "BASE", "HEAD")
        self.assertEqual((features, slugs), (["translations"], []))
