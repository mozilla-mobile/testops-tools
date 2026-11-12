#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Attributes Firefox iOS and Android source code to product features.

Reads features.yml (the Firefox Mobile feature IDs, shared by iOS and Android) and <platform>/feature-map.yml
(path and symbol rules) and resolves every source file under the configured roots
to exactly one feature. Rules are order-independent: an exact file path beats a
glob, and among globs the one with more literal path segments wins, then the
longer pattern. Two equally specific matching rules are an error.

Commands:
    check               Fail if any file is unmapped, a rule is ambiguous, a rule
                        matches no files, or a feature ID is unknown.
    files               CSV: resolved feature for every source file.
    lines               CSV: files and source lines per feature (and layer).
    drift               Markdown/JSON report of where the map and the code disagree,
                        with suggested rule changes. --apply writes the confident ones.

Usage:
    uv run feature_map.py ios --repo ~/git/firefox-ios check
    uv run feature_map.py android --repo ~/git/mozilla-firefox/firefox drift
"""

import argparse
import collections
import csv
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
PLATFORMS = ("ios", "android")
NON_FEATURE_PREFIXES = ("SHARED", "EXCLUDED", "UNMAPPED", "GENERATED")
CLOSURE_PREFIX = re.compile(r"^(?:(?:implicit )?closure #\d+ (?:\(\) )?in )+")


def glob_to_regex(pattern):
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)


def is_glob(path):
    return any(c in path for c in "*?[")


class Rule:
    def __init__(self, raw, index):
        self.path = raw["path"]
        self.feature = raw["feature"]
        self.by = raw.get("by", "human")
        self.symbols = [(re.compile(s["match"]), s["feature"]) for s in raw.get("symbols", [])]
        self.index = index
        self.optional = bool(raw.get("optional", False))   # may match no files, e.g. dirs created by the build
        self.is_glob = is_glob(self.path)
        self.regex = re.compile(glob_to_regex(self.path))
        literal_segments = [s for s in self.path.split("/") if not is_glob(s)]
        self.specificity = (0 if self.is_glob else 1, len(literal_segments), len(self.path))

    @property
    def reviewed(self):
        return self.by == "human"

    def matches(self, path):
        return self.regex.fullmatch(path) is not None

    def feature_for_symbol(self, function_name):
        name = CLOSURE_PREFIX.sub("", function_name)
        for pattern, feature in self.symbols:
            if pattern.search(name):
                return feature
        return self.feature


def load_taxonomy(path=None):
    """Returns {id: entry} for every feature, shared bucket, excluded bucket and L1 area.

    L1 area IDs (e.g. "CRED") are valid targets for code that serves the whole area.
    This is the entry point other tools (charts, scorecards) should use to read the taxonomy.
    """
    with open(path or os.path.join(HERE, "features.yml")) as f:
        data = yaml.safe_load(f)
    ids = {}
    for group in ("features", "shared", "excluded"):
        for item in data.get(group, []):
            ids[item["id"]] = dict(item, group=group)
    for item in data["features"]:
        l1 = item["id"].split(".")[0]
        ids.setdefault(l1, {"id": l1, "area": item["area"], "name": f"{item['area']} (whole area)", "group": "area"})
    return ids


def area_of(feature_id):
    return "" if feature_id.startswith(NON_FEATURE_PREFIXES) else feature_id.split(".")[0]


class FeatureMap:
    """One platform's map, bound to a checkout of that platform's repository."""

    def __init__(self, platform, repo, map_path=None, taxonomy_path=None):
        self.map_path = map_path or os.path.join(HERE, platform, "feature-map.yml")
        with open(self.map_path) as f:
            cfg = yaml.safe_load(f)
        if cfg.get("platform", platform) != platform:
            raise SystemExit(f"{self.map_path} is for platform {cfg['platform']}, not {platform}")
        self.platform = platform
        self.repo_name = cfg.get("repo", "")
        self.repo = os.path.abspath(os.path.expanduser(repo))
        self.base = os.path.join(self.repo, cfg.get("base") or "")
        self.roots = cfg["roots"]
        self.extensions = tuple(cfg.get("extensions", []))
        self.required_segment = cfg.get("require_path_segment")
        self.skip_dirs = set(cfg.get("skip_dirs", []))
        self.layers = cfg.get("layers", {})
        self.ids = load_taxonomy(taxonomy_path)
        self.rules = [Rule(r, i) for i, r in enumerate(cfg["rules"])]
        self._files = None
        if not os.path.isdir(self.base):
            raise SystemExit(f"{self.base} does not exist: --repo should point at a {self.repo_name} checkout")

    # ---- source discovery -------------------------------------------------

    def _prune(self, rel_dir):
        """True if no file under rel_dir can satisfy `require_path_segment` (e.g. src/test when src/main is required)."""
        if not self.required_segment:
            return False
        head, _, tail = self.required_segment.partition("/")
        parts = rel_dir.split("/")
        return any(p == head and i + 1 < len(parts) and tail and parts[i + 1] != tail for i, p in enumerate(parts))

    def source_files(self):
        """Repo-relative (to `base`) paths of every in-scope source file, sorted."""
        if self._files is not None:
            return self._files
        files = []
        for root in self.roots:
            top = os.path.join(self.base, root)
            for dirpath, dirnames, filenames in os.walk(top):
                rel_dir = os.path.relpath(dirpath, self.base)
                dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in self.skip_dirs
                                     and not self._prune(f"{rel_dir}/{d}"))
                for name in sorted(filenames):
                    if not name.endswith(self.extensions):
                        continue
                    rel = f"{rel_dir}/{name}" if rel_dir != "." else name
                    if self.required_segment and f"/{self.required_segment}/" not in f"/{rel}":
                        continue
                    files.append(rel)
        self._files = sorted(set(files))
        return self._files

    def abspath(self, rel):
        return os.path.join(self.base, rel)

    def count_lines(self, rel):
        with open(self.abspath(rel), errors="ignore") as f:
            return sum(1 for _ in f)

    def layer_of(self, rel):
        for prefix, name in self.layers.items():
            if rel.startswith(prefix):
                return name
        return ""

    # ---- resolution --------------------------------------------------------

    def resolve(self, path):
        """Returns (rule, error) for the most specific rule matching `path`."""
        matching = [r for r in self.rules if r.matches(path)]
        if not matching:
            return None, "unmapped"
        matching.sort(key=lambda r: r.specificity, reverse=True)
        if len(matching) > 1 and matching[0].specificity == matching[1].specificity:
            return None, f"ambiguous: {matching[0].path} vs {matching[1].path}"
        return matching[0], None

    def feature_of(self, path):
        rule, _ = self.resolve(path)
        return rule.feature if rule else "UNMAPPED"

    def problems(self):
        """Returns a dict of problem lists: unknown_ids, unmapped, ambiguous, dead_rules."""
        out = {k: [] for k in ("unknown_ids", "unmapped", "ambiguous", "dead_rules")}
        for r in self.rules:
            for feature in [r.feature] + [f for _, f in r.symbols]:
                if feature not in self.ids:
                    out["unknown_ids"].append((r, feature))
        used = set()
        for path in self.source_files():
            rule, error = self.resolve(path)
            if error == "unmapped":
                out["unmapped"].append(path)
            elif error:
                out["ambiguous"].append((path, error))
                # The tied rules do match; report them once, as ambiguous, not also as dead.
                tied = [r for r in self.rules if r.matches(path)]
                top = max(r.specificity for r in tied)
                used.update(r.index for r in tied if r.specificity == top)
            else:
                used.add(rule.index)
        out["dead_rules"] = [r for r in self.rules if r.index not in used and not r.optional]
        return out


# ---- commands -----------------------------------------------------------------


def cmd_check(fm, args):
    p = fm.problems()
    lines = []
    lines += [f"unknown feature {f} in rule {r.path}" for r, f in p["unknown_ids"]]
    lines += [f"unmapped: {path}" for path in p["unmapped"]]
    lines += [f"{err}: {path}" for path, err in p["ambiguous"]]
    lines += [f"rule matches no files: {r.path}" for r in p["dead_rules"]]
    for line in lines:
        print(line)
    pending = sum(1 for r in fm.rules if not r.reviewed)
    print(f"{fm.platform}: {len(fm.source_files())} files, {len(fm.rules)} rules, {pending} awaiting human review, "
          f"{len(lines)} problems", file=sys.stderr)
    return 1 if lines else 0


def cmd_files(fm, args):
    w = csv.writer(sys.stdout)
    w.writerow(["path", "layer", "feature", "area", "rule", "by", "has_symbol_rules", "lines"])
    for path in fm.source_files():
        rule, error = fm.resolve(path)
        if error:
            w.writerow([path, fm.layer_of(path), error.upper(), "", "", "", "", fm.count_lines(path)])
        else:
            w.writerow([path, fm.layer_of(path), rule.feature, area_of(rule.feature), rule.path, rule.by,
                        bool(rule.symbols), fm.count_lines(path)])
    return 0


def sort_key(ids):
    return lambda f: (f not in ids, ids.get(f, {}).get("area", "~"), f)


def cmd_lines(fm, args):
    totals = collections.defaultdict(collections.Counter)
    for path in fm.source_files():
        key = (fm.feature_of(path), fm.layer_of(path))
        totals[key]["files"] += 1
        totals[key]["lines"] += fm.count_lines(path)
    w = csv.writer(sys.stdout)
    w.writerow(["feature", "area", "name", "layer", "files", "lines"])
    order = sort_key(fm.ids)
    for feature, layer in sorted(totals, key=lambda k: (order(k[0]), k[1])):
        meta = fm.ids.get(feature, {})
        t = totals[(feature, layer)]
        w.writerow([feature, meta.get("area", ""), meta.get("name", ""), layer, t["files"], t["lines"]])
    return 0


def cmd_drift(fm, args):
    import drift
    report = drift.build_report(fm)
    if args.apply:
        changed = drift.apply(fm, report)
        print(f"{fm.map_path}: {changed} rule change(s) written, marked `by: drift`", file=sys.stderr)
        if fm.map_path == os.path.join(HERE, fm.platform, "feature-map.yml"):
            import taxonomy   # which features each platform has comes from the maps, so keep FEATURES.md current
            taxonomy.main([])
    out = drift.to_json(report) if args.format == "json" else drift.to_markdown(fm, report)
    if args.output:
        with open(args.output, "w") as f:
            f.write(out)
    else:
        sys.stdout.write(out)
    return 1 if (args.fail_on_action and report["needs_action"]) else 0


COMMANDS = {"check": cmd_check, "files": cmd_files, "lines": cmd_lines, "drift": cmd_drift}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("platform", choices=PLATFORMS)
    parser.add_argument("--repo", required=True,
                        help="checkout of mozilla-mobile/firefox-ios (ios) or mozilla-firefox/firefox (android)")
    parser.add_argument("--map", help="feature-map.yml to use instead of <platform>/feature-map.yml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("files")
    sub.add_parser("lines")
    d = sub.add_parser("drift")
    d.add_argument("--format", choices=("md", "json"), default="md")
    d.add_argument("--output", "-o", help="write the report here instead of stdout")
    d.add_argument("--apply", action="store_true",
                   help="write confident suggestions into the map, marked `by: drift`, for review in a PR")
    d.add_argument("--fail-on-action", action="store_true",
                   help="exit 1 if something needs a decision (check fails); changes that only need review don't fail")
    args = parser.parse_args(argv)
    fm = FeatureMap(args.platform, args.repo, map_path=args.map)
    return COMMANDS[args.command](fm, args)


if __name__ == "__main__":
    sys.exit(main())
