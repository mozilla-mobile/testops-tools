# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Stage 1: extract what changed in a git range.

Deterministic. Produces per-file churn measures that later feed the FMEA
Occurrence factor. The churn measures follow Nagappan & Ball, "Use of Relative
Code Churn Measures to Predict System Defect Density" (ICSE 2005), which found
that churn normalised against file size predicts defect density far better than
absolute churn does.
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

BUG_RE = re.compile(r"\bBug\s+(\d{6,})", re.IGNORECASE)
BACKOUT_RE = re.compile(r"\b(back(ed)?\s?out|revert(ed)?)\b", re.IGNORECASE)
RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"


@dataclass
class Commit:
    sha: str
    author: str
    date: str
    subject: str
    bugs: List[str] = field(default_factory=list)
    is_backout: bool = False
    files: List[str] = field(default_factory=list)


@dataclass
class FileChange:
    path: str
    added: int = 0
    deleted: int = 0
    commits: int = 0
    authors: int = 0
    total_lines: int = 0
    is_binary: bool = False
    touched_by_backout: bool = False

    @property
    def churned_lines(self) -> int:
        return self.added + self.deleted

    def relative_churn(self) -> Dict[str, float]:
        """Nagappan & Ball relative churn measures, as far as a git range allows.

        M1 churned LOC / total LOC   - how much of the file is new
        M2 deleted LOC / total LOC   - how much was torn out
        M4 churn count / file        - how many separate commits touched it
        M7 churned LOC / deleted LOC - add-vs-rewrite character of the change
        """
        total = max(self.total_lines, 1)
        return {
            "m1_churn_ratio": round(self.churned_lines / total, 4),
            "m2_delete_ratio": round(self.deleted / total, 4),
            "m4_commits_per_file": self.commits,
            "m7_churn_over_delete": round(
                self.churned_lines / self.deleted, 4
            ) if self.deleted else float(self.churned_lines),
        }


def _run(repo: str, args: List[str]) -> str:
    proc = subprocess.run(
        ["git"] + args,
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "git {} failed: {}".format(" ".join(args[:2]), proc.stderr.strip())
        )
    return proc.stdout


def _file_line_count(repo: str, path: str) -> int:
    """Line count of the file at the tip of the range."""
    try:
        out = _run(repo, ["show", "HEAD:{}".format(path)])
    except RuntimeError:
        return 0
    return out.count("\n")


def collect(
    repo: str,
    rev_range: str,
    pathspec: Optional[List[str]] = None,
    max_commits: int = 2000,
) -> Dict:
    """Walk a git range and return commits plus per-file churn."""
    pathspec = pathspec or []
    # The record separator must PREFIX each record: git emits the --numstat
    # block after the format string, so a trailing separator would split each
    # commit away from its own file list.
    fmt = RECORD_SEP + FIELD_SEP.join(["%H", "%an", "%aI", "%s"])

    args = [
        "log",
        "--no-merges",
        "--max-count={}".format(max_commits),
        "--format={}".format(fmt),
        "--numstat",
        rev_range,
    ]
    if pathspec:
        args += ["--"] + pathspec

    raw = _run(repo, args)

    commits: List[Commit] = []
    files: Dict[str, FileChange] = {}
    file_authors: Dict[str, set] = defaultdict(set)

    for record in raw.split(RECORD_SEP):
        record = record.strip("\n")
        if not record.strip():
            continue

        head, _, body = record.partition("\n")
        parts = head.split(FIELD_SEP)
        if len(parts) < 4:
            continue
        sha, author, date, subject = parts[0], parts[1], parts[2], parts[3]

        commit = Commit(
            sha=sha[:12],
            author=author,
            date=date,
            subject=subject,
            bugs=sorted(set(BUG_RE.findall(subject))),
            is_backout=bool(BACKOUT_RE.search(subject)),
        )

        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) != 3:
                continue
            added_s, deleted_s, path = cols

            # Git renames appear as "old => new"; attribute to the new path.
            if " => " in path:
                path = _resolve_rename(path)

            fc = files.setdefault(path, FileChange(path=path))
            if added_s == "-" or deleted_s == "-":
                fc.is_binary = True
            else:
                fc.added += int(added_s)
                fc.deleted += int(deleted_s)
            fc.commits += 1
            fc.touched_by_backout = fc.touched_by_backout or commit.is_backout
            file_authors[path].add(author)
            commit.files.append(path)

        commits.append(commit)

    for path, fc in files.items():
        fc.authors = len(file_authors[path])
        if not fc.is_binary:
            fc.total_lines = _file_line_count(repo, path)

    return {
        "range": rev_range,
        "pathspec": pathspec,
        "commit_count": len(commits),
        "file_count": len(files),
        "total_churn": sum(f.churned_lines for f in files.values()),
        "commits": [asdict(c) for c in commits],
        "files": [
            dict(asdict(fc), churned_lines=fc.churned_lines, **fc.relative_churn())
            for fc in sorted(
                files.values(), key=lambda f: f.churned_lines, reverse=True
            )
        ],
    }


def tip_in_working_tree(repo: str, commits: List[Dict]) -> Optional[str]:
    """Is the newest commit of the analysed range present in the checked-out tree?

    If it is not, the corpus and the churn describe different revisions: we
    would be scoring one branch's changes against another branch's tests, and
    reporting a confidence number that is quietly wrong. Analysing
    `origin/release..origin/beta` from a `main` checkout is the easy way to do
    this by accident.

    Returns the offending tip SHA, or None when the tree is consistent.
    """
    if not commits:
        return None

    tip = commits[0]["sha"]
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", tip, "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    return None if proc.returncode == 0 else tip


def _resolve_rename(path: str) -> str:
    """Turn git's 'a/{b => c}/d' or 'old => new' notation into the new path."""
    brace = re.search(r"\{(.*?) => (.*?)\}", path)
    if brace:
        return path[: brace.start()] + brace.group(2) + path[brace.end():]
    return path.split(" => ")[-1]
