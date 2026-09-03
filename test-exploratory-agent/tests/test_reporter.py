"""Tests for agent/reporter.py — bug deduplication within a session."""

from agent.reporter import Reporter


def _make_reporter(tmp_path):
    """Reporter needs a writable reports_dir; use pytest's tmp_path fixture."""
    return Reporter(objective="test", reports_dir=str(tmp_path))


def test_exact_match_case_insensitive_is_deduplicated(tmp_path):
    reporter = _make_reporter(tmp_path)
    reporter.report_bug("Tab counter wrong", "High", [], "expected", "actual", "shot.png")
    reporter.report_bug("TAB COUNTER WRONG", "High", [], "expected", "actual", "shot.png")

    assert len(reporter.bugs) == 1


def test_fuzzy_match_above_threshold_is_deduplicated(tmp_path):
    reporter = _make_reporter(tmp_path)
    reporter.report_bug("Tab counter shows incorrect value", "High", [], "e", "a", "s.png")
    # Same bug rephrased — high char overlap, ratio > 0.85
    reporter.report_bug("Tab counter shows an incorrect value", "High", [], "e", "a", "s.png")

    assert len(reporter.bugs) == 1


def test_clearly_different_titles_are_kept_separately(tmp_path):
    reporter = _make_reporter(tmp_path)
    reporter.report_bug("Modal dialog crashes on rotation", "High", [], "e", "a", "s.png")
    reporter.report_bug("Login button is unresponsive", "Medium", [], "e", "a", "s.png")

    assert len(reporter.bugs) == 2


def test_bug_step_index_matches_agentstep_numbering(tmp_path):
    """Regression: BugReport.step_index must align with AgentStep.step.

    In loop.py the flow for step N is:
        report_bug(...)    # bug detected while analyzing the step's screen
        log_step(...)      # appends AgentStep to self.steps
    So when report_bug runs, len(self.steps) is N-1. The +1 in
    reporter.report_bug keeps step_index aligned with the 1-indexed
    AgentStep.step numbering.
    """
    reporter = _make_reporter(tmp_path)
    reporter.report_bug("Anomaly at step 1", "High", [], "e", "a", "s.png")
    reporter.log_step("r", "tap", "btn", "ok", "s.png", "summary")

    assert reporter.bugs[0].step_index == reporter.steps[0].step == 1


def test_session_id_is_unique_across_rapid_reporter_creation(tmp_path):
    """Regression: session_id must include sub-second precision so two runs
    started in the same second (e.g. parallel CI) don't overwrite each other."""
    ids = {Reporter(objective=f"r{i}", reports_dir=str(tmp_path)).session_id
           for i in range(20)}
    assert len(ids) == 20, f"session_id collision: only {len(ids)} unique IDs out of 20"


def test_bugs_md_and_coverage_are_per_session(tmp_path):
    """Regression: bugs_found.md and coverage_map.json used to be shared —
    session B would clobber session A's evidence. They must now be keyed
    on session_id so back-to-back or parallel runs never overwrite."""
    import os

    r1 = _make_reporter(tmp_path)
    r1.report_bug("Bug A", "High", [], "e", "a", "s.png")
    r1.log_step("r", "tap", "btn", "ok", "s.png", "summary")
    r1.save()

    r2 = _make_reporter(tmp_path)
    r2.report_bug("Bug B", "Low", [], "e", "a", "s.png")
    r2.log_step("r", "tap", "btn", "ok", "s.png", "summary")
    r2.save()

    files = set(os.listdir(tmp_path))
    assert f"bugs_{r1.session_id}.md"       in files
    assert f"bugs_{r2.session_id}.md"       in files
    assert f"coverage_{r1.session_id}.json" in files
    assert f"coverage_{r2.session_id}.json" in files
    # Old flat names must not exist — that was the bug.
    assert "bugs_found.md"    not in files
    assert "coverage_map.json" not in files


def test_bugs_md_contains_only_its_own_sessions_bugs(tmp_path):
    """The bugs report for session A must not include bugs from session B."""
    r1 = _make_reporter(tmp_path)
    r1.report_bug("Bug A unique", "High", [], "e", "a", "s.png")
    r1.log_step("r", "tap", "btn", "ok", "s.png", "summary")
    r1.save()

    r2 = _make_reporter(tmp_path)
    r2.report_bug("Bug B unique", "Low", [], "e", "a", "s.png")
    r2.log_step("r", "tap", "btn", "ok", "s.png", "summary")
    r2.save()

    md_r1 = (tmp_path / f"bugs_{r1.session_id}.md").read_text()
    md_r2 = (tmp_path / f"bugs_{r2.session_id}.md").read_text()
    assert "Bug A unique" in md_r1 and "Bug B unique" not in md_r1
    assert "Bug B unique" in md_r2 and "Bug A unique" not in md_r2
