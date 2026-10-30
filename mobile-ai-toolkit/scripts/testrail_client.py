#!/usr/bin/env python3
"""Shared TestRail integration layer for the mobile-ai-toolkit agents.

This is the single place that knows how to talk to TestRail. Everything that is
not specific to one workflow lives here:

    * configuration + credential loading (``Config`` / ``load_config``,
      ``env_int``)
    * the selectable TestRail projects, the prompt the agents must show, and
      resolving/validating the chosen project's ids (``ProjectChoice``,
      ``project_menu``, ``project_target``, ``verify_project_target``)
    * the authenticated HTTP client, with retries and rate-limit handling
      (``TestRailClient``)
    * project / suite / section / case reads, with per-run metadata caching
    * text normalisation, rich-text flattening and numbered-step parsing
      (``parse_numbered`` / ``pair_numbered``)
    * the plain-text rendering of a case (``CaseView``)
    * custom-field and option-id resolution
    * Automation status resolution (``AutomationField``)
    * label reading
    * markdown report building (``md_table``) and CLI error handling
      (``run_cli``)

The workflow scripts build on it and contain only their own logic:

    testrail_import.py            CSV -> TestRail (creates cases)
    testrail_fetch_section.py     TestRail -> stdout (read-only)
    testrail_triage_automation.py TestRail -> automation triage (updates cases)

    agent -> workflow script -> testrail_client -> TestRail API

There is deliberately one client class, one config loader and one set of field
helpers, so authentication, pagination, retries and field mapping cannot drift
between the scripts.

Credentials come from the environment; a local .env is loaded automatically
when python-dotenv is installed. The API key is never printed or logged.
"""

from __future__ import annotations

import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field as dc_field
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from requests.auth import HTTPBasicAuth

try:
    from dotenv import load_dotenv
except ImportError:  # optional dependency
    load_dotenv = None


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

# Toolkit paths. Absolute and derived from this file's location, so the
# scripts behave the same whatever directory they are invoked from.
REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_ROOT = REPO_ROOT / "work" / "inputs"
OUTPUT_ROOT = REPO_ROOT / "work" / "outputs"


class TestRailError(Exception):
    """Any TestRail configuration, transport or API failure.

    One error type for every script: a failure is reported the same way whether
    it came from configuration, HTTP, or a rejected payload.
    """


TEMPORARY_HTTP_CODES = {409, 429, 500, 502, 503, 504}


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #

def norm(value: str) -> str:
    """Normalize unicode + line endings, strip trailing spaces per line."""
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+$", "", line) for line in value.split("\n")]
    return "\n".join(lines).strip()


def key(value: str) -> str:
    """Case-insensitive comparison key."""
    return re.sub(r"\s+", " ", norm(value).lower()).strip()


def field_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKC", value or "").lower())


_LIST_ITEM = re.compile(r"<\s*li[^>]*>", re.IGNORECASE)
_BLOCK = re.compile(r"<\s*/?\s*(?:br|p|div|ul|ol|tr|li)[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def html_to_text(value: str) -> str:
    """Flatten TestRail rich text to plain text; a no-op on plain text.

    Some suites author cases as HTML lists. Left raw, the markup gets quoted as
    if it were UI copy. List items become '- ' bullets, other block tags become
    line breaks, entities are unescaped.
    """
    if not value or "<" not in value:
        return norm(value or "")
    text = _TAG.sub("", _BLOCK.sub("\n", _LIST_ITEM.sub("\n- ", value)))
    text = unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return norm("\n".join(ln for ln in lines if ln and ln != "-"))


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

@dataclass
class Config:
    url: str
    user: str
    api_key: str
    project_id: int
    suite_id: int
    suite_id_low: int | None
    template_id: int | None
    default_priority_id: int | None
    default_type_id: int | None
    external_id_field: str
    references_field: str
    preconditions_field: str
    steps_field: str
    expected_field: str
    separated_steps_field: str
    sub_test_suite_field: str
    use_separated_steps: bool
    request_timeout: int
    max_retries: int
    external_id_available: bool = True
    sub_test_suite_available: bool = True


def env_int(name: str, default: int | None = None, *, required: bool = False,
            context: str = "") -> int | None:
    """Read an integer from the environment.

    The single reader for every numeric setting in the toolkit. `context` is
    appended to both error messages, so a caller can say what the variable is
    for and what the expected value is without re-implementing the checks.
    """
    suffix = f" {context}" if context else ""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        if required:
            raise TestRailError(
                f"Missing required environment variable: {name}.{suffix}"
            )
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise TestRailError(
            f"Environment variable {name} must be an integer, got "
            f"'{raw.strip()}'.{suffix}"
        ) from exc


def load_config(require_target: bool = True) -> Config:
    """Load credentials and field mapping from the environment.

    Raises TestRailError with an actionable message rather than falling back to
    a default for anything that would silently target the wrong instance.

    `require_target=False` loads the credentials and field mapping without
    demanding TESTRAIL_TMP_PROJECT_ID / TESTRAIL_TMP_SUITE_ID, for callers that choose
    their target project explicitly and set `project_id` / `suite_id`
    themselves. Such a caller must set both before using the client - a Config
    with project_id 0 reaches no project.
    """
    if load_dotenv is not None:
        load_dotenv()

    url = (os.getenv("TESTRAIL_URL") or "").rstrip("/")
    if not url:
        raise TestRailError("Missing required environment variable: TESTRAIL_URL")
    if not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise TestRailError("TESTRAIL_URL must use HTTPS (or an explicit local instance).")

    user = os.getenv("TESTRAIL_USER")
    api_key = os.getenv("TESTRAIL_API_KEY")
    if not user or not api_key:
        raise TestRailError("Missing TESTRAIL_USER and/or TESTRAIL_API_KEY.")

    return Config(
        url=url,
        user=user,
        api_key=api_key,
        project_id=env_int("TESTRAIL_TMP_PROJECT_ID", 0, required=require_target),
        suite_id=env_int("TESTRAIL_TMP_SUITE_ID", 0, required=require_target),
        suite_id_low=env_int("TESTRAIL_TMP_SUITE_ID_LOW"),
        template_id=env_int("TESTRAIL_TEMPLATE_ID"),
        default_priority_id=env_int("TESTRAIL_DEFAULT_PRIORITY_ID"),
        default_type_id=env_int("TESTRAIL_DEFAULT_TYPE_ID"),
        external_id_field=os.getenv("TESTRAIL_EXTERNAL_ID_FIELD", "custom_external_id"),
        references_field=os.getenv("TESTRAIL_REFERENCES_FIELD", "refs"),
        preconditions_field=os.getenv("TESTRAIL_PRECONDITIONS_FIELD", "custom_preconds"),
        steps_field=os.getenv("TESTRAIL_STEPS_FIELD", "custom_steps"),
        expected_field=os.getenv("TESTRAIL_EXPECTED_FIELD", "custom_expected"),
        separated_steps_field=os.getenv(
            "TESTRAIL_SEPARATED_STEPS_FIELD", "custom_steps_separated"
        ),
        sub_test_suite_field=os.getenv(
            "TESTRAIL_SUB_TEST_SUITE_FIELD", "custom_sub_test_suites"
        ),
        use_separated_steps=(os.getenv("TESTRAIL_USE_SEPARATED_STEPS", "") or "")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"},
        request_timeout=env_int("TESTRAIL_REQUEST_TIMEOUT", 30),
        max_retries=env_int("TESTRAIL_MAX_RETRIES", 3),
    )


# --------------------------------------------------------------------------- #
# TestRail projects
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ProjectChoice:
    """One selectable TestRail project.

    The ids are deliberately NOT stored here - they are read from the
    environment at run time, from this project's own pair of variables.
    `documented_*_id` is only the value .env is expected to carry: it is used to
    warn when the environment disagrees, and never as an id in its own right.
    """

    key: str
    number: int
    name: str
    url: str
    project_env: str
    suite_env: str
    documented_project_id: int
    documented_suite_id: int
    protected: bool
    note: str

    @property
    def label(self) -> str:
        return f"{self.name}{' (*)' if self.protected else ''}"

    def id_sources(self) -> tuple[tuple[str, int], ...]:
        """The (environment variable, documented value) pairs this project needs."""
        return (
            (self.project_env, self.documented_project_id),
            (self.suite_env, self.documented_suite_id),
        )

    def describe(self, env_name: str) -> str:
        """Why one of those variables matters, for an error message."""
        kind = "project" if env_name == self.project_env else "suite"
        documented = dict(self.id_sources())[env_name]
        return (f"It holds the {kind} id for TestRail project '{self.name}' "
                f"({self.url}); the expected value is {documented}.")


FIREFOX_IOS = ProjectChoice(
    key="firefox-ios",
    number=1,
    name="Firefox for iOS",
    url="https://mozilla.testrail.io/index.php?/projects/overview/14",
    project_env="TESTRAIL_iOS_PROJECT_ID",
    suite_env="TESTRAIL_iOS_FULL_SUITE_ID",
    documented_project_id=14,
    documented_suite_id=45443,
    protected=True,
    note=(
        "This is the official TestRail project containing the production test "
        "cases used by the Firefox for iOS team. Exercise extra caution when "
        "working with this project. Any changes to test cases, automation "
        "statuses, labels, or other TestRail data must be intentional and "
        "explicitly confirmed by the user before execution."
    ),
)

TEMP_APPROVALS = ProjectChoice(
    key="temp-approvals",
    number=2,
    name="[TEMP] iOS test project for TC approvals",
    url="https://mozilla.testrail.io/index.php?/projects/overview/92",
    project_env="TESTRAIL_TMP_PROJECT_ID",
    suite_env="TESTRAIL_TMP_SUITE_ID",
    documented_project_id=92,
    documented_suite_id=107983,
    protected=False,
    note="This is the temporary project used for testing and approvals.",
)

PROJECT_CHOICES = (FIREFOX_IOS, TEMP_APPROVALS)
PROJECT_VALUES = tuple(v for c in PROJECT_CHOICES for v in (str(c.number), c.key))
CONFIRM_FLAG = "--confirm-firefox-ios"


def resolve_project_choice(raw: str) -> ProjectChoice:
    """Map a --project value ('1'/'firefox-ios', '2'/'temp-approvals')."""
    wanted = (raw or "").strip().lower()
    for choice in PROJECT_CHOICES:
        if wanted in {choice.key, str(choice.number)}:
            return choice
    options = ", ".join(f"{c.number}|{c.key}" for c in PROJECT_CHOICES)
    raise TestRailError(
        f"Unknown --project '{raw}'. Choose one of: {options}. The project is "
        "never selected by default - ask the user which one to use."
    )


def project_menu() -> str:
    """The project selection prompt, verbatim.

    The single source of truth for what the agents show the user before they
    search for a section or read any case.
    """
    lines = ["Which TestRail project should I use?", ""]
    for choice in PROJECT_CHOICES:
        lines += [f"{choice.number}. {choice.label}", choice.url, ""]
        prefix = "⚠️ IMPORTANT: " if choice.protected else ""
        lines += [f"{prefix}{choice.note}", ""]
        lines += [
            "Configuration:",
            f"  {choice.project_env} (expected value: {choice.documented_project_id})",
            f"  {choice.suite_env} (expected value: {choice.documented_suite_id})",
            "",
        ]
    lines += [
        "(*) marks the production project. Nothing is written there without "
        "your explicit confirmation.",
        "",
        "Answer with 1 or 2. There is no default.",
    ]
    return "\n".join(lines)


@dataclass
class ProjectTarget:
    """The resolved project + suite a run works in, and how it was resolved."""

    choice: ProjectChoice
    project_id: int
    suite_id: int
    warnings: list[str] = dc_field(default_factory=list)


def project_target(choice: ProjectChoice, *,
                   fallback_to_documented: bool = False) -> ProjectTarget:
    """Resolve one project's ids from its own environment variables.

    Never falls back to the other project's variables, so a run cannot drift
    into a project the user did not pick. `fallback_to_documented` is for the
    read-only fetcher, whose documented defaults have always been optional;
    the triager leaves it off, so a missing variable stops the run.

    A value that disagrees with the documented one is a warning, not an error:
    the environment wins, but the run says so out loud.
    """
    hint = "" if fallback_to_documented else (
        " Add it to .env - the id is never hardcoded, and the run never falls "
        "back to the other project."
    )
    resolved: dict[str, int] = {}
    warnings: list[str] = []

    for env_name, documented in choice.id_sources():
        value = int(env_int(
            env_name,
            documented if fallback_to_documented else None,
            required=not fallback_to_documented,
            context=choice.describe(env_name) + hint,
        ))
        resolved[env_name] = value
        if value != documented:
            warnings.append(
                f"{env_name} is {value}, but '{choice.name}' is documented as "
                f"{documented}. Using {value} from the environment - confirm "
                ".env points where you intend before writing anything."
            )

    return ProjectTarget(
        choice=choice,
        project_id=resolved[choice.project_env],
        suite_id=resolved[choice.suite_env],
        warnings=warnings,
    )


def verify_project_target(client: TestRailClient,
                          target: ProjectTarget) -> tuple[str, str]:
    """Confirm the configured suite really belongs to the chosen project.

    Returns (project name, suite name) for the banner. A suite that lives in
    another project is a configuration error, not something to work around:
    silently working in the wrong project is what the selection step exists to
    prevent.
    """
    project = client.get_project(target.project_id)
    suite = client.get_suite(target.suite_id)
    owner = suite.get("project_id")
    if owner not in (None, target.project_id):
        raise TestRailError(
            f"Suite {target.suite_id} ({target.choice.suite_env}) belongs to "
            f"project {owner}, not {target.project_id} "
            f"({target.choice.project_env}). The two must describe the same "
            f"project - fix .env for '{target.choice.name}' instead of "
            "continuing against a mismatched pair."
        )
    return str(project.get("name") or "?"), str(suite.get("name") or "?")


def project_banner(target: ProjectTarget, project_name: str,
                   suite_name: str) -> list[str]:
    """The '# ...' lines every run prints to state where it is working."""
    choice = target.choice
    lines = [
        f"# TestRail project: {choice.label} - {target.project_id} "
        f"\"{project_name}\" / suite {target.suite_id} \"{suite_name}\"",
        f"# Source: {choice.project_env} / {choice.suite_env} | {choice.url}",
    ]
    if choice.protected:
        lines.append(
            "# ⚠️ PRODUCTION project - the Firefox for iOS team's real test "
            "cases. Writes require explicit user confirmation."
        )
    lines += [f"# ⚠️ {warning}" for warning in target.warnings]
    return lines


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #

class TestRailClient:
    """Authenticated TestRail API client.

    The only place HTTP, retries, pagination and auth are implemented. Read
    endpoints whose results never change within a run (priorities, case types,
    case fields, templates, labels, section trees) are cached per instance, so
    a batch of cases costs one metadata fetch rather than one per case.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.base_url = f"{config.url}/index.php?/api/v2/"
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(config.user, config.api_key)
        self.session.headers.update(
            {"Content-Type": "application/json", "Accept": "application/json"}
        )
        self._cache: dict[str, Any] = {}

    # -- transport ----------------------------------------------------------- #

    def _request(self, method: str, endpoint: str, payload: dict | None = None) -> Any:
        url = self.base_url + endpoint
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.session.request(
                    method, url, json=payload, timeout=self.config.request_timeout
                )
            except requests.RequestException as exc:
                if attempt >= self.config.max_retries:
                    raise TestRailError(f"Network error calling TestRail: {exc}") from exc
                time.sleep(min(2 ** attempt, 10))
                continue

            if response.status_code in {200, 201}:
                return response.json() if response.content else {}
            if response.status_code in {401, 403}:
                raise TestRailError(
                    f"TestRail authentication failed (HTTP {response.status_code})."
                )
            if response.status_code in TEMPORARY_HTTP_CODES and attempt < self.config.max_retries:
                retry_after = response.headers.get("Retry-After")
                delay = int(float(retry_after)) if retry_after else min(2 ** attempt, 30)
                time.sleep(max(1, delay))
                continue

            raise TestRailError(
                f"TestRail API error (HTTP {response.status_code}) on {endpoint}: "
                f"{response.text[:500]}"
            )
        raise TestRailError(f"TestRail request failed: {endpoint}")

    def get(self, endpoint: str) -> Any:
        return self._request("GET", endpoint)

    def post(self, endpoint: str, payload: dict) -> Any:
        return self._request("POST", endpoint, payload)

    def _paginated(self, endpoint: str, collection: str) -> list[dict]:
        items: list[dict] = []
        offset = 0
        sep = "&" if ("&" in endpoint or "?" in endpoint) else "?"
        while True:
            page = self.get(f"{endpoint}{sep}{urlencode({'limit': 250, 'offset': offset})}")
            if isinstance(page, list):
                items.extend(page)
                break
            batch = page.get(collection, [])
            items.extend(batch)
            if (page.get("_links") or {}).get("next"):
                offset += len(batch)
                continue
            if page.get("size", len(batch)) < page.get("limit", 250) or not batch:
                break
            offset += len(batch)
        return items

    def _cached(self, cache_key: str, producer) -> Any:
        if cache_key not in self._cache:
            self._cache[cache_key] = producer()
        return self._cache[cache_key]

    # -- reads: project / suite ---------------------------------------------- #

    def get_project(self, pid: int) -> dict:
        return self._cached(f"project:{pid}", lambda: self.get(f"get_project/{pid}"))

    def get_suite(self, sid: int) -> dict:
        return self._cached(f"suite:{sid}", lambda: self.get(f"get_suite/{sid}"))

    # -- reads: sections ------------------------------------------------------ #

    def get_sections(self, suite_id: int) -> list[dict]:
        """Every section in a suite. Cached; one call per suite per run."""
        return self._cached(
            f"sections:{suite_id}",
            lambda: self._paginated(
                f"get_sections/{self.config.project_id}&suite_id={suite_id}", "sections"
            ),
        )

    def section_index(self, suite_id: int) -> dict[int, dict]:
        """Sections indexed by id, each carrying its full '/'-joined path."""
        return self._cached(
            f"section_index:{suite_id}",
            lambda: section_tree(self.get_sections(suite_id)),
        )

    # -- reads: cases --------------------------------------------------------- #

    def get_cases(self, suite_id: int, section_id: int | None = None) -> list[dict]:
        """Cases in a suite, optionally limited to a single section.

        Not cached: callers may re-read after a write.
        """
        endpoint = f"get_cases/{self.config.project_id}&suite_id={suite_id}"
        if section_id is not None:
            endpoint += f"&section_id={section_id}"
        return self._paginated(endpoint, "cases")

    def get_case(self, case_id: int) -> dict:
        return self.get(f"get_case/{case_id}")

    # -- reads: metadata ------------------------------------------------------ #

    def get_priorities(self) -> list[dict]:
        return self._cached("priorities", lambda: self.get("get_priorities"))

    def get_case_types(self) -> list[dict]:
        return self._cached("case_types", lambda: self.get("get_case_types"))

    def get_case_fields(self) -> list[dict]:
        return self._cached("case_fields", lambda: self.get("get_case_fields"))

    def get_templates(self) -> list[dict]:
        return self._cached(
            "templates", lambda: self.get(f"get_templates/{self.config.project_id}")
        )

    def priority_names(self) -> dict[int, str]:
        """priority id -> display name."""
        return {int(p["id"]): p["name"] for p in self.get_priorities()}

    def type_names(self) -> dict[int, str]:
        """case type id -> display name."""
        return {int(t["id"]): t["name"] for t in self.get_case_types()}

    # -- writes ---------------------------------------------------------------- #

    def add_section(self, name: str, parent_id: int | None, suite_id: int) -> dict:
        payload: dict[str, Any] = {"suite_id": suite_id, "name": name}
        if parent_id is not None:
            payload["parent_id"] = parent_id
        return self.post(f"add_section/{self.config.project_id}", payload)

    def add_case(self, section_id: int, payload: dict) -> dict:
        return self.post(f"add_case/{section_id}", payload)

    def update_case(self, case_id: int, payload: dict) -> dict:
        """Partial update. Only the keys present in `payload` are modified."""
        return self.post(f"update_case/{case_id}", payload)


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #

def section_tree(sections: list[dict]) -> dict[int, dict]:
    """Index sections by id, attaching a full '/'-joined path to each."""
    index = {int(s["id"]): dict(s) for s in sections}
    for section in index.values():
        parts, cursor, guard = [], section, 0
        while cursor is not None and guard < 50:
            parts.append(cursor.get("name", ""))
            parent = cursor.get("parent_id")
            cursor = index.get(int(parent)) if parent else None
            guard += 1
        section["path"] = " / ".join(reversed(parts))
    return index


def resolve_section(index: dict[int, dict], wanted: str) -> dict:
    """Find the requested section: by id, then exact name, then substring."""
    wanted = wanted.strip()
    if wanted.isdigit() and int(wanted) in index:
        return index[int(wanted)]

    target = key(wanted)
    exact = [s for s in index.values() if key(s.get("name", "")) == target]
    found = exact or [s for s in index.values() if target in key(s.get("name", ""))]

    if not found:
        raise TestRailError(f"Section '{wanted}' was not found.")
    if len(found) > 1:
        names = ", ".join(f"{s['name']} (id {s['id']})" for s in found)
        raise TestRailError(
            f"Section '{wanted}' is ambiguous: {names}. Re-run with the section id."
        )
    return found[0]


def descendants(index: dict[int, dict], root_id: int) -> list[dict]:
    """The root plus every section beneath it, parents before children."""
    children: dict[int, list[dict]] = {}
    for section in index.values():
        if section.get("parent_id") is not None:
            children.setdefault(int(section["parent_id"]), []).append(section)
    ordered, stack = [], [index[root_id]]
    while stack:
        current = stack.pop(0)
        ordered.append(current)
        kids = sorted(children.get(int(current["id"]), []),
                      key=lambda s: (s.get("display_order") or 0, s.get("name") or ""))
        stack = kids + stack
    return ordered


@dataclass
class SectionSubtree:
    """One section and everything beneath it.

    The unit of work for every section-scoped workflow: the fetcher prints it,
    the triager limits itself to it.
    """

    root: dict
    sections: list[dict] = dc_field(default_factory=list)  # root first

    @property
    def id(self) -> int:
        return int(self.root["id"])

    @property
    def name(self) -> str:
        return str(self.root.get("name") or "")

    @property
    def path(self) -> str:
        return str(self.root.get("path") or self.name)

    @property
    def section_ids(self) -> set[int]:
        return {int(s["id"]) for s in self.sections}

    def contains(self, case: dict) -> bool:
        return int(case.get("section_id") or 0) in self.section_ids

    def relative_path(self, section: dict) -> str:
        """A child's path with the root prefix stripped, for display."""
        full = str(section.get("path") or section.get("name") or "")
        if full.startswith(self.path):
            return full[len(self.path):].strip(" /")
        return full


def section_subtree(client: TestRailClient, suite_id: int,
                    wanted: str) -> SectionSubtree:
    """Resolve a section by id/name and return it with its whole subtree."""
    index = client.section_index(suite_id)
    if not index:
        raise TestRailError(
            f"Suite {suite_id} in project {client.config.project_id} has no sections."
        )
    root = resolve_section(index, wanted)   # raises on unknown/ambiguous names
    return SectionSubtree(root=root, sections=descendants(index, int(root["id"])))


# --------------------------------------------------------------------------- #
# Cases
# --------------------------------------------------------------------------- #

NUMBERED_ITEM = re.compile(
    r"^\s*(?:step\s+)?(?P<number>\d+)\s*[\.\):\-]\s*(?P<text>.*)$",
    re.IGNORECASE,
)


def parse_numbered(value: str, *, split_unnumbered: bool = True) -> list[tuple[int, str]]:
    """Split a Steps / Expected Results text into (number, text) items.

    The one parser for numbered prose, used for both CSV cells on the way in
    and TestRail fields on the way out.

    A line that is not numbered is a CONTINUATION of the item above it - most
    often a bullet under a numbered expected result - and is appended to that
    item rather than becoming an item of its own.

    When nothing is numbered at all, `split_unnumbered` decides the fallback:
    True gives one item per line (what a CSV cell means), False keeps the text
    as a single item (what a TestRail field means).
    """
    lines = [norm(line) for line in norm(value).splitlines() if norm(line)]
    items: list[tuple[int, list[str]]] = []   # (number, [line, ...])
    preamble: list[str] = []                  # unnumbered lines before item 1

    for line in lines:
        match = NUMBERED_ITEM.match(line)
        if match:
            items.append((int(match.group("number")), [norm(match.group("text"))]))
        elif items:
            items[-1][1].append(line)
        else:
            preamble.append(line)

    if not items:
        if split_unnumbered:
            return [(i, line) for i, line in enumerate(lines, start=1)]
        text = norm("\n".join(lines))
        return [(1, text)] if text else []

    if preamble:
        # Keep stray leading text with the first item so the numbering holds.
        items[0][1][:0] = preamble

    return [(number, norm("\n".join(parts))) for number, parts in items]


def pair_numbered(actions: str, expected: str, *,
                  split_unnumbered: bool = True) -> list[tuple[str, str]]:
    """Pair numbered actions with their numbered expected results.

    Matching is by item number, falling back to position when the numbers do
    not line up. An expected result that matches no action is kept as a pair
    with an empty action rather than silently dropped - malformed input should
    be visible in the report, not invisible.
    """
    step_items = parse_numbered(actions, split_unnumbered=split_unnumbered)
    expected_items = parse_numbered(expected, split_unnumbered=split_unnumbered)
    expected_by_number = dict(expected_items)

    pairs: list[tuple[str, str]] = []
    used: set[int] = set()
    for index, (number, text) in enumerate(step_items):
        if number in expected_by_number:
            used.add(number)
            pairs.append((text, expected_by_number[number]))
        elif index < len(expected_items):
            used.add(expected_items[index][0])
            pairs.append((text, expected_items[index][1]))
        else:
            pairs.append((text, ""))

    pairs += [("", text) for number, text in expected_items if number not in used]
    return pairs


def steps_of(case: dict, config: Config) -> list[tuple[str, str]]:
    """Return [(action, expected)] from either the separated or plain format."""
    separated = case.get(config.separated_steps_field)
    if isinstance(separated, list) and separated:
        return [
            (html_to_text(str(s.get("content") or "")),
             html_to_text(str(s.get("expected") or "")))
            for s in separated
        ]

    actions = html_to_text(str(case.get(config.steps_field) or ""))
    expected = html_to_text(str(case.get(config.expected_field) or ""))
    if not actions and not expected:
        return []
    # A TestRail field with no numbering is one block of prose, not one step
    # per line - hence split_unnumbered=False.
    return pair_numbered(actions, expected, split_unnumbered=False)


@dataclass
class CaseView:
    """A TestRail case flattened to plain text, ready to print or serialise.

    One definition of "what a case looks like as text", so the fetcher and the
    triager cannot disagree about field mapping or placeholder wording.
    """

    case_id: int
    title: str
    section: str
    priority: str
    type: str
    preconditions: str
    refs: str
    url: str = ""
    labels: list[str] = dc_field(default_factory=list)
    sub_test_suites: list[str] = dc_field(default_factory=list)
    steps: list[tuple[str, str]] = dc_field(default_factory=list)

    def step_lines(self) -> list[str]:
        """Numbered 'action -> expected' lines, with the standard placeholders."""
        lines: list[str] = []
        for i, (action, expected) in enumerate(self.steps, start=1):
            lines.append(f"{i}. {action or '(empty)'}")
            lines.append(f"   -> {expected or '(NO EXPECTED RESULT)'}")
        return lines

    def text_lines(self, *, include_section: bool = True) -> list[str]:
        """The case as plain text, the way every script prints it.

        `include_section` is off for callers that already group their output by
        section, where repeating the path on each case is just noise.
        """
        lines = [f"### C{self.case_id} | {self.title}"]
        if include_section:
            lines.append(f"Section: {self.section or '(none)'}")
        meta = f"Priority: {self.priority or '?'} | Type: {self.type or '?'}"
        if self.labels:
            meta += f" | Labels: {', '.join(self.labels)}"
        lines.append(meta)
        if self.sub_test_suites:
            lines.append(f"Sub Test Suite(s): {', '.join(self.sub_test_suites)}")
        if self.url:
            lines.append(f"TestRail: {self.url}")
        if self.refs:
            lines.append(f"Refs: {self.refs}")
        if self.preconditions:
            lines.append(f"Preconditions: {self.preconditions}")
        lines += self.step_lines() if self.steps else ["(NO STEPS)"]
        return lines

    def as_dict(self) -> dict:
        """JSON-friendly form."""
        return {
            "case_id": self.case_id,
            "title": self.title,
            "section": self.section,
            "priority": self.priority,
            "type": self.type,
            "preconditions": self.preconditions,
            "refs": self.refs,
            "url": self.url,
            "labels": list(self.labels),
            "sub_test_suites": list(self.sub_test_suites),
            "steps": [{"step": a, "expected": e} for a, e in self.steps],
        }


def case_url(config: Config, case_id: int) -> str:
    """The browser URL of a case - the form the XCUITest suite links to."""
    return f"{config.url}/index.php?/cases/view/{case_id}"


def sub_test_suites_of(case: dict, client: TestRailClient,
                       config: Config) -> list[str]:
    """The case's 'Sub Test Suite(s)' labels, resolved from option ids."""
    raw = case.get(config.sub_test_suite_field)
    if not isinstance(raw, list) or not raw:
        return []
    names = field_option_names(
        find_case_field(client.get_case_fields(), config.sub_test_suite_field)
    )
    resolved = []
    for value in raw:
        try:
            resolved.append(names.get(int(value), str(value)))
        except (TypeError, ValueError):
            resolved.append(str(value))
    return resolved


def case_view(case: dict, client: TestRailClient, config: Config,
              suite_id: int) -> CaseView:
    """Flatten a raw TestRail case into its plain-text view."""
    section = client.section_index(suite_id).get(
        int(case.get("section_id") or 0)
    ) or {}
    return CaseView(
        case_id=int(case["id"]),
        title=html_to_text(str(case.get("title") or "")),
        section=str(section.get("path") or section.get("name") or ""),
        priority=client.priority_names().get(case.get("priority_id"), ""),
        type=client.type_names().get(case.get("type_id"), ""),
        preconditions=html_to_text(str(case.get(config.preconditions_field) or "")),
        refs=norm(str(case.get(config.references_field) or "")),
        url=case_url(config, int(case["id"])),
        labels=[label_title(x) for x in (case.get("labels") or [])],
        sub_test_suites=sub_test_suites_of(case, client, config),
        steps=steps_of(case, config),
    )


# --------------------------------------------------------------------------- #
# Custom fields
# --------------------------------------------------------------------------- #

def by_name(values: list[dict]) -> dict[str, dict]:
    return {key(str(v.get("name", ""))): v for v in values if v.get("name")}


def map_id(value: str, available: dict[str, dict], default_id: int | None,
           aliases: dict[str, str] | None = None) -> int:
    """Map a display name to its TestRail id, honouring aliases and a default."""
    lookup = key(value)
    if aliases and lookup in aliases:
        lookup = aliases[lookup]
    match = available.get(lookup)
    if match is not None:
        return int(match["id"])
    if default_id is not None:
        return default_id
    raise TestRailError(
        f"'{value}' is not a valid TestRail value. Available: {sorted(available)}"
    )


def field_items(field: dict | None) -> list[tuple[int, str]]:
    """The (option id, display name) pairs of a dropdown/multi-select field.

    TestRail returns them as an "items" string like
    "9, Special Case\n10, Regression". Parsed in one place so the id->name and
    name->id views below cannot disagree about what counts as an option.
    """
    pairs: list[tuple[int, str]] = []
    if not field:
        return pairs
    for cfg in field.get("configs", []):
        items = ((cfg.get("options") or {}).get("items") or "")
        for line in items.splitlines():
            raw_id, _, raw_name = line.strip().partition(",")
            if raw_id.strip().isdigit() and raw_name.strip():
                pairs.append((int(raw_id.strip()), raw_name.strip()))
    return pairs


def field_options(field: dict | None) -> dict[str, int]:
    """label_key -> option id, for mapping an authored label onto TestRail."""
    return {key(name): option_id for option_id, name in field_items(field)}


def field_option_names(field: dict | None) -> dict[int, str]:
    """option id -> display name, for rendering a stored value back to a label."""
    return dict(field_items(field))


def find_case_field(case_fields: list[dict], wanted: str) -> dict | None:
    """Locate a case field by system_name, falling back to its display label."""
    match = next(
        (f for f in case_fields if str(f.get("system_name", "")).strip() == wanted), None
    )
    if match is None:
        match = next(
            (f for f in case_fields if key(str(f.get("label", ""))) == key(wanted)), None
        )
    return match


def field_applies_to_project(field: dict, project_id: int) -> bool:
    """True when the field is global or explicitly scoped to this project."""
    configs = field.get("configs") or []
    if not configs:
        return True
    for entry in configs:
        context = entry.get("context") or {}
        if context.get("is_global"):
            return True
        ids = context.get("project_ids")
        if not ids:
            return True
        if project_id in {int(pid) for pid in ids}:
            return True
    return False


# --------------------------------------------------------------------------- #
# Automation status
# --------------------------------------------------------------------------- #

@dataclass
class AutomationField:
    """A resolved Automation status field: system name plus its option ids.

    Every id comes from TestRail metadata, so a project that renamed the field
    or renumbered its options still works without a code change.
    """

    system_name: str
    label: str
    name_to_id: dict[str, int]
    id_to_name: dict[int, str]

    def id_for(self, status_name: str) -> int:
        option_id = self.name_to_id.get(key(status_name))
        if option_id is None:
            raise TestRailError(
                f"Automation status '{status_name}' is not an option of "
                f"'{self.system_name}'. Available: {sorted(self.name_to_id)}"
            )
        return option_id

    def name_for(self, option_id: Any) -> str | None:
        if option_id is None:
            return None
        try:
            return self.id_to_name.get(int(option_id))
        except (TypeError, ValueError):
            return None

    def status_of(self, case: dict) -> str | None:
        """The case's current automation status name, or None when unset."""
        return self.name_for(case.get(self.system_name))

    def has_status(self, case: dict, status_name: str) -> bool:
        current = self.status_of(case)
        return current is not None and key(current) == key(status_name)


def resolve_automation_field(case_fields: list[dict], project_id: int,
                             field_name: str,
                             required_statuses: tuple[str, ...] = ()) -> AutomationField:
    """Resolve the Automation status field and its option ids from metadata.

    `required_statuses` names the options the caller depends on; a project
    missing one fails here rather than halfway through a batch.
    """
    match = find_case_field(case_fields, field_name)
    if match is None:
        available = sorted(
            str(f.get("system_name", ""))
            for f in case_fields
            if "autom" in f"{f.get('system_name','')}{f.get('label','')}".lower()
        )
        raise TestRailError(
            f"Automation status field '{field_name}' does not exist in this "
            f"TestRail instance. Automation-like fields available: "
            f"{available or 'none'}. Set TESTRAIL_AUTOMATION_STATUS_FIELD to the "
            "correct system name."
        )

    system_name = str(match.get("system_name") or field_name)
    if not field_applies_to_project(match, project_id):
        raise TestRailError(
            f"Field '{system_name}' is not enabled for project {project_id}. "
            "Check the field's project configuration in TestRail."
        )

    name_to_id = field_options(match)
    if not name_to_id:
        raise TestRailError(
            f"Field '{system_name}' has no selectable options in its TestRail "
            "configuration, so its statuses cannot be resolved."
        )

    missing = [s for s in required_statuses if key(s) not in name_to_id]
    if missing:
        raise TestRailError(
            f"Field '{system_name}' is missing required option(s): "
            f"{', '.join(missing)}. Found: {sorted(name_to_id)}"
        )

    return AutomationField(
        system_name=system_name,
        label=str(match.get("label") or system_name),
        name_to_id=name_to_id,
        id_to_name=field_option_names(match),
    )


# --------------------------------------------------------------------------- #
# Labels
# --------------------------------------------------------------------------- #

def label_title(label: dict) -> str:
    """A label's display text, tolerating both response shapes TestRail uses.

    get_labels returns {"id", "name"}; a case's own labels return {"id", "title"}.
    """
    return str(label.get("title") or label.get("name") or "").strip()


def build_automation_update(case: dict, automation: AutomationField,
                            target_status: str) -> tuple[dict, str]:
    """Build the minimal update payload for one case.

    Returns (payload, status_change). The payload carries the automation status
    and nothing else - never a label, never any other field. An empty payload
    means the case is already in the target state and no request is needed.
    """
    current_id = case.get(automation.system_name)
    target_id = automation.id_for(target_status)
    if current_id == target_id:
        return {}, ""
    return (
        {automation.system_name: target_id},
        f"{automation.name_for(current_id) or 'unset'} -> {target_status}",
    )

# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #

def md_cell(value) -> str:
    """Make a value safe for one cell of a markdown table.

    `is None` rather than falsy: a count of 0 is a value worth printing.
    """
    text = "" if value is None else str(value)
    return norm(text).replace("|", "\\|").replace("\n", " ")


def md_table(headers: list[str], rows: list[list], aligns: str = "") -> list[str]:
    """A markdown table. `aligns` is one character per column: 'l', 'r' or 'c'.

    Used by every report, so column syntax is written once rather than
    hand-assembled per script.
    """
    marks = {"l": "---", "r": "---:", "c": ":---:"}
    spec = [marks.get(aligns[i] if i < len(aligns) else "l", "---")
            for i in range(len(headers))]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(spec) + "|"]
    lines += ["| " + " | ".join(md_cell(c) for c in row) + " |" for row in rows]
    return lines


def md_fields(pairs: list[tuple[str, object]]) -> list[str]:
    """The '- Label: value' header block every report opens with.

    A pair with no value is dropped rather than printed as a dangling label.
    """
    return [f"- {label}: {value}" for label, value in pairs
            if value is not None and str(value) != ""]


def write_report(path: Path, lines: list[str]) -> Path:
    """Write a markdown report, creating its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def run_cli(command, *args) -> int:
    """Run a script's entry point, turning a TestRailError into exit code 1.

    Every script fails the same way: one 'Error: ...' line on stderr, no
    traceback, no partial success reported as success.
    """
    try:
        return command(*args)
    except TestRailError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
