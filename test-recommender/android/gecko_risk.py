"""
Engine-change risk signal for Firefox Android.

Android is not iOS: iOS renders with WKWebView, so engine changes are invisible
to the firefox-ios repo. Firefox Android embeds GeckoView, and because
mozilla-central is a monorepo GeckoView is built from the same tree — every
beta ships the engine at that revision. A report that looks only at
`mobile/android/{fenix,android-components}` will state "nothing changed" for a
beta in which `dom/` and `netwerk/` moved substantially.

Per beta range the engine typically moves far more files than the app does,
and in a large share of ranges the app side is empty and the engine is the
only signal there is. `python3 -m android.calibrate` prints the split.

This module deliberately does *not* try to map engine files onto individual
TestRail cases. Two reasons:

  - The inference is far weaker than the app's. `fenix/settings/` ->
    `Menus > Settings menu` is close to a rename; `dom/canvas/` -> a manual
    case is a guess.
  - Gecko change is covered by Gecko's own CI (mochitest, reftest,
    web-platform-tests), not by Fenix manual regression. The Android manual
    catalogue is overwhelmingly app-UI oriented — `Menus` and `Browsing`
    dominate it, and almost no case exercises engine internals directly.

So the output is a coarse, auditable risk summary with section *hints*, plus
one decision the pipeline must respect: `vetoes_no_regression`. When the app
diff is empty but engine churn is material, the report must not conclude
"l10n only, no functional regression required".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from android.change_extractor import ChangedFile, _git, classify_path


# =============================================================================
# Scope
# =============================================================================


DESKTOP_ONLY: tuple[str, ...] = (
    "browser/",          # desktop front-end; Android ships its own
    "devtools/",         # not shipped on Android
    "toolkit/mozapps/",  # desktop updater / extension manager UI
)
"""Trees Android does not ship. Excluding them removes 20-34 files per beta
that would otherwise read as engine risk."""


# Ordered most-specific first: `classify_gecko_path()` takes the first match,
# so `dom/media` must precede the general `dom/` entry.
#
# `sections` are *hints* for the report's exploratory-testing section, phrased
# as depth-2 TestRail section names where one exists. They are not used to
# select individual cases.
GECKO_AREAS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("remote_settings", ("Search", "Browsing"),
     "services/settings"),
    ("media", ("Browsing", "Picture in picture", "PWA"),
     "dom/media"),
    ("push", ("Accounts & Sync",),
     "dom/push"),
    ("graphics", ("Browsing", "Dark mode"),
     "gfx"),
    ("layout", ("Browsing",),
     "layout"),
    ("networking", ("Browsing", "Downloads"),
     "netwerk"),
    ("security", ("Navigation toolbar", "Browsing"),
     "security"),
    ("permissions", ("Browsing",),
     "caps"),
    ("translations", ("Translations",),
     "toolkit/components/translations"),
    ("extensions", ("Menus",),
     "toolkit/components/extensions"),
    ("search_service", ("Search",),
     "toolkit/components/search"),
    ("downloads_backend", ("Downloads",),
     "toolkit/components/downloads"),
    ("accessibility", ("Browsing",),
     "accessible"),
    ("geckoview_api", ("Browsing",),
     "mobile/android/geckoview"),
    ("android_widget", ("Browsing",),
     "widget/android"),
    ("mobile_shared", ("Browsing",),
     "mobile/shared"),
    ("dom", ("Browsing",),
     "dom"),
    ("js_engine", ("Browsing",),
     "js"),
    ("engine_core", ("Browsing",),
     "xpcom"),
    ("docshell", ("Browsing",),
     "docshell"),
    ("widget", ("Browsing",),
     "widget"),
    ("toolkit", ("Browsing",),
     "toolkit"),
    ("services", ("Accounts & Sync",),
     "services"),
)

GECKO_SCOPE: tuple[str, ...] = tuple(
    dict.fromkeys(prefix for _, _, prefix in GECKO_AREAS)
)
"""Paths passed to `git diff`. Derived from GECKO_AREAS so the two cannot drift
apart."""

MATERIAL_CHURN = 500
"""Engine churn (added + deleted lines, excluding tests, vendored source and
Remote Settings dumps, and generated trust blobs) above which the engine
counts as materially changed.

Calibrated against every beta-to-beta pair and final-beta-to-RC range in the
tree, and set so that it discriminates where it matters: on ranges whose app
diff is quiet it should fire for some and stay silent for others. A threshold
that fires on all of them, or none, is miscalibrated.

`python3 -m android.calibrate` prints the churn distribution and that
quiet-range split, and warns when the veto stops discriminating.

A file-count criterion was considered and dropped: the one range it would have
changed already vetoed via a notable Remote Settings collection.
"""


# =============================================================================
# Data models
# =============================================================================


@dataclass
class GeckoArea:
    """One engine area that changed."""
    name: str
    files: list[ChangedFile] = field(default_factory=list)
    section_hints: tuple[str, ...] = ()

    @property
    def churn(self) -> int:
        return sum(f.churn for f in self.files)

    @property
    def product_files(self) -> list[ChangedFile]:
        return [f for f in self.files if f.category not in EXCLUDED_FROM_CHURN]

    @property
    def product_churn(self) -> int:
        return sum(f.churn for f in self.product_files)


@dataclass
class GeckoRisk:
    base: str
    head: str
    areas: list[GeckoArea] = field(default_factory=list)
    excluded_test: int = 0
    excluded_vendored: int = 0
    excluded_generated: int = 0
    # Generated trust/data blobs refreshed in this range (HSTS preload, CT
    # logs, PSL). Reported by name: a refresh is worth a line, not 900.
    generated_data_files: list[str] = field(default_factory=list)
    # Remote Settings collections refreshed in this range, by collection name.
    remote_settings_collections: list[str] = field(default_factory=list)

    @property
    def product_churn(self) -> int:
        """Churn excluding engine tests, vendored source, and Remote Settings
        data dumps — the figure MATERIAL_CHURN is compared against."""
        return sum(a.product_churn for a in self.areas)

    @property
    def file_count(self) -> int:
        return sum(len(a.files) for a in self.areas)

    @property
    def product_file_count(self) -> int:
        return sum(len(a.product_files) for a in self.areas)

    @property
    def notable_collections(self) -> list[str]:
        """Remote Settings collections whose refresh can change behaviour,
        excluding the ones that regenerate every cycle."""
        return [c for c in self.remote_settings_collections
                if not is_routine_collection(c)]

    @property
    def is_material(self) -> bool:
        """Material if real engine code moved, or if a non-routine Remote
        Settings collection shipped. The latter counts on its own: it reaches
        users without a build, so a zero-code beta can still change
        behaviour."""
        return (self.product_churn >= MATERIAL_CHURN
                or bool(self.notable_collections))

    @property
    def section_hints(self) -> list[str]:
        """Deduplicated TestRail section hints, ordered by the churn of the
        areas that suggested them."""
        weight: dict[str, int] = {}
        for area in self.areas:
            # Weight by product churn, so a 15k-line vendored FFmpeg header
            # import does not push "Picture in picture" to the top.
            if not area.product_churn:
                continue
            for hint in area.section_hints:
                weight[hint] = weight.get(hint, 0) + area.product_churn
        return [h for h, _ in sorted(weight.items(), key=lambda kv: -kv[1])]

    def vetoes_no_regression(self, app_has_product_change: bool) -> bool:
        """True when the report must not conclude "no functional regression
        required" — the app diff is quiet but the engine underneath is not.

        This is the guard for the `b5->b6` shape: zero Kotlin product files,
        which on its own reads as an l10n-only beta.
        """
        return not app_has_product_change and self.is_material

    def top_areas(self, limit: int = 5) -> list[GeckoArea]:
        return sorted(self.areas, key=lambda a: -a.product_churn)[:limit]


# =============================================================================
# Classification
# =============================================================================


def is_desktop_only(path: str) -> bool:
    return path.startswith(DESKTOP_ONLY)


def classify_gecko_path(path: str) -> Optional[tuple[str, tuple[str, ...]]]:
    """Return `(area_name, section_hints)` for an engine path, or None if the
    path is desktop-only or outside the engine scope."""
    if is_desktop_only(path):
        return None
    for name, sections, prefix in GECKO_AREAS:
        if path == prefix or path.startswith(prefix + "/"):
            return (name, sections)
    return None


def _is_engine_test(path: str) -> bool:
    """Gecko's own test files. Excluded from the churn figure: a 5k-line
    web-platform-test import is not Android product risk."""
    parts = path.split("/")
    return any(
        p in {"test", "tests", "mochitest", "reftests", "crashtests",
              "gtest", "unit", "browser_tests"}
        for p in parts
    ) or "/web-platform/" in path


REMOTE_SETTINGS_DUMPS = "services/settings/dumps/"
"""Pre-packaged Remote Settings collections. Measured in *files*, never lines:
a single routine refresh of `security-state/intermediates.json` or
`blocklists/addons.json` runs to five figures and would swamp every real code
change in the range.

They are not noise, though — a change to `main/cookie-banner-rules-list.json`
or `main/translations-models.json` alters behaviour, and Remote Settings ships
to users without a build. Reported as a collection count instead.
"""


ROUTINE_COLLECTIONS: tuple[str, ...] = (
    "blocklists/addons-bloomfilters",   # regenerated every cycle
    "blocklists/addons",
    "security-state/intermediates",     # CA intermediate cache refresh
    "security-state/onecrl",
    "main/ms-images",
)
"""Collections that are refreshed as a matter of course. They appeared in all
every sampled beta range, so treating any collection change as notable makes
the signal fire constantly and mean nothing.

Everything else — `main/cookie-banner-rules-list`, `main/translations-models`,
`main/search-config-icons`, `main/*-experiments`, webcompat interventions — can
change user-visible behaviour and is reported.
"""


def is_routine_collection(collection: str) -> bool:
    return collection.startswith(ROUTINE_COLLECTIONS)


def collection_name(path: str) -> str:
    """The Remote Settings collection a dump file belongs to.

    Always the first two path components under `dumps/`, because collections
    store per-record attachments in a subdirectory: a single search-config
    refresh writes 57 files as
    `main/search-config-icons/<uuid>.meta`, which must collapse to
    `main/search-config-icons` rather than read as 57 collections.
    """
    rel = path[len(REMOTE_SETTINGS_DUMPS):] if path.startswith(REMOTE_SETTINGS_DUMPS) else path
    parts = [p for p in rel.split("/") if p]
    if not parts:
        return rel
    if len(parts) == 1:
        return parts[0].removesuffix(".json")
    return f"{parts[0]}/{parts[1].removesuffix('.json')}"


GENERATED_DATA: tuple[str, ...] = (
    "security/manager/ssl/nsSTSPreloadList.inc",   # HSTS preload list
    "security/manager/ssl/StaticHPKPins.h",        # HPKP pins
    "security/ct/CTKnownLogs.h",                   # Certificate Transparency
    "security/manager/tools/log_list.json",
    "netwerk/dns/effective_tld_names.dat",         # Public Suffix List
    "netwerk/dns/etld_data.inc",
)
"""Generated trust/data blobs refreshed on a schedule, not hand-written code.

Same trap as the Remote Settings dumps, in a different costume: a routine
`nsSTSPreloadList.inc` refresh can account for nearly all the lines attributed
to `security`, making a scheduled data update read as the largest engine
change in the range. It is worth knowing about; it is not new security logic,
and it must not outrank actual code.
"""


def _is_generated_data(path: str) -> bool:
    return path in GENERATED_DATA


def _is_vendored(path: str) -> bool:
    """Imported third-party source. `dom/media/platforms/ffmpeg/ffmpeg63/
    include/libavcodec/avcodec.h` alone runs to thousands of lines."""
    return (
        path.startswith("third_party/")
        or "/include/libav" in path
        or "/ffmpeg" in path and "/include/" in path
    )


def classify_engine_path(path: str) -> str:
    """Category for an engine file, from the risk metric's point of view.

    Distinct from `change_extractor.classify_path()`, which is tuned for the
    Android app tree (Kotlin, Gradle, `res/values-*`).
    """
    if path.startswith(REMOTE_SETTINGS_DUMPS):
        return "remote_settings_data"
    if _is_generated_data(path):
        return "generated_data"
    if _is_vendored(path):
        return "vendored"
    if _is_engine_test(path):
        return "test"
    return classify_path(path)


EXCLUDED_FROM_CHURN = frozenset(
    {"test", "vendored", "remote_settings_data", "generated_data"}
)
"""Categories counted but kept out of `product_churn`."""


# =============================================================================
# Extraction
# =============================================================================


def extract_gecko_risk(
    repo: str, base: str, head: str, scope: Iterable[str] = GECKO_SCOPE,
) -> GeckoRisk:
    """Summarize engine change between two tags.

    Uses the same diff-driven approach as `change_extractor.extract_range()`;
    see that module's docstring on why `git log` is not authoritative here.
    """
    out = _git(repo, ["diff", "--numstat", base, head, "--", *scope])

    areas: dict[str, GeckoArea] = {}
    excluded_test = 0
    excluded_vendored = 0
    generated: list[str] = []
    collections: list[str] = []

    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add, dele, path = parts
        classified = classify_gecko_path(path)
        if classified is None:
            continue
        name, hints = classified
        category = classify_engine_path(path)
        changed = ChangedFile(
            path=path,
            additions=0 if add == "-" else int(add),
            deletions=0 if dele == "-" else int(dele),
            category=category,
        )
        if category == "test":
            excluded_test += 1
        elif category == "vendored":
            excluded_vendored += 1
        elif category == "generated_data":
            generated.append(path)
        elif category == "remote_settings_data":
            collection = collection_name(path)
            if collection not in collections:
                collections.append(collection)
        area = areas.get(name)
        if area is None:
            area = GeckoArea(name=name, section_hints=hints)
            areas[name] = area
        area.files.append(changed)

    return GeckoRisk(
        base=base, head=head,
        areas=sorted(areas.values(), key=lambda a: -a.product_churn),
        excluded_test=excluded_test,
        excluded_vendored=excluded_vendored,
        excluded_generated=len(generated),
        generated_data_files=sorted(generated),
        remote_settings_collections=sorted(collections),
    )


def summarize(risk: GeckoRisk, limit: int = 5) -> str:
    """One-paragraph, auditable summary for the report's risk section."""
    if not risk.areas:
        return (f"No engine change between {risk.base} and {risk.head} "
                f"(Gecko trees Android ships were untouched).")
    top = ", ".join(
        f"{a.name} ({len(a.product_files)}f/{a.product_churn} lines)"
        for a in risk.top_areas(limit) if a.product_files
    ) or "none"
    verdict = "material" if risk.is_material else "minor"
    parts = [
        f"Engine change is {verdict}: {risk.product_file_count} product "
        f"file(s), {risk.product_churn} lines across {len(risk.areas)} area(s). "
        f"Largest: {top}."
    ]
    notable = risk.notable_collections
    if notable:
        shown = ", ".join(notable[:4])
        more = len(notable) - 4
        routine = len(risk.remote_settings_collections) - len(notable)
        parts.append(
            f"{len(notable)} Remote Settings collection(s) with behaviour "
            f"impact ({shown}{f', +{more} more' if more > 0 else ''}) — these "
            f"reach users without a build"
            f"{f'; {routine} routine refresh(es) ignored' if routine else ''}."
        )
    if risk.generated_data_files:
        names = ", ".join(f.rsplit("/", 1)[-1] for f in risk.generated_data_files[:3])
        parts.append(
            f"{len(risk.generated_data_files)} generated trust/data blob(s) "
            f"refreshed ({names}) — excluded from the line count."
        )
    if risk.excluded_test or risk.excluded_vendored:
        parts.append(
            f"Excluded {risk.excluded_test} engine-test and "
            f"{risk.excluded_vendored} vendored file(s) from the line count."
        )
    if risk.section_hints:
        parts.append(
            f"Suggested exploratory focus: {', '.join(risk.section_hints[:4])}."
        )
    return " ".join(parts)
