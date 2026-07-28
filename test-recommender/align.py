#!/usr/bin/env python3
"""
Firefox iOS Test Recommender — mapping curation tool.

Interactive counterpart to `recommend.py`. Where `recommend.py` runs per
release and surfaces mapping drift as a warning at the top of the report,
`align.py` runs on demand and helps the QA lead curate the mapping YAML.

Pipeline:

    INPUT: testrail_export.xlsx, mapping.yaml, firefox-ios clone
      │
      ├─ 1. Drift detection
      │     · TestRail sections in export but not in YAML  → new_section
      │     · YAML sections not in TestRail export         → stale_section
      │     · Repo modules under known parent dirs but not
      │       referenced anywhere in YAML                   → new_module
      │
      ├─ 2. LLM proposals (Anthropic API):
      │     · For each new_section: propose module paths using the section
      │       name, five sample test titles, and the current list of code
      │       modules discovered from the local clone.
      │     · For each new_module: propose which existing TestRail section
      │       it should be attached to (or route to
      │       modules_without_clear_section).
      │
      ├─ 3. Interactive review (CLI):
      │       [a]ccept   [e]dit   [r]eject   [s]kip
      │
      └─ OUTPUT:
          · section_to_module_mapping.yaml   (updated in place, .bak backup)
          · pending_mapping_review.yaml       (rejected proposals — inbox
                                               for the next curator session)

The script never modifies the YAML without user confirmation on each
proposal. If ANTHROPIC_API_KEY is unset or the SDK is missing, the LLM
proposals stage is skipped and each drift finding becomes a manual entry
that the user fills in via the [e]dit path.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

# Reuse loaders + drift primitives from recommend.py to keep behaviour aligned.
from recommend import (
    TestCase,
    load_testrail,
    known_modules_from_mapping,
)

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


LLM_MODEL = os.environ.get("ALIGN_MODEL", "claude-sonnet-4-6")


# =============================================================================
# Repo module discovery
# =============================================================================
#
# Directories we consider "module roots" — a child directory here is a
# module candidate. These mirror the parents used by recommend.detect_drift.

_MODULE_PARENTS = (
    "BrowserKit/Sources",
    "firefox-ios/Client/Frontend",
    "firefox-ios/Client",
    "firefox-ios",
)

_MODULE_NOISE = {
    "Tests", "firefox-ios-tests", "firefox-iosTests", "firefox-iosUITests",
    "focus-ios", "focus-iosTests", "Client.xcodeproj", "Client.xcworkspace",
    "Assets.xcassets", "en-US.lproj", "Base.lproj",
    # firefox-ios/-level noise: non-code directories that pollute drift
    "Documentation", "docs", "scripts", "content-blocker-lib-ios",
    "l10n-screenshots-desc", "test-fixtures", "focus-iosUITests",
    # Build tooling / third-party / auto-generated: not product code and
    # therefore have no TestRail mapping by design. Filtered out entirely
    # rather than routed through `modules_without_clear_section`.
    "fastlane", "ThirdParty", "Generated",
    # Build-time codegen tools (produce content-blocker rulesets etc.).
    "ContentBlockingGenerator", "ExecutableContentBlockingGenerator",
}


def _contains_swift_recursive(root: Path, max_depth: int = 3) -> bool:
    """Return True if `root` has any `.swift` file within `max_depth` levels.

    Used to skip container directories that are technically subdirectories
    of a module parent but hold no Swift code (Documentation/, scripts/,
    l10n/, etc.). Depth-bounded to keep the walk cheap on huge trees."""
    def _walk(p: Path, depth: int) -> bool:
        try:
            for entry in p.iterdir():
                if entry.is_file() and entry.suffix == ".swift":
                    return True
                if entry.is_dir() and depth > 0 and not entry.name.startswith("."):
                    if _walk(entry, depth - 1):
                        return True
        except (PermissionError, OSError):
            return False
        return False
    return _walk(root, max_depth)


def discover_repo_modules(repo_root: Path) -> list[str]:
    """Enumerate module-shaped directories under a local firefox-ios clone.

    Returns paths relative to the repo root, matching the shape used inside
    the mapping YAML (e.g. `BrowserKit/Sources/ToolbarKit`,
    `firefox-ios/Client/Frontend/Home`).

    Two filters keep the output tight:
      1. Container directories that themselves house modules (e.g.
         `firefox-ios` holds `Client` which holds `Frontend`) are pruned —
         we only surface the leaf-module tier configured in `_MODULE_PARENTS`.
      2. A directory qualifies as a module only if it contains at least
         one `.swift` file within 3 levels. This filters out
         Documentation/, scripts/, config-only, and localization dirs.
    """
    # Any parent-of-a-parent is a container, not a module — e.g. we scan
    # both `firefox-ios/` and `firefox-ios/Client/`, so `Client` itself
    # should not surface as a module when scanning `firefox-ios/`.
    container_names = set()
    for p in _MODULE_PARENTS:
        for other in _MODULE_PARENTS:
            if other != p and other.startswith(p.rstrip("/") + "/"):
                head = other[len(p.rstrip("/")) + 1:].split("/", 1)[0]
                container_names.add((p, head))

    modules: set[str] = set()
    for parent in _MODULE_PARENTS:
        base = repo_root / parent
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if name.startswith(".") or name in _MODULE_NOISE:
                continue
            if name.endswith(".xcodeproj") or name.endswith(".xcworkspace"):
                continue
            if (parent, name) in container_names:
                continue
            if not _contains_swift_recursive(child):
                continue
            modules.add(f"{parent}/{name}")
    return sorted(modules)


# =============================================================================
# Drift detection
# =============================================================================


@dataclass
class NewSectionFinding:
    name: str
    test_count: int
    automated_count: int
    sample_titles: list[str]


@dataclass
class StaleSectionFinding:
    name: str


@dataclass
class NewModuleFinding:
    path: str


@dataclass
class DriftReport:
    new_sections: list[NewSectionFinding] = field(default_factory=list)
    stale_sections: list[StaleSectionFinding] = field(default_factory=list)
    new_modules: list[NewModuleFinding] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.new_sections or self.stale_sections or self.new_modules)


def detect_drift(tests: list[TestCase], mapping: dict, repo_modules: list[str]) -> DriftReport:
    yaml_sections = {s["name"] for s in mapping.get("sections", [])}

    # TestRail-side drift
    export_sections = {tc.section_top for tc in tests if tc.section_top}
    new_names = sorted(export_sections - yaml_sections)
    stale_names = sorted(yaml_sections - export_sections)

    new_sections = []
    for name in new_names:
        in_section = [tc for tc in tests if tc.section_top == name]
        automated = sum(1 for tc in in_section if tc.automation == "Completed")
        titles = [tc.title for tc in in_section[:5]]
        new_sections.append(NewSectionFinding(
            name=name,
            test_count=len(in_section),
            automated_count=automated,
            sample_titles=titles,
        ))

    # Repo-side drift: modules discovered on disk but never referenced in the
    # YAML (neither under `sections:` nor `modules_without_clear_section`).
    known = set(known_modules_from_mapping(mapping))
    new_modules: list[NewModuleFinding] = []
    for m in repo_modules:
        if m in known:
            continue
        # Skip if a *parent* path is already declared with the same prefix
        # — the parent covers this child by longest-prefix match at
        # recommend-time, so the child is not a fresh mapping gap.
        if any(m.startswith(k.rstrip("/") + "/") for k in known):
            continue
        new_modules.append(NewModuleFinding(path=m))

    return DriftReport(
        new_sections=new_sections,
        stale_sections=[StaleSectionFinding(name=n) for n in stale_names],
        new_modules=new_modules,
    )


# =============================================================================
# LLM proposal
# =============================================================================


SYSTEM_PROMPT = """You are a mapping-curation assistant for the Firefox iOS test recommender. Given a TestRail section (or a code module) that is not yet mapped, propose the best-fit counterpart(s) from a fixed list.

Rules:
  - Only pick paths from the provided `known_modules` list. Never invent paths.
  - Confidence: "high" only when the section name or sample titles clearly map to one module; "medium" for reasonable inference; "low" for a guess.
  - For a section, ALWAYS propose at least one module (1-3, rarely more). If no strong match exists, pick the closest fit with "low" confidence and explain in `rationale`. Never return an empty list — the user can override, but you must make an initial pick.
  - For a module without a clear TestRail section, either pick one section from `known_sections` or set `route: "modules_without_clear_section"` if the module is cross-cutting (Redux, Common, Shared, telemetry, etc.).
  - Every proposal MUST include a one-sentence `rationale` explaining why.
"""


SECTION_PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "modules": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["path", "confidence"],
                "additionalProperties": False,
            },
        },
        "rationale": {"type": "string"},
    },
    "required": ["modules", "rationale"],
    "additionalProperties": False,
}


MODULE_PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": ["section", "modules_without_clear_section"]},
        "section_name": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "rationale": {"type": "string"},
    },
    "required": ["route", "confidence", "rationale"],
    "additionalProperties": False,
}


def _llm_available() -> bool:
    return _ANTHROPIC_AVAILABLE and bool(os.environ.get("ANTHROPIC_API_KEY"))


def _llm_call(user_payload: dict, schema: dict) -> Optional[dict]:
    """Single-shot LLM call returning a parsed JSON object, or None on failure."""
    if not _llm_available():
        return None
    client = anthropic.Anthropic(max_retries=6)
    user_text = (
        "Propose the best-fit mapping. Follow the schema.\n\n"
        f"```json\n{json.dumps(user_payload, separators=(',', ':'))}\n```"
    )
    kwargs: dict = {
        "model": LLM_MODEL,
        "max_tokens": 800,
        "thinking": {"type": "disabled"},
        "output_config": {
            "format": {"type": "json_schema", "schema": schema},
            "effort": "low",
        },
        "system": [{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        "messages": [{"role": "user", "content": user_text}],
    }
    if "sonnet-5" not in LLM_MODEL.lower() and "opus-4-8" not in LLM_MODEL.lower():
        kwargs["temperature"] = 0

    try:
        response = client.messages.create(**kwargs)
    except Exception as e:
        sys.stderr.write(f"[align] LLM call failed: {e}\n")
        return None

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[align] LLM returned non-JSON: {e}\n")
        return None


def propose_section_mapping(finding: NewSectionFinding, known_modules: list[str]) -> Optional[dict]:
    payload = {
        "task": "map_testrail_section_to_code_modules",
        "section": {
            "name": finding.name,
            "test_count": finding.test_count,
            "automated_count": finding.automated_count,
            "sample_titles": finding.sample_titles,
        },
        "known_modules": known_modules,
    }
    return _llm_call(payload, SECTION_PROPOSAL_SCHEMA)


def propose_module_mapping(finding: NewModuleFinding, known_sections: list[str]) -> Optional[dict]:
    payload = {
        "task": "map_code_module_to_testrail_section",
        "module": {"path": finding.path},
        "known_sections": known_sections,
    }
    return _llm_call(payload, MODULE_PROPOSAL_SCHEMA)


# =============================================================================
# Interactive CLI
# =============================================================================


class _AlignAborted(SystemExit):
    """Raised when stdin runs dry mid-session — treated as an operator abort."""


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        print()
        print("stdin closed — aborting align session (no partial writes).")
        raise _AlignAborted(3)


def _prompt_choice(msg: str, choices: str = "aers") -> str:
    """Prompt until the user types one of the allowed single letters.

    Bounded retry loop: after 5 invalid responses we bail out with an
    error rather than spin forever (e.g. when stdin feeds a runaway or
    malformed batch)."""
    for _ in range(5):
        raw = _prompt(msg).lower()
        if raw and raw[0] in choices:
            return raw[0]
        print(f"  please answer one of: {', '.join(choices)}")
    print("too many invalid responses — aborting align session.")
    raise _AlignAborted(3)


def review_section_proposal(finding: NewSectionFinding, proposal: Optional[dict], known_modules: list[str]) -> dict:
    """Return a decision dict: {'action': 'accept'|'reject'|'skip', ...payload...}."""
    print()
    print(f"━━━ New TestRail section: {finding.name!r}")
    print(f"    tests: {finding.test_count} ({finding.automated_count} automated)")
    if finding.sample_titles:
        print(f"    sample titles:")
        for t in finding.sample_titles:
            print(f"      · {t}")
    proposed_modules = list(proposal.get("modules", [])) if proposal else []
    if proposal:
        print(f"    LLM proposal ({proposal.get('rationale', '').strip()}):")
        if proposed_modules:
            for m in proposed_modules:
                print(f"      → {m['path']}  [confidence: {m['confidence']}]")
        else:
            print("      (LLM declined to pick a module — use [e]dit or [r]eject)")
    else:
        print("    (no LLM proposal — will be entered manually if accepted)")

    while True:
        choice = _prompt_choice("    [a]ccept  [e]dit  [r]eject  [s]kip ? ")
        if choice == "a":
            if not proposed_modules:
                print("    nothing to accept — the proposal has no modules. Try [e]dit or [r]eject.")
                continue
            return {"action": "accept", "modules": proposed_modules}
        if choice == "e":
            modules = _edit_module_list(proposed_modules, known_modules)
            if not modules:
                print("    no modules entered — treating as skip")
                return {"action": "skip"}
            return {"action": "accept", "modules": modules}
        if choice == "r":
            return {"action": "reject", "proposal": proposal or {}}
        return {"action": "skip"}


def review_module_proposal(finding: NewModuleFinding, proposal: Optional[dict], known_sections: list[str]) -> dict:
    print()
    print(f"━━━ New/unmapped repo module: {finding.path}")
    if proposal:
        route = proposal.get("route")
        conf = proposal.get("confidence", "?")
        rat = proposal.get("rationale", "").strip()
        if route == "section":
            print(f"    LLM proposal: attach to section {proposal.get('section_name')!r} [confidence: {conf}]")
        else:
            print(f"    LLM proposal: route to modules_without_clear_section [confidence: {conf}]")
        print(f"    rationale: {rat}")
    else:
        print("    (no LLM proposal — will be entered manually if accepted)")

    while True:
        choice = _prompt_choice("    [a]ccept  [e]dit  [r]eject  [s]kip ? ")
        if choice == "a":
            if not proposal:
                print("    nothing to accept — the LLM did not produce a proposal. Try [e]dit or [r]eject.")
                continue
            return {"action": "accept", **proposal}
        if choice == "e":
            return _edit_module_routing(proposal or {}, known_sections)
        if choice == "r":
            return {"action": "reject", "proposal": proposal or {}}
        return {"action": "skip"}


def _edit_module_list(initial: list[dict], known_modules: list[str]) -> list[dict]:
    """Let the user override the LLM's proposed module list.

    Input format on stdin: `path[:confidence], path[:confidence], ...`
    Confidence defaults to `medium` when omitted."""
    hint = ", ".join(f"{m['path']}:{m['confidence']}" for m in initial) or "<empty>"
    print(f"    current: {hint}")
    raw = _prompt("    new modules (comma-separated `path[:confidence]`, blank keeps current): ")
    if not raw:
        return list(initial)
    known = set(known_modules)
    out: list[dict] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            path, conf = chunk.rsplit(":", 1)
            path, conf = path.strip(), conf.strip().lower()
        else:
            path, conf = chunk, "medium"
        if conf not in ("high", "medium", "low"):
            conf = "medium"
        if path and path not in known:
            print(f"    warning: {path} not in known module list — keeping anyway")
        out.append({"path": path, "confidence": conf})
    return out


def _edit_module_routing(initial: dict, known_sections: list[str]) -> dict:
    """Let the user override the LLM's section routing for a new repo module."""
    print("    known sections (first 20):")
    for s in known_sections[:20]:
        print(f"      · {s}")
    raw = _prompt("    section name (blank → modules_without_clear_section): ")
    if not raw:
        return {"action": "accept", "route": "modules_without_clear_section",
                "confidence": "medium", "rationale": "manual: cross-cutting"}
    return {"action": "accept", "route": "section", "section_name": raw,
            "confidence": "medium", "rationale": "manual"}


# =============================================================================
# YAML round-trip writer
# =============================================================================


def _make_yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def load_mapping_roundtrip(path: Path):
    with path.open() as f:
        return _make_yaml().load(f)


def save_mapping_roundtrip(mapping, path: Path) -> None:
    with path.open("w") as f:
        _make_yaml().dump(mapping, f)


def _flow_module_entry(path: str, confidence: str) -> CommentedMap:
    """Build a `{ path: ..., confidence: ... }` mapping in inline flow style,
    matching the existing YAML convention."""
    cm = CommentedMap()
    cm["path"] = path
    cm["confidence"] = confidence
    cm.fa.set_flow_style()
    return cm


def append_section(mapping, name: str, test_count: int, automated_count: int, modules: list[dict], stamp_comment: Optional[str] = None) -> None:
    """Append a new section to the `sections:` list.

    `stamp_comment` (if provided) is attached as an end-of-line comment on
    the `name` field of the new entry — a per-entry stamp such as
    `added 2026-07-27 by align.py`. We deliberately avoid block-level
    "before" comments on the list because ruamel.yaml stores those against
    the following top-level key (here `modules_without_clear_section`),
    which reorders visually when the previous list grows.

    Known cosmetic caveat: the file's original block comment above
    `modules_without_clear_section:` remains attached to that key. When
    the `sections:` list grows, the block comment ends up visually
    *between* the last section entries — it still parses fine, but a human
    editor may want to move it back down after a big align run."""
    sections = mapping.get("sections")
    if sections is None:
        raise RuntimeError("mapping has no `sections:` block — cannot append")

    entry = CommentedMap()
    entry["name"] = name
    entry["test_count"] = test_count
    entry["automated"] = automated_count
    mod_seq = CommentedSeq()
    for m in modules:
        mod_seq.append(_flow_module_entry(m["path"], m["confidence"]))
    entry["modules"] = mod_seq

    sections.append(entry)
    if stamp_comment:
        entry.yaml_add_eol_comment(stamp_comment, key="name")


def append_module_without_section(mapping, path: str, tag_comment: Optional[str] = None) -> None:
    key = "modules_without_clear_section"
    seq = mapping.get(key)
    if seq is None:
        seq = CommentedSeq()
        mapping[key] = seq
    idx = len(seq)
    seq.append(path)
    if tag_comment:
        seq.yaml_add_eol_comment(tag_comment, key=idx)


def add_module_to_section(mapping, section_name: str, path: str, confidence: str = "medium") -> bool:
    """Find `section_name` in mapping.sections and append a module entry. Returns True if inserted."""
    for s in mapping.get("sections", []):
        if s.get("name") == section_name:
            mods = s.get("modules")
            if mods is None:
                mods = CommentedSeq()
                s["modules"] = mods
            # Skip duplicates
            for existing in mods:
                if existing.get("path") == path:
                    return False
            mods.append(_flow_module_entry(path, confidence))
            return True
    return False


# =============================================================================
# pending_mapping_review.yaml writer
# =============================================================================


def write_pending(path: Path, entries: list[dict]) -> None:
    if not entries:
        return
    payload = {
        "generated_by": "align.py",
        "generated_at": datetime.date.today().isoformat(),
        "entries": entries,
    }
    y = _make_yaml()
    with path.open("w") as f:
        y.dump(payload, f)


# =============================================================================
# Orchestration
# =============================================================================


def _resolve_stale_section(finding: StaleSectionFinding) -> str:
    """Ask the user what to do with a YAML section that's no longer in the export.

    We don't rename automatically — rename detection is deferred (see README
    roadmap). Options are limited to: keep, remove, or route to pending."""
    print()
    print(f"━━━ Stale YAML section (not in latest TestRail export): {finding.name!r}")
    print("    [k]eep (assume TestRail export is incomplete)")
    print("    [r]emove from YAML")
    print("    [p]end (route to pending_mapping_review.yaml for later)")
    print("    [s]kip")
    return _prompt_choice("    ? ", choices="krps")


def remove_section(mapping, name: str) -> bool:
    sections = mapping.get("sections", [])
    for i, s in enumerate(sections):
        if s.get("name") == name:
            del sections[i]
            return True
    return False


def _report_only_run(drift: DriftReport, pending_path: Path, known_modules: list[str], known_sections: list[str], use_llm: bool) -> int:
    """Non-interactive CI mode: fetch LLM proposals (if enabled), dump every
    drift finding into pending_mapping_review.yaml, and exit with a non-zero
    code so CI can gate on \"drift detected\"."""
    entries: list[dict] = []

    total = len(drift.new_sections)
    for i, finding in enumerate(drift.new_sections, start=1):
        proposal = propose_section_mapping(finding, known_modules) if use_llm else None
        print(f"[align] section {i}/{total} — {finding.name}", file=sys.stderr)
        entries.append({
            "kind": "new_section",
            "name": finding.name,
            "test_count": finding.test_count,
            "automated_count": finding.automated_count,
            "sample_titles": finding.sample_titles,
            "proposal": proposal or {},
        })

    for finding in drift.stale_sections:
        entries.append({
            "kind": "stale_section",
            "name": finding.name,
            "detail": "section in YAML not present in latest TestRail export",
        })

    total = len(drift.new_modules)
    for i, finding in enumerate(drift.new_modules, start=1):
        proposal = propose_module_mapping(finding, known_sections) if use_llm else None
        print(f"[align] module {i}/{total} — {finding.path}", file=sys.stderr)
        entries.append({
            "kind": "new_module",
            "path": finding.path,
            "proposal": proposal or {},
        })

    write_pending(pending_path, entries)
    print(f"✓ wrote {pending_path} with {len(entries)} entries")
    print(f"  drift summary: {len(drift.new_sections)} new sections, "
          f"{len(drift.stale_sections)} stale sections, "
          f"{len(drift.new_modules)} new modules")
    # Exit non-zero so CI can gate on \"drift detected\".
    return 1


def orchestrate(
    testrail_path: Path,
    mapping_path: Path,
    repo_path: Path,
    pending_path: Path,
    dry_run: bool,
    verbose: bool,
    report_only: bool = False,
    no_llm: bool = False,
) -> int:
    def vlog(msg: str) -> None:
        if verbose:
            print(f"[align] {msg}", file=sys.stderr)

    vlog("loading TestRail export …")
    tests = load_testrail(testrail_path)

    vlog("loading mapping YAML (round-trip) …")
    mapping = load_mapping_roundtrip(mapping_path)

    vlog("discovering repo modules …")
    repo_modules = discover_repo_modules(repo_path)
    vlog(f"  found {len(repo_modules)} candidate modules")

    vlog("detecting drift …")
    drift = detect_drift(tests, mapping, repo_modules)
    vlog(f"  new sections: {len(drift.new_sections)}  "
         f"stale sections: {len(drift.stale_sections)}  "
         f"new modules: {len(drift.new_modules)}")

    if drift.empty:
        print("No drift detected — mapping is in sync with TestRail and the repo.")
        return 0

    use_llm = _llm_available() and not no_llm
    if not use_llm:
        sys.stderr.write(
            "[align] LLM proposals disabled "
            f"({'--no-llm' if no_llm else 'ANTHROPIC_API_KEY not set / SDK missing'}). "
            "Interactive mode falls back to manual [e]dit; report-only skips proposals.\n"
        )

    known_modules = sorted(set(known_modules_from_mapping(mapping)) | set(repo_modules))
    known_sections = sorted({s["name"] for s in mapping.get("sections", [])})

    if report_only:
        return _report_only_run(drift, pending_path, known_modules, known_sections, use_llm)

    pending_entries: list[dict] = []
    mutated = False

    # -------- new sections --------
    date_stamp = datetime.date.today().isoformat()
    stamp = f"added {date_stamp} by align.py"

    total = len(drift.new_sections)
    for i, finding in enumerate(drift.new_sections, start=1):
        if use_llm:
            print(f"[align] fetching LLM proposal — section {i}/{total} ({finding.name}) …", file=sys.stderr)
        proposal = propose_section_mapping(finding, known_modules) if use_llm else None
        decision = review_section_proposal(finding, proposal, known_modules)
        if decision["action"] == "accept":
            append_section(
                mapping,
                name=finding.name,
                test_count=finding.test_count,
                automated_count=finding.automated_count,
                modules=decision["modules"],
                stamp_comment=stamp,
            )
            mutated = True
            print(f"    ✓ accepted — will write {finding.name!r} with {len(decision['modules'])} module(s)")
        elif decision["action"] == "reject":
            pending_entries.append({
                "kind": "new_section",
                "name": finding.name,
                "test_count": finding.test_count,
                "sample_titles": finding.sample_titles,
                "proposal": decision.get("proposal", {}),
            })
            print("    ✗ rejected — routed to pending review file")
        else:
            print("    · skipped")

    # -------- stale sections --------
    for finding in drift.stale_sections:
        choice = _resolve_stale_section(finding)
        if choice == "r":
            if remove_section(mapping, finding.name):
                mutated = True
                print(f"    ✓ removed {finding.name!r} from YAML")
            else:
                print("    (nothing to remove)")
        elif choice == "p":
            pending_entries.append({
                "kind": "stale_section",
                "name": finding.name,
                "detail": "section in YAML not present in latest TestRail export",
            })
            print("    ✗ routed to pending review file")
        elif choice == "k":
            print("    · kept as-is")
        else:
            print("    · skipped")

    # -------- new modules --------
    total = len(drift.new_modules)
    for i, finding in enumerate(drift.new_modules, start=1):
        if use_llm:
            print(f"[align] fetching LLM proposal — module {i}/{total} ({finding.path}) …", file=sys.stderr)
        proposal = propose_module_mapping(finding, known_sections) if use_llm else None
        decision = review_module_proposal(finding, proposal, known_sections)
        if decision["action"] == "accept":
            route = decision.get("route")
            if route == "section":
                target = decision.get("section_name", "")
                conf = decision.get("confidence", "medium")
                if add_module_to_section(mapping, target, finding.path, confidence=conf):
                    mutated = True
                    print(f"    ✓ attached to section {target!r}")
                else:
                    print(f"    ! could not attach to {target!r} (section not found or duplicate)")
                    pending_entries.append({
                        "kind": "new_module",
                        "path": finding.path,
                        "detail": f"target section {target!r} not found or duplicate — needs manual placement",
                    })
            else:
                append_module_without_section(mapping, finding.path,
                                              tag_comment=f"AUTO-ADDED {date_stamp} (align): {decision.get('rationale', '').strip()[:80]}")
                mutated = True
                print("    ✓ added under modules_without_clear_section")
        elif decision["action"] == "reject":
            pending_entries.append({
                "kind": "new_module",
                "path": finding.path,
                "proposal": decision.get("proposal", {}),
            })
            print("    ✗ rejected — routed to pending review file")
        else:
            print("    · skipped")

    # -------- write --------
    if mutated and not dry_run:
        backup = mapping_path.with_suffix(mapping_path.suffix + ".bak")
        shutil.copy2(mapping_path, backup)
        save_mapping_roundtrip(mapping, mapping_path)
        print(f"\n✓ wrote {mapping_path} (backup at {backup.name})")
    elif mutated and dry_run:
        print("\n(dry-run) mapping YAML changes NOT written to disk")
    else:
        print("\nno accepted changes — mapping YAML untouched")

    if pending_entries:
        write_pending(pending_path, pending_entries)
        print(f"✓ wrote {pending_path} with {len(pending_entries)} entr{'y' if len(pending_entries) == 1 else 'ies'} for later review")

    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Firefox iOS Test Recommender — mapping curation")
    p.add_argument("--testrail", required=True, type=Path, help="Path to TestRail export .xlsx")
    p.add_argument("--mapping", required=True, type=Path, help="Path to section_to_module_mapping.yaml")
    p.add_argument("--repo", required=True, type=Path, help="Path to a local firefox-ios clone (used to enumerate modules)")
    p.add_argument("--pending", type=Path, default=Path("pending_mapping_review.yaml"),
                   help="Output path for rejected proposals (default: ./pending_mapping_review.yaml)")
    p.add_argument("--dry-run", action="store_true", help="Compute drift and prompt as usual, but do not write the mapping YAML")
    p.add_argument("--report-only", action="store_true",
                   help="Non-interactive: write every drift finding + LLM proposal to --pending and exit "
                        "with code 1 if drift was found. Meant for CI. Never mutates the mapping YAML.")
    p.add_argument("--no-llm", action="store_true",
                   help="Skip LLM proposal calls entirely. Useful for fast offline runs — "
                        "in interactive mode each finding drops straight to [e]dit; in --report-only "
                        "mode the pending file lists findings with empty proposals.")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    for label, path in (("--testrail", args.testrail), ("--mapping", args.mapping), ("--repo", args.repo)):
        if not path.exists():
            sys.stderr.write(f"error: {label} path does not exist: {path}\n")
            sys.exit(2)

    sys.exit(orchestrate(
        testrail_path=args.testrail,
        mapping_path=args.mapping,
        repo_path=args.repo,
        pending_path=args.pending,
        dry_run=args.dry_run,
        verbose=args.verbose,
        report_only=args.report_only,
        no_llm=args.no_llm,
    ))


if __name__ == "__main__":
    main()
