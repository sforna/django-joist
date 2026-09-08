"""Builds the optional custom-theme stylesheet from ``JOIST["theme"]``.

A faithful port of the reference ``ThemeStylesheet``: the public API is a
small set of semantic knobs (accent, background, text, ...) each mapping onto
one or more internal ``--bp-*`` CSS custom properties. Only the knobs a host
actually set are emitted, so the shipped blueprint default shows through
everywhere else.

Because config values are written verbatim into a CSS response, every value is
validated against a strict allow-list first: a value that could break out of
the declaration is dropped (never emitted), so the sheet can only ever degrade
to the default, never be broken or injected.
"""

from __future__ import annotations

import re

#: Semantic knob => the internal ``--bp-*`` tokens it drives. Iterated in this
#: order for deterministic output. The knob names are the public contract.
KNOBS: dict[str, list[str]] = {
    "accent": ["ink", "focus-border"],
    "accent-secondary": ["cyan"],
    "background": ["bg", "edge-bg"],
    "surface": ["panel", "entity-bg", "row-odd", "field"],
    "surface-alt": ["row-even"],
    "text": ["fg", "entity-text"],
    "muted": ["muted", "rel", "edge"],
    "border": ["entity-border", "hair", "panel-line", "field-line"],
}

# Anchored and character-restricted, so nothing containing ';', '{', '}', '@',
# a comment, url(, var(, or a newline can pass.
COLOR = re.compile(
    r"^(#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})"
    r"|(?:rgb|rgba|hsl|hsla)\([0-9.,%\s/]+\)"
    r"|[a-zA-Z]+)$"
)

# A font-family value: family names (quoted or bare), commas, spaces, dots,
# hyphens. Rejects anything that could break out of the declaration.
FONT = re.compile(r"^[A-Za-z0-9\s,'\".\-]+$")

_HEX = re.compile(r"^#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class ThemeStylesheet:
    def build(self, config: dict) -> str:
        fonts = config.get("fonts") or {}
        colors = config.get("colors") or {}

        root = [*self._font_declarations(fonts), *self._color_declarations(colors.get("light") or {})]
        dark = self._color_declarations(colors.get("dark") or {})

        blocks = []
        if root:
            blocks.append(self._rule(":root", root))
        if dark:
            # Mirror the base stylesheet exactly: auto-dark via the media query
            # (excluding a forced-light root), and forced-dark via the
            # data-theme selector, so custom overrides follow the toggle.
            blocks.append(
                "@media (prefers-color-scheme: dark) {\n"
                + self._rule(':root:not([data-theme="light"])', dark, 1)
                + "\n}"
            )
            blocks.append(self._rule(':root[data-theme="dark"]', dark))

        return ("\n".join(blocks) + "\n") if blocks else ""

    def is_configured(self, config: dict) -> bool:
        """Whether a custom theme is configured at all, so the shell can skip
        the theme <link> entirely on a default install."""

        def any_value(values: dict) -> bool:
            return any(v is not None and v != "" for v in values.values())

        colors = config.get("colors") or {}
        return (
            any_value(config.get("fonts") or {})
            or any_value(colors.get("light") or {})
            or any_value(colors.get("dark") or {})
        )

    # -- internals ---------------------------------------------------------
    def _color_declarations(self, knobs: dict) -> list[str]:
        decls: list[str] = []
        for knob, tokens in KNOBS.items():
            if knob not in knobs:
                continue
            value = self._sanitize_color(knobs[knob])
            if value is None:
                continue
            decls.extend(f"--bp-{token}: {value};" for token in tokens)

        # Row hairlines are a translucent tint of the border, not the same
        # colour: the border knob paints four tokens at once, and without
        # this a custom theme flattens the outline and the separators into one
        # value. Emitted after the loop so it wins. Needs colour channels, so
        # a non-hex border leaves the hairline equal to it.
        border = self._hex_to_channels(self._sanitize_color(knobs["border"])) if "border" in knobs else None
        if border:
            decls.append(f"--bp-hair: rgba({border}, 0.35);")

        # The background grid is a translucent tint of the accent, so it
        # follows a custom accent rather than staying on the shipped blue.
        accent = self._hex_to_channels(self._sanitize_color(knobs["accent"])) if "accent" in knobs else None
        if accent:
            decls.append(f"--bp-grid: rgba({accent}, 0.07);")
            decls.append(f"--bp-grid-strong: rgba({accent}, 0.12);")

        return decls

    def _font_declarations(self, fonts: dict) -> list[str]:
        decls = []
        for key in ("mono", "sans"):
            value = self._sanitize_font(fonts.get(key))
            if value is not None:
                decls.append(f"--bp-{key}: {value};")
        return decls

    @staticmethod
    def _sanitize_color(value) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value if COLOR.match(value) else None

    @staticmethod
    def _sanitize_font(value) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value if value and FONT.match(value) else None

    @staticmethod
    def _hex_to_channels(value: str | None) -> str | None:
        """The "r, g, b" channels of a hex colour, or None when not hex."""
        if value is None or not _HEX.match(value):
            return None
        hex_part = value[1:]
        if len(hex_part) <= 4:
            hex_part = "".join(c * 2 for c in hex_part[:3])
        return ", ".join(str(int(hex_part[i : i + 2], 16)) for i in (0, 2, 4))

    @staticmethod
    def _rule(selector: str, decls: list[str], indent: int = 0) -> str:
        pad = "  " * indent
        body = "\n".join(f"{pad}  {d}" for d in decls)
        return f"{pad}{selector} {{\n{body}\n{pad}}}"
