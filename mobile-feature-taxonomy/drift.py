# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Drift between a feature map and the current code, with suggested fixes.

Two kinds of drift:

1. Action needed: the map no longer describes the code, so `check` fails.
     - unmapped files, grouped into new directories or stray files, each with a suggested
       feature (from what neighbouring code maps to and from name matches)
     - rules that match nothing (moved/deleted code); exact paths get a "moved to" guess
     - ambiguous matches and unknown feature IDs
2. Review: `check` passes, but files changed since <platform>/snapshot.csv was written.
     - new files that an existing glob assigned silently (is that glob still right?)
     - files whose feature changed, moved files, removed files

`apply()` writes only the confident suggestions into feature-map.yml, marked `by: drift`, and
refreshes the snapshot, so a person reviews the result as a normal PR diff. Anything uncertain
stays in the report and keeps `check` failing until someone decides.
"""

import collections
import csv
import datetime
import json
import math
import os
import re
import subprocess

CONFIDENT_SHARE = 0.8      # neighbours agreeing on one feature, alone enough to apply
AGREEING_SHARE = 0.5       # enough when the name match points at the same feature
STRONG_NAME_SCORE = 3.0    # name-match score (sum of idf) that beats neighbours for a low-confidence guess
LIST_LIMIT = 15
STOP_WORDS = {"and", "the", "for", "src", "main", "java", "kotlin", "org", "mozilla", "components", "fenix",
              "firefox", "ios", "client", "frontend", "sources", "swift", "kt", "app", "browser", "view",
              "views", "controller", "manager", "model", "state", "store", "ui", "impl", "utils", "helper",
              "feature", "lib", "service", "support", "ext", "extensions", "page", "pages", "settings"}


# ---- helpers ------------------------------------------------------------------


def tokens(text):
    """Lower-case word tokens from paths and names: splits camelCase, digits, -, _, /, ."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    return {t for t in re.split(r"[^a-zA-Z]+", text.lower()) if len(t) >= 3 and t not in STOP_WORDS}


def snapshot_path(fm):
    return os.path.join(os.path.dirname(fm.map_path), "snapshot.csv")


def read_snapshot(fm):
    path = snapshot_path(fm)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return {row["path"]: row["feature"] for row in csv.DictReader(f)}


def write_snapshot(fm, resolved):
    with open(snapshot_path(fm), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["path", "feature"])
        for path in sorted(resolved):
            w.writerow([path, resolved[path]])


def repo_commit(fm):
    try:
        return subprocess.run(["git", "-C", fm.repo, "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def ancestors(path):
    parts = path.split("/")[:-1]
    return ["/".join(parts[:i]) for i in range(len(parts), 0, -1)]


def root_of(fm, path):
    return next((r for r in fm.roots if path == r or path.startswith(r.rstrip("/") + "/")), "")


# ---- suggestions -----------------------------------------------------------------


class Suggester:
    """Proposes a feature for unmapped code from (a) neighbouring mapped code and (b) name matches."""

    def __init__(self, fm, resolved):
        self.fm = fm
        self.resolved = {p: f for p, f in resolved.items() if f not in ("UNMAPPED", "AMBIGUOUS")}
        self.by_dir = collections.defaultdict(collections.Counter)   # dir (any depth) -> feature counts below it
        for path, feature in self.resolved.items():
            for d in ancestors(path):
                self.by_dir[d][feature] += 1
        # Name index: words from the feature's name/id and from every path mapped to it.
        self.feature_tokens = collections.defaultdict(set)
        for fid, meta in fm.ids.items():
            self.feature_tokens[fid] |= tokens(meta.get("name", "")) | tokens(fid.replace(".", " "))
        for path, feature in self.resolved.items():
            self.feature_tokens[feature] |= tokens(path[len(root_of(fm, path)):])
        df = collections.Counter(t for toks in self.feature_tokens.values() for t in toks)
        n = max(len(self.feature_tokens), 1)
        self.idf = {t: math.log(n / c) for t, c in df.items()}
        sizes = sorted(len(t) for t in self.feature_tokens.values() if t)
        self.typical_size = sizes[len(sizes) // 2] if sizes else 1

    def neighbours(self, directory):
        """Feature distribution of mapped code in the nearest ancestor (inclusive) that has any."""
        root = root_of(self.fm, directory + "/")
        for d in [directory] + ancestors(directory + "/x")[1:]:
            if len(d) < len(root):
                break
            counts = self.by_dir.get(d)
            if counts:
                return d, counts
        return None, collections.Counter()

    def name_matches(self, text):
        mine = tokens(text)
        scores = collections.Counter()
        for feature, toks in self.feature_tokens.items():
            # Names only hint at product features; shared buckets come from the neighbour signal.
            if feature.startswith(("SHARED", "EXCLUDED")) or self.fm.ids.get(feature, {}).get(self.fm.platform) is False:
                continue
            hit = mine & toks
            if hit:
                # Damp features with large vocabularies so they don't win on size alone.
                damping = min(1.0, (self.typical_size / len(toks)) ** 0.5)
                scores[feature] = sum(self.idf.get(t, 0) for t in hit) * damping
        return [(f, round(s, 2), sorted(mine & self.feature_tokens[f])) for f, s in scores.most_common(3)]

    def suggest(self, directory, name_text):
        near_dir, counts = self.neighbours(directory)
        total = sum(counts.values())
        top, top_n = (counts.most_common(1)[0] if counts else (None, 0))
        share = top_n / total if total else 0
        names = self.name_matches(name_text)
        name_top = names[0][0] if names else None
        if top and share >= CONFIDENT_SHARE:
            feature, confidence = top, "high"
        elif top and share >= AGREEING_SHARE and top == name_top:
            feature, confidence = top, "medium"
        else:
            strong_name = names and names[0][1] >= STRONG_NAME_SCORE
            feature, confidence = (name_top if strong_name else top) or name_top, "low"
        return {
            "feature": feature,
            "confidence": confidence,
            "neighbours": {"dir": near_dir, "total": total,
                           "top": [(f, n, round(n / total, 2)) for f, n in counts.most_common(3)]},
            "name_matches": names,
        }


def group_unmapped(fm, unmapped, resolved):
    """Groups unmapped files by the shallowest directory with no mapped code under it.

    A whole new directory gets one `dir/**` rule; a new file in a directory that already has
    mapped code gets an exact-path rule.
    """
    mapped_dirs = {d for p, f in resolved.items() if f != "UNMAPPED" for d in ancestors(p)}
    groups = collections.OrderedDict()
    for path in unmapped:
        root = root_of(fm, path).rstrip("/")
        new_dir = None
        for d in reversed(ancestors(path)):          # shallow to deep
            if len(d) <= len(root):
                continue
            if d not in mapped_dirs:
                new_dir = d
                break
        key = (new_dir + "/**") if new_dir else path
        groups.setdefault(key, []).append(path)
    return groups


# ---- report --------------------------------------------------------------------


def build_report(fm):
    problems = fm.problems()
    files = fm.source_files()
    ambiguous_paths = {p for p, _ in problems["ambiguous"]}
    resolved = {p: ("AMBIGUOUS" if p in ambiguous_paths else fm.feature_of(p)) for p in files}
    suggester = Suggester(fm, resolved)

    unmapped = []
    for rule_path, group in group_unmapped(fm, problems["unmapped"], resolved).items():
        directory = rule_path[:-3] if rule_path.endswith("/**") else os.path.dirname(rule_path)
        # Match on what is new (the directory's own name and its file names), not on the parent path,
        # which the neighbour signal already covers.
        own_name = os.path.basename(directory) if rule_path.endswith("/**") else ""
        name_text = " ".join([own_name] + [os.path.splitext(os.path.basename(p))[0] for p in group])
        s = suggester.suggest(directory, name_text)
        unmapped.append(dict(rule=rule_path, files=group, lines=sum(fm.count_lines(p) for p in group), **s))

    by_basename = collections.defaultdict(list)
    for p in files:
        by_basename[os.path.basename(p)].append(p)
    dead = []
    for r in problems["dead_rules"]:
        entry = {"rule": r.path, "feature": r.feature, "by": r.by, "moved_to": None, "candidates": []}
        if not r.is_glob:
            entry["candidates"] = by_basename.get(os.path.basename(r.path), [])
            # Only call it a move when exactly one file has that name and no exact rule claims it.
            if len(entry["candidates"]) == 1:
                rule, _ = fm.resolve(entry["candidates"][0])
                if rule is None or rule.is_glob:
                    entry["moved_to"] = entry["candidates"][0]
        else:
            last = next((s for s in reversed(r.path.split("/")) if s and not any(c in s for c in "*?[")), "")
            entry["candidates"] = sorted({d for p in files for d in ancestors(p) if d.endswith("/" + last)})[:5]
        dead.append(entry)

    snapshot = read_snapshot(fm)
    review = None
    if snapshot is not None:
        added = sorted(set(resolved) - set(snapshot))
        removed = sorted(set(snapshot) - set(resolved))
        removed_by_name = collections.defaultdict(list)
        for p in removed:
            removed_by_name[os.path.basename(p)].append(p)
        moved, new = [], []
        for p in added:
            olds = removed_by_name.get(os.path.basename(p), [])
            if len(olds) == 1:
                moved.append({"from": olds[0], "to": p, "old_feature": snapshot[olds[0]], "feature": resolved[p]})
            else:
                rule, _ = fm.resolve(p)
                new.append({"path": p, "feature": resolved[p], "rule": rule.path if rule else ""})
        moved_from = {m["from"] for m in moved}
        changed = [{"path": p, "old_feature": snapshot[p], "feature": resolved[p]}
                   for p in sorted(set(snapshot) & set(resolved)) if snapshot[p] != resolved[p]]
        review = {"new": [n for n in new if n["feature"] not in ("UNMAPPED", "AMBIGUOUS")],
                  "moved": moved, "changed": changed, "removed": [p for p in removed if p not in moved_from]}

    unreviewed = collections.Counter(area_or_bucket(r.feature) for r in fm.rules if not r.reviewed)
    report = {
        "platform": fm.platform,
        "repo": fm.repo_name,
        "commit": repo_commit(fm),
        "generated": datetime.date.today().isoformat(),
        "files": len(files),
        "rules": len(fm.rules),
        "unreviewed_rules": sum(unreviewed.values()),
        "unreviewed_by_area": dict(unreviewed.most_common()),
        "unmapped": unmapped,
        "dead_rules": dead,
        "ambiguous": [{"path": p, "error": e} for p, e in problems["ambiguous"]],
        "unknown_ids": [{"rule": r.path, "feature": f} for r, f in problems["unknown_ids"]],
        "disabled_ids": [{"rule": r.path, "feature": f} for r, f in problems["disabled_ids"]],
        "snapshot": "missing" if snapshot is None else "present",
        "review": review,
        "_resolved": resolved,
    }
    action = unmapped or dead or report["ambiguous"] or report["unknown_ids"] or report["disabled_ids"]
    report["has_drift"] = bool(action or (review and any(review.values())))
    return report


def area_or_bucket(feature):
    return feature if feature.startswith(("SHARED", "EXCLUDED")) else feature.split(".")[0]


def to_json(report):
    return json.dumps({k: v for k, v in report.items() if not k.startswith("_")}, indent=2) + "\n"


def _capped(items, fmt, limit=LIST_LIMIT):
    out = [fmt(i) for i in items[:limit]]
    if len(items) > limit:
        out.append(f"- … and {len(items) - limit} more")
    return out


def to_markdown(fm, report):
    ids = fm.ids
    name = lambda f: f"`{f}` {ids[f]['name']}" if f in ids else f"`{f}`"
    commit = report["commit"][:12] or "unknown"
    out = [f"# Feature map drift: {report['platform']}", "",
           f"`{report['repo']}` at `{commit}`, {report['generated']}. "
           f"{report['files']} source files, {report['rules']} rules, "
           f"{report['unreviewed_rules']} not yet reviewed by a person.", ""]

    actions = (len(report["unmapped"]), len(report["dead_rules"]), len(report["ambiguous"]),
               len(report["unknown_ids"]) + len(report["disabled_ids"]))
    out += ["| Needs a decision | Count |", "|---|---|",
            f"| Unmapped code (groups) | {actions[0]} |", f"| Rules that match nothing | {actions[1]} |",
            f"| Ambiguous files | {actions[2]} |", f"| Unknown or disabled feature IDs | {actions[3]} |", ""]
    if not any(actions):
        out += ["`check` passes: every file maps to exactly one feature.", ""]

    if report["unmapped"]:
        out += ["## Unmapped code", "",
                "Suggested from what neighbouring code maps to and from matching names. "
                "`--apply` writes **high** and **medium** suggestions; **low** needs a person.", ""]
        for u in report["unmapped"]:
            out.append(f"### `{u['rule']}`  →  {name(u['feature']) if u['feature'] else '?'}  ({u['confidence']})")
            out.append("")
            nb = u["neighbours"]
            if nb["dir"]:
                dist = ", ".join(f"`{f}` {int(s * 100)}%" for f, _, s in nb["top"])
                out.append(f"- Neighbours: {nb['total']} mapped files under `{nb['dir']}`: {dist}")
            if u["name_matches"]:
                out.append("- Name matches: " + ", ".join(f"`{f}` ({', '.join(w)})" for f, _, w in u["name_matches"]))
            out.append(f"- {len(u['files'])} file(s), {u['lines']} lines:")
            out += ["  " + line for line in _capped(u["files"], lambda p: f"- `{p}`", 8)]
            out.append("")
        out += ["Rules to paste (or run `drift --apply`):", "", "```yaml"]
        out += [rule_line(u["rule"], u["feature"] or "TODO", comment=f"{u['confidence']} confidence")
                for u in report["unmapped"]]
        out += ["```", ""]

    if report["dead_rules"]:
        out += ["## Rules that match nothing", "",
                "The code moved or was deleted. Update the path, or delete the rule. "
                "Mark rules for build-generated code `optional: true`.", ""]
        for d in report["dead_rules"]:
            hint = ""
            if d["moved_to"]:
                hint = f" — probably moved to `{d['moved_to']}` (`--apply` updates it)"
            elif d["candidates"]:
                hint = " — similar: " + ", ".join(f"`{c}`" for c in d["candidates"][:3])
            out.append(f"- `{d['rule']}` ({d['feature']}){hint}")
        out.append("")

    if report["ambiguous"]:
        out += ["## Ambiguous files", "", "Two equally specific rules match. Make one more specific.", ""]
        out += _capped(report["ambiguous"], lambda a: f"- `{a['path']}`: {a['error']}")
        out.append("")

    if report["unknown_ids"] or report["disabled_ids"]:
        out += ["## Unknown or disabled feature IDs", ""]
        out += [f"- `{u['rule']}` uses unknown `{u['feature']}`" for u in report["unknown_ids"]]
        out += [f"- `{u['rule']}` uses `{u['feature']}`, marked `{fm.platform}: false` in features.yml"
                for u in report["disabled_ids"]]
        out.append("")

    review = report["review"]
    if review is None:
        out += ["## Changes since the last snapshot", "",
                f"No `{fm.platform}/snapshot.csv` yet. `drift --apply` creates it, and the next report lists "
                "new, moved and removed files against it.", ""]
    elif any(review.values()):
        out += ["## Changes since the last snapshot", "",
                "These already resolve, so `check` passes, but confirm the feature is right.", ""]
        if review["new"]:
            out += [f"### New files assigned by existing rules ({len(review['new'])})", ""]
            by_feature = collections.defaultdict(list)
            for n in review["new"]:
                by_feature[n["feature"]].append(n)
            for feature in sorted(by_feature):
                out.append(f"- {name(feature)}")
                out += ["  " + line for line in _capped(by_feature[feature],
                                                         lambda n: f"- `{n['path']}` via `{n['rule']}`", 8)]
            out.append("")
        if review["moved"]:
            out += [f"### Moved files ({len(review['moved'])})", ""]
            out += _capped(review["moved"], lambda m: f"- `{m['from']}` → `{m['to']}`" + (
                f" — feature changed `{m['old_feature']}` → `{m['feature']}`"
                if m["old_feature"] != m["feature"] else ""))
            out.append("")
        if review["changed"]:
            out += [f"### Files whose feature changed ({len(review['changed'])})", ""]
            out += _capped(review["changed"], lambda c: f"- `{c['path']}`: `{c['old_feature']}` → `{c['feature']}`")
            out.append("")
        if review["removed"]:
            out += [f"### Removed files ({len(review['removed'])})", ""]
            out += _capped(review["removed"], lambda p: f"- `{p}`")
            out.append("")

    if report["unreviewed_rules"]:
        out += ["## Review backlog", "",
                f"{report['unreviewed_rules']} of {report['rules']} rules are still `by: ai`/`by: drift`. By area: "
                + ", ".join(f"`{a}` {n}" for a, n in report["unreviewed_by_area"].items()), ""]
    return "\n".join(out)


# ---- apply ---------------------------------------------------------------------


def rule_line(path, feature, comment=""):
    line = f'  - {{path: "{path}", feature: {feature}, by: drift}}'
    return f"{line}    # {comment}" if comment else line


def apply(fm, report):
    """Writes confident suggestions into the map file and refreshes the snapshot. Returns the change count."""
    with open(fm.map_path) as f:
        text = f.read()
    changes = 0
    for d in report["dead_rules"]:
        if d["moved_to"]:
            old = f'path: "{d["rule"]}"'
            if text.count(old) == 1:
                text = text.replace(old, f'path: "{d["moved_to"]}"')
                changes += 1
    new_rules = [u for u in report["unmapped"] if u["confidence"] in ("high", "medium") and u["feature"]]
    if new_rules:
        if not text.endswith("\n"):
            text += "\n"
        text += f"\n  # Added by `feature_map.py drift --apply` on {report['generated']}"
        text += f" ({report['repo']} {report['commit'][:12]}). Review, then delete `by: drift`.\n"
        text += "\n".join(rule_line(u["rule"], u["feature"], f"{u['confidence']} confidence") for u in new_rules)
        text += "\n"
        changes += len(new_rules)
    with open(fm.map_path, "w") as f:
        f.write(text)

    # Re-resolve with the updated rules so the snapshot matches what was written.
    from feature_map import FeatureMap
    updated = FeatureMap(fm.platform, fm.repo, map_path=fm.map_path)
    resolved = {}
    for p in updated.source_files():
        rule, error = updated.resolve(p)
        resolved[p] = rule.feature if rule else ("UNMAPPED" if error == "unmapped" else "AMBIGUOUS")
    write_snapshot(fm, resolved)
    return changes
