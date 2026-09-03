"""
setup_check.py

Run this BEFORE running the agent to verify your environment is ready.
Detects which platforms you have set up (iOS via Xcode, Android via adb)
and runs the relevant toolchain checks. Cross-platform checks always run
(Python packages, Appium, API key).

Usage:
    python setup_check.py
"""

import json
import os
import socket
import subprocess
import sys

# Load .env if python-dotenv is available so ANTHROPIC_API_KEY set only
# in .env (and not exported to the shell) is still visible to this script.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass   # will be flagged in the Python-packages check below

# Firefox variants to detect
IOS_FIREFOX_BUNDLES = [
    "org.mozilla.ios.Fennec",       # Nightly
    "org.mozilla.ios.FirefoxBeta",  # Beta
    "org.mozilla.ios.Firefox",      # Release
]

ANDROID_FIREFOX_PACKAGES = [
    "org.mozilla.fenix",             # Nightly
    "org.mozilla.firefox_beta",      # Beta
    "org.mozilla.firefox",           # Release
]

APPIUM_PORT = 4723


# ── Helpers ────────────────────────────────────────────────────────────────────

def run(cmd: list) -> tuple[int, str, str]:
    """Run a command safely — never raise; return (rc, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 127, "", ""


def check(label: str, ok: bool, detail: str = "", fix: str = "") -> bool:
    icon = "✅" if ok else "❌"
    print(f"  {icon}  {label}")
    if detail:
        print(f"       {detail}")
    if not ok and fix:
        print(f"       FIX: {fix}")
    return ok


def detect_toolchains() -> tuple[bool, bool]:
    """Which mobile platform toolchains does the user have installed?"""
    has_xcode = run(["xcode-select", "--print-path"])[0] == 0
    has_adb   = run(["adb", "version"])[0] == 0
    return has_xcode, has_adb


# ── Per-platform checks ────────────────────────────────────────────────────────

def check_ios() -> bool:
    """iOS-specific checks. Returns True if all pass."""
    ok = True

    code, out, _ = run(["xcode-select", "--print-path"])
    ok = check("Xcode CLI tools", code == 0, out.strip(),
               "xcode-select --install") and ok

    code, _, _ = run(["xcrun", "simctl", "help"])
    ok = check("xcrun simctl available", code == 0, "",
               "Install Xcode from App Store") and ok

    code, out, _ = run(["xcrun", "simctl", "list", "devices", "booted", "--json"])
    booted_name = ""
    if code == 0:
        try:
            data = json.loads(out)
            for _rt, devs in data.get("devices", {}).items():
                for d in devs:
                    if d.get("state") == "Booted":
                        booted_name = f"{d['name']} ({d['udid'][:8]}...)"
                        break
                if booted_name:
                    break
        except (json.JSONDecodeError, KeyError):
            pass
    ok = check("Simulator is booted", bool(booted_name), booted_name,
               "xcrun simctl boot <device>  OR  open Xcode → Simulator") and ok

    if booted_name:
        code, out, _ = run(["xcrun", "simctl", "listapps", "booted"])
        installed = [b for b in IOS_FIREFOX_BUNDLES if b in out]
        ok = check("Firefox iOS installed on simulator",
                   bool(installed),
                   f"found: {installed}" if installed else "",
                   "Install a Firefox iOS build via Xcode  OR\n"
                   "       xcrun simctl install booted /path/to/Firefox.app") and ok

    code, out, _ = run(["ffmpeg", "-version"])
    ok = check("ffmpeg installed (for session video)",
               code == 0,
               out.splitlines()[0] if code == 0 else "",
               "brew install ffmpeg") and ok

    return ok


def check_android() -> bool:
    """Android-specific checks. Returns True if all pass."""
    ok = True

    code, out, _ = run(["adb", "version"])
    ok = check("adb (Android SDK Platform Tools)",
               code == 0,
               out.splitlines()[0] if code == 0 else "",
               "Install Android SDK  OR  brew install --cask android-platform-tools") and ok

    devices: list[str] = []
    code, out, _ = run(["adb", "devices"])
    if code == 0:
        for line in out.splitlines()[1:]:   # skip header
            if "\tdevice" in line:
                devices.append(line.split("\t")[0])
    ok = check("Android device/emulator connected",
               bool(devices),
               f"found: {devices}" if devices else "",
               "Start an emulator or connect a device with USB debugging enabled") and ok

    if devices:
        code, out, _ = run(["adb", "shell", "pm", "list", "packages", "org.mozilla"])
        installed = [p for p in ANDROID_FIREFOX_PACKAGES if p in out]
        ok = check("Firefox Android installed",
                   bool(installed),
                   f"found: {installed}" if installed else "",
                   "adb install /path/to/firefox.apk") and ok

    return ok


# ── Cross-platform checks ─────────────────────────────────────────────────────

def check_python_packages() -> bool:
    ok = True
    packages = {
        "appium-python-client": "appium",
        "anthropic":            "anthropic",
        "selenium":             "selenium",
        "python-dotenv":        "dotenv",
    }
    for pkg, import_name in packages.items():
        try:
            __import__(import_name)
            ok = check(pkg, True) and ok
        except ImportError:
            ok = check(pkg, False, fix=f"pip install {pkg}") and ok
    return ok


def check_appium(has_xcode: bool, has_adb: bool) -> bool:
    ok = True

    code, out, _ = run(["appium", "--version"])
    ok = check("Appium CLI installed",
               code == 0,
               out.strip() if code == 0 else "",
               "npm install -g appium") and ok

    if code == 0:
        code2, out2, err2 = run(["appium", "driver", "list", "--installed"])
        combined = (out2 + err2).lower()
        if has_xcode:
            ok = check("XCUITest driver (iOS)",
                       "xcuitest" in combined,
                       "",
                       "appium driver install xcuitest") and ok
        if has_adb:
            ok = check("UiAutomator2 driver (Android)",
                       "uiautomator2" in combined,
                       "",
                       "appium driver install uiautomator2") and ok

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    server_running = sock.connect_ex(("127.0.0.1", APPIUM_PORT)) == 0
    sock.close()
    ok = check(f"Appium server running on port {APPIUM_PORT}",
               server_running,
               f"http://127.0.0.1:{APPIUM_PORT}" if server_running else "",
               f"Run in a separate terminal:  appium --port {APPIUM_PORT}") and ok

    return ok


def check_api_key() -> bool:
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return check("ANTHROPIC_API_KEY set",
                 has_key,
                 "✓ found" if has_key else "",
                 "Add to .env:  ANTHROPIC_API_KEY=sk-ant-...\n"
                 "       Or export:  export ANTHROPIC_API_KEY=sk-ant-...")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    print("\n🔍 Firefox Mobile Agent — Environment Check\n" + "=" * 50)

    has_xcode, has_adb = detect_toolchains()

    if not has_xcode and not has_adb:
        print("\n  ⚠️  Neither Xcode nor adb detected. Install at least one:")
        print("       iOS:      xcode-select --install")
        print("       Android:  brew install --cask android-platform-tools")
        return 1

    all_ok = True
    section = 1

    if has_xcode:
        print(f"\n[{section}] iOS toolchain")
        all_ok = check_ios() and all_ok
        section += 1

    if has_adb:
        print(f"\n[{section}] Android toolchain")
        all_ok = check_android() and all_ok
        section += 1

    print(f"\n[{section}] Python packages")
    all_ok = check_python_packages() and all_ok
    section += 1

    print(f"\n[{section}] Appium")
    all_ok = check_appium(has_xcode, has_adb) and all_ok
    section += 1

    print(f"\n[{section}] API key")
    all_ok = check_api_key() and all_ok

    # Summary
    print("\n" + "=" * 50)
    if all_ok:
        print("✅  All checks passed! Ready to run the agent.\n")
        if has_xcode:
            print("    Example (iOS):")
            print('    python agent/loop.py --objective "Explore private browsing mode"')
        if has_adb:
            print("\n    Example (Android):")
            print('    python agent/loop.py --platform android --objective "Explore tabs"')
    else:
        print("❌  Some checks failed. Fix the issues above before running the agent.")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
