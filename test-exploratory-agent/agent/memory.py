"""
agent/memory.py

Persistent memory between sessions stored as a simple JSON file.

Two responsibilities:
1. At session END   — extract semantic insights via a cheap Haiku call (no images)
2. At session START — inject relevant context into the agent's prompt
"""

import difflib
import json
import os
import tempfile
from datetime import datetime

MEMORY_FILE = os.path.join("reports", "agent_memory.json")


# ── Tool-error filter ──────────────────────────────────────────────────────────
#
# Before the SYSTEM_PROMPT rule "tool errors are not bugs" existed, sessions
# routinely reported Appium/driver failures as if they were Firefox defects.
# Those pseudo-bugs got persisted into agent_memory.json under bugs_confirmed
# and then, on subsequent sessions, biased the LLM AWAY from re-testing
# features whose "bug" was actually a tool problem — even after the tool
# problem was fixed (see the long_press W3C migration).
#
# We strip anything matching these substrings (case-insensitive) both when
# loading memory (auto-heal existing files) and when ingesting new insights
# (belt-and-suspenders — the prompt rule already tells the LLM not to emit
# these, but memory extraction is a separate LLM call that could regenerate
# similar phrasings).

_TOOL_ERROR_PATTERNS: tuple[str, ...] = (
    "unhandled endpoint",
    "unknowncommand",              # matches UnknownCommandError / "unknown command"
    "unknown command",
    "nosuchelement",               # matches NoSuchElementError / NoSuchElementException
    "unsupported target type",
    "json parse error",
    "refused:",                    # our own Python-side security refusals
    "session execution stalled",
    "session stalled",
    "not supported on ios xcuitest",
    "touch/perform",
    "webdriverexception",
)


def _looks_like_tool_error(bug: dict) -> bool:
    """True if the bug's text matches known Appium/driver-side failure patterns
    rather than an actual application defect.

    Checks title + description + actual — extract_insights and reporter.bugs
    use different field names for the free-text portion, so we scan them all
    defensively.
    """
    haystack = " ".join(
        str(bug.get(k, "") or "") for k in ("title", "description", "actual")
    ).lower()
    return any(pat in haystack for pat in _TOOL_ERROR_PATTERNS)


def _default_memory() -> dict:
    """Full schema with empty values — used for both new files and to backfill
    keys missing from older/partial memory files."""
    return {
        "features_tested":         [],   # e.g. "private browsing toggle"
        "bugs_confirmed":          [],   # {title, severity, session, still_present}
        "behavioral_patterns":     [],   # e.g. "spinner ~2s after tab creation"
        "unexplored_areas":        [],   # areas the agent noticed but didn't visit
        "recommended_objectives":  [],   # suggested next objectives
        "sessions_run":            0,
        "last_updated":            None,
    }


# ── Load / Save ────────────────────────────────────────────────────────────────

def load() -> dict:
    """Read the memory file, merge with the default schema, and auto-heal
    accumulated tool-error pseudo-bugs.

    Merging with defaults means an older/partial memory file (missing keys the
    current schema expects) doesn't crash build_context_summary with a
    KeyError. Loaded values override defaults; missing keys get the empty
    default.

    Auto-heal: bugs_confirmed entries matching _TOOL_ERROR_PATTERNS are dropped.
    Those were mis-classified Appium/driver failures that shouldn't have been
    persisted; leaving them in memory biases future sessions away from
    re-testing features whose "bug" was actually a fixed tool problem.
    """
    defaults = _default_memory()
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE) as f:
                loaded = json.load(f)
            merged = {**defaults, **loaded}

            original = merged.get("bugs_confirmed", [])
            cleaned  = [b for b in original if not _looks_like_tool_error(b)]
            removed  = len(original) - len(cleaned)
            if removed:
                print(f"[memory] Auto-heal: dropped {removed} tool-error "
                      f"pseudo-bug(s) from bugs_confirmed on load")
            merged["bugs_confirmed"] = cleaned
            return merged
        except json.JSONDecodeError as e:
            # A crash during save() (see below) can leave the file truncated.
            # Fall back to empty memory instead of bricking the agent startup.
            print(f"[memory] ⚠️  {MEMORY_FILE} is corrupt ({e}) — starting with empty memory")
    return defaults


def save(memory: dict):
    """Atomic write using a unique tempfile + os.replace.

    Concurrent writers no longer collide on a shared `.tmp` name (before this
    fix, N parallel saves would produce a JSON-corrupt MEMORY_FILE — verified
    empirically). Each writer gets its own tempfile from tempfile.mkstemp.

    Note: this makes the write itself safe (JSON is always valid), but does
    NOT prevent semantic lost-updates when two sessions read → modify → write
    concurrently. The last writer still wins. Parallel runs sharing memory
    should either be avoided or use per-worker memory files (wrapper concern).
    """
    reports_dir = os.path.dirname(MEMORY_FILE) or "."
    os.makedirs(reports_dir, exist_ok=True)
    memory["last_updated"] = datetime.now().isoformat()
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(MEMORY_FILE) + ".",
        suffix=".tmp",
        dir=reports_dir,
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(memory, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, MEMORY_FILE)
    except Exception:
        # Best-effort cleanup of the temp file so failures don't accumulate
        # noise in the reports/ directory.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── Insight extraction ─────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are a QA analyst reviewing an exploratory testing session log.
Extract structured insights from the session and return ONLY valid JSON, no markdown, no explanation.

JSON schema:
{
  "features_tested": ["list of specific features/flows that were tested"],
  "bugs_found": [
    {"title": "short bug title", "severity": "Critical|High|Medium|Low", "description": "one sentence"}
  ],
  "behavioral_patterns": ["observed app behaviors worth remembering, e.g. timing, animations, quirks"],
  "unexplored_areas": ["areas the agent saw but did not explore"],
  "recommended_next_objective": "the single most valuable thing to test next based on this session"
}

Be specific. Use feature names, not generic descriptions.
"private browsing toggle" is good. "explored the app" is useless."""


def extract_insights(reporter, client) -> dict:
    """
    Makes one cheap Haiku call (text only, no images) at end of session
    to extract semantic insights from the session log.
    Returns the extracted dict.

    `client` is a TrackedClient (from agent.cost) so the call is
    automatically counted in the session's cost breakdown.
    """
    # Build a compact text-only session log for Haiku
    steps_text = []
    for step in reporter.steps:
        line = f"Step {step.step}: {step.action}({step.action_detail}) → {step.result}"
        if step.reasoning:
            line += f" | reasoning: {step.reasoning[:100]}"
        steps_text.append(line)

    bugs_text = "\n".join([
        f"- [{b.severity}] {b.title}: {b.actual}"
        for b in reporter.bugs
    ]) or "None found"

    session_text = f"""OBJECTIVE: {reporter.objective}
STEPS EXECUTED: {len(reporter.steps)}

ACTION LOG:
{chr(10).join(steps_text)}

BUGS REPORTED DURING SESSION:
{bugs_text}"""

    try:
        response = client.messages_create(
            "memory-extraction",
            model      = "claude-haiku-4-5",   # cheap — text only, no images
            max_tokens = 600,
            messages   = [{
                "role":    "user",
                "content": f"{EXTRACTION_PROMPT}\n\nSESSION LOG:\n{session_text}"
            }]
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        print(f"[memory] Insight extraction failed: {e}")
        return {}


def _find_similar_bug(title: str, existing_bugs: list) -> int:
    """
    Returns the index of a matching bug in existing_bugs, or -1 if none.
    Matches on exact title (case-insensitive) or fuzzy ratio > 0.85
    to handle rephrased descriptions of the same underlying issue.
    """
    normalized = title.lower().strip()
    for i, bug in enumerate(existing_bugs):
        existing_norm = bug.get("title", "").lower().strip()
        if existing_norm == normalized:
            return i
        ratio = difflib.SequenceMatcher(None, normalized, existing_norm).ratio()
        if ratio > 0.85:
            return i
    return -1


def update_from_session(reporter, client) -> dict:
    """
    Called at end of session. Extracts insights and merges into persistent memory.
    `client` is a TrackedClient — passed through to extract_insights so the
    Haiku call is counted in the session's cost breakdown.
    """
    print("[memory] Extracting insights from session (Haiku call)...")
    insights = extract_insights(reporter, client)

    mem = load()

    # Merge features tested (deduplicated)
    new_features = insights.get("features_tested", [])
    mem["features_tested"] = list(dict.fromkeys(mem["features_tested"] + new_features))   # dict.fromkeys preserves insertion order (unlike set)

    # Merge bugs — deduplicated by fuzzy title match.
    # Known bugs get their occurrences counter incremented and last_seen updated.
    # New bugs are added with occurrences=1.
    # First: filter out any incoming "bug" that looks like an Appium/driver
    # failure. The prompt-side rule already tells the LLM not to emit these,
    # but memory extraction is a separate LLM call — this is the backstop.
    incoming_bugs = insights.get("bugs_found", [])
    filtered_bugs = [b for b in incoming_bugs if not _looks_like_tool_error(b)]
    dropped = len(incoming_bugs) - len(filtered_bugs)
    if dropped:
        print(f"[memory] Filtered {dropped} tool-error pseudo-bug(s) from "
              f"session extraction before merging into memory")
    for bug in filtered_bugs:
        idx = _find_similar_bug(bug.get("title", ""), mem["bugs_confirmed"])
        if idx >= 0:
            mem["bugs_confirmed"][idx]["still_present"] = True
            mem["bugs_confirmed"][idx]["occurrences"]   = mem["bugs_confirmed"][idx].get("occurrences", 1) + 1
            mem["bugs_confirmed"][idx]["last_seen"]      = reporter.session_id
            print(f"[memory] ↩  Known bug re-confirmed (×{mem['bugs_confirmed'][idx]['occurrences']}): {bug.get('title', '')[:60]}")
        else:
            bug["session"]       = reporter.session_id
            bug["still_present"] = True
            bug["occurrences"]   = 1
            mem["bugs_confirmed"].append(bug)

    # Append new behavioral patterns (keep last 20)
    new_patterns = insights.get("behavioral_patterns", [])
    mem["behavioral_patterns"] = list(dict.fromkeys(
        mem["behavioral_patterns"] + new_patterns
    ))[-20:]

    # Append unexplored areas (keep last 20, deduplicated)
    new_unexplored = insights.get("unexplored_areas", [])
    mem["unexplored_areas"] = list(dict.fromkeys(
        mem["unexplored_areas"] + new_unexplored
    ))[-20:]

    # Keep last 5 recommended objectives
    if insights.get("recommended_next_objective"):
        mem["recommended_objectives"].append({
            "session":   reporter.session_id,
            "objective": insights["recommended_next_objective"],
        })
        mem["recommended_objectives"] = mem["recommended_objectives"][-5:]

    mem["sessions_run"] += 1
    save(mem)

    print(f"[memory] Saved — {len(mem['features_tested'])} features, "
          f"{len(mem['bugs_confirmed'])} bugs, "
          f"{len(mem['unexplored_areas'])} unexplored areas")
    return mem


# ── Context injection ──────────────────────────────────────────────────────────

def build_context_summary(objective: str = "") -> str:
    """
    Returns a compact block to inject into the agent's prompt at session start.

    If `objective` is provided, features whose name overlaps with objective
    keywords are dropped from the "previously covered" list — a user asking
    for X should never be told "X is already tested". Keeps regression
    coverage possible when features may have changed between sessions.
    """
    mem = load()

    if mem["sessions_run"] == 0:
        return "No previous sessions — this is the first run."

    lines = [f"=== AGENT MEMORY ({mem['sessions_run']} previous sessions) ==="]

    if mem["features_tested"]:
        # Drop features that appear in the current objective — the user is
        # explicitly asking for them, memory shouldn't discourage the retest.
        objective_words = {w for w in objective.lower().split() if len(w) > 3}
        covered = [f for f in mem["features_tested"]
                   if not any(w in f.lower() for w in objective_words)]
        if covered:
            lines.append("\nPREVIOUSLY COVERED (may have regressed since — prioritize new areas but re-verify if the objective touches these):")
            for f in covered:
                lines.append(f"  ✓ {f}")

    if mem["bugs_confirmed"]:
        lines.append("\nKNOWN BUGS (re-verify if you encounter these areas):")
        for b in mem["bugs_confirmed"][-8:]:
            lines.append(f"  [{b['severity']}] {b['title']}")

    if mem["unexplored_areas"]:
        lines.append("\nUNEXPLORED AREAS (prioritize these):")
        for a in mem["unexplored_areas"][-8:]:
            lines.append(f"  → {a}")

    if mem["behavioral_patterns"]:
        lines.append("\nAPP BEHAVIOR PATTERNS:")
        for p in mem["behavioral_patterns"][-5:]:
            lines.append(f"  • {p}")

    if mem["recommended_objectives"]:
        last = mem["recommended_objectives"][-1]["objective"]
        lines.append(f"\nSUGGESTED FOCUS: {last}")

    lines.append("=" * 40)
    return "\n".join(lines)
