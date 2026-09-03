"""
agent/knowledge.py

Loads relevant business rules from the knowledge base based on the current screen.
Zero API cost — pure file reads injected into the prompt.

Knowledge base structure:
    knowledge_base/
    ├── ios_firefox/
    │   └── fennec.md
    ├── android_firefox/
    │   └── firefox_android.md
    └── android_car/
        └── firefox_car.md

Resolution order for knowledge dir:
    --knowledge CLI arg  →  platform default (ios→ios_firefox, android→android_firefox)
    android_car is ALWAYS explicit — never selected by default.
"""

import os
import re

KNOWLEDGE_DIR = "knowledge_base"

# ── Default knowledge dir per platform ────────────────────────────────────────

_PLATFORM_DEFAULTS = {
    "ios":     "ios_firefox",
    "android": "android_firefox",
}

# ── Main knowledge file per app dir ───────────────────────────────────────────

_APP_FILES = {
    "ios_firefox":     "fennec.md",
    "android_firefox": "firefox_android.md",
    "android_car":     "firefox_car.md",
}

# ── Section maps per app dir ───────────────────────────────────────────────────
# Maps screen/objective keywords → list of markdown section headers to inject.

_SECTION_MAPS: dict[str, dict[str, list[str]]] = {

    "ios_firefox": {
        "private":   [
            "Private browsing",
            "CRITICAL: How to enter private mode and navigate to a URL",
            "CRITICAL: Main Menu does NOT have \"New Private Tab\"",
            "CRITICAL: How to check history isolation (the actual test)",
            "CRITICAL: Common mistakes that cause infinite loops",
            "Private browsing rules",
        ],
        "tab":       ["Tab management", "Tab management rules"],
        "download":  ["Downloads"],
        "settings":  ["Settings"],
        "search":    ["Search rules", "URL Bar"],
        "pdf":       ["Known fragile areas"],
        "bookmark":  ["Reading list / Bookmarks"],
        "history":   [
            "Private browsing rules",
            "CRITICAL: How to enter private mode and navigate to a URL",
            "CRITICAL: Common mistakes that cause infinite loops",
            "CRITICAL: How to check history isolation (the actual test)",
        ],
        "isolation": [
            "Private browsing rules",
            "CRITICAL: How to enter private mode and navigate to a URL",
            "CRITICAL: Common mistakes that cause infinite loops",
            "CRITICAL: How to check history isolation (the actual test)",
        ],
        "menu":      ["CRITICAL: Main Menu does NOT have \"New Private Tab\""],
    },

    "android_firefox": {
        "private":   ["Private browsing", "Private browsing rules"],
        "tab":       ["Tab management", "Tab management rules"],
        "download":  ["Downloads"],
        "settings":  ["Settings"],
        "search":    ["Search rules", "URL Bar"],
        "history":   ["Private browsing rules"],
        "menu":      ["Menu (three-dot)"],
    },

    "android_car": {
        # Minimal until the knowledge base is populated after initial exploration
        "private":   ["Important differences from Firefox Android"],
        "settings":  ["Known constraints (automotive context)"],
        "listening": ["Important differences from Firefox Android"],
        "voice":     ["Important differences from Firefox Android"],
        "dialog":    ["Important differences from Firefox Android"],
        "catch":     ["Important differences from Firefox Android"],  # "Didn't catch that"
    },
}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _load_sections(filepath: str, section_headers: list[str]) -> str:
    """Extract specific sections from a markdown file."""
    if not os.path.exists(filepath):
        return ""
    with open(filepath) as f:
        content = f.read()

    extracted = []
    for header in section_headers:
        # After the escaped header, allow either:
        #   - immediate newline (exact match), OR
        #   - whitespace followed by a non-word char, then rest of line
        #     — accepts annotations like `(HIGH PRIORITY)` or `/ Navigation`
        #     while rejecting word-continuations like `Tab management rules`
        #     when only `Tab management` was requested.
        # See tests/test_knowledge.py for the full matrix.
        pattern = rf"###? {re.escape(header)}(?:[ \t](?!\w)[^\n]*)?\n(.*?)(?=\n###? |\Z)"
        matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
        if matches:
            extracted.append(f"### {header}\n{matches[0].strip()}")

    return "\n\n".join(extracted)


def _resolve_filepath(knowledge_dir: str) -> str:
    """Returns the full path to the knowledge file for the given app dir."""
    filename = _APP_FILES.get(knowledge_dir, "")
    if not filename:
        return ""
    return os.path.join(KNOWLEDGE_DIR, knowledge_dir, filename)


# ── Public API ─────────────────────────────────────────────────────────────────

def resolve_knowledge_dir(platform: str, knowledge_override: str = None) -> str:
    """
    Returns the knowledge dir to use.
    Called once at agent startup to set self._knowledge_dir.

    Resolution order:
        knowledge_override (--knowledge CLI arg)
        → platform default (ios→ios_firefox, android→android_firefox)
        → empty string (no knowledge base available)
    """
    if knowledge_override:
        if knowledge_override not in _APP_FILES:
            print(f"[knowledge] Unknown knowledge dir '{knowledge_override}'. "
                  f"Available: {list(_APP_FILES.keys())}")
            return ""
        return knowledge_override

    return _PLATFORM_DEFAULTS.get((platform or "ios").lower(), "")


def get_rules_for_screen(
    screen_summary: str,
    objective:      str = "",
    knowledge_dir:  str = "ios_firefox",
) -> str:
    """
    Returns relevant business rules for the current screen.
    Injected into the agent prompt — zero API cost.

    Strategy:
    1. Check objective + screen keywords against the app's section map
    2. Load only the matching sections (not the entire file)
    """
    if not knowledge_dir:
        return ""

    section_map = _SECTION_MAPS.get(knowledge_dir, {})
    if not section_map:
        return ""

    combined = (screen_summary + " " + objective).lower()
    sections_to_load = []

    for keyword, sections in section_map.items():
        if keyword in combined:
            sections_to_load.extend(sections)

    if not sections_to_load:
        return ""

    # Deduplicate preserving order
    sections_to_load = list(dict.fromkeys(sections_to_load))

    filepath = _resolve_filepath(knowledge_dir)
    content  = _load_sections(filepath, sections_to_load)

    if not content:
        return ""

    return f"\n--- BUSINESS RULES FOR THIS SCREEN ---\n{content}\n---"
