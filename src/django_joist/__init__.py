"""django-joist: a live database structure viewer for Django.

Reads schema only: Joist introspects the live schema (tables,
columns, keys, indexes, foreign keys, comments) and renders it as a zoomable
ER diagram, exports, a structural diff and a deterministic schema review.
Row contents are never queried or exposed.

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
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["snapshot", "schema", "SnapshotBuilder", "__version__"]


def snapshot():
    """A fresh immutable export builder over the cached snapshot."""
    from .cache import schema_cache
    from .export.builder import ExportBuilder

    return ExportBuilder(cache=schema_cache())


def schema(alias: str | None = None):
    """The serialized schema snapshot for an alias (dict shape per DESIGN)."""
    from .cache import schema_cache

    return schema_cache().get(alias)


def __getattr__(name):
    # Keep the import of the introspection package lazy-ish: importing
    # django_joist must not require configured settings.
    if name == "SnapshotBuilder":
        from .introspection import SnapshotBuilder

        return SnapshotBuilder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
