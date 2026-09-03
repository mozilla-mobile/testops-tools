"""
agent/reporter.py

Tracks everything the agent does and writes (all keyed on session_id so
back-to-back or parallel runs never overwrite each other's evidence):
  - reports/session_<session_id>.json       (machine-readable full history)
  - reports/bugs_<session_id>.md            (human-readable bug reports)
  - reports/coverage_<session_id>.json      (what screens/areas were visited)
  - reports/screenshots/<session_id>/*.png  (per-step evidence)

The session JSON records token usage (never USD — see agent/cost.py for why).
For authoritative billing, use the Anthropic console:
    https://console.anthropic.com/settings/usage
"""

import difflib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class AgentStep:
    step:       int
    timestamp:  str
    reasoning:  str          # what the LLM decided and why
    action:     str          # what action was taken
    action_detail: str       # specifics of the action
    result:     str          # ok / error
    screenshot: str          # path to screenshot before action
    screen_summary: str      # text summary of screen before action

@dataclass
class BugReport:
    title:      str
    severity:   str          # Critical / High / Medium / Low
    steps:      list[str]
    expected:   str
    actual:     str
    screenshot: str
    step_index: int


# ── Reporter ───────────────────────────────────────────────────────────────────

class Reporter:

    def __init__(self, objective: str, reports_dir: str = "reports"):
        self.objective   = objective
        self.reports_dir = reports_dir
        # Includes microseconds so two sessions started in the same second
        # (e.g. parallel CI runs) don't collide and overwrite each other's
        # session_*.json. Scripts slice the first 8 chars for the date, and
        # sort by string comparison — both are unaffected by the suffix.
        self.session_id  = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.steps:         list[AgentStep]  = []
        self.bugs:          list[BugReport]  = []
        self.screen_visits: dict[str, int]   = {}
        self._usage_summary: dict            = {}
        self._video_path:   str           = ""

        os.makedirs(reports_dir, exist_ok=True)
        print(f"[reporter] Session {self.session_id} started")
        print(f"[reporter] Objective: {objective}")

    def log_step(
        self,
        reasoning:     str,
        action:        str,
        action_detail: str,
        result:        str,
        screenshot:    str,
        screen_summary: str,
    ):
        step = AgentStep(
            step           = len(self.steps) + 1,
            timestamp      = datetime.now().isoformat(),
            reasoning      = reasoning,
            action         = action,
            action_detail  = action_detail,
            result         = result,
            screenshot     = screenshot,
            screen_summary = screen_summary,
        )
        self.steps.append(step)

        # Console output so you can follow along
        status_icon = "✓" if result == "ok" else "✗"
        print(f"\n[step {step.step:03d}] {status_icon} {action}: {action_detail}")
        print(f"          reasoning: {reasoning[:120]}...")


    def report_bug(
        self,
        title:      str,
        severity:   str,
        steps:      list[str],
        expected:   str,
        actual:     str,
        screenshot: str,
    ):
        # Skip if a similar bug was already logged in this session
        if self._is_duplicate_bug(title):
            print(f"[reporter] ⏭  Duplicate skipped (already logged this session): {title[:70]}")
            return

        bug = BugReport(
            title      = title,
            severity   = severity,
            steps      = steps,
            expected   = expected,
            actual     = actual,
            screenshot = screenshot,
            # +1 so the bug's step_index matches the AgentStep.step numbering
            # used everywhere else. In loop.py, report_bug() runs BEFORE the
            # log_step() for the same step, so len(self.steps) here is N-1
            # when we're processing step N.
            step_index = len(self.steps) + 1,
        )
        self.bugs.append(bug)

        # Immediate console alert
        icon = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🔵"}.get(severity, "⚪")
        print(f"\n{icon} BUG FOUND [{severity}]: {title}")
        print(f"   Screenshot: {screenshot}")

    def set_usage(self, usage_summary: dict):
        """Attach token-usage data from CostTracker before save/flush."""
        self._usage_summary = usage_summary

    def set_video(self, video_path: str):
        """Attach the session video path before save/flush."""
        self._video_path = video_path

    def flush(self):
        """
        Write the session log to disk immediately.
        Safe to call at any point during a session — used for crash recovery.
        Bugs and coverage map are only written by save() at session end.
        """
        self._save_session_log()

    def save(self):
        """Write all reports to disk."""
        self._save_session_log()
        self._save_bugs_md()
        self._save_coverage_map()
        self._print_summary()

    # ── Private ───────────────────────────────────────────────────────────────

    def _is_duplicate_bug(self, title: str) -> bool:
        """
        Returns True if a similar bug has already been logged in this session.
        Exact match (case-insensitive) or fuzzy ratio > 0.85 to catch
        rephrased descriptions of the same issue.
        """
        normalized = title.lower().strip()
        for existing in self.bugs:
            existing_norm = existing.title.lower().strip()
            if existing_norm == normalized:
                return True
            ratio = difflib.SequenceMatcher(None, normalized, existing_norm).ratio()
            if ratio > 0.85:
                return True
        return False

    def _save_session_log(self):
        path = os.path.join(self.reports_dir, f"session_{self.session_id}.json")
        data = {
            "session_id":  self.session_id,
            "objective":   self.objective,
            "started_at":  self.steps[0].timestamp if self.steps else None,
            "ended_at":    datetime.now().isoformat(),
            "total_steps": len(self.steps),
            "bugs_found":  len(self.bugs),
            "video":       self._video_path,
            "usage":          self._usage_summary,
            "screens_visited": dict(sorted(self.screen_visits.items(), key=lambda x: -x[1])),
            "steps":          [asdict(s) for s in self.steps],
            "bugs":           [asdict(b) for b in self.bugs],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"[reporter] Session log → {path}")

    def _save_bugs_md(self):
        path = os.path.join(self.reports_dir, f"bugs_{self.session_id}.md")
        lines = [
            f"# Bugs Found — {self.session_id}",
            f"**Objective**: {self.objective}",
            f"**Total bugs**: {len(self.bugs)}",
            f"**Steps executed**: {len(self.steps)}",
            "",
        ]
        if not self.bugs:
            lines.append("No bugs found in this session. ✅")
        else:
            for i, bug in enumerate(self.bugs, 1):
                icon = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🔵"}.get(bug.severity, "⚪")
                lines += [
                    f"---",
                    f"## {icon} Bug {i}: {bug.title}",
                    f"**Severity**: {bug.severity}  ",
                    f"**Found at step**: {bug.step_index}  ",
                    f"**Screenshot**: `{bug.screenshot}`",
                    "",
                    "**Steps to reproduce**:",
                    *[f"{j+1}. {s}" for j, s in enumerate(bug.steps)],
                    "",
                    f"**Expected**: {bug.expected}",
                    "",
                    f"**Actual**: {bug.actual}",
                    "",
                ]
        with open(path, "w") as f:
            f.write("\n".join(lines))
        print(f"[reporter] Bug report  → {path}")

    def _save_coverage_map(self):
        path = os.path.join(self.reports_dir, f"coverage_{self.session_id}.json")
        data = {
            "session_id":       self.session_id,
            "unique_screens":   len(self.screen_visits),
            "total_steps":      len(self.steps),
            "actions_used":     list({s.action for s in self.steps}),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"[reporter] Coverage map → {path}")

    def _print_summary(self):
        print("\n" + "="*60)
        print(f"SESSION COMPLETE — {self.session_id}")
        print(f"  Objective:      {self.objective}")
        print(f"  Steps executed: {len(self.steps)}")
        print(f"  Screens seen:   {len(self.screen_visits)}")
        print(f"  Bugs found:     {len(self.bugs)}")
        if self.bugs:
            print("\n  Bugs:")
            for b in self.bugs:
                icon = {"Critical":"🔴","High":"🟠","Medium":"🟡","Low":"🔵"}.get(b.severity,"⚪")
                print(f"    {icon} [{b.severity}] {b.title}")
        if self._video_path:
            print(f"\n  Video:          {self._video_path}")
        if self._usage_summary:
            print(f"  API usage:      {self._usage_summary.get('total_calls', 0)} calls  ·  "
                  f"{self._usage_summary.get('total_input_tokens', 0):,} in  ·  "
                  f"{self._usage_summary.get('total_output_tokens', 0):,} out  "
                  f"({self._usage_summary.get('total_tokens', 0):,} total tokens)")
            print(f"  For $ cost:     https://console.anthropic.com/settings/usage")
        print("="*60)
