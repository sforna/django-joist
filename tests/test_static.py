"""Static-asset tests: every allow-listed name resolves to a real file, the
port renamed consistently (joist- everywhere, no truss leftovers), and the
import graph inside joist.js only references ported modules."""

import re
from pathlib import Path

import pytest

from django_joist import views

STATIC = Path(views.STATIC_ROOT)


@pytest.fixture()
def enabled_joist(settings):
    """Local mirror of the http gate so the asset route answers: DEBUG open +
    enabled true. Kept self-contained by design (no cross-file fixture
    imports)."""
    settings.DEBUG = True
    from django_joist.conf import joist_settings

    merged = joist_settings.wrapped
    previous = merged.get("enabled")
    merged["enabled"] = True
    yield
    merged["enabled"] = previous


def test_every_asset_exists():
    missing = [name for name, rel in views.ASSETS.items() if not (STATIC / rel).is_file()]
    assert missing == []


@pytest.mark.django_db
def test_assets_served_with_types(client, enabled_joist):
    from django.urls import reverse

    for name in ("joist.js", "joist.css", "mermaid.min.js", "ibm-plex-mono-400.woff2"):
        response = client.get(reverse("joist:asset", args=[name]))
        assert response.status_code == 200, name
        CT = response["Content-Type"]
        if name.endswith(".css"):
            assert "text/css" in CT
        elif name.endswith(".woff2"):
            assert "font" in CT
        else:
            assert "javascript" in CT


def test_vendored_mermaid_is_the_pinned_version():
    """The bundle's version only exists as a literal inside the minified file,
    and nothing else in the repo records which release was vendored. The note
    beside it is the pin, so a swapped file and a forgotten note fail here
    together instead of silently shipping one without the other."""
    note = (STATIC / "vendor" / "mermaid.LICENSE").read_text(encoding="utf-8")
    pinned = re.search(r"mermaid\.min\.js v(\d+\.\d+\.\d+)", note)
    assert pinned, "the vendored Mermaid version is not recorded in mermaid.LICENSE"

    bundle = (STATIC / "vendor" / "mermaid.min.js").read_text(encoding="utf-8", errors="replace")
    assert f'version:"{pinned.group(1)}"' in bundle
    # The shell loads this with a plain <script src>, so the bundle has to keep
    # the IIFE flavour that assigns the global. An ESM-only build would leave
    # the page with no `mermaid` at all - a blank diagram, no error.
    assert 'globalThis["mermaid"]' in bundle


def test_css_renamed_consistently():
    css = (STATIC / "css" / "joist.css").read_text(encoding="utf-8")
    assert ".joist-" in css
    assert "joist-app" in css
    assert "truss" not in css.lower()
    # theme tokens are shared with django_joist.theme - they must survive
    assert "--bp-ink" in css


def _strip_attribution(text):
    """The only allowed 'truss'/'laravel' mentions are the attribution comment
    lines ("UI adapted from Laravel Truss...") at the top of joist.js."""
    out = []
    for line in text.splitlines():
        if "Laravel Truss" in line or "ported to django-joist" in line:
            continue
        out.append(line)
    return "\n".join(out)


def test_js_has_no_truss_leftovers_and_only_known_imports():
    entry = _strip_attribution((STATIC / "js" / "joist.js").read_text(encoding="utf-8"))
    assert "truss" not in entry.lower()
    assert "laravel" not in entry.lower()
    imported = set(re.findall(r"from '\./([a-z0-9.\-]+\.js)'", entry))
    assert imported, "expected ES-module imports"
    known = set(views.ASSETS)
    assert imported <= known, f"unimportable modules: {imported - known}"


def test_all_ported_modules_clean():
    for path in sorted((STATIC / "js").glob("*.js")):
        text = _strip_attribution(path.read_text(encoding="utf-8"))
        assert "truss" not in text.lower(), path.name
    # the NUL sentinel in the combobox survived the byte-level rename intact
    combo = (STATIC / "js" / "focus-combobox.js").read_bytes()
    assert b"\x00clear" in combo


def test_vendor_licenses_preserved():
    lic = (STATIC / "vendor" / "mermaid.LICENSE").read_text()
    assert "MIT License" in lic
    assert (STATIC / "fonts" / "IBM-Plex.LICENSE").read_text() != ""
    assert (STATIC / "vendor" / "mermaid.min.js").stat().st_size > 1_000_000


@pytest.mark.django_db
def test_index_template_rendered(client, enabled_joist):
    from django.urls import reverse

    response = client.get(reverse("joist:index"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "joist-app" in body
    assert "__format__" in body
    assert "{%" not in body and "{{" not in body  # no unrendered template syntax
    assert "@json" not in body  # no leftover blade
    assert "truss" not in body.lower()
    assert "Django types" in body
