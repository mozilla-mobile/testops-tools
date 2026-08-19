#!/usr/bin/env python3
"""
reconcile_conversion.py — reconcile legacy->efficiency conversion status against repo truth.

WHY THIS EXISTS: the Project Tracker Sheet's "Legacy Inventory (Detail)" tab (and the
Summary tab + dashboards) must reflect which legacy ui/ tests are actually converted. Doing
that reconciliation by hand-walking ~627 rows through the Sheets connector is slow and
hang-prone. This tool computes the converted set deterministically from the repo and emits
a single aligned column-J payload for one batched Sheet write.

CONVERTED SIGNALS (a legacy @Test method counts as converted if EITHER holds):
  A. replacedBy  — the legacy method carries a `replacedBy = [...efficiency.tests.X#m...]`
                   annotation (authoritative; this is what testops-bot counts).
  B. name-match  — the legacy method name exists as an @Test method in the efficiency suite
                   (captures in-flight conversions not yet annotated, e.g. onboarding).

USAGE:
  # 1. discover set + stats only:
  python3 reconcile_conversion.py --ui-dir <FENIX_UI_DIR>

  # 2. emit aligned column-J values for the Detail tab (align to a fresh A:B export):
  python3 reconcile_conversion.py --ui-dir <FENIX_UI_DIR> \
      --sheet-tsv detail_ab.tsv --out-json j_payload.json

  detail_ab.tsv = TAB-separated "Class<TAB>Method" rows in the exact order they appear in
  the Detail tab (row 2 downward), fetched via the Sheets connector each run so alignment
  is always against live sheet order (never positional guessing).
"""
import os, re, glob, csv, json, argparse, sys

def find_ui_dir():
    for base in ("/sessions",):
        for p in glob.glob(base + "/*/mnt/firefox/mobile/android/fenix/app/src/androidTest/java/org/mozilla/fenix/ui"):
            return p
    return None

def parse_legacy(ui_dir):
    """Return ordered list of dicts: Class, Method, smoke, ignored, has_replacedBy, replacedBy_target."""
    rows = []
    for path in sorted(glob.glob(os.path.join(ui_dir, "*.kt"))):
        lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
        cls = None
        for l in lines:
            m = re.search(r'\bclass\s+(\w+)', l)
            if m:
                cls = m.group(1); break
        if not cls:
            cls = os.path.basename(path)[:-3]
        n = len(lines); i = 0
        while i < n:
            mfun = re.search(r'\bfun\s+(`[^`]+`|[A-Za-z_]\w*)\s*\(', lines[i])
            if mfun:
                # gather contiguous annotation/comment block above (balanced parens/brackets)
                j = i - 1; block = []; running = 0
                while j >= 0:
                    raw = lines[j]; t = raw.strip()
                    bal = raw.count("(") + raw.count("[") - raw.count(")") - raw.count("]")
                    is_ann = t.startswith("@") or t.startswith("//") or t.startswith("*") or t.startswith("/*") or t.endswith("*/")
                    if is_ann or running != 0 or bal != 0:
                        block.insert(0, raw); running += bal; j -= 1; continue
                    break
                blk = "\n".join(block)
                if "@Test" in blk:
                    method = mfun.group(1).strip("`")
                    rb = re.search(r'replacedBy\s*=\s*\[(.*?)\]', blk, re.DOTALL)
                    rb_target = ""
                    if rb:
                        mt = re.search(r'efficiency\.tests\.[A-Za-z0-9_]+#[A-Za-z0-9_]+', rb.group(1))
                        rb_target = mt.group(0) if mt else rb.group(1).strip().strip('"')
                    rows.append({
                        "Class": cls, "Method": method,
                        "smoke": "@SmokeTest" in blk,
                        "ignored": "@Ignore" in blk,
                        "has_replacedBy": bool(rb),
                        "replacedBy_target": rb_target,
                    })
            i += 1
    return rows

def parse_efficiency(ui_dir):
    """Return set of @Test method names in the efficiency suite."""
    eff_dir = os.path.join(ui_dir, "efficiency", "tests")
    names = set()
    for path in glob.glob(os.path.join(eff_dir, "*.kt")):
        lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
        for i, l in enumerate(lines):
            if "@Test" in l:
                for k in range(i, min(i + 6, len(lines))):
                    m = re.search(r'\bfun\s+(`[^`]+`|[A-Za-z_]\w*)\s*\(', lines[k])
                    if m:
                        names.add(m.group(1).strip("`")); break
    return names

def _tae_version():
    """Version of the whole tae-conversion toolchain (tools + docs are stamped together).

    realpath, not __file__: these tools are commonly invoked through symlinks from another checkout's
    tools/ dir, and an unresolved path would look for VERSION in the wrong repo and report "unknown"
    exactly where a staleness check matters most.
    """
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "VERSION")
    try:
        return open(p).read().strip()
    except OSError:
        return "unknown"


def main():
    if "--version" in sys.argv[1:]:
        print(f"{os.path.basename(__file__)} \u2014 tae-conversion {_tae_version()}")
        sys.exit(0)
    ap = argparse.ArgumentParser()
    ap.add_argument("--ui-dir", default=None)
    ap.add_argument("--sheet-tsv", default=None, help="TSV Class<TAB>Method in Detail-tab order")
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-csv", default=None)
    args = ap.parse_args()

    ui_dir = args.ui_dir or find_ui_dir()
    if not ui_dir or not os.path.isdir(ui_dir):
        sys.exit(f"UI dir not found: {ui_dir}")

    legacy = parse_legacy(ui_dir)
    eff_names = parse_efficiency(ui_dir)

    for r in legacy:
        r["conv_name"] = r["Method"] in eff_names
        r["converted"] = r["has_replacedBy"] or r["conv_name"]

    # stats
    tot = len(legacy)
    smoke = [r for r in legacy if r["smoke"]]
    conv_all = [r for r in legacy if r["converted"]]
    conv_smoke = [r for r in smoke if r["converted"]]
    rb_smoke = [r for r in smoke if r["has_replacedBy"]]
    print(f"UI dir: {ui_dir}")
    print(f"efficiency @Test method names: {len(eff_names)}")
    print(f"legacy @Test methods: {tot}  | smoke: {len(smoke)}")
    print(f"converted (all @Test): {len(conv_all)}")
    print(f"converted smoke: {len(conv_smoke)}  (of {len(smoke)} = {100*len(conv_smoke)/len(smoke):.1f}%)")
    print(f"  - via replacedBy (landed/annotated): {len(rb_smoke)}")
    print(f"  - via name-match only (in-flight, no annotation yet): {len(conv_smoke)-len(rb_smoke)}")

    if args.out_csv:
        with open(args.out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Class", "Method", "Smoke", "Converted", "Signal"])
            for r in conv_all:
                sig = "replacedBy" if r["has_replacedBy"] else "name-match"
                w.writerow([r["Class"], r["Method"], "Yes" if r["smoke"] else "", "Converted", sig])
        print(f"wrote {args.out_csv} ({len(conv_all)} converted rows)")

    # aligned column-J payload against the live sheet order
    if args.sheet_tsv:
        conv_keys = {(r["Class"], r["Method"]) for r in conv_all}
        j_values = []
        matched = 0; unmatched_rows = []
        legacy_keys = {(r["Class"], r["Method"]) for r in legacy}
        with open(args.sheet_tsv, encoding="utf-8") as f:
            sheet_rows = [line.rstrip("\n").split("\t") for line in f if line.strip()]
        for cls, meth in [(r[0], r[1]) for r in sheet_rows]:
            is_conv = (cls, meth) in conv_keys
            j_values.append(["Converted" if is_conv else "Not started"])
            if is_conv:
                matched += 1
            if (cls, meth) not in legacy_keys:
                unmatched_rows.append((cls, meth))
        print(f"sheet rows: {len(sheet_rows)}  | marked Converted: {matched}")
        # sanity: every converted key should be found in the sheet
        sheet_keyset = {(r[0], r[1]) for r in sheet_rows}
        missing_in_sheet = sorted(conv_keys - sheet_keyset)
        if missing_in_sheet:
            print(f"WARNING: {len(missing_in_sheet)} converted tests not present as sheet rows:")
            for k in missing_in_sheet:
                print("   ", k)
        if unmatched_rows:
            print(f"NOTE: {len(unmatched_rows)} sheet rows not found in current repo (stale rows):")
            for k in unmatched_rows[:20]:
                print("   ", k)
        if args.out_json:
            json.dump({"range_start_row": 2, "column": "J", "values": j_values,
                       "converted_count": matched, "sheet_row_count": len(sheet_rows)},
                      open(args.out_json, "w"))
            print(f"wrote {args.out_json}")

if __name__ == "__main__":
    main()
