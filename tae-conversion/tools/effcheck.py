#!/usr/bin/env python3
"""
effcheck — static pre-flight for converted ui/efficiency tests (no device / no build needed).

Catches the errors that are checkable without compiling, so a device build/run is spent on real
behavior, not typos. Verifies a page object + its selector catalog against the live app source and
the harness authoring rules.

Checks:
  RES   getStringResource(R.string.X) → <string name="X"> exists in app res
  ID    ESPRESSO_BY_ID value → R.id name plausibly exists in app source
  TAG   COMPOSE_BY_TAG literal/constant → appears in app source (best-effort; flags unverifiable)
  NAV   (page object) registers a nav path with real steps OR a launch=LaunchConfig(...)   [gotcha B1]
  CAT   (page object) contains no inline SelectorStrategy. — selectors belong in the catalog [gotcha B2]
  VERB  moz* verbs used exist on BasePage
  TEXT  text-based selectors flagged (prefer tag/id/content-desc)                            [rule B5]

Usage:
  effcheck.py --app-root <fenix>/app/src/main --eff-root <...>/ui/efficiency FILE.kt [FILE.kt ...]
Exit code is non-zero if any FAIL. WARN never fails the run.
"""
import os, re, sys, glob, argparse, json

def load_string_names(app_root):
    names = set()
    for f in glob.glob(os.path.join(app_root, "res", "**", "strings*.xml"), recursive=True) + \
             glob.glob(os.path.join(app_root, "res", "values*", "*.xml"), recursive=True):
        try:
            for m in re.findall(r'<string[^>]*\bname="([^"]+)"', open(f, encoding="utf-8").read()):
                names.add(m)
        except Exception:
            pass
    return names

def grep_app(app_root, needle):
    # cheap fixed-string presence check across app source (kt/xml)
    for f in glob.glob(os.path.join(app_root, "**", "*.kt"), recursive=True):
        try:
            if needle in open(f, encoding="utf-8", errors="ignore").read():
                return True
        except Exception:
            pass
    return False

def basepage_verbs(eff_root):
    bp = os.path.join(eff_root, "helpers", "BasePage.kt")
    try:
        return set(re.findall(r"fun (moz[A-Za-z0-9_]+)", open(bp, encoding="utf-8").read()))
    except Exception:
        return set()

def check_file(path, strings, app_root, eff_root, verbs, tag_cache):
    txt = open(path, encoding="utf-8").read()
    p = path.replace("\\", "/")
    is_page = re.search(r"(^|/)pageObjects/", p) is not None
    is_test = re.search(r"(^|/)tests/", p) is not None
    res = []  # (level, msg)
    def add(l, m): res.append((l, m))

    if is_test:
        # MWS: BaseTest does not expose mockWebServer; a test class must declare the accessor itself.
        if re.search(r"\bmockWebServer\b", txt) and "fenixTestRule.mockWebServer" not in txt:
            add("FAIL", "MWS  uses mockWebServer but is missing "
                        "`private val mockWebServer get() = fenixTestRule.mockWebServer`")
        # IMP: TestAssetHelper members (extensions/props on MockWebServer) need importing even when
        # called on a receiver (mockWebServer.getGenericAsset(...)). Qualified TestAssetHelper.x is fine.
        for member in ("getGenericAsset", "firstForeignWebPageAsset", "pdfFormAsset",
                       "getLoremIpsumAsset", "getEnhancedTrackingProtectionAsset"):
            if not re.search(r"(?<![\w])" + member + r"(?![\w])", txt):
                continue
            imported = re.search(r"\bTestAssetHelper\." + member + r"\b", txt)  # import line OR qualified use
            if not imported:
                add("FAIL", f"IMP  {member} used without `import ...TestAssetHelper.{member}`")

    # DUP: duplicate fun names in the same file => Kotlin "conflicting overloads" at build (gotcha: a
    # test already converted upstream). Cheap to catch here instead of burning a build cycle.
    funs = re.findall(r"\bfun\s+([A-Za-z0-9_]+)\s*\(", txt)
    for n in sorted({f for f in funs if funs.count(f) > 1}):
        add("FAIL", f"DUP  fun {n}() defined {funs.count(n)}× in this file (conflicting overloads — already converted?)")

    # RES: string resources resolve
    for name in sorted(set(re.findall(r"R\.string\.([A-Za-z0-9_]+)", txt))):
        if name.startswith("mozac_"):
            continue  # android-components module strings; not in fenix app/src/main/res (effcheck doesn't scan AC)
        if strings and name not in strings:
            add("FAIL", f"RES  R.string.{name} not found in app res")
    # ID: espresso ids (value passed to toResourceId → R.id name)
    for m in re.findall(r"ESPRESSO_BY_ID[^)]*?value\s*=\s*\"([^\"]+)\"", txt):
        if not grep_app(app_root, '"' + m + '"') and not grep_app(app_root, "R.id." + m):
            add("WARN", f"ID   R.id/{m} not obviously present in app source (verify by hand)")
    # TAG: compose tags — best effort
    for m in re.findall(r"COMPOSE_BY_TAG[^)]*?value\s*=\s*\"([^\"]+)\"", txt):
        if m not in tag_cache:
            tag_cache[m] = grep_app(app_root, '"' + m + '"')
        if not tag_cache[m]:
            add("WARN", f"TAG  literal testTag \"{m}\" not found in app source (verify it's the real tag)")
    # TEXT rule
    n_text = len(re.findall(r"COMPOSE_BY_TEXT\b|ESPRESSO_BY_TEXT|UIAUTOMATOR_WITH_TEXT", txt))
    if n_text:
        add("INFO", f"TEXT {n_text} text-based selector(s) — ok only where no tag/id/content-desc exists (rule B5)")

    if is_page:
        # CAT (B2): no inline selectors in a page object
        if "SelectorStrategy." in txt:
            add("WARN", "CAT  inline Selector(...) in a page object — move it into the *Selectors catalog (gotcha B2)")
        # NAV (B1): registered edges must have steps OR a launch config
        for reg in re.findall(r"NavigationRegistry\.register\((.*?)\)\s*(?:\}|$)", txt, re.S):
            has_steps = re.search(r"steps\s*=\s*listOf\(\s*[^)\s]", reg)
            has_launch = "launch" in reg and "LaunchConfig" in reg
            if not has_steps and not has_launch:
                add("FAIL", "NAV  page registers an edge with empty steps and no launch=LaunchConfig(...) (gotcha B1)")
    # VERB: moz* verbs used exist on BasePage
    if verbs:
        for v in sorted(set(re.findall(r"\.(moz[A-Za-z0-9_]+)\(", txt))):
            if v not in verbs:
                add("FAIL", f"VERB .{v}() is not a BasePage verb")
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--app-root", required=True, help="path to <fenix>/app/src/main")
    ap.add_argument("--eff-root", required=True, help="path to .../ui/efficiency")
    ap.add_argument("--json", action="store_true", help="emit a structured JSON verdict instead of text")
    a = ap.parse_args()
    strings = load_string_names(a.app_root)
    verbs = basepage_verbs(a.eff_root)
    tag_cache = {}
    files_out, any_fail = [], False
    for f in a.files:
        rs = check_file(f, strings, a.app_root, a.eff_root, verbs, tag_cache)
        fails = [m for l, m in rs if l == "FAIL"]
        warns = [m for l, m in rs if l == "WARN"]
        infos = [m for l, m in rs if l == "INFO"]
        verdict = "FAIL" if fails else ("WARN" if warns else "PASS")
        any_fail = any_fail or bool(fails)
        files_out.append({"file": os.path.basename(f), "path": f, "verdict": verdict,
                          "fails": fails, "warns": warns, "infos": infos})
    if a.json:
        print(json.dumps({"tool": "effcheck", "ok": not any_fail,
                          "app_strings": len(strings), "basepage_verbs": len(verbs),
                          "files": files_out}))
    else:
        print(f"effcheck — {len(strings)} app strings, {len(verbs)} BasePage verbs loaded\n")
        for fo in files_out:
            print(f"[{fo['verdict']}] {fo['file']}")
            for m in fo["fails"]: print("   ✖", m)
            for m in fo["warns"]: print("   ⚠", m)
            for m in fo["infos"]: print("   ·", m)
            if fo["verdict"] == "PASS": print("   ✓ statically clean")
            print()
    sys.exit(1 if any_fail else 0)

if __name__ == "__main__":
    main()
