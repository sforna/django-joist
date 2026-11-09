"""django-joist: a live database structure viewer for Django.

Reads schema only: Joist introspects the live schema (tables,
columns, keys, indexes, foreign keys, comments) and renders it as a zoomable
ER diagram, exports, a structural diff and a deterministic schema review.
With the default settings, row contents are never queried or exposed. The
optional migration replay can run project code when a connection fails.

Public API::

    from django_joist import snapshot

    text = (
        snapshot()
        .only(["orders", "order_lines"])
        .focus("orders", depth=1)
        .compact()
        .to_dbml()
    )

``snapshot()`` returns an immutable, fluent
:class:`django_joist.export.builder.ExportBuilder`; every filter returns a new
instance, so a base builder is safe to share.

``payload()`` returns the dict the dashboard runs on - the same one the JSON
endpoint serves - for a custom page that renders the diagram itself.
"""

from __future__ import annotations

__version__ = "0.3.1"

__all__ = ["SnapshotBuilder", "__version__", "payload", "schema", "snapshot"]


def snapshot():
    """A fresh immutable export builder over the cached snapshot."""
    from .cache import schema_cache
    from .export.builder import ExportBuilder

    return ExportBuilder(cache=schema_cache())


def schema(alias: str | None = None):
    """The serialized schema snapshot for an alias (dict shape per DESIGN)."""
    from .cache import schema_cache

    return schema_cache().get(alias)


def payload(alias: str | None = None):
    """The dashboard payload for an alias, in process, with no HTTP request.

    Unlike :func:`schema`, which is the raw cached snapshot, this is exactly
    what the dashboard's JSON endpoint serves: ``excluded_tables`` filtered
    out, plus the ``diff`` against the baseline, the ``doctor`` report, and
    the ``diff_unavailable`` / ``cache_unavailable`` flags when those apply.

    Runs no authorization: a page that exposes the result is responsible for
    gating it. Raises ``ValueError`` for an alias Joist does not manage.
    """
    from .dashboard import dashboard_payload

    return dashboard_payload(alias)


def __getattr__(name):
    # Keep the import of the introspection package lazy-ish: importing
    # django_joist must not require configured settings.
    if name == "SnapshotBuilder":
        from .introspection import SnapshotBuilder

        return SnapshotBuilder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
