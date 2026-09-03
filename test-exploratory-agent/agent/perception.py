"""
agent/perception.py

Gives the agent its "eyes":
  - screenshot()          → saves PNG, returns file path
  - accessibility_tree()  → returns parsed XML of all UI elements
  - visible_elements()    → returns flat list of actionable elements
"""

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from PIL import Image


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class UIElement:
    """A single element from the accessibility tree."""
    type:     str             # XCUIElementTypeButton, XCUIElementTypeTextField, etc.
    name:     str             # accessibility identifier
    label:    str             # human-readable label (what a user sees)
    value:    str             # current value (e.g. URL in address bar)
    x:        int
    y:        int
    width:    int
    height:   int
    enabled:  bool
    visible:  bool
    children: list = field(default_factory=list)

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def __str__(self) -> str:
        # Apostrophes in label/name/value truncate loop._screen_key (regex uses `'` as delimiter).
        coords = f"({self.x},{self.y} {self.width}x{self.height})"
        status = "✓" if self.enabled else "✗"
        return f"[{status}] {self.short_type:<12} name='{self.name}' label='{self.label}' value='{self.value}' {coords}"

    @property
    def short_type(self) -> str:
        return (self.type
                .replace("XCUIElementType", "")
                .replace("android.widget.", "")
                .replace("android.view.", ""))


# ── Perception class ───────────────────────────────────────────────────────────

class Perception:

    def __init__(self, driver, screenshots_dir: str = "reports/screenshots"):
        self.driver = driver
        self.screenshots_dir = screenshots_dir
        self._step = 0
        os.makedirs(screenshots_dir, exist_ok=True)

    def screenshot(self, label: str = "") -> str:
        """
        Captures a screenshot from the simulator and compresses it.
        Resizing to 50% reduces API cost ~60% with no loss in reasoning quality.
        Returns the file path of the saved PNG.
        """
        self._step += 1
        filename = f"step_{self._step:04d}"
        if label:
            safe_label = label.replace(" ", "_").replace("/", "-")[:40]
            filename += f"_{safe_label}"
        filename += ".png"

        path = os.path.join(self.screenshots_dir, filename)
        self.driver.save_screenshot(path)

        # Compress: resize to 50% — Claude reasons equally well at lower resolution
        try:
            img = Image.open(path)
            img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
            img.save(path, optimize=True)   # quality= is JPEG-only, ignored for PNG
        except Exception as e:
            print(f"[perception] Compression skipped: {e}")

        print(f"[perception] Screenshot saved → {path}")
        return path

    def accessibility_tree(self) -> str:
        """
        Returns the raw XML accessibility tree of the current screen.
        This is the full hierarchy of all UI elements.
        """
        return self.driver.page_source   # Appium returns XML

    def visible_elements(self) -> list[UIElement]:
        """
        Returns a flat list of all visible, potentially interactable elements.
        Useful for the LLM to understand what it can tap/type on.
        """
        xml = self.accessibility_tree()
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            print(f"[perception] ⚠️  Failed to parse accessibility XML: {e}")
            print(f"[perception] Raw XML head: {xml[:200] if xml else '(empty)'}")
            return []
        elements = []
        self._parse_tree(root, elements)
        # Filter: only visible elements with some identifier
        return [e for e in elements if e.visible and (e.name or e.label)]

    def summarize_screen(self) -> str:
        """
        Returns a compact text summary of the current screen for the LLM.
        More token-efficient than sending the full XML.
        """
        elements = self.visible_elements()
        lines = [f"=== Screen summary ({len(elements)} visible elements) ==="]
        for e in elements:
            lines.append(str(e))
        return "\n".join(lines)

    # ── Private ───────────────────────────────────────────────────────────────

    def _parse_tree(self, node, result: list, depth: int = 0):
        """Recursively walks the XML tree and extracts UIElements.

        Handles both platforms automatically:
          - iOS:     attributes are type/name/label/value/x/y/width/height/visible
          - Android: attributes are class/content-desc/text/bounds/displayed
        """
        attrib = node.attrib

        # ── Coordinates ───────────────────────────────────────────────────────
        # Android uses bounds="[x1,y1][x2,y2]"; iOS uses separate x/y/width/height
        bounds = attrib.get("bounds", "")
        if bounds:
            nums = re.findall(r"-?\d+", bounds)   # allow negative coords (off-screen elements)
            if len(nums) == 4:
                x1, y1, x2, y2 = map(int, nums)
                x, y, width, height = x1, y1, x2 - x1, y2 - y1
            else:
                x = y = width = height = 0
        else:
            try:
                x      = int(attrib.get("x", 0))
                y      = int(attrib.get("y", 0))
                width  = int(attrib.get("width", 0))
                height = int(attrib.get("height", 0))
            except ValueError:
                x = y = width = height = 0

        # ── Element type ──────────────────────────────────────────────────────
        # Android: "class" attribute (e.g. "android.widget.Button")
        # iOS:     "type"  attribute (e.g. "XCUIElementTypeButton")
        el_type = attrib.get("class") or attrib.get("type", "Unknown")

        # ── Name / label ──────────────────────────────────────────────────────
        # Android: content-desc (accessibility label) and text (visible text)
        # iOS:     name (accessibility id) and label (visible text)
        name  = attrib.get("name")  or attrib.get("content-desc", "")
        label = attrib.get("label") or attrib.get("text", "")

        # ── Value ─────────────────────────────────────────────────────────────
        value = attrib.get("value", "")

        # ── Visibility ────────────────────────────────────────────────────────
        # Android uses "displayed"; iOS uses "visible"
        visible_raw = attrib.get("displayed") or attrib.get("visible", "true")
        visible = visible_raw == "true"

        el = UIElement(
            type    = el_type,
            name    = name,
            label   = label,
            value   = value,
            x       = x,
            y       = y,
            width   = width,
            height  = height,
            enabled = attrib.get("enabled", "true") == "true",
            visible = visible,
        )
        result.append(el)

        for child in node:
            self._parse_tree(child, result, depth + 1)