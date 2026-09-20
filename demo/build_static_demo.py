"""Regenerate the static django-joist demo published on sforna.im.

The public site is an assets-only Cloudflare Worker: no Python runtime, no
database, so the demo cannot be a live Django app. What it can be is the real
dashboard, unchanged, served from a baked snapshot: the page shell, the JS/CSS
and the vendored Mermaid are copied verbatim, the schema JSON that the shell
would fetch from ``/joist/api/schema`` is written as a static file, and the
deterministic exports become static files too.

Usage (from the repo root, with the dev venv)::

    .venv/bin/python demo/build_static_demo.py --out ../sforna.im/public/projects/django-joist/demo

The two-step migration is deliberate: ``0001`` is migrated first and the cache
is allowed to rebuild, so when the ``0002`` migrations run the ``post_migrate``
receiver captures that first schema as the diff baseline. That is what gives
the "Changes since last migration" panel something real to show - the same
mechanism a developer gets by running ``migrate`` twice.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
REPO = DEMO_DIR.parent
STATIC = REPO / "src" / "django_joist" / "static" / "joist"

#: Where the shell's own URLs get remapped to on the site.
SITE_PATH = "/projects/django-joist/demo"
PROJECT_PAGE = "/projects/django-joist/"

FORMATS = ["dbml", "json", "csv", "markdown", "mermaid", "llm"]
DEMO_APPS = ["catalog", "inventory", "sales", "support"]

NOTICE = (
    'Static demo: the real dashboard, reading a synthetic schema snapshot. Structural '
    'exports return the whole schema, not the filtered subset.'
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="output directory (the site's public/ dir)")
    args = parser.parse_args()
    out = Path(args.out).expanduser().resolve()

    sys.path.insert(0, str(DEMO_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "proj.settings")
    import django

    django.setup()

    _fresh_database()
    _migrate_in_two_steps()

    from django.test import Client

    client = Client()
    shell = client.get("/joist/")
    schema = client.get("/joist/api/schema")
    exports = {fmt: client.get(f"/joist/export/{fmt}") for fmt in FORMATS}
    for label, response in [("shell", shell), ("schema", schema), *exports.items()]:
        if response.status_code != 200:
            raise SystemExit(f"{label}: HTTP {response.status_code}")

    _write_tree(out, _rewrite(shell.content.decode()), schema.content, exports)
    _copy_assets(out / "assets")
    print(f"demo written to {out}")
    print(f"  {len(schema.content) // 1024} KB schema, {len(shell.content) // 1024} KB shell")
    return 0


def _fresh_database() -> None:
    """A rerunnable script needs a rerunnable database: no leftover tables and,
    more importantly, no leftover baseline from a previous run - a stale
    baseline would silently turn the diff panel into nonsense."""
    var = DEMO_DIR / "var"
    shutil.rmtree(var, ignore_errors=True)
    var.mkdir(parents=True, exist_ok=True)


def _migrate_in_two_steps() -> None:
    from django.core.management import call_command

    for app in DEMO_APPS:
        call_command("migrate", app, "0001", verbosity=0)

    call_command("migrate", verbosity=0)


def _rewrite(html: str) -> str:
    """Point the shell's own routes at their static counterparts.

    Every runtime URL lives under ``/joist/`` (the view renders them with
    ``reverse()``), so one replacement covers the page's assets, the schema
    endpoint and the export route at once.
    """
    html = html.replace("/joist/", f"{SITE_PATH}/")

    # Keep the demo out of the index. It is a client-rendered JavaScript app with
    # almost no text of its own and its own head keyword, so indexing it competes
    # with the project page that is meant to rank. `follow` so the link back still
    # counts. It is not a route, so it is absent from the sitemap either way.
    html = html.replace("</title>", '</title>\n    <meta name="robots" content="noindex, follow">', 1)

    notice = (
        f'<div id="joist-demo-notice">'
        f'<div class="joist-banner joist-banner--info" role="note">'
        f"{NOTICE} "
        f'<a class="joist-banner-action" href="{PROJECT_PAGE}">Back to the project page</a>'
        f"</div></div>"
    )
    # The notice is a flex row of its own height, while the viewport's height is
    # a hardcoded calc() against the toolbar and the footer, so the extra strip
    # has to be subtracted or the page scrolls by exactly that much. Its height
    # is measured rather than assumed: the notice wraps on a narrow window.
    style = (
        "<style>"
        "#joist-demo-notice .joist-banner{flex-wrap:wrap}"
        "#joist-viewport{height:calc(100vh - 54px - 28px - var(--joist-notice-h, 32px))}"
        "</style>"
    )
    html = html.replace("</head>", f"{style}</head>")
    # Measured at the end of the body: a head script runs before the notice
    # exists and would silently leave the fallback height in place.
    measure = (
        "<script>"
        "var n=document.getElementById('joist-demo-notice');"
        "var fit=function(){document.documentElement.style.setProperty('--joist-notice-h',n.offsetHeight+'px')};"
        "addEventListener('resize',fit);fit();"
        "</script>"
    )
    html = html.replace("</body>", f"{measure}</body>")
    html = html.replace("</header>", f"</header>{notice}", 1)
    return html


def _write_tree(out: Path, shell: str, schema: bytes, exports: dict) -> None:
    (out / "api").mkdir(parents=True, exist_ok=True)
    (out / "export").mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(shell, encoding="utf-8")
    (out / "api" / "schema").write_bytes(schema)
    # Extensionless on purpose: the dashboard builds these paths from the
    # route template, replacing __format__ with the format name.
    for fmt, response in exports.items():
        (out / "export" / fmt).write_bytes(response.content)


def _copy_assets(assets: Path) -> None:
    """Flat, matching the shell's flat asset URLs (the allow-list route serves
    names, not paths). The ES module graph imports itself relatively, so flat
    is the layout it expects anyway."""
    assets.mkdir(parents=True, exist_ok=True)
    for source in [*STATIC.glob("js/*.js"), *STATIC.glob("fonts/*.woff2")]:
        shutil.copyfile(source, assets / source.name)
    shutil.copyfile(STATIC / "css" / "joist.css", assets / "joist.css")
    shutil.copyfile(STATIC / "vendor" / "mermaid.min.js", assets / "mermaid.min.js")
    # Licences travel with the fonts and with Mermaid: both are redistributed here.
    shutil.copyfile(STATIC / "vendor" / "mermaid.LICENSE", assets / "mermaid.LICENSE")
    shutil.copyfile(STATIC / "fonts" / "IBM-Plex.LICENSE", assets / "IBM-Plex.LICENSE")


if __name__ == "__main__":
    raise SystemExit(main())
