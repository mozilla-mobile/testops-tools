"""
Change extractor for Firefox Android (mozilla-firefox/firefox monorepo).

The iOS pipeline is PR-centric: `gh api compare` returns a list of pull
requests and that list *is* the release. mozilla-central has no pull requests —
code is reviewed in Phabricator, landed by Lando onto `autoland`, and merged to
`firefox-main`. The unit of change here is a Bugzilla bug, reconstructed from
commit trailers.

Design goals:

  - **Diff-driven, not log-driven.** Release promotion (`Promote beta to
    release`) is a *merge*, so an unscoped `git log <beta>..<rc>` reports
    commits whose content is already present in the base — on one measured
    cycle it listed around twenty commits for a tree delta of four version-bump
    files. The authoritative change set is therefore `git diff --numstat`, and
    commits are attributed to it afterwards.

    Two consequences for `log_commits()`:

      * Git's default *history simplification* already prunes most of those
        commits once `-- <scope>` is passed, because they are TREESAME along
        the simplified path. **Never pass `--full-history`** — it resurrects
        every phantom.
      * A commit that survives simplification but still touches nothing in the
        net diff is reported as a phantom rather than silently included. Two
        causes seen in practice: the promotion merge above, and a land/revert
        pair inside one range, where a file is updated and reverted so both
        commits appear in the log while the tree is unchanged.

  - **Scoped to the Android app.** The monorepo diff between two release tags
    runs to tens of thousands of files. Scoped to
    `mobile/android/{fenix,android-components}` a beta-to-beta delta is two
    orders of magnitude smaller, and only a fraction of that is Kotlin product
    code — `python3 -m android.calibrate` prints the current spread.

  - **Locale-aware noise filtering.** `res/values-*/strings.xml` are
    translation imports, and they dominate the file count of a typical beta.
    `res/values/strings.xml` has no locale qualifier: it is the en-US source
    and signals new UI copy.

  - Bugzilla enrichment is injected, so the deterministic layer is testable
    without network I/O.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional


# =============================================================================
# Scope
# =============================================================================


DEFAULT_SCOPE: tuple[str, ...] = (
    "mobile/android/fenix",
    "mobile/android/android-components",
)
"""Paths passed to `git diff -- <scope>`. Focus and GeckoView are deliberately
excluded; see the scope decision in android/README.md."""


# =============================================================================
# Tag resolution
# =============================================================================


# FIREFOX-ANDROID_154_0b10_RELEASE / _BUILD1   → beta
# FIREFOX-ANDROID_154_0_BUILD1                 → release candidate
# FIREFOX-ANDROID_154_0_RELEASE                → shipped release
# FIREFOX-ANDROID_153_0_2_RELEASE              → dot release
TAG_RE = re.compile(
    r"^FIREFOX-ANDROID_(?P<major>\d+)_0"
    r"(?:b(?P<beta>\d+))?"
    r"(?:_(?P<patch>\d+))?"
    r"_(?:BUILD(?P<build>\d+)|(?P<shipped>RELEASE))$"
)


@dataclass(frozen=True)
class AndroidTag:
    """A parsed Firefox Android release tag."""
    raw: str
    major: int
    kind: str                      # "beta" | "rc" | "dot"
    beta: Optional[int] = None
    patch: Optional[int] = None
    build: Optional[int] = None    # None on a _RELEASE tag
    shipped: bool = False          # True for _RELEASE

    @property
    def sort_key(self) -> tuple:
        """Order tags within a cycle: betas, then RC/dot builds. `shipped`
        outranks any BUILD<n> because `_RELEASE` points at whichever build was
        actually promoted."""
        return (
            self.major,
            0 if self.kind == "beta" else 1,
            self.beta or 0,
            self.patch or 0,
            1 if self.shipped else 0,
            self.build or 0,
        )


def parse_tag(raw: str) -> Optional[AndroidTag]:
    """Parse a tag name, or return None if it is not an Android release tag."""
    m = TAG_RE.match(raw)
    if not m:
        return None
    beta = int(m.group("beta")) if m.group("beta") else None
    patch = int(m.group("patch")) if m.group("patch") else None
    build = int(m.group("build")) if m.group("build") else None
    if beta is not None:
        kind = "beta"
    elif patch is not None:
        kind = "dot"
    else:
        kind = "rc"
    return AndroidTag(
        raw=raw,
        major=int(m.group("major")),
        kind=kind,
        beta=beta,
        patch=patch,
        build=build,
        shipped=bool(m.group("shipped")),
    )


def list_tags(repo: str) -> list[AndroidTag]:
    """All Android release tags in the repo, ascending."""
    out = _git(repo, ["tag", "--list", "FIREFOX-ANDROID_*"])
    tags = [t for t in (parse_tag(line.strip()) for line in out.splitlines()) if t]
    return sorted(tags, key=lambda t: t.sort_key)


def _preferred(candidates: list[AndroidTag]) -> Optional[AndroidTag]:
    """Pick the tag representing the build that actually shipped.

    Prefer `_RELEASE`; fall back to the highest `_BUILD<n>` when nothing has
    shipped yet (an RC mid-validation). That fallback is the respin case, where
    BUILD2 supersedes BUILD1.
    """
    if not candidates:
        return None
    shipped = [t for t in candidates if t.shipped]
    if shipped:
        return shipped[0]
    return max(candidates, key=lambda t: t.build or 0)


def resolve_beta(repo: str, major: int, beta: int) -> Optional[AndroidTag]:
    """Resolve `<major> beta <n>` to the tag of the build that shipped."""
    return _preferred([
        t for t in list_tags(repo)
        if t.major == major and t.kind == "beta" and t.beta == beta
    ])


def latest_beta(repo: str, major: int) -> Optional[AndroidTag]:
    """The highest-numbered beta of a cycle. Betas are not zero-padded in the
    tag name, so this compares numerically, not lexically — b10 > b9."""
    betas = [t for t in list_tags(repo) if t.major == major and t.kind == "beta"]
    if not betas:
        return None
    top = max(t.beta or 0 for t in betas)
    return _preferred([t for t in betas if t.beta == top])


def resolve_rc(repo: str, major: int) -> Optional[AndroidTag]:
    """The release candidate of a cycle (highest BUILD, or the shipped tag)."""
    return _preferred([
        t for t in list_tags(repo) if t.major == major and t.kind == "rc"
    ])


def beta_pairs(repo: str, major: int) -> list[tuple[AndroidTag, AndroidTag]]:
    """Consecutive beta-to-beta ranges for a cycle, in order."""
    numbers = sorted(
        {t.beta for t in list_tags(repo) if t.major == major and t.kind == "beta"}
    )
    resolved = [t for t in (resolve_beta(repo, major, n) for n in numbers) if t]
    return list(zip(resolved, resolved[1:]))


# =============================================================================
# File classification
# =============================================================================


# `res/values-es/strings.xml`, `res/values-b+sr+Latn/...` — translation imports.
# The unqualified `res/values/strings.xml` is the en-US source and is NOT noise.
TRANSLATION_RE = re.compile(r"/res/values-[^/]+/")

CATEGORY_RULES: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("translation", lambda p: bool(TRANSLATION_RE.search(p))),
    # Split deliberately: only `androidTest/` (instrumented UI tests) carries
    # `// TestRail link:` comments, so only it can produce an exact match.
    # On the beta branch nearly every test change is a unit test, so lumping
    # them together makes "tests changed" read as a TestRail signal when it is
    # not one.
    ("test_ui", lambda p: "/src/androidTest/" in p),
    ("test_unit", lambda p: "/src/test/" in p),
    ("source_strings", lambda p: p.endswith("/res/values/strings.xml")),
    # `.fml.yaml` declares the feature surface; `initial_experiments.json` is
    # the manifest of experiments baked into the build. A change to either can
    # alter behaviour with no code diff, which is why iOS treats its
    # equivalents as a standing risk category rather than a plain resource.
    ("nimbus", lambda p: p.endswith((".fml.yaml", "initial_experiments.json"))),
    ("telemetry", lambda p: p.endswith(("metrics.yaml", "pings.yaml"))),
    # Version pins for Application Services / GeckoView / Glean. A bump here is
    # a release-level risk signal, the analogue of iOS's Package.swift.
    ("dependency", lambda p: "/plugins/dependencies/" in p
                             or p.endswith(("DependenciesPlugin.kt", "libs.versions.toml"))),
    ("build", lambda p: p.endswith((".gradle", ".gradle.kts", "gradle.properties",
                                    ".pro", "AndroidManifest.xml"))),
    ("docs", lambda p: p.endswith((".md", ".rst", ".txt")) or "/docs/" in p),
    ("asset", lambda p: p.endswith((".png", ".webp", ".jpg", ".svg", ".ttf"))),
    ("resource", lambda p: "/res/" in p),
    ("code", lambda p: p.endswith((".kt", ".java"))),
)

TEST_CATEGORIES = frozenset({"test_ui", "test_unit"})
"""Both are tests, but only `test_ui` can yield a TestRail exact match."""

NOISE_CATEGORIES = frozenset({"translation", "docs", "asset"})
"""Categories excluded from module grouping and risk scoring. They are counted
and reported, never silently dropped."""


def classify_path(path: str) -> str:
    """Bucket a changed file. First matching rule wins, so order matters: the
    `test` rule precedes `code` so test sources are never counted as product
    code, and `translation` precedes `resource`."""
    for name, rule in CATEGORY_RULES:
        if rule(path):
            return name
    return "other"


@dataclass
class ChangedFile:
    path: str
    additions: int
    deletions: int
    category: str

    @property
    def is_noise(self) -> bool:
        return self.category in NOISE_CATEGORIES

    @property
    def churn(self) -> int:
        return self.additions + self.deletions


# =============================================================================
# Commits
# =============================================================================


BUG_RE = re.compile(r"\bBug\s+(\d{6,})\b", re.IGNORECASE)
PHAB_RE = re.compile(r"Differential Revision:\s*\S+/(D\d+)")
REVIEWER_RE = re.compile(r"\br=([\w\-.,+]+)")
APPROVER_RE = re.compile(r"\ba=([\w\-.,+]+)")
BACKOUT_RE = re.compile(r"^(?:Backed out|Revert)\b", re.IGNORECASE)

# Subjects that are release/l10n plumbing rather than product change.
PLUMBING_RE = re.compile(
    # Branch names contain hyphens (`firefox-autoland`), so `\w` alone is wrong.
    r"^(?:No Bug[ ,-]|Automatic version bump|Promote beta to release|"
    r"Merge [\w-]+ to [\w-]+|Bumping [\w-]+ l10n)",
    re.IGNORECASE,
)


@dataclass
class MozCommit:
    sha: str
    subject: str
    body: str
    author: str
    date: str
    # Per-file line counts for *this commit*, from `git log --numstat`. Needed
    # because the net diff cannot be split across the commits that produced it:
    # two commits touching one file would each claim the file's full churn.
    stats: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def files(self) -> list[str]:
        return list(self.stats)

    @property
    def additions(self) -> int:
        return sum(a for a, _ in self.stats.values())

    @property
    def deletions(self) -> int:
        return sum(d for _, d in self.stats.values())

    @property
    def bug_id(self) -> Optional[int]:
        m = BUG_RE.search(self.subject) or BUG_RE.search(self.body)
        return int(m.group(1)) if m else None

    @property
    def phab_revision(self) -> Optional[str]:
        m = PHAB_RE.search(self.body)
        return m.group(1) if m else None

    @property
    def reviewers(self) -> list[str]:
        m = REVIEWER_RE.search(self.subject)
        return [r for r in m.group(1).split(",") if r] if m else []

    @property
    def approver(self) -> Optional[str]:
        """`a=<name>` marks an uplift approved by release management. On a
        beta or RC range its presence means the change bypassed the normal
        train — a strong risk signal."""
        m = APPROVER_RE.search(self.subject)
        return m.group(1) if m else None

    @property
    def is_backout(self) -> bool:
        return bool(BACKOUT_RE.match(self.subject))

    @property
    def is_plumbing(self) -> bool:
        return bool(PLUMBING_RE.match(self.subject))


@dataclass
class BugChange:
    """One Bugzilla bug's contribution to a range — the Android analogue of an
    iOS pull request."""
    bug_id: Optional[int]          # None for the "no bug" bucket
    title: str
    commits: list[MozCommit] = field(default_factory=list)
    files: list[ChangedFile] = field(default_factory=list)
    # Filled by enrich_with_bugzilla(); left empty when enrichment is skipped.
    component: Optional[str] = None
    severity: Optional[str] = None
    keywords: list[str] = field(default_factory=list)

    @property
    def additions(self) -> int:
        """Lines this bug's own commits added, counted per commit.

        Deliberately *not* the sum of `files[].additions`: those are net-diff
        figures for the whole range, so two bugs touching one file would each
        report its full churn. The trade-off is that summing every bug can
        exceed the net diff when commits rewrite the same lines — correct for
        "how much work did this bug do", which is what the risk heuristics want.
        """
        return sum(c.additions for c in self.commits)

    @property
    def deletions(self) -> int:
        return sum(c.deletions for c in self.commits)

    @property
    def phab_revisions(self) -> list[str]:
        return [r for r in (c.phab_revision for c in self.commits) if r]

    @property
    def is_uplift(self) -> bool:
        return any(c.approver for c in self.commits)

    @property
    def touches_tests(self) -> bool:
        return any(f.category in TEST_CATEGORIES for f in self.files)

    @property
    def touches_ui_tests(self) -> bool:
        """Instrumented tests only — the ones that can move a TestRail case."""
        return any(f.category == "test_ui" for f in self.files)

    @property
    def product_files(self) -> list[ChangedFile]:
        return [f for f in self.files
                if not f.is_noise and f.category not in TEST_CATEGORIES]


@dataclass
class ExtractionResult:
    base: str
    head: str
    files: list[ChangedFile]
    bugs: list[BugChange]
    phantom_commits: list[MozCommit] = field(default_factory=list)
    unattributed: list[ChangedFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def signal_files(self) -> list[ChangedFile]:
        return [f for f in self.files if not f.is_noise]

    def counts_by_category(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.files:
            out[f.category] = out.get(f.category, 0) + 1
        return out


# =============================================================================
# Git plumbing
# =============================================================================


def _git(repo: str, args: list[str]) -> str:
    out = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def diff_files(
    repo: str, base: str, head: str, scope: Iterable[str] = DEFAULT_SCOPE,
) -> list[ChangedFile]:
    """The authoritative change set: a tree-to-tree comparison.

    Uses `git diff`, never `git log`. See the module docstring for why.
    """
    out = _git(repo, ["diff", "--numstat", base, head, "--", *scope])
    files: list[ChangedFile] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add, dele, path = parts
        # Binary files report "-" for both counts.
        files.append(ChangedFile(
            path=path,
            additions=0 if add == "-" else int(add),
            deletions=0 if dele == "-" else int(dele),
            category=classify_path(path),
        ))
    return sorted(files, key=lambda f: f.path)


_REC_SEP = "\x1e"
_FIELD_SEP = "\x1f"


def log_commits(
    repo: str, base: str, head: str, scope: Iterable[str] = DEFAULT_SCOPE,
) -> list[MozCommit]:
    """Commits reachable from `head` but not `base`, restricted to `scope`.

    Relies on git's default history simplification to drop promotion-merge
    artifacts; see the module docstring. Do not add `--full-history`.

    The result can still be a superset of the commits that actually changed the
    tree; `extract_range()` reconciles it against `diff_files()`.
    """
    fmt = _REC_SEP + _FIELD_SEP.join(["%H", "%s", "%b", "%an", "%cI"])
    out = _git(repo, [
        "log", f"{base}..{head}", f"--format={fmt}", "--numstat",
        "--no-merges", "--", *scope,
    ])
    commits: list[MozCommit] = []
    for record in out.split(_REC_SEP):
        if not record.strip():
            continue
        fields = record.split(_FIELD_SEP)
        if len(fields) < 5:
            continue
        sha, subject, body, author = (f.strip("\n") for f in fields[:4])
        # `--numstat` appends "<add>\t<del>\t<path>" rows after the last format
        # field, separated from it by a blank line.
        tail = fields[4].split("\n")
        date = tail[0].strip()
        stats: dict[str, tuple[int, int]] = {}
        for line in tail[1:]:
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            add, dele, path = parts
            stats[path] = (
                0 if add == "-" else int(add),
                0 if dele == "-" else int(dele),
            )
        commits.append(MozCommit(
            sha=sha, subject=subject, body=body,
            author=author, date=date, stats=stats,
        ))
    return commits


# =============================================================================
# Extraction
# =============================================================================


def extract_range(
    repo: str,
    base: str,
    head: str,
    scope: Iterable[str] = DEFAULT_SCOPE,
    include_noise: bool = False,
) -> ExtractionResult:
    """Reconcile the tree diff with the commit log into per-bug changes.

    A commit is attributed only to the files it touched that also appear in the
    net diff. A commit whose files are all absent from the net diff is a
    *phantom* — its content was already in `base`, reached via the other parent
    of a promotion merge — and is reported separately instead of inflating the
    change set.
    """
    files = diff_files(repo, base, head, scope)
    by_path = {f.path: f for f in files}
    considered = {
        p: f for p, f in by_path.items() if include_noise or not f.is_noise
    }

    commits = log_commits(repo, base, head, scope)

    bugs: dict[Optional[int], BugChange] = {}
    phantoms: list[MozCommit] = []
    attributed: set[str] = set()
    warnings: list[str] = []

    for commit in commits:
        hits = [considered[p] for p in commit.files if p in considered]
        if not hits:
            # Either a phantom, or it only touched noise/filtered files.
            if not any(p in by_path for p in commit.files):
                phantoms.append(commit)
            continue

        # Plumbing commits are kept when they touched real files: an
        # Application Services version bump lands as "No Bug - ..." and is a
        # genuine risk signal, so it belongs in the `None` bucket rather than
        # being dropped and resurfacing as an unattributed file.
        key = commit.bug_id
        bug = bugs.get(key)
        if bug is None:
            bug = BugChange(bug_id=key, title=_clean_subject(commit.subject))
            bugs[key] = bug
        bug.commits.append(commit)
        known = {x.path for x in bug.files}
        for f in hits:
            if f.path not in known:
                bug.files.append(f)
                known.add(f.path)
            attributed.add(f.path)

    unattributed = [f for p, f in considered.items() if p not in attributed]
    if unattributed:
        warnings.append(
            f"{len(unattributed)} changed file(s) could not be attributed to a "
            f"commit in {base}..{head}; likely landed via a merge parent."
        )
    if phantoms:
        warnings.append(
            f"{len(phantoms)} commit(s) in the log changed nothing in the net "
            f"diff (release-promotion merge artifacts) and were excluded."
        )

    ordered = sorted(
        bugs.values(),
        key=lambda b: (-sum(f.churn for f in b.files), b.bug_id or 0),
    )
    return ExtractionResult(
        base=base, head=head, files=files, bugs=ordered,
        phantom_commits=phantoms, unattributed=unattributed, warnings=warnings,
    )


# `"featureId": "homescreen"` in initial_experiments.json, or a top-level
# feature key in a `.fml.yaml`.
NIMBUS_FEATURE_RE = re.compile(r'"featureId"\s*:\s*"([^"]+)"')
NIMBUS_SLUG_RE = re.compile(r'"slug"\s*:\s*"([^"]+)"')

# Placeholder features Nimbus requires on every experiment; they name no
# surface and would otherwise look like a real blast radius.
NIMBUS_IGNORED_FEATURES = frozenset({
    "this-is-included-for-mobile-pre-96-support",
    "nimbus-validation",
})


EXPERIMENTS_MANIFEST = "mobile/android/fenix/app/src/main/res/raw/initial_experiments.json"


def _experiments_at(repo: str, rev: str) -> dict[str, dict]:
    """`{slug: experiment}` from the manifest at `rev`, or {} if absent."""
    try:
        raw = _git(repo, ["show", f"{rev}:{EXPERIMENTS_MANIFEST}"])
        payload = json.loads(raw)
    except Exception:
        return {}
    entries = payload.get("data", payload)
    if not isinstance(entries, list):
        return {}
    return {e["slug"]: e for e in entries if isinstance(e, dict) and e.get("slug")}


def nimbus_features_changed(
    repo: str, base: str, head: str, scope: Iterable[str] = DEFAULT_SCOPE,
) -> tuple[list[str], list[str]]:
    """Return `(feature_ids, experiment_slugs)` added or changed by this range.

    A Nimbus change has no file-level blast radius to follow — the diff is one
    JSON manifest — so the feature IDs it names are the only way to tell which
    product surfaces it touches. Reading them is far more precise than guessing
    from the fact that *some* experiment changed: the feature IDs name a
    couple of concrete surfaces and select a handful of sections, where a
    coarse prefix match over section names takes a large slice of the
    catalogue.

    The manifest is parsed as JSON rather than grepped, because `slug` appears
    at three nesting levels — experiment, branch (`control`, `treatment-a`),
    and per-branch feature (`awesomebar`, `pocket`). A line scan reported all
    of them as experiments.
    """
    before = _experiments_at(repo, base)
    after = _experiments_at(repo, head)

    slugs = [s for s, e in after.items() if before.get(s) != e]
    features: list[str] = []
    for slug in slugs:
        for feature in after[slug].get("featureIds") or []:
            if feature not in NIMBUS_IGNORED_FEATURES and feature not in features:
                features.append(feature)

    # `.fml.yaml` feature definitions have no manifest to diff; fall back to
    # scanning added lines for feature IDs there.
    if not before and not after:
        out = _git(repo, ["diff", base, head, "--", *scope])
        for line in out.splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            for m in NIMBUS_FEATURE_RE.finditer(line):
                f = m.group(1)
                if f not in NIMBUS_IGNORED_FEATURES and f not in features:
                    features.append(f)

    return features, sorted(slugs)


def _clean_subject(subject: str) -> str:
    """Strip the `r=`/`a=` trailers and the `Bug N -` prefix from a subject."""
    s = REVIEWER_RE.sub("", subject)
    s = APPROVER_RE.sub("", s)
    s = re.sub(r"^Bug\s+\d+\s*[-:]?\s*", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip(" -,")


# =============================================================================
# Bugzilla enrichment
# =============================================================================


BUGZILLA_API = "https://bugzilla.mozilla.org/rest/bug"

BugzillaFetcher = Callable[[list[int]], dict[int, dict]]
"""Injected so the deterministic layer stays testable without network I/O."""


def _default_bugzilla_fetcher(bug_ids: list[int]) -> dict[int, dict]:
    """Fetch bug metadata in one batched request. Returns {} on any failure —
    enrichment is an enhancement, never a hard dependency of the pipeline."""
    if not bug_ids:
        return {}
    params = urllib.parse.urlencode({
        "id": ",".join(str(b) for b in bug_ids),
        "include_fields": "id,summary,component,product,severity,keywords",
    })
    try:
        with urllib.request.urlopen(f"{BUGZILLA_API}?{params}", timeout=30) as resp:
            payload = json.load(resp)
    except Exception:
        return {}
    return {b["id"]: b for b in payload.get("bugs", [])}


def enrich_with_bugzilla(
    result: ExtractionResult,
    fetcher: Optional[BugzillaFetcher] = None,
    batch_size: int = 100,
) -> ExtractionResult:
    """Attach component / severity / keywords to each bug, in place.

    Bugzilla's `component` (e.g. `Fenix::Settings`) is the structured signal
    that GitHub PR labels never reliably provided on iOS.
    """
    fetch = fetcher or _default_bugzilla_fetcher
    ids = [b.bug_id for b in result.bugs if b.bug_id]
    if not ids:
        return result

    meta: dict[int, dict] = {}
    for i in range(0, len(ids), batch_size):
        meta.update(fetch(ids[i:i + batch_size]))

    missing = 0
    for bug in result.bugs:
        info = meta.get(bug.bug_id) if bug.bug_id else None
        if not info:
            if bug.bug_id:
                missing += 1
            continue
        product = info.get("product") or ""
        component = info.get("component") or ""
        bug.component = f"{product}::{component}" if product else component or None
        bug.severity = info.get("severity")
        bug.keywords = list(info.get("keywords") or [])
        if info.get("summary"):
            bug.title = info["summary"]

    if missing:
        result.warnings.append(
            f"Bugzilla metadata unavailable for {missing} of {len(ids)} bug(s) "
            f"(private/security bugs, or the API was unreachable)."
        )
    return result
