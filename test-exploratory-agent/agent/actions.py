"""
agent/actions.py

Gives the agent its "hands":
  - tap, type_text, type_url, swipe, long_press
  - rotate, pinch, background_app, press_home, shake
  - key_press, press_back, wait

Every action logs what it did and returns a result dict so the agent loop
can track history.
"""

import time
from typing import Optional, Union
from urllib.parse import urlparse

from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.extensions.android.nativekey import AndroidKey
from selenium.common.exceptions import WebDriverException, NoSuchElementException
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput

from agent.perception import UIElement


def _hostname_matches_allowlist(hostname: str, allowlist: list) -> bool:
    """Return True if `hostname` exactly matches any entry OR is a subdomain
    of any entry (host-suffix match). Empty hostname never matches.

    Example: allowlist=['firefox.com', 'localhost']
      → 'firefox.com' ✓, 'blog.firefox.com' ✓, 'evilfirefox.com' ✗, 'localhost' ✓
    """
    if not hostname:
        return False
    hostname = hostname.lower()
    for entry in allowlist:
        entry = entry.strip().lower().lstrip(".")
        if not entry:
            continue
        if hostname == entry or hostname.endswith("." + entry):
            return True
    return False


def _is_secure_field(el) -> bool:
    """Best-effort detection: does the given element look like a password /
    secure text field? Covers native iOS/Android — WebView `<input type=password>`
    is NOT reliably detectable this way and is documented as such."""
    # iOS: XCUIElementTypeSecureTextField shows up under the `type` attribute.
    try:
        t = el.get_attribute("type") or ""
        if "Secure" in t:
            return True
    except WebDriverException:
        pass
    # Android: EditText with password="true" (or in some versions, the class
    # itself carries a "Password" hint).
    try:
        p = el.get_attribute("password") or ""
        if p.lower() == "true":
            return True
    except WebDriverException:
        pass
    return False


# ── Result structure ───────────────────────────────────────────────────────────

def ok(action: str, detail: str = "") -> dict:
    return {"status": "ok", "action": action, "detail": detail, "ts": time.time()}

def err(action: str, error: str) -> dict:
    return {"status": "error", "action": action, "error": error, "ts": time.time()}


# ── Actions class ──────────────────────────────────────────────────────────────
#
# TECHNICAL DEBT — legacy Appium-Python-Client 3.x APIs still in use:
#
# The APIs below were REMOVED in Appium-Python-Client 4.0.0 (empirically
# verified on 4.5.1 and 5.3.1). Some also rely on Appium *server*-side
# endpoints (like /touch/perform) that the modern XCUITest/UiAutomator2
# drivers no longer expose:
#   - driver.tap([(x,y)])      (tap coordinates, twice)   — method removed
#   - el.tap()                 (type_url)                 — method removed
#   - driver.swipe(x1,y1,...)  (swipe)                    — method removed
#   - driver.background_app()  (background_app)           — method removed
#   - driver.shake()           (shake)                    — method removed
#
# MIGRATED: long_press used TouchAction, which raised "Unhandled endpoint
# /touch/perform" on every call in real Appium 2.x XCUITest sessions.
# Rewritten to selenium W3C ActionBuilder — cross-platform, no server-side
# legacy endpoint. See long_press() below.
#
# requirements.txt still pins Appium-Python-Client to <4.0 because the
# other methods above would fail to import on 4.x. To lift the pin, migrate
# each method to either:
#   - W3C Actions via selenium.webdriver.common.actions.action_builder, OR
#   - driver.execute_script("mobile: X", {...})   (e.g. "mobile: tap",
#     "mobile: swipeGesture", "mobile: backgroundApp")
#
# Each replacement must be validated on a real iOS simulator and Android
# emulator — mobile: gesture behavior differs subtly between XCUITest and
# UiAutomator2. Do not lift the pin without that validation.
# ─────────────────────────────────────────────────────────────────────────────

class Actions:

    def __init__(self, driver, allowed_domains: Optional[list] = None):
        """`allowed_domains`: opt-in host-suffix allowlist for type_url().
        When None (default), no URL restriction — matches historical behavior
        and preserves the exploratory-testing use case. When provided, any
        URL navigation to a host outside the list is refused with err()."""
        self.driver          = driver
        self.allowed_domains = allowed_domains or None   # normalize [] → None

    def tap(self, target: Union[UIElement, tuple, list, str]) -> dict:
        """
        Taps on:
          - a UIElement (uses center coordinates)
          - an (x, y) tuple or [x, y] list (raw coordinates — JSON has no tuple type,
            so the LLM's coordinate fallback always arrives as a list)
          - a string (finds element by accessibility ID or label)
        """
        try:
            if isinstance(target, UIElement):
                x, y = target.center
                self.driver.tap([(x, y)])
                return ok("tap", f"element '{target.name or target.label}' at ({x},{y})")

            elif (isinstance(target, (tuple, list))
                  and len(target) == 2
                  and all(isinstance(v, (int, float)) for v in target)):
                x, y = int(target[0]), int(target[1])
                self.driver.tap([(x, y)])
                return ok("tap", f"coordinates ({x},{y})")

            elif isinstance(target, str):
                # Try accessibility ID first (works on both iOS and Android),
                # then XPath covering iOS attrs (name/label) and
                # Android attrs (content-desc/text)
                try:
                    el = self.driver.find_element(AppiumBy.ACCESSIBILITY_ID, target)
                except NoSuchElementException:
                    el = self.driver.find_element(
                        AppiumBy.XPATH,
                        f'//*[@content-desc="{target}" or @text="{target}"'
                        f' or @label="{target}" or @name="{target}"]'
                    )
                el.click()
                return ok("tap", f"by name/label '{target}'")

            else:
                # Unknown target type — return a clear error instead of falling
                # through and returning None implicitly.
                return err("tap", f"unsupported target type: {type(target).__name__}")

        except WebDriverException as e:
            return err("tap", str(e))

    def type_text(self, text: str, clear_first: bool = True) -> dict:
        """
        Types text into the currently focused input field.
        Optionally clears existing content first.

        Refuses to write into secure/password fields (best-effort check on the
        focused element's attributes). Prompt-side rules also tell the LLM
        never to type credentials — this is the Python-side backstop.
        """
        try:
            active = self.driver.switch_to.active_element
            if _is_secure_field(active):
                return err(
                    "type_text",
                    "refused: focused element looks like a secure/password field",
                )
            if clear_first:
                active.clear()
            active.send_keys(text)
            return ok("type_text", f"typed '{text}'")
        except WebDriverException as e:
            return err("type_text", str(e))

    def type_url(self, url: str) -> dict:
        """
        Taps the address bar and types a URL, then submits.
        Handles the common Firefox iOS URL bar patterns.

        When `allowed_domains` was set on Actions.__init__, any host outside
        the allowlist is refused before Appium is touched. This is the Python-
        side enforcement of the domain policy (prompt-side rules can be
        bypassed by a prompt injection — this can't).

        TODO: URL bar detection has only been validated on Firefox iOS. The
        `url_bar_ids` list and XPath fallback are iOS-flavored (use `@label`).
        Firefox Android's toolbar uses different accessibility patterns
        (likely `content-desc` on views like `mozac_browser_toolbar_url_view`).
        Verify against a Fenix session and extend the ID list + XPath when
        Android becomes a supported target.
        """
        if self.allowed_domains:
            parsed = urlparse(url if "://" in url else f"http://{url}")
            host = parsed.hostname or ""
            if not _hostname_matches_allowlist(host, self.allowed_domains):
                return err(
                    "type_url",
                    f"refused: {host or url!r} not in --allowed-domains "
                    f"({', '.join(self.allowed_domains)})",
                )
        try:
            # Try to tap the URL bar (Firefox uses several possible identifiers).
            # AddressToolbar.address first — observed in real Firefox iOS sessions;
            # historical IDs kept as fallback for older builds and other Firefox
            # variants.
            url_bar_ids = [
                "AddressToolbar.address",
                "url", "address", "Search or enter address",
                "URLBar", "AddressBar", "TabLocationView",
            ]
            tapped = False
            for id_ in url_bar_ids:
                try:
                    el = self.driver.find_element(AppiumBy.ACCESSIBILITY_ID, id_)
                    el.tap()
                    tapped = True
                    break
                except WebDriverException:
                    continue

            if not tapped:
                # Fallback: XPath. The observed AddressToolbar.address has an
                # empty label, so we also match by name-contains for it and
                # keep the label-based check for other variants.
                el = self.driver.find_element(
                    AppiumBy.XPATH,
                    '//*[contains(@name,"AddressToolbar") or contains(@name,"URLBar") '
                    'or contains(@label,"address") or contains(@label,"Search")]'
                )
                el.click()

            time.sleep(0.5)
            active = self.driver.switch_to.active_element
            active.clear()
            active.send_keys(url)
            # Submit with Enter key (key code 40 = Return on iOS)
            # self.driver.execute_script("mobile: type", {"text": "\n"})
            active.send_keys("\n")
            return ok("type_url", f"navigated to '{url}'")

        except WebDriverException as e:
            return err("type_url", str(e))

    def swipe(self, direction: str, distance: float = 0.5) -> dict:
        """
        Swipes in a direction: 'up', 'down', 'left', 'right'.
        distance: fraction of screen (0.0 - 1.0).
        """
        try:
            size = self.driver.get_window_size()
            w, h = size["width"], size["height"]
            cx, cy = w // 2, h // 2

            deltas = {
                "up":    (0, -int(h * distance)),
                "down":  (0,  int(h * distance)),
                "left":  (-int(w * distance), 0),
                "right": ( int(w * distance), 0),
            }
            if direction not in deltas:
                return err("swipe", f"Unknown direction '{direction}'. Use: up/down/left/right")

            dx, dy = deltas[direction]
            self.driver.swipe(cx, cy, cx + dx, cy + dy, duration=400)
            return ok("swipe", f"swiped {direction} ({distance*100:.0f}% of screen)")

        except WebDriverException as e:
            return err("swipe", str(e))

    def long_press(self, target: Union[UIElement, str], duration_ms: int = 1000) -> dict:
        """Long presses an element via the W3C Actions API (touch pointer).

        Uses selenium's ActionBuilder with a PointerInput of type
        POINTER_TOUCH — cross-platform (XCUITest + UiAutomator2), no
        dependency on the legacy /touch/perform Appium endpoint which the
        modern XCUITest driver removed (that was returning "Unhandled
        endpoint" for every long_press in real sessions).
        """
        try:
            if isinstance(target, UIElement):
                x, y = target.center
            else:
                el  = self.driver.find_element(AppiumBy.ACCESSIBILITY_ID, target)
                loc = el.location
                sz  = el.size
                x = loc["x"] + sz["width"]  // 2
                y = loc["y"] + sz["height"] // 2

            touch   = PointerInput(interaction.POINTER_TOUCH, "touch")
            actions = ActionBuilder(self.driver, mouse=touch)
            actions.pointer_action \
                .move_to_location(x, y) \
                .pointer_down() \
                .pause(duration_ms / 1000.0) \
                .pointer_up()
            actions.perform()
            return ok("long_press", f"long pressed at ({x},{y}) for {duration_ms}ms")

        except WebDriverException as e:
            return err("long_press", str(e))

    def pinch(self, scale: float = 0.5) -> dict:
        """
        Pinches the screen. scale < 1 = zoom out, scale > 1 = zoom in.

        TODO: `mobile: pinch` may be legacy — modern XCUITest and UiAutomator2
        expose `mobile: pinchOpenGesture` / `mobile: pinchCloseGesture`
        instead. Not currently exposed to the LLM (not in the loop.py
        dispatch), so latent. Verify + migrate if this is ever wired in.
        """
        try:
            self.driver.execute_script("mobile: pinch", {
                "scale": scale,
                "velocity": -1 if scale < 1 else 1
            })
            action = "zoom out" if scale < 1 else "zoom in"
            return ok("pinch", f"{action} (scale={scale})")
        except WebDriverException as e:
            return err("pinch", str(e))

    def rotate(self, orientation: str = "LANDSCAPE") -> dict:
        """Rotates the device. orientation: 'LANDSCAPE' or 'PORTRAIT'."""
        try:
            self.driver.orientation = orientation.upper()
            time.sleep(0.8)  # wait for rotation animation
            return ok("rotate", f"rotated to {orientation}")
        except WebDriverException as e:
            return err("rotate", str(e))

    def background_app(self, seconds: float = 2.0) -> dict:
        """Sends app to background for N seconds, then brings it back."""
        try:
            self.driver.background_app(seconds)
            return ok("background_app", f"backgrounded for {seconds}s")
        except WebDriverException as e:
            return err("background_app", str(e))

    def press_home(self) -> dict:
        """
        Presses the iOS home button.

        TODO: iOS-only — uses `mobile: pressButton` (XCUITest). Android needs
        `mobile: shell` with `input keyevent KEYCODE_HOME`. Not currently in
        the LLM dispatch (loop.py); when it is, add platform detection.
        """
        try:
            self.driver.execute_script("mobile: pressButton", {"name": "home"})
            return ok("press_home")
        except WebDriverException as e:
            return err("press_home", str(e))

    def shake(self) -> dict:
        """
        Shakes the device (useful for undo/feedback triggers).

        TODO: iOS-only — `driver.shake()` uses XCUIDeviceShakeAction. No
        native Android equivalent exists (real devices can't be programmatically
        shaken). Not currently exposed to the LLM; when it is, either restrict
        to iOS or document the Android no-op.
        """
        try:
            self.driver.shake()
            return ok("shake")
        except WebDriverException as e:
            return err("shake", str(e))

    def key_press(self, key: str = "ENTER") -> dict:
        """
        Sends a key event to the currently focused element.
        Common keys: ENTER, RETURN, BACK_SPACE, TAB.

        TODO: `driver.press_keycode()` is an Android-only extension. On iOS
        this call will fail. The fallback branch (`active.send_keys(key)`)
        works on both platforms — consider using it exclusively, or add
        platform detection so ENTER on iOS routes through send_keys.
        """
        key_map = {
            "ENTER":      AndroidKey.ENTER,
            "RETURN":     AndroidKey.ENTER,
            "BACK_SPACE": AndroidKey.DEL,
            "TAB":        AndroidKey.TAB,
        }
        try:
            code = key_map.get(key.upper())
            if code:
                self.driver.press_keycode(code)
            else:
                # Fallback: send as text to focused element
                self.driver.switch_to.active_element.send_keys(key)
            return ok("key_press", f"pressed {key}")
        except WebDriverException as e:
            return err("key_press", str(e))

    def press_back(self) -> dict:
        """
        Presses the Android hardware Back button (driver.back()).
        Use to dismiss dialogs, overlays, or navigate back in the app.
        No-op on iOS (iOS uses swipe-left gesture instead).
        """
        try:
            self.driver.back()
            return ok("press_back", "pressed Android Back button")
        except WebDriverException as e:
            return err("press_back", str(e))

    def wait(self, seconds: float = 1.0) -> dict:
        """Explicit wait. Use sparingly — only when a loading state is expected."""
        time.sleep(seconds)
        return ok("wait", f"waited {seconds}s")
