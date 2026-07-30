#!/usr/bin/env python3
"""
effscaffold — front-load the per-test investigation for a legacy→efficiency conversion.

Given a legacy smoke test (Class.method or just method), it prints in one shot the things I otherwise
grep for by hand: the legacy method body, its TestRail link, whether it's @Ignore'd, the robots it
drives + their selector-bearing lines (ids/text/testTags/content-desc), whether an efficiency test of
the same name already exists (don't re-convert!), and which efficiency page objects/selectors already
model the screens involved.

Usage:
  effscaffold.py <method>                     # search all legacy ui/ smoke tests for the method
  effscaffold.py <Class.method>               # e.g. UnifiedTrustPanelTest.verifySecure...
  [REPO=~/Workspace/firefox] effscaffold.py ...
"""
import os, re, sys, glob, json

REPO = os.environ.get("REPO", os.path.expanduser("~/Workspace/firefox"))
AT = os.path.join(REPO, "mobile/android/fenix/app/src/androidTest/java/org/mozilla/fenix")
UI, EFF = os.path.join(AT, "ui"), os.path.join(AT, "ui/efficiency")

def find_method_file(cls, method):
    if cls:
        p = os.path.join(UI, cls + ".kt")
        return p if os.path.isfile(p) else None
    for f in glob.glob(os.path.join(UI, "*.kt")):
        if re.search(r"\bfun\s+" + re.escape(method) + r"\s*\(", open(f, errors="ignore").read()):
            return f
    return None

def method_block(txt, method):
    m = re.search(r"\bfun\s+" + re.escape(method) + r"\s*\(", txt)
    if not m:
        return None, None
    s = txt.rfind("\n\n", 0, m.start())
    i = txt.find("{", m.end()); d = 0; j = i
    while j < len(txt):
        c = txt[j]
        if c == "{": d += 1
        elif c == "}":
            d -= 1
            if d == 0: break
        j += 1
    return txt[s:j + 1].strip(), txt[i:j + 1]

SELRE = re.compile(r"(withId|withText|onNodeWith\w+|withContentDescription|resourceId|testTag|R\.id\.|R\.string\.)")

def main():
    args = [x for x in sys.argv[1:] if x != "--json"]
    as_json = "--json" in sys.argv[1:]
    arg = args[0] if args else ""
    if not arg:
        (print(json.dumps({"tool": "effscaffold", "found": False, "error": "no method arg"}))
         if as_json else print(__doc__)); sys.exit(2)
    cls, method = (arg.split(".", 1) if "." in arg else (None, arg))
    f = find_method_file(cls, method)
    if not f:
        if as_json:
            print(json.dumps({"tool": "effscaffold", "found": False, "method": method,
                              "error": f"legacy method not found under {UI}"}))
        else:
            print(f"✖ legacy method '{method}' not found under {UI}")
        sys.exit(1)
    txt = open(f, errors="ignore").read()
    block, body = method_block(txt, method)
    head = block.split("fun ")[0]
    tr = re.search(r"cases/view/\d+", head)
    testrail = ("https://mozilla.testrail.io/index.php?/" + tr.group(0)) if tr else None
    ignored = "@Ignore" in head
    ig_reason = (re.search(r'@Ignore\("([^"]*)"', head).group(1)
                 if ignored and re.search(r'@Ignore\("([^"]*)"', head) else "")
    conv = [os.path.basename(x) for x in glob.glob(os.path.join(EFF, "tests", "*.kt"))
            if re.search(r"\bfun\s+" + re.escape(method) + r"\s*\(", open(x, errors="ignore").read())]
    robots = set(re.findall(r"\b([a-z][A-Za-z]+)Robot\b", body)) | \
             set(re.findall(r"\b(navigationToolbar|homeScreen|browserScreen|searchScreen|homeScreenSpecific)\s*[\({]", body))
    robotfiles = []
    for f2 in glob.glob(os.path.join(UI, "robots", "*.kt")):
        b = os.path.basename(f2)
        if any(r.lower() in b.lower() for r in robots) or any(r in open(f2, errors="ignore").read()[:200] for r in robots):
            robotfiles.append(f2)
    robot_sel = {}
    for rf in sorted(set(robotfiles))[:4]:
        lines = [ln.strip()[:150] for ln in open(rf, errors="ignore")
                 if SELRE.search(ln) and ("value" in ln or "\"" in ln)]
        robot_sel[os.path.basename(rf)] = lines
    pos = sorted(os.path.basename(x).replace("Page.kt", "").replace(".kt", "")
                 for x in glob.glob(os.path.join(EFF, "pageObjects", "*.kt")))

    if as_json:
        print(json.dumps({
            "tool": "effscaffold", "found": True,
            "legacy_file": os.path.relpath(f, REPO), "method": method,
            "testrail": testrail, "ignored": ignored, "ignore_reason": ig_reason,
            "already_converted": conv, "legacy_body": block or "",
            "robot_selector_lines": robot_sel, "page_objects": pos,
        }))
        return
    print(f"# legacy: {os.path.relpath(f, REPO)} :: {method}\n")
    print("TestRail:", testrail or "(none found)")
    if ignored:
        print("⚠️ @Ignore'd upstream — " + ig_reason + " (still try to convert; park if it won't pass)")
    print("\n--- legacy body ---\n" + (block or ""))
    print("\n--- already converted? ---")
    print("⚠️ EXISTS in efficiency: " + ", ".join(conv) + " (do NOT re-convert)" if conv else "no efficiency test of this name (good)")
    print("\n--- robot selector lines (ids / text / testTags / content-desc) ---")
    for rf, lines in robot_sel.items():
        print(f"  [{rf}]")
        for ln in lines: print("    " + ln)
    print("\n--- efficiency coverage (page objects / selectors that may already model these screens) ---")
    print("  page objects:", ", ".join(pos))

if __name__ == "__main__":
    main()
