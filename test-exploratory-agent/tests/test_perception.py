"""Tests for agent/perception.py — XML parsing across iOS and Android."""

from agent.perception import Perception


class _MockDriver:
    """Minimal driver stub — only page_source is used by visible_elements()."""

    def __init__(self, page_source: str):
        self.page_source = page_source


def _perception(page_source: str, tmp_path) -> Perception:
    return Perception(driver=_MockDriver(page_source), screenshots_dir=str(tmp_path))


IOS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<XCUIElementTypeApplication>
  <XCUIElementTypeButton type="XCUIElementTypeButton"
                         name="btn1" label="Click me" value=""
                         x="10" y="20" width="100" height="50"
                         enabled="true" visible="true"/>
  <XCUIElementTypeStaticText type="XCUIElementTypeStaticText"
                             name="" label="Hidden text" value=""
                             x="0" y="0" width="0" height="0"
                             enabled="true" visible="false"/>
</XCUIElementTypeApplication>"""


ANDROID_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <android.widget.Button class="android.widget.Button"
                        content-desc="btn1" text="Click me"
                        bounds="[10,20][110,70]"
                        enabled="true" displayed="true"/>
</hierarchy>"""


def test_ios_element_parsed_with_xywh_coords(tmp_path):
    perception = _perception(IOS_XML, tmp_path)
    elements = perception.visible_elements()

    # Root Application node is filtered (no name/label). Only the Button survives.
    assert len(elements) == 1
    btn = elements[0]
    assert btn.name == "btn1"
    assert btn.label == "Click me"
    assert btn.x == 10 and btn.y == 20
    assert btn.width == 100 and btn.height == 50
    assert btn.visible is True


def test_android_element_parsed_with_bounds_notation(tmp_path):
    """Android uses bounds='[x1,y1][x2,y2]' — perception converts to x/y/w/h."""
    perception = _perception(ANDROID_XML, tmp_path)
    elements = perception.visible_elements()

    assert len(elements) == 1
    btn = elements[0]
    assert btn.name == "btn1"           # from content-desc
    assert btn.label == "Click me"      # from text
    assert (btn.x, btn.y) == (10, 20)
    assert (btn.width, btn.height) == (100, 50)   # 110-10, 70-20


def test_invisible_elements_are_filtered_out(tmp_path):
    """The IOS_XML fixture contains one invisible element — it must not be returned."""
    perception = _perception(IOS_XML, tmp_path)
    elements = perception.visible_elements()

    assert all(e.visible for e in elements)
    assert not any(e.label == "Hidden text" for e in elements)


def test_malformed_xml_returns_empty_list_and_does_not_crash(tmp_path):
    """Defensive parsing: malformed XML must degrade gracefully, not kill the session."""
    perception = _perception("<not-valid-xml>unclosed", tmp_path)
    elements = perception.visible_elements()
    assert elements == []


def test_empty_xml_returns_empty_list(tmp_path):
    perception = _perception("", tmp_path)
    elements = perception.visible_elements()
    assert elements == []


def test_android_negative_bounds_preserve_sign(tmp_path):
    """Regression: bounds='[-10,20][100,50]' must parse x=-10, not x=10."""
    xml = """<?xml version="1.0"?>
<hierarchy>
  <android.widget.Button class="android.widget.Button"
                        content-desc="btn" text="B"
                        bounds="[-10,20][100,50]"
                        enabled="true" displayed="true"/>
</hierarchy>"""
    perception = _perception(xml, tmp_path)
    el = perception.visible_elements()[0]
    assert (el.x, el.y, el.width, el.height) == (-10, 20, 110, 30)


def test_screenshot_paths_are_isolated_between_perception_instances(tmp_path):
    """Regression: two Perception instances used to collide at
    reports/screenshots/step_0001.png. Session isolation is enforced by the
    caller (loop.py passes screenshots_dir=reports/screenshots/<session_id>),
    so each Perception must honor its own screenshots_dir without leaking."""
    import os

    class _StubDriver:
        def save_screenshot(self, path):
            with open(path, "wb") as f:
                f.write(b"\x89PNG stub")

    dir_a = tmp_path / "session_A"
    dir_b = tmp_path / "session_B"
    p_a = Perception(_StubDriver(), screenshots_dir=str(dir_a))
    p_b = Perception(_StubDriver(), screenshots_dir=str(dir_b))

    path_a = p_a.screenshot(label="step1")
    path_b = p_b.screenshot(label="step1")

    assert path_a != path_b
    assert os.path.dirname(path_a) == str(dir_a)
    assert os.path.dirname(path_b) == str(dir_b)
    # Both files exist independently.
    assert os.path.isfile(path_a) and os.path.isfile(path_b)
