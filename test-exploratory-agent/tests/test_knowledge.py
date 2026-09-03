"""Tests for agent/knowledge.py — markdown section extraction."""

import os
from pathlib import Path

from agent.knowledge import _load_sections, get_rules_for_screen

_FENNEC_MD = Path(__file__).parent.parent / "knowledge_base" / "ios_firefox" / "fennec.md"


def test_load_sections_does_not_match_header_prefix(tmp_path):
    """Regression: requesting header 'Foo' must not match a header 'Foo bar'.

    The prior regex `## Foo.*?\\n` allowed prefix matches, so asking for
    'Tab management' would (depending on file order) return the content of
    'Tab management rules'. The fix requires only whitespace between the
    header text and the newline.
    """
    md = tmp_path / "sample.md"
    # Order matters — `## Tab management rules` appears FIRST, which is the
    # case that triggered the original bug (re.findall returns matches in
    # file order, and the buggy regex matched both).
    md.write_text(
        "### Tab management rules\n"
        "1. Content A — rules\n"
        "\n"
        "### Tab management\n"
        "- Content B — feature description\n"
    )

    result = _load_sections(str(md), ["Tab management"])
    assert "Content B" in result, "Should return the feature description section"
    assert "Content A" not in result, "Must NOT return the rules section for a 'Tab management' query"


def test_load_sections_returns_empty_when_file_missing(tmp_path):
    """Graceful fallback: a missing knowledge file returns empty string."""
    result = _load_sections(str(tmp_path / "does_not_exist.md"), ["Anything"])
    assert result == ""


def test_load_sections_returns_empty_when_header_not_found(tmp_path):
    """Requesting a header that doesn't exist in the file returns empty."""
    md = tmp_path / "sample.md"
    md.write_text("### Existing header\nContent\n")
    result = _load_sections(str(md), ["Nonexistent header"])
    assert result == ""


def test_load_sections_handles_multiple_headers(tmp_path):
    """Loading multiple headers concatenates their contents."""
    md = tmp_path / "sample.md"
    md.write_text(
        "### Section one\n"
        "First content\n"
        "\n"
        "### Section two\n"
        "Second content\n"
    )
    result = _load_sections(str(md), ["Section one", "Section two"])
    assert "First content" in result
    assert "Second content" in result


# ── Knowledge-base file integrity ────────────────────────────────────────────

def test_fennec_md_does_not_claim_menu_has_new_private_tab():
    """Regression: fennec.md used to contain both:
        - CRITICAL: 'Main Menu does NOT have New Private Tab'
        - a stale bulleted line 'New tab / New private tab' under a generic
          Menu section
    Depending on which section the knowledge selector injected, the LLM would
    get contradictory guidance. The stale generic Menu section was removed;
    this test guards against re-introducing it."""
    content = _FENNEC_MD.read_text()
    assert "New tab / New private tab" not in content, (
        "fennec.md contains the stale 'New tab / New private tab' claim — "
        "the Menu does not have this option; the CRITICAL section is "
        "authoritative"
    )


def test_frontmatter_does_not_leak_into_extracted_rules(tmp_path, monkeypatch):
    """YAML frontmatter at the top of a knowledge file must not appear in
    get_rules_for_screen output. The section extractor keys on ###/## headers
    so frontmatter (delimited by ---) should be invisible — this test
    guards against a regex regression that would start matching it."""
    kb_dir = tmp_path / "knowledge_base" / "ios_firefox"
    kb_dir.mkdir(parents=True)
    (kb_dir / "fennec.md").write_text(
        "---\n"
        "app: Firefox iOS Test\n"
        "bundle_id: com.test.secret_should_not_leak\n"
        "last_verified: 2026-08-05\n"
        "---\n"
        "\n"
        "# Title\n"
        "\n"
        "### Private browsing\n"
        "- Private tabs do not persist\n"
    )
    monkeypatch.chdir(tmp_path)

    rules = get_rules_for_screen(
        screen_summary="private browsing screen",
        objective="test private mode",
        knowledge_dir="ios_firefox",
    )
    assert "Private tabs do not persist" in rules   # sanity
    assert "secret_should_not_leak" not in rules
    assert "last_verified" not in rules
    assert "bundle_id" not in rules


def test_fennec_frontmatter_present_and_current():
    """The frontmatter block must be at the top of fennec.md so operators
    can see when the file was last hand-verified. Missing or misplaced
    frontmatter is a documentation regression."""
    content = _FENNEC_MD.read_text()
    assert content.startswith("---\n"), (
        "fennec.md must open with YAML frontmatter"
    )
    # Must contain the key facts we care about (values may drift over time).
    for key in ("app:", "bundle_id:", "last_verified:"):
        assert key in content.split("---\n", 2)[1], (
            f"frontmatter missing required key {key!r}"
        )
