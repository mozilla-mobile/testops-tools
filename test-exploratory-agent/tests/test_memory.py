"""Tests for agent/memory.py — fuzzy dedup + persistence + context building."""

import json

from agent import memory
from agent.memory import _find_similar_bug, _looks_like_tool_error


def test_exact_match_case_insensitive_returns_index():
    existing = [
        {"title": "Tab counter shows wrong value"},
        {"title": "Login button broken"},
    ]
    assert _find_similar_bug("TAB COUNTER SHOWS WRONG VALUE", existing) == 0
    assert _find_similar_bug("login button broken", existing) == 1


def test_fuzzy_match_above_threshold_returns_index():
    """Titles with SequenceMatcher ratio > 0.85 are treated as the same bug."""
    existing = [{"title": "Tab counter shows incorrect value"}]
    # Rephrase — same underlying bug, high char overlap
    assert _find_similar_bug("Tab counter shows an incorrect value", existing) == 0


def test_clearly_different_titles_return_negative_one():
    existing = [{"title": "Modal dialog crashes on rotation"}]
    assert _find_similar_bug("Login button is unresponsive", existing) == -1


def test_empty_existing_list_returns_negative_one():
    assert _find_similar_bug("Anything at all", []) == -1


def test_first_matching_index_is_returned_when_multiple_exist():
    """When multiple existing bugs match, the first index wins."""
    existing = [
        {"title": "Same bug"},
        {"title": "Same bug"},
        {"title": "Different bug entirely"},
    ]
    assert _find_similar_bug("Same bug", existing) == 0


# ── Persistence + context building ─────────────────────────────────────────────
# These tests monkeypatch MEMORY_FILE so they never touch the real
# reports/agent_memory.json used by production sessions.


def test_load_returns_default_schema_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("agent.memory.MEMORY_FILE", str(tmp_path / "does_not_exist.json"))

    result = memory.load()
    assert result["sessions_run"] == 0
    assert result["features_tested"] == []
    assert result["bugs_confirmed"] == []


def test_save_and_load_roundtrip(monkeypatch, tmp_path):
    """Anything written by save() must be readable by load() with a timestamp added."""
    fake_path = str(tmp_path / "agent_memory.json")
    monkeypatch.setattr("agent.memory.MEMORY_FILE", fake_path)

    memory.save({"features_tested": ["url_bar"], "sessions_run": 1, "bugs_confirmed": []})
    reloaded = memory.load()

    assert reloaded["features_tested"] == ["url_bar"]
    assert reloaded["sessions_run"] == 1
    assert "last_updated" in reloaded   # save() stamps this automatically


def test_build_context_returns_no_sessions_message_when_empty(monkeypatch, tmp_path):
    monkeypatch.setattr("agent.memory.MEMORY_FILE", str(tmp_path / "empty.json"))

    summary = memory.build_context_summary()
    assert "No previous sessions" in summary


def test_load_returns_defaults_when_file_is_corrupt(monkeypatch, tmp_path, capsys):
    """Regression: a truncated/corrupt memory file must not crash the agent at startup.
    load() falls back to the default schema and prints a warning."""
    corrupt = tmp_path / "agent_memory.json"
    corrupt.write_text('{"features_tested": ["foo"], "bugs_conf')   # cut off
    monkeypatch.setattr("agent.memory.MEMORY_FILE", str(corrupt))

    result = memory.load()
    assert result["sessions_run"] == 0
    assert result["features_tested"] == []
    assert "corrupt" in capsys.readouterr().out.lower()


def test_save_is_atomic_no_partial_file_on_crash(monkeypatch, tmp_path):
    """Regression: save() must write via a temp file so a mid-write crash
    cannot leave MEMORY_FILE in a truncated state."""
    target = tmp_path / "agent_memory.json"
    monkeypatch.setattr("agent.memory.MEMORY_FILE", str(target))

    # Write a valid memory file first
    memory.save({"features_tested": ["a"], "sessions_run": 1, "bugs_confirmed": []})
    original = target.read_bytes()

    # Force json.dump to crash mid-write
    def crashing_dump(obj, fp, **kwargs):
        fp.write('{"features_tested": ["par')
        raise RuntimeError("simulated crash")
    monkeypatch.setattr("agent.memory.json.dump", crashing_dump)

    try:
        memory.save({"features_tested": ["b"], "sessions_run": 2, "bugs_confirmed": []})
    except RuntimeError:
        pass

    # Target must still be the original — os.replace only runs if json.dump succeeds
    assert target.read_bytes() == original


def test_features_preserve_insertion_order(monkeypatch, tmp_path):
    """Regression: dict.fromkeys preserves insertion order — set() reshuffled it."""
    monkeypatch.setattr("agent.memory.MEMORY_FILE", str(tmp_path / "m.json"))

    memory.save({
        "features_tested":         ["a", "b", "c", "d", "e"],
        "bugs_confirmed":          [],
        "behavioral_patterns":     [],
        "unexplored_areas":        [],
        "recommended_objectives":  [],
        "sessions_run":            0,
    })

    reloaded = memory.load()
    merged = list(dict.fromkeys(reloaded["features_tested"] + ["f"]))
    assert merged == ["a", "b", "c", "d", "e", "f"]


def test_build_context_includes_features_bugs_and_areas(monkeypatch, tmp_path):
    fake_path = str(tmp_path / "agent_memory.json")
    monkeypatch.setattr("agent.memory.MEMORY_FILE", fake_path)

    with open(fake_path, "w") as f:
        json.dump({
            "sessions_run":           3,
            "features_tested":        ["url_bar", "private_mode"],
            "bugs_confirmed":         [{"title": "Tab counter wrong", "severity": "High"}],
            "behavioral_patterns":    ["Slow load on 3G"],
            "unexplored_areas":       ["downloads"],
            "recommended_objectives": [],
            "last_updated":           None,
        }, f)

    summary = memory.build_context_summary()
    assert "url_bar" in summary
    assert "Tab counter wrong" in summary
    assert "downloads" in summary
    assert "3 previous sessions" in summary


def test_build_context_omits_features_that_match_the_objective(monkeypatch, tmp_path):
    """Regression: if the user asks to test X, memory must not say 'X already covered'."""
    fake_path = str(tmp_path / "agent_memory.json")
    monkeypatch.setattr("agent.memory.MEMORY_FILE", fake_path)

    with open(fake_path, "w") as f:
        json.dump({
            "sessions_run":           2,
            "features_tested":        ["private_browsing", "downloads", "url_bar"],
            "bugs_confirmed":         [],
            "behavioral_patterns":    [],
            "unexplored_areas":       [],
            "recommended_objectives": [],
            "last_updated":           None,
        }, f)

    summary = memory.build_context_summary("test private browsing regressions")
    assert "private_browsing" not in summary   # matched the objective — excluded
    assert "downloads" in summary              # unrelated — kept as context
    assert "url_bar" in summary                # unrelated — kept as context


def test_load_backfills_missing_keys_from_default_schema(monkeypatch, tmp_path):
    """Regression: a memory file with only a subset of the current schema's
    keys (e.g. from an older version) used to raise KeyError('features_tested')
    inside build_context_summary. load() now merges with defaults so partial
    files upgrade gracefully."""
    partial = tmp_path / "partial.json"
    partial.write_text('{"sessions_run": 5}')   # only one key, rest missing
    monkeypatch.setattr("agent.memory.MEMORY_FILE", str(partial))

    result = memory.load()
    # Preserved from the file
    assert result["sessions_run"] == 5
    # Backfilled by defaults
    assert result["features_tested"]    == []
    assert result["bugs_confirmed"]     == []
    assert result["behavioral_patterns"] == []
    assert result["unexplored_areas"]   == []
    assert result["recommended_objectives"] == []
    assert result["last_updated"] is None

    # And a partial file must not crash build_context_summary
    summary = memory.build_context_summary()
    assert isinstance(summary, str) and summary   # no crash, some content


def test_concurrent_save_leaves_file_valid_json(monkeypatch, tmp_path):
    """Regression: before this fix, N parallel save() calls all wrote to a
    fixed 'agent_memory.json.tmp' path and raced — the winning replace could
    leave MEMORY_FILE with interleaved bytes and JSONDecodeError on the next
    load. Unique tmp paths (tempfile.mkstemp) fix the on-disk validity."""
    import threading

    mem_path = tmp_path / "agent_memory.json"
    monkeypatch.setattr("agent.memory.MEMORY_FILE", str(mem_path))

    errors = []
    def writer(name):
        try:
            memory.save({
                "features_tested": [f"feat-{name}"],
                "bugs_confirmed":  [],
                "behavioral_patterns":    [],
                "unexplored_areas":       [],
                "recommended_objectives": [],
                "sessions_run":   1,
            })
        except Exception as e:
            errors.append((name, type(e).__name__, str(e)))

    threads = [threading.Thread(target=writer, args=(f"w{i}",)) for i in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()

    # No writer should have failed with FileNotFoundError on the tmp path
    # (which was the pre-fix symptom).
    assert not errors, f"concurrent save() raised: {errors}"

    # The persistent file is intact JSON regardless of which writer won.
    with open(mem_path) as f:
        data = json.load(f)   # must not raise
    assert data["sessions_run"] == 1
    assert data["features_tested"][0].startswith("feat-w")

    # No stray tmp files left behind.
    strays = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert not strays, f"leftover tmp files: {strays}"


# ── Tool-error filter ────────────────────────────────────────────────────────

def test_looks_like_tool_error_catches_known_patterns():
    """Regression: bugs whose text matches Appium/driver failure patterns
    must be flagged, otherwise they'd stay in memory and bias the LLM."""
    cases = [
        {"title": "long_press action returned an Unhandled endpoint error"},
        {"title": "type_url action fails with NoSuchElementError on address bar"},
        {"title": "UnknownCommandError from /session/.../touch/perform"},
        {"title": "Something",
         "description": "Session execution stalled after initial action"},
        {"title": "type_url refused: domain not in --allowed-domains"},
        {"title": "long_press action not supported on iOS XCUITest driver"},
        {"title": "JSON parse error from LLM"},
        {"title": "WebDriverException while trying to tap"},
    ]
    for c in cases:
        assert _looks_like_tool_error(c), (
            f"tool error not detected in: {c!r}"
        )


def test_looks_like_tool_error_leaves_real_bugs_alone():
    """Regression: real Firefox behavior descriptions must NOT be flagged.
    The filter's false-positive rate is what determines whether it's safe to
    apply automatically on load()."""
    real_bugs = [
        {"title": "Tab counter mismatch in Private tabs mode"},
        {"title": "Purple mask icon not visible in private mode"},
        {"title": "Page Zoom dropdown partially collapses or inaccessible"},
        {"title": "Delete history button unresponsive"},
        {"title": "App becomes unresponsive after onboarding Continue tap"},
        {"title": "Network error persists when accessing addons.mozilla.org"},
        {"title": "Menu button unresponsive in Tab Tray normal mode"},
    ]
    for c in real_bugs:
        assert not _looks_like_tool_error(c), (
            f"real bug incorrectly flagged as tool error: {c!r}"
        )


def test_load_auto_heals_tool_error_bugs_from_existing_memory(monkeypatch, tmp_path, capsys):
    """Regression from real session: agent_memory.json accumulated ~10
    tool-error pseudo-bugs (long_press unsupported, type_url NoSuchElement,
    JSON parse errors, etc). load() must strip them on read so future
    sessions don't see them as 'known Firefox bugs'."""
    polluted = tmp_path / "agent_memory.json"
    polluted.write_text(json.dumps({
        "sessions_run": 40,
        "features_tested":       ["url_bar", "private_mode"],
        "bugs_confirmed":        [
            {"title": "Tab counter mismatch in Private tabs mode", "severity": "High"},
            {"title": "long_press action not supported on iOS XCUITest driver", "severity": "Critical"},
            {"title": "type_url action fails with NoSuchElementError on address bar", "severity": "Critical"},
            {"title": "JSON parse errors during wait actions", "severity": "High"},
            {"title": "Purple mask icon not visible in private mode", "severity": "Medium"},
        ],
        "behavioral_patterns":    [],
        "unexplored_areas":       [],
        "recommended_objectives": [],
    }))
    monkeypatch.setattr("agent.memory.MEMORY_FILE", str(polluted))

    loaded = memory.load()
    titles = [b["title"] for b in loaded["bugs_confirmed"]]

    assert "Tab counter mismatch in Private tabs mode" in titles
    assert "Purple mask icon not visible in private mode" in titles
    assert not any("long_press" in t for t in titles)
    assert not any("NoSuchElementError" in t for t in titles)
    assert not any("JSON parse" in t for t in titles)

    # Operator should see the auto-heal message
    assert "Auto-heal" in capsys.readouterr().out


def test_update_from_session_filters_incoming_tool_error_bugs(monkeypatch, tmp_path, capsys):
    """Regression: even if the LLM (during memory extraction) emits a
    tool-error 'bug' in insights.bugs_found, memory must reject it before
    persisting. Belt-and-suspenders — the SYSTEM_PROMPT rule is the first
    line, this filter is the second."""
    mem_path = tmp_path / "agent_memory.json"
    monkeypatch.setattr("agent.memory.MEMORY_FILE", str(mem_path))

    # Stub extract_insights to return one real + one tool-error bug
    def fake_extract(reporter, client):
        return {
            "features_tested":    ["private_mode"],
            "bugs_found":         [
                {"title": "Real Firefox bug: bookmark icon missing",
                 "severity": "High", "description": "The bookmark star does not appear"},
                {"title": "long_press action returned Unhandled endpoint",
                 "severity": "Critical", "description": "Tool failure, not app bug"},
            ],
            "behavioral_patterns":         [],
            "unexplored_areas":            [],
            "recommended_next_objective":  "test bookmarks",
        }
    monkeypatch.setattr("agent.memory.extract_insights", fake_extract)

    class _FakeReporter:
        session_id = "20260806_000000_000000"
        objective  = "test"
        bugs       = []
        steps      = []

    result = memory.update_from_session(_FakeReporter(), client=None)

    # The real bug survived
    titles = [b["title"] for b in result["bugs_confirmed"]]
    assert any("bookmark icon missing" in t for t in titles)
    # The tool-error bug did NOT get persisted
    assert not any("long_press" in t for t in titles)
    assert not any("Unhandled endpoint" in t for t in titles)

    # Operator sees the filter message
    assert "Filtered 1 tool-error" in capsys.readouterr().out


def test_build_context_uses_advisory_language_not_prescriptive(monkeypatch, tmp_path):
    """Regression: the label must not tell the LLM to avoid re-testing."""
    fake_path = str(tmp_path / "agent_memory.json")
    monkeypatch.setattr("agent.memory.MEMORY_FILE", fake_path)

    with open(fake_path, "w") as f:
        json.dump({
            "sessions_run":           1,
            "features_tested":        ["settings"],
            "bugs_confirmed":         [],
            "behavioral_patterns":    [],
            "unexplored_areas":       [],
            "recommended_objectives": [],
            "last_updated":           None,
        }, f)

    summary = memory.build_context_summary()
    assert "avoid repeating" not in summary.lower()
    assert "may have regressed" in summary.lower()
