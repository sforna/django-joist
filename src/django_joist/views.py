"""The dashboard's HTTP surface: page shell, JSON schema endpoint, server-side
export, custom-theme stylesheet, and gated package assets.

Same shape as the reference's two-route design, extended with the three
auxiliary routes:

* ``GET /``               - renders the page shell; the schema itself is
  fetched client-side from the JSON endpoint (this serves no schema data).
* ``GET /api/schema``     - the cached snapshot for one connection, with
  ``excluded_tables`` filtered server-side so excluded structure never
  reaches the client, plus the ``diff`` and ``doctor`` payloads.
* ``GET /export/<format>``- structural export via the same builder the
  command and facade drive, so all three produce identical bytes.
* ``GET /theme.css``      - the optional custom-theme overrides, as a
  same-origin sheet (CSP-friendly, never inline).
* ``GET /assets/<file>``  - the dashboard's JS/CSS/fonts + the vendored
  Mermaid, allow-listed by name: no collectstatic step, no CDN.

Every route sits behind ``joist_protected`` (enabled + authorizer, denial =
404), so none of them ever confirms Joist exists to the unauthorized.
"""

from __future__ import annotations

import json
import posixpath
from pathlib import Path
from typing import Any

from django.conf import settings
from django.http import FileResponse, HttpRequest, Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from .cache import schema_cache
from .conf import joist_settings
from .security import joist_protected
from .selection import excluded_tables_for, without_excluded_tables
from .theme import ThemeStylesheet

#: Public asset name -> path relative to the package's static/joist dir.
#: Allow-listing by name maps names to paths and makes traversal impossible.
ASSETS: dict[str, str] = {
    "joist.js": "js/joist.js",
    "selection.js": "js/selection.js",
    "mermaid-definition.js": "js/mermaid-definition.js",
    "export-request.js": "js/export-request.js",
    "diff-view.js": "js/diff-view.js",
    "doctor-view.js": "js/doctor-view.js",
    "type-labels.js": "js/type-labels.js",
    "viewport.js": "js/viewport.js",
    "url-state.js": "js/url-state.js",
    "table-match.js": "js/table-match.js",
    "focus-combobox.js": "js/focus-combobox.js",
    "export-menu.js": "js/export-menu.js",
    "label-face-gate.js": "js/label-face-gate.js",
    "mermaid.min.js": "vendor/mermaid.min.js",
    "joist.css": "css/joist.css",
    "ibm-plex-mono-400.woff2": "fonts/ibm-plex-mono-400.woff2",
    "ibm-plex-mono-500.woff2": "fonts/ibm-plex-mono-500.woff2",
    "ibm-plex-mono-600.woff2": "fonts/ibm-plex-mono-600.woff2",
}

STATIC_ROOT = Path(__file__).parent / "static" / "joist"

EXPORT_MIME = {
    "dbml": "text/plain",
    "json": "application/json",
    "csv": "text/csv",
    "markdown": "text/markdown",
    "mermaid": "text/plain",
    "llm": "text/plain",
}


# -- page shell ---------------------------------------------------------------
@joist_protected
def index(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "joist/index.html",
        {
            "connections": json.dumps(schema_cache().managed_aliases()),
            "has_custom_theme": ThemeStylesheet().is_configured(joist_settings.get("theme") or {}),
            "type_labels": joist_settings.get("diagram.type_labels", "native"),
            "warn_above": joist_settings.get("large_schema.warn_above", 60),
            "focus_depth": joist_settings.get("focus.default_depth", 1),
            "min_zoom": joist_settings.get("diagram.min_zoom", 0.7),
            "doctor_flag_tables": bool(joist_settings.get("doctor.flag_tables", True)),
            "mermaid_url": joist_settings.get("diagram.mermaid_url")
            or reverse("joist:asset", args=("mermaid.min.js",)),
        },
    )


# -- JSON schema endpoint -----------------------------------------------------
@joist_protected
def schema_api(request: HttpRequest) -> JsonResponse:
    cache = schema_cache()
    alias = request.GET.get("connection") or "default"
    if alias not in cache.managed_aliases():
        raise Http404  # only managed connections are visualizable

    snapshot = cache.get(alias)
    # A snapshot Joist could not cache is still a correct snapshot, just built
    # live. Flagged rather than 500ing: the diagram works on a broken cache
    # store and the dashboard can say why.
    cache_unavailable = cache.last_error is not None

    snapshot["tables"] = without_excluded_tables(snapshot.get("tables", []), alias)
    diff_result, baseline_unavailable = _diff_for(alias, snapshot)
    snapshot["diff"] = diff_result
    snapshot["doctor"] = _doctor_for(alias, snapshot)
    if baseline_unavailable:
        snapshot["diff_unavailable"] = True
    if cache_unavailable:
        snapshot["cache_unavailable"] = True

    return JsonResponse(snapshot, json_dumps_params={"indent": None})


def _diff_for(alias: str, snapshot: dict) -> tuple[Any, bool]:
    """The structural diff against the recorded baseline, or None when the
    feature is off or no baseline exists. The baseline is filtered through the
    same exclusion list before comparison, so an excluded table never
    surfaces via the diff either."""
    if not joist_settings.get("diff.enabled", True):
        return None, False

    from .diff.baseline import BaselineStore
    from .diff.differ import SchemaDiffer

    baselines = BaselineStore()
    baseline = baselines.get(alias)
    if baseline is None:
        # A read failure and "no baseline yet" both land here; only the first
        # is worth telling anyone about (the second is a fresh install's
        # normal state until the next migration).
        return None, baselines.last_error is not None

    baseline["tables"] = without_excluded_tables(baseline.get("tables", []), alias)
    return SchemaDiffer().diff(baseline, snapshot), False


def _doctor_for(alias: str, snapshot: dict) -> dict | None:
    """The doctor report, or None when the dashboard Health panel is off. The
    snapshot is already exclusion-filtered, so excluded tables never reach a
    finding. Rides the same endpoint as the diagram: no extra request."""
    if not joist_settings.get("doctor.dashboard", True):
        return None

    from .doctor import DoctorReport

    return DoctorReport().for_snapshot(alias, snapshot)


# -- server-side export -------------------------------------------------------
@joist_protected
def export(request: HttpRequest, fmt: str) -> HttpResponse:
    """Structural export in the requested format, driving the same
    ExportBuilder the command and facade use. A malformed request (unknown
    format, unmanaged connection, missing focus table) 404s rather than
    confirming anything."""
    if fmt not in EXPORT_MIME:
        raise Http404

    from .export.builder import ExportBuilder

    builder = ExportBuilder().only(_list(request, "only")).exclude(_list(request, "except"))

    connection = request.GET.get("connection") or ""
    if connection:
        builder = builder.connection(connection)
    focus = request.GET.get("focus") or ""
    if focus:
        depth = request.GET.get("depth")
        builder = builder.focus(focus, int(depth) if depth is not None else None)
    if _boolean(request, "compact"):
        builder = builder.compact()
    if _boolean(request, "no_annotations"):
        builder = builder.without_annotations()

    try:
        content = builder.render(fmt)
    except ValueError:
        raise Http404 from None

    return HttpResponse(content, content_type=f"{EXPORT_MIME[fmt]}; charset=utf-8")


def _list(request: HttpRequest, key: str) -> list[str]:
    return [p for p in (s.strip() for s in (request.GET.get(key) or "").split(",")) if p]


def _boolean(request: HttpRequest, key: str) -> bool:
    return (request.GET.get(key) or "").lower() in ("1", "true", "yes", "on")


# -- theme + assets -------------------------------------------------------------
@joist_protected
def theme_css(request: HttpRequest) -> HttpResponse:
    css = ThemeStylesheet().build(joist_settings.get("theme") or {})
    response = HttpResponse(css, content_type="text/css; charset=UTF-8")
    response["Cache-Control"] = "no-store" if settings.DEBUG else "private, max-age=86400"
    return response


@joist_protected
def asset(request: HttpRequest, file: str) -> HttpResponse:
    """Serve a dashboard asset from the package. Allow-listed by basename -
    only known names map to paths, which makes traversal impossible - and
    gated with everything else."""
    relative = ASSETS.get(file)
    if relative is None:
        raise Http404
    # Defense in depth on top of the allow-list.
    path = (STATIC_ROOT / posixpath.normpath(relative)).resolve()
    if not path.is_file() or STATIC_ROOT.resolve() not in path.parents:
        raise Http404

    response = FileResponse(path.open("rb"), as_attachment=False, filename=file)
    response["Content-Type"] = _content_type(file)
    response["Cache-Control"] = "no-store" if settings.DEBUG else "private, max-age=86400"
    return response


def _content_type(file: str) -> str:
    if file.endswith(".css"):
        return "text/css"
    if file.endswith(".woff2"):
        return "font/woff2"
    return "text/javascript"
