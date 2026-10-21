"""
Generate `config/section_to_module_mapping.yaml` for Firefox Android.

iOS curated its mapping by hand, section by section. That does not transfer
here: Android has far more sections, and the payoff is lower because the
median beta touches only a handful of Kotlin product files — often none. So
the mapping is *generated* from evidence, and only the largest sections are
worth human review.

Three sources, in descending confidence:

  high    The section's cases already map to test classes (via
          `testrail_index`), and those classes resolve through TEST_CLASS_MODULES.
          This is evidence, not inference: QA linked the case to the test, and
          the test class's area was verified against the repo.

  medium  No mapped cases, but the section name matches a module directory
          name. Pure inference.

  low     Neither. Emitted with an empty module list and surfaced in the
          review report so a human can fill it in.

Re-run whenever the TestRail export or the repo changes; the output carries a
provenance header. Existing `notes:` written by humans are preserved.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from android.testrail_index import TestRailIndex, build_index, split_hierarchy


FENIX_ROOT = "mobile/android/fenix/app/src/main/java/org/mozilla/fenix"
AC_ROOT = "mobile/android/android-components/components"
# The Fenix app also ships a tiny `org/mozilla/gecko` package — currently just
# `search/SearchWidgetProvider.kt`, the home-screen search widget. Scanning
# only `org/mozilla/fenix` made every search-widget change invisible to the
# scorer — a build whose headline changes were search-widget fixes scored
# as if they had not happened.
GECKO_PKG_ROOT = "mobile/android/fenix/app/src/main/java/org/mozilla/gecko"


# =============================================================================
# Curated: test class -> code modules
# =============================================================================


# Only a few dozen test classes carry linked cases — small enough to curate
# exactly, which beats fuzzy name matching. (Most classes in the tree have no
# TestRail link yet.) Token matching was tried first and was wrong in both
# directions: `TabbedBrowsingTest`, `HistoryTest` and `UnifiedTrustPanelTest`
# matched nothing, while `SitePermissionsTest` matched `feature/top-sites` on
# the shared token "site".
#
# `python3 -m android.calibrate` lists any linked class missing from this
# table, which is the signal that it needs an entry.
#
# Paths are relative to FENIX_ROOT unless prefixed with `ac:`, which resolves
# against AC_ROOT. Every entry below was checked against the tree — several are
# not where the name suggests: the trust panel lives under `settings/`, history
# and recently-closed under `library/`, top sites under `home/`.
TEST_CLASS_MODULES: dict[str, tuple[str, ...]] = {
    # --- menus & toolbar ---
    "MainMenuTest": ("components/menu", "ac:browser/menu2", "ac:concept/menu",
                     "ac:compose/menu"),
    "NavigationToolbarTest": ("components/toolbar", "ac:compose/browser-toolbar"),
    "NavigationToolbarExpandedTest": ("components/toolbar", "ac:compose/browser-toolbar"),
    "UnifiedTrustPanelTest": ("settings/trustpanel", "trackingprotection"),
    # --- search ---
    "SearchTest": ("search", "ac:feature/search", "ac:feature/awesomebar",
                   "gecko:search"),
    "SettingsSearchTest": ("settings", "search", "ac:feature/search"),
    "FirefoxSuggestTest": ("search", "ac:feature/fxsuggest"),
    # --- browsing & tabs ---
    "TabbedBrowsingTest": ("tabstray", "browser", "ac:feature/tabs"),
    "RecentlyClosedTabsTest": ("library/recentlyclosed", "ac:browser/session-storage"),
    "CustomTabsTest": ("customtabs", "ac:feature/customtabs"),
    "TextSelectionTest": ("browser", "ac:feature/contextmenu"),
    "ContextMenusTest": ("browser", "ac:feature/contextmenu"),
    "BrowsingErrorPagesTest": ("browser", "ac:browser/errorpages"),
    "WebControlsTest": ("browser", "ac:feature/prompts"),
    "PromptTest": ("ac:feature/prompts",),
    "FindInPageTest": ("ac:feature/findinpage",),
    "ReaderViewTest": ("ac:feature/readerview",),
    "PDFViewerTest": ("browser",),
    "TextFragmentsTest": ("browser",),
    "AboutURITest": ("browser",),
    "MediaNotificationTest": ("ac:feature/media",),
    "GlobalPrivacyControlTest": ("settings", "trackingprotection"),
    # --- library ---
    "BookmarksTest": ("bookmarks", "library/bookmarks"),
    "HistoryTest": ("library/history", "library/historymetadata"),
    "CollectionTest": ("collections", "ac:feature/tab-collections"),
    "CollectionsTest": ("collections", "ac:feature/tab-collections"),
    "DownloadTest": ("downloads", "ac:feature/downloads"),
    "DownloadFileTypesTest": ("downloads", "ac:feature/downloads"),
    # --- home ---
    "HomeScreenTest": ("home",),
    "HomeTest": ("home",),
    "TopSitesTest": ("home/topsites", "ac:feature/top-sites"),
    "SponsoredShortcutsTest": ("home/topsites", "ac:service/contile"),
    "ShortcutsTest": ("home/topsites", "shortcut"),
    "PocketTest": ("home", "ac:service/pocket"),
    # --- onboarding & first run ---
    "OnboardingTest": ("onboarding",),
    "NoNetworkAccessStartupTests": ("startupCrash", "perf"),
    # --- autofill & credentials ---
    "LoginsTest": ("settings/logins", "ac:feature/logins"),
    "SettingsPasswordsTest": ("settings/logins", "ac:feature/logins"),
    "CreditCardAutofillTest": ("settings/creditcards", "ac:feature/autofill"),
    "AddressAutofillTest": ("autofill/address", "ac:feature/autofill"),
    # --- settings ---
    "SettingsTest": ("settings",),
    "SettingsGeneralTest": ("settings",),
    "SettingsAdvancedTest": ("settings",),
    "SettingsAboutTest": ("settings",),
    "SettingsCustomizeTest": ("settings", "theme", "wallpapers"),
    "SettingsHomepageTest": ("settings", "home"),
    "SettingsPrivacyTest": ("settings", "trackingprotection"),
    "SettingsPrivateBrowsingTest": ("settings", "pbmlock"),
    "SettingsHTTPSOnlyModeTest": ("settings",),
    "SettingsSitePermissionsTest": ("settings/quicksettings", "ac:feature/sitepermissions"),
    "SitePermissionsTest": ("settings/quicksettings", "ac:feature/sitepermissions"),
    "UploadPermissionsTest": ("ac:feature/prompts",),
    "SettingsDeleteBrowsingDataTest": ("settings/deletebrowsingdata",),
    "SettingsDeleteBrowsingDataOnQuitTest": ("settings/deletebrowsingdata",),
    "SettingsOpenLinksInAppsTest": ("settings", "ac:feature/app-links"),
    "SettingsAddonsTest": ("addons", "ac:feature/addons"),
    "SettingsPageSummariesTest": ("summarization", "ac:feature/summarize"),
    "SettingsEnhancedTrackingProtectionTest": ("settings", "trackingprotection"),
    "PrivateBrowsingTest": ("pbmlock", "settings"),
    # --- platform & services ---
    "ReportBrokenSiteTest": ("webcompat", "ac:feature/webcompat-reporter"),
    "GoogleLensSearchTest": ("components", "search"),
    "HomeScreenRedesignedUITest": ("home",),
    "TranslationsTest": ("translations",),
    "SyncIntegrationTest": ("settings", "ac:service/firefox-accounts"),
    "CrashReportingTest": ("crashes", "ac:lib/crash"),
    "PwaTest": ("ac:feature/pwa",),
    "PWATest": ("ac:feature/pwa",),
}


# Sections with no mapped cases that are nonetheless unambiguous. Keeps a
# handful of large, obviously-placed sections out of the manual review queue.
SECTION_HINTS: dict[str, tuple[str, ...]] = {
    "Biometric authentication": ("settings/biometric", "pbmlock"),
    "Shake to summarize": ("summarization", "ac:feature/summarize"),
    "AI controls": ("settings", "summarization"),
    "Dark mode": ("theme",),
    "Crash reporting": ("crashes", "ac:lib/crash"),
    "Splash-screen": ("splashscreen",),
    "PWA": ("ac:feature/pwa",),
    "Picture in picture": ("ac:feature/pwa", "browser"),
    "Homescreen launcher icon": ("iconpicker",),
    "Custom tabs": ("customtabs", "ac:feature/customtabs"),
    "[Android > 14] Native share sheet options": ("components/share", "share"),
    "[Fx 157] Address bar focus mode": ("components/toolbar",),
    "Onboarding": ("onboarding",),
    "Translations": ("translations",),
    "Downloads": ("downloads", "ac:feature/downloads"),
    "Bookmarks": ("bookmarks", "library/bookmarks"),
    "History": ("library/history",),
    "Accounts & Sync": ("settings", "ac:service/firefox-accounts"),
    "Navigation toolbar": ("components/toolbar", "ac:compose/browser-toolbar"),
    "Homescreen": ("home",),
    "Search": ("search", "ac:feature/search"),
    "Browsing": ("browser", "tabstray"),
    "Menus": ("components/menu", "settings"),
}


# Sections that are explicitly not product areas.
OUT_OF_SCOPE = ("Relay - not in scope",)


def resolve_module(ref: str) -> str:
    """Expand a short module reference into a repo-relative path.

    `ac:` resolves against android-components, `gecko:` against the app's
    `org/mozilla/gecko` package, anything else against Fenix.
    """
    if ref.startswith("ac:"):
        return f"{AC_ROOT}/{ref[3:]}"
    if ref.startswith("gecko:"):
        return f"{GECKO_PKG_ROOT}/{ref[6:]}"
    return f"{FENIX_ROOT}/{ref}"


# =============================================================================
# Generation
# =============================================================================


MAX_SECTION_SIZE = 80
"""Descend a hierarchy level whenever a section holds more cases than this.

A fixed depth of 2 puts roughly a quarter of the catalogue into
`Menus > Settings menu`, which then accumulates modules spanning half of Fenix
— a bucket that matches every diff discriminates nothing. Descending
adaptively splits it into `... > General > Customize`,
`... > General > Autofill` and
`... > Privacy and security settings > Site settings`, each mapping to a
specific module.

A section already at MAX_DEPTH cannot be split further and may stay over the
cap; that is expected. `python3 -m android.calibrate` reports the current
section sizes.
"""

MAX_DEPTH = 4
MAX_MODULES = 10
"""Cap on modules per section, applied after sorting by evidence weight."""


class MappedSection:
    def __init__(self, name: str):
        self.name = name
        self.test_count = 0
        self.automated = 0
        self.manual_only = 0
        self.automation_gap = 0
        # (path, confidence, weight) — weight is the number of case links
        # backing the module, so the scorer can tell a section's core module
        # from an incidental one.
        self.modules: list[tuple[str, str, int]] = []
        self.evidence: Counter = Counter()         # test class -> case count
        self.notes: str = ""

    @property
    def confidence(self) -> str:
        if not self.modules:
            return "none"
        return min((c for _, c, _ in self.modules),
                   key=["high", "medium", "low"].index)

    @property
    def needs_review(self) -> bool:
        return not self.modules or self.confidence != "high"


def assign_section_keys(
    cases: list, min_depth: int = 2,
    max_depth: int = MAX_DEPTH, max_size: int = MAX_SECTION_SIZE,
) -> dict[str, str]:
    """Map each case id to its section key, descending where a level is too
    coarse. See MAX_SECTION_SIZE."""
    counts = {
        d: Counter(c.section_at(d) for c in cases)
        for d in range(min_depth, max_depth + 1)
    }
    keys: dict[str, str] = {}
    for case in cases:
        depth = min_depth
        while (depth < max_depth
               and counts[depth][case.section_at(depth)] > max_size
               and len(case.section_parts) > depth):
            depth += 1
        keys[case.case_id] = case.section_at(depth)
    return keys


def build_sections(
    index: TestRailIndex, repo: str, min_depth: int = 2,
    max_size: int = MAX_SECTION_SIZE,
) -> list[MappedSection]:
    """Derive one MappedSection per TestRail section, at adaptive depth."""
    existing_modules = _module_inventory(repo)
    cases = list(index.cases.values())
    keys = assign_section_keys(cases, min_depth=min_depth, max_size=max_size)

    sections: dict[str, MappedSection] = {}
    for case in cases:
        key = keys[case.case_id]
        section = sections.get(key)
        if section is None:
            section = MappedSection(key)
            sections[key] = section
        section.test_count += 1
        section.automated += int(case.is_automated)
        section.manual_only += int(case.is_manual_only)
        section.automation_gap += int(case.is_automation_gap)
        # Sorted because case_to_files holds sets, whose iteration order varies
        # between processes under hash randomisation — otherwise ties below
        # resolve differently on each run and the generated YAML churns.
        for path in sorted(index.case_to_files.get(case.case_id, ())):
            section.evidence[Path(path).stem] += 1

    for section in sections.values():
        if section.name.startswith(OUT_OF_SCOPE):
            section.notes = "Explicitly out of scope per the section name."
            continue
        _assign_modules(section, existing_modules)

    return sorted(sections.values(), key=lambda s: (-s.test_count, s.name))


def _by_weight_then_name(counter: Counter) -> list[tuple[str, int]]:
    """`Counter.most_common()` leaves ties in insertion order; break them on
    the key so regeneration is byte-stable."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))


def _assign_modules(section: MappedSection, existing: set[str]) -> None:
    """Fill `section.modules`, highest-confidence source first."""
    # 1. Evidence: the section's cases are linked to these test classes.
    scored: Counter = Counter()
    for test_class, weight in section.evidence.items():
        for ref in TEST_CLASS_MODULES.get(test_class, ()):
            scored[ref] += weight
    if scored:
        for ref, weight in _by_weight_then_name(scored)[:MAX_MODULES]:
            path = resolve_module(ref)
            if path in existing:
                section.modules.append((path, "high", weight))
        if section.modules:
            unknown = [c for c in section.evidence if c not in TEST_CLASS_MODULES]
            if unknown:
                section.notes = (
                    "Test class(es) not in TEST_CLASS_MODULES: "
                    + ", ".join(sorted(unknown))
                )
            return

    # 2. Explicit hint, trying the most specific prefix first. Sections now sit
    #    at adaptive depth, so `Menus > Settings menu > General > Autofill`
    #    must still be able to fall back to the `Menus` hint.
    parts = split_hierarchy(section.name)
    prefixes = [" > ".join(parts[:i]) for i in range(len(parts), 0, -1)]
    for key in prefixes:
        for ref in SECTION_HINTS.get(key, ()):
            path = resolve_module(ref)
            if path in existing:
                section.modules.append((path, "medium", 0))
        if section.modules:
            section.notes = (
                f"No cases linked to code; mapped from the section name "
                f"'{key}'. Verify."
            )
            return

    # 3. Nothing. Left for a human.
    section.notes = "UNMAPPED — no linked cases and no name match. Needs review."


def _module_inventory(repo: str) -> set[str]:
    """Every candidate module directory that currently exists, so the generator
    can never emit a path that has been renamed away."""
    root = Path(repo)
    found: set[str] = set()

    gecko = root / GECKO_PKG_ROOT
    if gecko.is_dir():
        for d in gecko.rglob("*"):
            if d.is_dir() and any(d.glob("*.kt")):
                found.add(str(d.relative_to(root)))

    fenix = root / FENIX_ROOT
    if fenix.is_dir():
        for d in fenix.rglob("*"):
            if d.is_dir() and any(d.glob("*.kt")):
                found.add(str(d.relative_to(root)))

    ac = root / AC_ROOT
    if ac.is_dir():
        for group in ac.iterdir():
            if not group.is_dir():
                continue
            for d in group.iterdir():
                if d.is_dir() and any(d.rglob("*.kt")):
                    found.add(str(d.relative_to(root)))
    return found


# =============================================================================
# YAML emission
# =============================================================================


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_yaml(sections: list[MappedSection], export: str, repo: str) -> str:
    today = datetime.date.today().isoformat()
    mapped = sum(1 for s in sections if s.modules)
    out: list[str] = [
        "# Mapping: TestRail depth-2 section  ->  Firefox Android code modules",
        "#",
        f"# GENERATED by android/build_mapping.py on {today}. Re-run after a",
        "# TestRail re-export or a repo restructure; hand-written `notes:` are",
        "# preserved, `modules:` are not — curate via TEST_CLASS_MODULES and",
        "# SECTION_HINTS in that script, so the curation survives regeneration.",
        "#",
        f"#   export: {os.path.basename(export)}",
        f"#   repo:   {repo}",
        f"#   {len(sections)} sections, {mapped} mapped, "
        f"{len(sections) - mapped} needing review",
        "#",
        "# confidence:",
        "#   high   = the section's cases are linked to test classes whose area",
        "#            was verified against the tree (evidence, not inference)",
        "#   medium = inferred from the section name only",
        "#",
        "# test_count     cases under this section",
        "# automated      Automation = Completed or Disabled (deprioritize)",
        "# manual_only    Automation = Unsuitable (core manual pool)",
        "# automation_gap Automation = Suitable (candidates to automate)",
        "",
        "sections:",
    ]

    for section in sections:
        out.append("")
        out.append(f"  - name: {_quote(section.name)}")
        out.append(f"    test_count: {section.test_count}")
        out.append(f"    automated: {section.automated}")
        out.append(f"    manual_only: {section.manual_only}")
        out.append(f"    automation_gap: {section.automation_gap}")
        if section.modules:
            out.append("    modules:")
            for path, confidence, weight in section.modules:
                out.append(f"      - {{path: {path}, "
                           f"confidence: {confidence}, weight: {weight}}}")
        else:
            out.append("    modules: []")
        if section.evidence:
            top = ", ".join(
                f"{c}({n})"
                for c, n in _by_weight_then_name(section.evidence)[:4]
            )
            out.append(f"    evidence: {_quote(top)}")
        if section.notes:
            out.append("    notes: |")
            for line in section.notes.splitlines() or [""]:
                out.append(f"      {line}")
    out.append("")
    return "\n".join(out)


def _short_path(path: str) -> str:
    """A readable, unambiguous label for a module path.

    The bare last segment collides across trees — `fenix/search` and
    `android-components/components/feature/search` both render as `search`,
    which reads like a duplicate entry in the review queue.
    """
    if path.startswith(AC_ROOT + "/"):
        return "ac:" + path[len(AC_ROOT) + 1:]
    if path.startswith(GECKO_PKG_ROOT + "/"):
        return "gecko:" + path[len(GECKO_PKG_ROOT) + 1:]
    if path.startswith(FENIX_ROOT + "/"):
        return path[len(FENIX_ROOT) + 1:]
    return path


def render_review(sections: list[MappedSection]) -> str:
    """Human-facing queue: what the generator could not establish."""
    unmapped = [s for s in sections if not s.modules]
    inferred = [s for s in sections if s.modules and s.confidence != "high"]
    unknown_classes: Counter = Counter()
    for s in sections:
        for c, n in s.evidence.items():
            if c not in TEST_CLASS_MODULES:
                unknown_classes[c] += n

    lines = ["# Mapping review queue", ""]
    covered = sum(s.test_count for s in sections if s.modules)
    total = sum(s.test_count for s in sections)
    lines.append(
        f"{len(sections) - len(unmapped)}/{len(sections)} sections mapped, "
        f"covering {covered}/{total} cases ({100 * covered / total:.0f}%)."
    )
    lines.append("")

    if unmapped:
        lines.append(f"## Unmapped sections ({len(unmapped)}) — highest value first")
        lines.append("")
        for s in sorted(unmapped, key=lambda s: -s.test_count):
            lines.append(f"- **{s.name}** — {s.test_count} cases "
                         f"({s.manual_only} manual-only)")
        lines.append("")

    if inferred:
        lines.append(f"## Mapped by name only ({len(inferred)}) — verify")
        lines.append("")
        for s in sorted(inferred, key=lambda s: -s.test_count):
            paths = ", ".join(_short_path(p) for p, _, _ in s.modules)
            lines.append(f"- **{s.name}** — {s.test_count} cases -> {paths}")
        lines.append("")

    if unknown_classes:
        lines.append(f"## Test classes missing from TEST_CLASS_MODULES "
                     f"({len(unknown_classes)})")
        lines.append("")
        for c, n in _by_weight_then_name(unknown_classes):
            lines.append(f"- `{c}` — {n} case link(s)")
        lines.append("")
    return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================


def main(argv: Optional[list[str]] = None) -> int:
    here = Path(__file__).parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True,
                        help="path to a mozilla-firefox/firefox checkout")
    parser.add_argument("--export",
                        default=str(here / "config/testrail_export_android.xlsx"))
    parser.add_argument("--out",
                        default=str(here / "config/section_to_module_mapping.yaml"))
    parser.add_argument("--review",
                        default=str(here / "config/mapping_review.md"))
    parser.add_argument("--min-depth", type=int, default=2,
                        help="shallowest section depth to key on (default 2)")
    parser.add_argument("--max-size", type=int, default=MAX_SECTION_SIZE,
                        help="descend a level above this many cases "
                             f"(default {MAX_SECTION_SIZE})")
    args = parser.parse_args(argv)

    index = build_index(args.export, args.repo)
    sections = build_sections(index, args.repo,
                              min_depth=args.min_depth, max_size=args.max_size)

    Path(args.out).write_text(
        render_yaml(sections, args.export, args.repo), encoding="utf-8")
    Path(args.review).write_text(render_review(sections), encoding="utf-8")

    mapped = sum(1 for s in sections if s.modules)
    covered = sum(s.test_count for s in sections if s.modules)
    total = sum(s.test_count for s in sections)
    print(f"{args.out}: {len(sections)} sections, {mapped} mapped")
    print(f"{args.review}: {len(sections) - mapped} to review, "
          f"{covered}/{total} cases covered ({100 * covered / total:.0f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
