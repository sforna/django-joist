"""The theme stylesheet as a unit: which knobs map onto which internal tokens,
when the dark blocks are emitted, how derived tints are computed, and the
allow-list that keeps config values from breaking out of a declaration.

The HTTP layer that serves this sheet is covered in test_http.py; what is worth
pinning here is the pure builder, including the paths the endpoint tests never
reach (dark mode, derived tints, rejected values).
"""

import pytest

from django_joist.theme import KNOBS, ThemeStylesheet

sheet = ThemeStylesheet()


def build(**theme_config):
    return sheet.build(theme_config)


# -- output shape ------------------------------------------------------------
def test_a_default_install_emits_nothing():
    assert build() == ""
    assert build(fonts={"mono": None, "sans": ""}) == ""
    assert sheet.is_configured({}) is False


def test_light_colors_map_onto_the_internal_tokens():
    css = build(colors={"light": {"accent": "#0af", "background": "#fff"}})
    assert css.startswith(":root {\n")
    assert "--bp-ink: #0af;" in css  # accent paints ink ...
    assert "--bp-focus-border: #0af;" in css  # ... and the focus ring
    assert "--bp-bg: #fff;" in css
    assert "prefers-color-scheme" not in css  # light needs no media query


def test_fonts_emit_their_tokens_and_skip_the_unset_one():
    css = build(fonts={"mono": "IBM Plex Mono, monospace", "sans": None})
    assert "--bp-mono: IBM Plex Mono, monospace;" in css
    assert "--bp-sans" not in css


def test_dark_colors_emit_a_media_query_and_a_forced_selector():
    css = build(colors={"dark": {"surface": "#111"}})
    # Auto-dark excludes a root that forced light; the explicit selector serves
    # the toggle. Both mirror the shipped stylesheet, so custom overrides follow
    # the same two paths.
    assert "@media (prefers-color-scheme: dark) {" in css
    assert ':root:not([data-theme="light"])' in css
    assert ':root[data-theme="dark"]' in css
    assert css.count("--bp-panel: #111;") == 2


def test_dark_only_config_needs_no_plain_root_block():
    css = build(colors={"dark": {"surface": "#111"}})
    assert css.startswith("@media")
    assert not css.startswith(":root {")


def test_every_knob_paints_its_declared_tokens():
    colors = {knob: "#123456" for knob in KNOBS}
    css = build(colors={"light": colors})
    for knob, tokens in KNOBS.items():
        for token in tokens:
            assert f"--bp-{token}: #123456;" in css, (knob, token)


# -- derived tints -----------------------------------------------------------
def test_a_hex_border_also_derives_a_translucent_hairline():
    css = build(colors={"light": {"border": "#112233"}})
    assert "--bp-hair: #112233;" in css  # the knob's own token, first
    assert "--bp-hair: rgba(17, 34, 51, 0.35);" in css  # then the tint, which wins
    assert css.index("rgba(17, 34, 51, 0.35)") > css.index("--bp-hair: #112233;")


@pytest.mark.parametrize(
    "accent,channels",
    [
        ("#0a0", "0, 170, 0"),  # 3-digit shorthand is expanded
        ("#00aa00", "0, 170, 0"),
        ("#00aa0080", "0, 170, 0"),  # alpha is dropped: the tint carries its own
    ],
)
def test_a_hex_accent_derives_the_grid_tints(accent, channels):
    css = build(colors={"light": {"accent": accent}})
    assert f"--bp-grid: rgba({channels}, 0.07);" in css
    assert f"--bp-grid-strong: rgba({channels}, 0.12);" in css


def test_a_non_hex_border_leaves_the_hairline_as_the_border():
    # rgb()/named colours carry no channels to tint, and inventing some would
    # flatten the outline and the separators back into one colour.
    css = build(colors={"light": {"border": "rgb(1, 2, 3)"}})
    assert "--bp-hair: rgb(1, 2, 3);" in css
    assert "rgba(" not in css


# -- the allow-list ----------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    [
        "red; } body { display: none",
        "url(//evil.example/x.css)",
        "var(--somewhere-else)",
        "#12345",
        "javascript:alert(1)",
        "@import 'x'",
        "red\n--bp-evil: 1",
        "expression(alert(1))",
        "  ",
        "",
        None,
        42,
    ],
)
def test_a_colour_outside_the_allow_list_is_dropped(value):
    css = build(colors={"light": {"accent": value}})
    assert css == ""  # nothing to emit, so the shipped default shows through


@pytest.mark.parametrize(
    "value",
    [
        "Comic Sans; } body { display: none",
        "url(//evil.example/x.woff2)",
        "<script>",
        "mono\n--bp-evil: 1",
        "",
        None,
        42,
    ],
)
def test_a_font_outside_the_allow_list_is_dropped(value):
    assert build(fonts={"mono": value}) == ""


@pytest.mark.parametrize(
    "value,expected",
    [
        ("  #abc  ", "#abc"),  # trimmed
        ("rebeccapurple", "rebeccapurple"),
        ("rgb(1, 2, 3)", "rgb(1, 2, 3)"),
        ("rgba(1, 2, 3, 0.5)", "rgba(1, 2, 3, 0.5)"),
        ("hsl(120 50% 50%)", "hsl(120 50% 50%)"),
        ("#aabbccdd", "#aabbccdd"),
    ],
)
def test_allowed_colours_are_kept_verbatim(value, expected):
    assert sheet._sanitize_color(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("IBM Plex Mono", "IBM Plex Mono"),
        ("'IBM Plex Mono', monospace", "'IBM Plex Mono', monospace"),
        ("system-ui", "system-ui"),
        ("Fira Code 2.0", "Fira Code 2.0"),
    ],
)
def test_allowed_fonts_are_kept_verbatim(value, expected):
    assert sheet._sanitize_font(value) == expected


# -- is_configured -----------------------------------------------------------
@pytest.mark.parametrize(
    "config,expected",
    [
        ({"fonts": {"mono": "IBM Plex Mono"}}, True),
        ({"colors": {"light": {"accent": "#0af"}}}, True),
        ({"colors": {"dark": {"accent": "#0af"}}}, True),
        ({"fonts": {"mono": None, "sans": ""}}, False),
        ({"colors": {"light": {}, "dark": {}}}, False),
        ({"colors": {"light": {"accent": ""}}}, False),
        ({"colors": None, "fonts": None}, False),
    ],
)
def test_is_configured_reports_whether_any_knob_is_set(config, expected):
    assert sheet.is_configured(config) is expected
