"""Tests for config/appium_caps.py — device auto-detection metadata.

Subprocess calls (xcrun simctl, adb) are mocked. Each test rebuilds the
mock so tests can't leak into each other.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

from config.appium_caps import (
    DeviceInfo,
    _parse_ios_runtime_version,
    _query_android_props,
    get_capabilities,
)


def _fake_subprocess(stdout: str, returncode: int = 0):
    """Return a fake subprocess.run callable that always yields the given stdout."""
    def _run(*args, **kwargs):
        return SimpleNamespace(stdout=stdout, returncode=returncode)
    return _run


# ── iOS runtime-key parser ─────────────────────────────────────────────────────

def test_parse_ios_runtime_version_simple():
    assert _parse_ios_runtime_version(
        "com.apple.CoreSimulator.SimRuntime.iOS-18-5"
    ) == "18.5"


def test_parse_ios_runtime_version_three_components():
    """iOS point releases like 17.5.2 must be preserved as 17.5.2, not truncated."""
    assert _parse_ios_runtime_version(
        "com.apple.CoreSimulator.SimRuntime.iOS-17-5-2"
    ) == "17.5.2"


def test_parse_ios_runtime_version_returns_none_on_unknown_shape():
    assert _parse_ios_runtime_version("garbage") is None
    assert _parse_ios_runtime_version("com.apple.CoreSimulator.SimRuntime.watchOS-10-0") is None


# ── iOS auto-detect flow ───────────────────────────────────────────────────────

def test_ios_auto_detect_populates_all_three_fields():
    """Regression: previously deviceName and platformVersion stayed at their
    hardcoded defaults even when auto-detection returned a different device.
    Only the UDID was resolved correctly."""
    fake_output = json.dumps({
        "devices": {
            "com.apple.CoreSimulator.SimRuntime.iOS-18-5": [
                {"name": "iPhone 16", "udid": "U1", "state": "Booted", "isAvailable": True}
            ]
        }
    })
    with patch("subprocess.run", side_effect=_fake_subprocess(fake_output)):
        caps = get_capabilities(platform="ios", udid="auto")

    assert caps["appium:deviceName"]      == "iPhone 16"
    assert caps["appium:platformVersion"] == "18.5"
    assert caps["appium:udid"]            == "U1"


def test_ios_cli_override_beats_auto_detected_value():
    """If the user explicitly passes --device-name, that must win over the
    auto-detected value."""
    fake_output = json.dumps({
        "devices": {
            "com.apple.CoreSimulator.SimRuntime.iOS-18-5": [
                {"name": "iPhone 16", "udid": "U1", "state": "Booted", "isAvailable": True}
            ]
        }
    })
    with patch("subprocess.run", side_effect=_fake_subprocess(fake_output)):
        caps = get_capabilities(
            platform="ios", udid="auto",
            device_name="My Custom Name", platform_version="17.0",
        )

    assert caps["appium:deviceName"]      == "My Custom Name"
    assert caps["appium:platformVersion"] == "17.0"
    assert caps["appium:udid"]            == "U1"   # still auto-detected


def test_ios_env_var_beats_auto_detected_but_loses_to_cli(monkeypatch):
    """Precedence order: CLI arg > env var > auto-detected > hardcoded default."""
    fake_output = json.dumps({
        "devices": {
            "com.apple.CoreSimulator.SimRuntime.iOS-18-5": [
                {"name": "iPhone 16", "udid": "U1", "state": "Booted", "isAvailable": True}
            ]
        }
    })
    monkeypatch.setenv("DEVICE_NAME",      "env-name")
    monkeypatch.setenv("PLATFORM_VERSION", "16.0")

    with patch("subprocess.run", side_effect=_fake_subprocess(fake_output)):
        # CLI arg absent → env wins over auto-detect.
        caps = get_capabilities(platform="ios", udid="auto")

    assert caps["appium:deviceName"]      == "env-name"
    assert caps["appium:platformVersion"] == "16.0"


def test_ios_explicit_udid_falls_back_to_default_metadata():
    """If the user passes an explicit UDID (not 'auto'), we don't run simctl —
    so name/version have no detected value and must fall through to defaults."""
    with patch("subprocess.run") as sp:
        caps = get_capabilities(platform="ios", udid="EXPLICIT-UDID")
        sp.assert_not_called()   # no auto-detect when UDID is explicit

    # Defaults from _IOS_DEFAULTS take over.
    assert caps["appium:udid"] == "EXPLICIT-UDID"
    assert caps["appium:deviceName"]      == "iPhone 15"   # hardcoded default
    assert caps["appium:platformVersion"] == "17.5"        # hardcoded default


# ── Android auto-detect flow ───────────────────────────────────────────────────

def test_android_query_props_parses_getprop_output():
    """getprop calls return version on line 1, model on line 2."""
    fake_stdout = "14\nPixel 7\n"
    with patch("subprocess.run", side_effect=_fake_subprocess(fake_stdout)):
        info = _query_android_props("emulator-5554")
    assert info == DeviceInfo(udid="emulator-5554",
                              name="Pixel 7",
                              platform_version="14")


def test_android_query_props_returns_udid_only_when_getprop_fails():
    """A subprocess failure must not crash the pipeline — Appium still gets
    a UDID and can proceed. Session logs just lose the model/version."""
    def _boom(*a, **kw):
        raise FileNotFoundError("adb missing")
    with patch("subprocess.run", side_effect=_boom):
        info = _query_android_props("emulator-5554")
    assert info == DeviceInfo(udid="emulator-5554", name=None, platform_version=None)


def test_android_auto_detect_populates_all_three_fields():
    """Regression: previously deviceName stayed at 'emulator-5554' and
    platformVersion stayed at '14' regardless of the actual device."""
    call_count = {"n": 0}

    def _run(*args, **kwargs):
        call_count["n"] += 1
        # First call: `adb devices` → serial list
        if call_count["n"] == 1:
            return SimpleNamespace(
                stdout="List of devices attached\nemu-99\tdevice\n",
                returncode=0,
            )
        # Second call: `adb -s <serial> shell getprop ...`
        return SimpleNamespace(stdout="13\nPixel 8\n", returncode=0)

    with patch("subprocess.run", side_effect=_run):
        caps = get_capabilities(platform="android", udid="auto")

    assert caps["appium:udid"]            == "emu-99"
    assert caps["appium:deviceName"]      == "Pixel 8"
    assert caps["appium:platformVersion"] == "13"


def test_android_cli_override_beats_auto_detected_value():
    def _run(*args, **kwargs):
        cmd = args[0]
        if cmd[:2] == ["adb", "devices"]:
            return SimpleNamespace(
                stdout="List of devices attached\nemu-99\tdevice\n",
                returncode=0,
            )
        return SimpleNamespace(stdout="13\nPixel 8\n", returncode=0)

    with patch("subprocess.run", side_effect=_run):
        caps = get_capabilities(
            platform="android", udid="auto",
            device_name="my-emu", platform_version="12",
        )

    assert caps["appium:deviceName"]      == "my-emu"
    assert caps["appium:platformVersion"] == "12"
    assert caps["appium:udid"]            == "emu-99"


def test_android_explicit_udid_still_enriches_via_getprop():
    """An explicit serial should still get name/version via getprop — the
    only thing we skip is the `adb devices` scan."""
    with patch("subprocess.run", side_effect=_fake_subprocess("13\nPixel 8\n")):
        caps = get_capabilities(platform="android", udid="emu-77")

    assert caps["appium:udid"]            == "emu-77"
    assert caps["appium:deviceName"]      == "Pixel 8"
    assert caps["appium:platformVersion"] == "13"
