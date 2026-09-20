"""Palette guard: the shipped default theme has to stay legible, and its two
dark blocks have to stay identical.

Colour is the one part of the dashboard no test can render, so it is asserted
here instead: every text pair at 4.5:1 and every graphic pair (borders, the FK
connector lines, the diff tints) at 3:1, in both themes. WCAG 1.4.3 and 1.4.11
are the bars. A palette that fails this is not a matter of taste - it is text
somebody cannot read.

The dark palette is written twice on purpose (OS-dark via the media query, and
forced dark via the attribute), so the two blocks are compared token by token:
a value edited in one and forgotten in the other is the obvious way to ship a
half-changed theme.
"""

import re
from pathlib import Path

import pytest

from django_joist import views

CSS = Path(views.STATIC_ROOT) / "css" / "joist.css"

#: (foreground token, background token, minimum ratio)
TEXT_PAIRS = [
    ("fg", "bg"),
    ("entity-text", "entity-bg"),
    ("entity-text", "row-even"),
    ("muted", "bg"),
    ("ink", "bg"),
    ("cyan", "bg"),
    ("edge", "edge-bg"),
    ("info-fg", "info-bg"),
    ("warn-fg", "warn-bg"),
    ("error-fg", "error-bg"),
]
GRAPHIC_PAIRS = [
    ("focus-border", "focus-bg"),
    ("entity-border", "entity-bg"),
    ("rel", "bg"),
    ("diff-added-border", "diff-added-bg"),
    ("diff-changed-border", "diff-changed-bg"),
]


def _blocks() -> dict[str, dict[str, str]]:
    """The three palette blocks, keyed by name. The light one is `:root`; the
    two dark ones differ only in how they are selected."""
    css = CSS.read_text(encoding="utf-8")
    found = {}
    for name, selector in [
        ("light", r":root\s*\{"),
        ("dark-os", r':root:not\(\[data-theme="light"\]\)\s*\{'),
        ("dark-forced", r':root\[data-theme="dark"\]\s*\{'),
    ]:
        match = re.search(selector + r"(.*?)\n\s*\}", css, re.S)
        assert match, f"palette block not found: {name}"
        found[name] = dict(re.findall(r"--bp-([a-z-]+):\s*([^;]+);", match.group(1)))
    return found


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.strip()
    hexa = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value)
    if hexa:
        digits = hexa.group(1)
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))
    parts = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    assert parts, f"unsupported colour: {value}"
    return tuple(int(float(p)) for p in parts.group(1).split(",")[:3])


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(v) for v in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _ratio(one: str, other: str) -> float:
    a, b = _luminance(_rgb(one)), _luminance(_rgb(other))
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark-os", "dark-forced"])
@pytest.mark.parametrize("pair,minimum", [(p, 4.5) for p in TEXT_PAIRS] + [(p, 3.0) for p in GRAPHIC_PAIRS])
def test_palette_contrast(theme, pair, minimum):
    tokens = _blocks()[theme]
    foreground, background = pair
    ratio = _ratio(tokens[foreground], tokens[background])
    assert ratio >= minimum, (
        f"{theme}: --bp-{foreground} on --bp-{background} is {ratio:.2f}:1, needs {minimum}:1"
    )


def test_dark_blocks_agree():
    blocks = _blocks()
    assert blocks["dark-os"] == blocks["dark-forced"]
