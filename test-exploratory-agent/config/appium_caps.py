"""
config/appium_caps.py

Builds Appium capabilities for iOS or Android.

Resolution order for every setting:
    CLI args  →  environment variables  →  platform defaults

iOS quick-start (auto-detects booted simulator):
    python agent/loop.py --platform ios --objective "..."

Android quick-start (auto-detects connected device/emulator):
    python agent/loop.py --platform android --objective "..."

Supported env vars:
    PLATFORM             ios | android       (default: ios)
    DEVICE_UDID          UDID or 'auto'      (default: auto)
    DEVICE_NAME          device display name (default: see per-platform below)
    PLATFORM_VERSION     OS version string   (default: see per-platform below)
    APP_ID               bundle ID / package (default: see per-platform below)
    APP_ACTIVITY         Android only — main activity class
    APPIUM_URL           full Appium URL     (default: http://127.0.0.1:4723)
"""

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Optional


# ── Appium server ──────────────────────────────────────────────────────────────

APPIUM_URL = os.getenv("APPIUM_URL", "http://127.0.0.1:4723")


# ── Platform defaults ──────────────────────────────────────────────────────────

_IOS_DEFAULTS = {
    "device_name":      "iPhone 15",
    "platform_version": "17.5",
    "app_id":           "org.mozilla.ios.Fennec",
    # See README "Reference app IDs" for other Firefox iOS bundle IDs.
}

_ANDROID_DEFAULTS = {
    "device_name":      "emulator-5554",
    "platform_version": "14",
    "app_id":           "org.mozilla.firefox",
    # Firefox Android's launcher across all flavors is an activity-alias
    # named "${applicationId}.App" (verified against the Fenix
    # AndroidManifest.xml). We derive app_activity dynamically from the
    # resolved app_id in get_capabilities() — setting --app-id automatically
    # picks the right activity, no need to also pass --app-activity or
    # APP_ACTIVITY. See README "Reference app IDs" for the full list of
    # Firefox Android package names.
}


# ── Device auto-detection ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class DeviceInfo:
    """Everything auto-detect can learn about a device.

    name / platform_version are Optional because when the user passes an
    explicit UDID/serial we skip auto-detection and don't know these values —
    the caller then falls back to CLI/env/default in that order.
    """
    udid:             str
    name:             Optional[str] = None
    platform_version: Optional[str] = None


def _parse_ios_runtime_version(runtime_key: str) -> Optional[str]:
    """simctl runtime keys look like 'com.apple.CoreSimulator.SimRuntime.iOS-18-5'
    or '.iOS-17-5-2'. Return the dot-separated version, or None if the key
    doesn't match the expected shape."""
    marker = "SimRuntime.iOS-"
    if marker not in runtime_key:
        return None
    return runtime_key.split(marker, 1)[1].replace("-", ".")


def _resolve_ios_device(udid: str) -> DeviceInfo:
    """Resolves 'auto' to the first booted iOS simulator's full metadata.
    An explicit UDID short-circuits — we don't know that device's name/version."""
    if udid != "auto":
        return DeviceInfo(udid=udid)
    try:
        result = subprocess.run(
            ["xcrun", "simctl", "list", "devices", "booted", "--json"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "xcrun not found — Xcode command line tools are not installed.\n"
            "  Install with:  xcode-select --install"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "xcrun simctl timed out after 10s — Xcode may be stuck or corrupted.\n"
            "  Try:  xcrun simctl help  (to reproduce), or restart Xcode."
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"xcrun returned invalid JSON — this is unexpected.\n"
            f"  Stdout was: {result.stdout[:200]!r}\n"
            f"  Error: {e}"
        )
    for runtime_key, devices in data.get("devices", {}).items():
        for d in devices:
            if d.get("state") == "Booted":
                version = _parse_ios_runtime_version(runtime_key)
                print(f"[config] Auto-detected iOS simulator: {d['name']} "
                      f"(iOS {version or '?'}, UDID {d['udid']})")
                return DeviceInfo(udid=d["udid"], name=d["name"], platform_version=version)
    raise RuntimeError(
        "No booted iOS simulator found.\n"
        "  Boot one:  xcrun simctl boot 'iPhone 15'\n"
        "  Or open:   Xcode → Window → Devices and Simulators"
    )


def _query_android_props(serial: str) -> DeviceInfo:
    """Best-effort enrichment of a serial via `adb -s <serial> shell getprop`.
    Any failure returns the serial alone — Appium still works, only session
    logs lose the human-readable model/version."""
    try:
        result = subprocess.run(
            ["adb", "-s", serial, "shell",
             "getprop ro.build.version.release; getprop ro.product.model"],
            capture_output=True, text=True, timeout=5,
        )
        lines   = [l.strip() for l in result.stdout.strip().splitlines()]
        version = lines[0] if len(lines) >= 1 and lines[0] else None
        name    = lines[1] if len(lines) >= 2 and lines[1] else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        version = None
        name    = None
    return DeviceInfo(udid=serial, name=name, platform_version=version)


def _resolve_android_device(udid: str) -> DeviceInfo:
    """Resolves 'auto' to the first connected device/emulator's full metadata.
    An explicit serial still gets enriched via getprop (best-effort)."""
    if udid != "auto":
        return _query_android_props(udid)
    try:
        result = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "adb not found — Android SDK Platform Tools are not installed.\n"
            "  Install with:  brew install --cask android-platform-tools"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "adb timed out after 10s — the adb server may be stuck.\n"
            "  Try:  adb kill-server && adb start-server"
        )
    for line in result.stdout.strip().splitlines()[1:]:   # skip header
        if "\tdevice" in line:
            serial = line.split("\t")[0].strip()
            info   = _query_android_props(serial)
            print(f"[config] Auto-detected Android device: {info.name or serial} "
                  f"(Android {info.platform_version or '?'}, serial {serial})")
            return info
    raise RuntimeError(
        "No connected Android device or running emulator found.\n"
        "  Check:  adb devices\n"
        "  Start an emulator from Android Studio or: emulator -avd <name>"
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def get_capabilities(
    platform:         str = None,
    udid:             str = None,
    device_name:      str = None,
    platform_version: str = None,
    app_id:           str = None,
) -> dict:
    """
    Returns Appium desired capabilities for iOS or Android.

    Every parameter is optional. Resolution order:
        function argument → environment variable → platform default
    """
    resolved_platform = (platform or os.getenv("PLATFORM", "ios")).lower()

    if resolved_platform not in ("ios", "android"):
        raise ValueError(
            f"Unknown platform: '{resolved_platform}'. Use 'ios' or 'android'."
        )

    # Resolution order for name/version: CLI arg → env var → auto-detected → default.
    # The auto-detected slot ensures logs don't lie when the user only sets --udid auto.

    if resolved_platform == "ios":
        d                = _IOS_DEFAULTS
        resolved_udid    = udid    or os.getenv("DEVICE_UDID", "auto")
        resolved_app_id  = app_id  or os.getenv("APP_ID",      d["app_id"])
        info             = _resolve_ios_device(resolved_udid)
        resolved_name    = (device_name      or os.getenv("DEVICE_NAME")
                            or info.name or d["device_name"])
        resolved_version = (platform_version or os.getenv("PLATFORM_VERSION")
                            or info.platform_version or d["platform_version"])

        caps = {
            "platformName":                  "iOS",
            "appium:automationName":         "XCUITest",
            "appium:deviceName":             resolved_name,
            "appium:platformVersion":        resolved_version,
            "appium:udid":                   info.udid,
            "appium:bundleId":               resolved_app_id,
            "appium:noReset":                True,
            "appium:newCommandTimeout":      120,
            "appium:screenshotQuality":      1,
            "appium:waitForQuiescence":      False,
        }
        resolved_udid = info.udid

    else:  # android
        d                    = _ANDROID_DEFAULTS
        resolved_udid        = udid    or os.getenv("DEVICE_UDID", "auto")
        resolved_app_id      = app_id  or os.getenv("APP_ID",      d["app_id"])
        # Launcher activity: always "${appId}.App" (activity-alias) unless overridden.
        resolved_activity    = os.getenv("APP_ACTIVITY", f"{resolved_app_id}.App")
        info                 = _resolve_android_device(resolved_udid)
        resolved_name        = (device_name      or os.getenv("DEVICE_NAME")
                                or info.name or d["device_name"])
        resolved_version     = (platform_version or os.getenv("PLATFORM_VERSION")
                                or info.platform_version or d["platform_version"])

        caps = {
            "platformName":                          "Android",
            "appium:automationName":                 "UiAutomator2",
            "appium:deviceName":                     resolved_name,
            "appium:platformVersion":                resolved_version,
            "appium:udid":                           info.udid,
            "appium:appPackage":                     resolved_app_id,
            "appium:appActivity":                    resolved_activity,
            "appium:noReset":                        True,
            "appium:newCommandTimeout":              120,
            "appium:uiautomator2ServerLaunchTimeout": 60000,
        }
        resolved_udid = info.udid

    print(f"[config] Platform: {resolved_platform.upper()} | App: {resolved_app_id} | Device: {resolved_udid}")
    return caps
