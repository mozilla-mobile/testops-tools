"""Tests for agent/actions.py — action dispatcher contract with the LLM."""

from agent.actions import Actions


class _FakeDriver:
    def __init__(self):
        self.tapped = []

    def tap(self, points):
        self.tapped.append(points)


def _make_actions():
    a = Actions.__new__(Actions)
    a.driver = _FakeDriver()
    return a


# ── Coordinate targets ─────────────────────────────────────────────────────────

def test_tap_accepts_json_style_list_coordinates():
    """Regression: the LLM returns coordinates as a JSON array, which
    json.loads decodes into a Python list — never a tuple. The old
    isinstance(target, tuple) check silently rejected every LLM-produced
    coordinate tap with 'unsupported target type: list'."""
    a = _make_actions()
    result = a.tap([150, 400])
    assert result["status"] == "ok"
    assert a.driver.tapped == [[(150, 400)]]
    assert "150" in result["detail"] and "400" in result["detail"]


def test_tap_still_accepts_tuple_coordinates():
    """Sanity: internal callers (e.g. UIElement.center unpacking) may still
    pass tuples. Both must work."""
    a = _make_actions()
    result = a.tap((10, 20))
    assert result["status"] == "ok"
    assert a.driver.tapped == [[(10, 20)]]


def test_tap_accepts_float_coordinates_and_truncates():
    """Some Appium element geometries report floats. Coerce to int for the
    driver.tap() call (which expects int pixels)."""
    a = _make_actions()
    result = a.tap([12.7, 34.9])
    assert result["status"] == "ok"
    # int() truncates toward zero — that's fine for pixel coordinates.
    assert a.driver.tapped == [[(12, 34)]]


def test_tap_rejects_three_element_list():
    """Guard against the LLM emitting a nonsense payload like [x, y, z]."""
    a = _make_actions()
    result = a.tap([1, 2, 3])
    assert result["status"] == "error"
    assert "unsupported target type" in result["error"]


def test_tap_rejects_list_of_strings():
    """Guard against non-numeric list contents."""
    a = _make_actions()
    result = a.tap(["100", "200"])
    assert result["status"] == "error"
    assert "unsupported target type" in result["error"]


# ── --allowed-domains enforcement ────────────────────────────────────────────

class _FakeDriverNoOp:
    """Enough of a driver for type_url to reach the domain check but not
    actually perform any Appium calls (the domain check refuses first)."""
    def find_element(self, *args, **kwargs):
        raise AssertionError("driver.find_element should not be called when "
                             "type_url is refused by the allowlist")


def test_type_url_refuses_host_not_in_allowlist():
    """Regression: with an allowlist, unrelated hosts must be refused BEFORE
    reaching Appium. Enforced in Python because prompt-side rules can be
    bypassed by injection."""
    a = Actions.__new__(Actions)
    a.driver = _FakeDriverNoOp()
    a.allowed_domains = ["firefox.com", "localhost"]

    result = a.type_url("https://evil.example.com/pwn")
    assert result["status"] == "error"
    assert "not in --allowed-domains" in result["error"]
    assert "firefox.com" in result["error"]   # tells the operator what's allowed


def test_type_url_accepts_exact_host_match():
    """Exact hostname match on the allowlist passes the check. We stub the
    rest of type_url out — this test only verifies the domain gate."""
    from unittest.mock import MagicMock

    a = Actions.__new__(Actions)
    a.allowed_domains = ["firefox.com"]
    a.driver = MagicMock()
    a.driver.find_element.return_value = MagicMock()
    a.driver.switch_to.active_element = MagicMock()
    result = a.type_url("https://firefox.com/download")
    assert result["status"] == "ok", f"expected ok, got {result!r}"


def test_type_url_accepts_subdomain_of_allowlisted_host():
    """Host-suffix match: 'firefox.com' allows 'blog.firefox.com' but NOT
    'evilfirefox.com'."""
    from unittest.mock import MagicMock

    # Subdomain accepted
    a = Actions.__new__(Actions)
    a.allowed_domains = ["firefox.com"]
    a.driver = MagicMock()
    a.driver.find_element.return_value = MagicMock()
    a.driver.switch_to.active_element = MagicMock()
    good = a.type_url("https://blog.firefox.com/post")
    assert good["status"] == "ok"

    # Look-alike domain refused (evilfirefox.com is NOT a subdomain of firefox.com)
    a.driver = _FakeDriverNoOp()
    bad = a.type_url("https://evilfirefox.com/pwn")
    assert bad["status"] == "error"
    assert "not in --allowed-domains" in bad["error"]


def test_type_url_no_allowlist_preserves_historical_behavior():
    """Regression: with allowed_domains=None, no restriction is applied
    (default state — exploratory testing has full URL freedom)."""
    from unittest.mock import MagicMock

    a = Actions.__new__(Actions)
    a.allowed_domains = None
    a.driver = MagicMock()
    a.driver.find_element.return_value = MagicMock()
    a.driver.switch_to.active_element = MagicMock()
    result = a.type_url("https://anything.example.com/whatever")
    assert result["status"] == "ok"


# ── Secure/password field refusal ────────────────────────────────────────────

def test_type_text_refuses_ios_secure_text_field():
    """Regression: type_text must not write into a XCUIElementTypeSecureTextField.
    The prompt-side rule says the same thing but can be bypassed by prompt
    injection — this is the Python backstop."""
    from unittest.mock import MagicMock

    a = Actions.__new__(Actions)
    a.driver = MagicMock()
    secure_el = MagicMock()
    secure_el.get_attribute = lambda name: (
        "XCUIElementTypeSecureTextField" if name == "type" else None
    )
    a.driver.switch_to.active_element = secure_el

    result = a.type_text("hunter2")
    assert result["status"] == "error"
    assert "secure/password field" in result["error"]
    # send_keys must NOT have been called on the secure element
    secure_el.send_keys.assert_not_called()


def test_type_text_refuses_android_password_field():
    """Same guard, Android accessibility attribute (password='true')."""
    from unittest.mock import MagicMock

    a = Actions.__new__(Actions)
    a.driver = MagicMock()
    secure_el = MagicMock()
    secure_el.get_attribute = lambda name: (
        "true" if name == "password" else None
    )
    a.driver.switch_to.active_element = secure_el

    result = a.type_text("s3cret")
    assert result["status"] == "error"
    assert "secure/password field" in result["error"]
    secure_el.send_keys.assert_not_called()


def test_type_text_writes_to_normal_field():
    """Sanity: a plain text field must still accept type_text."""
    from unittest.mock import MagicMock

    a = Actions.__new__(Actions)
    a.driver = MagicMock()
    plain_el = MagicMock()
    plain_el.get_attribute = lambda name: None   # no secure indicator
    a.driver.switch_to.active_element = plain_el

    result = a.type_text("hello world")
    assert result["status"] == "ok"
    plain_el.send_keys.assert_called_once_with("hello world")


# ── long_press: W3C ActionBuilder migration ──────────────────────────────────

def test_long_press_uses_w3c_action_builder_not_touch_action():
    """Regression from real session: TouchAction hit /touch/perform which
    modern XCUITest drivers no longer expose ('Unhandled endpoint' error on
    every long_press call in production). Migrated to selenium's W3C
    ActionBuilder — must reach driver.perform() indirectly via the builder.
    """
    from unittest.mock import MagicMock, patch

    a = Actions.__new__(Actions)
    a.driver = MagicMock()
    el = MagicMock()
    el.location = {"x": 100, "y": 200}
    el.size     = {"width": 40, "height": 40}
    a.driver.find_element.return_value = el

    with patch("agent.actions.ActionBuilder") as MockBuilder:
        builder_instance = MockBuilder.return_value
        # Chainable pointer_action calls: move_to_location().pointer_down().pause().pointer_up()
        builder_instance.pointer_action.move_to_location.return_value = builder_instance.pointer_action
        builder_instance.pointer_action.pointer_down.return_value     = builder_instance.pointer_action
        builder_instance.pointer_action.pause.return_value            = builder_instance.pointer_action
        builder_instance.pointer_action.pointer_up.return_value       = builder_instance.pointer_action

        result = a.long_press("someElement", duration_ms=800)

    assert result["status"] == "ok"
    # Builder was constructed, chain was invoked, and perform() was called on it.
    MockBuilder.assert_called_once()
    builder_instance.pointer_action.move_to_location.assert_called_once()
    builder_instance.pointer_action.pointer_down.assert_called_once()
    builder_instance.pointer_action.pause.assert_called_once_with(0.8)   # ms → seconds
    builder_instance.pointer_action.pointer_up.assert_called_once()
    builder_instance.perform.assert_called_once()


def test_long_press_no_touch_action_imported():
    """Guard: the legacy TouchAction import must not be present anywhere in
    actions.py — Appium-Python-Client 4.x removed the module and the modern
    XCUITest driver rejects the /touch/perform endpoint anyway."""
    import agent.actions as actions_module
    src = open(actions_module.__file__).read()
    # Uses in module (import or reference)
    lines_with_ta = [
        line for line in src.splitlines()
        if "TouchAction" in line and not line.strip().startswith("#")
    ]
    assert not lines_with_ta, (
        f"TouchAction still referenced in non-comment code: {lines_with_ta!r}"
    )


# ── type_url: URL bar identifier drift ───────────────────────────────────────

def test_type_url_probes_addresstoolbar_address_first():
    """Regression from real session: the URL bar in Firefox iOS is
    'AddressToolbar.address' but our list started with older IDs that no
    longer match — every type_url fell through to XPath and failed."""
    from unittest.mock import MagicMock

    a = Actions.__new__(Actions)
    a.allowed_domains = None
    a.driver = MagicMock()
    a.driver.find_element.return_value = MagicMock()
    a.driver.switch_to.active_element = MagicMock()

    a.type_url("https://en.wikipedia.org/wiki/Main_Page")

    # First find_element call must ask for the observed real ID.
    from appium.webdriver.common.appiumby import AppiumBy
    first_call = a.driver.find_element.call_args_list[0]
    assert first_call.args == (AppiumBy.ACCESSIBILITY_ID, "AddressToolbar.address"), (
        f"first find_element call was not AddressToolbar.address: {first_call!r}"
    )
