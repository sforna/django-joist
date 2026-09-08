"""The canonical export pipeline as an immutable fluent builder.

Select an alias and filters, then render one structural format. This is the
single source of truth that the ``joist_export`` command, the gated export
route, and the package facade (``django_joist.snapshot()``) all drive, so
every access path produces identical output for the same inputs.

Each filter returns a new instance (the base is never mutated), so a
partially configured builder can be shared and branched safely. Structure
only: it reads the same cached snapshot the dashboard uses and never touches
row data. The same safeguards apply on every path: ``excluded_tables``
stripping, the ``managed_aliases()`` allow-list, and the alias's own
exclusions.
"""

from __future__ import annotations

from typing import Any

from ..conf import joist_settings
from ..selection import excluded_tables_for
from .annotator import Annotator, comments_from_snapshot
from .exporter import SchemaExporter
from .transforms import CompactTransform, FocusTransform


class ExportBuilder:
    def __init__(
        self,
        cache: Any = None,
        exporter: SchemaExporter | None = None,
        *,
        alias: str | None = None,
        only: list[str] | None = None,
        exclude: list[str] | None = None,
        focus_table: str | None = None,
        focus_depth: int | None = None,
        compact: bool = False,
        annotations: bool = True,
        fresh: bool = False,
    ) -> None:
        # Late-resolved so importing this module never needs Django settings;
        # one shared repository per process keeps last_error coherent.
        if cache is None:
            from ..cache import schema_cache

            cache = schema_cache()
        self._cache = cache
        self._exporter = exporter or SchemaExporter()
        self._alias = alias
        self._only = list(only or [])
        self._exclude = list(exclude or [])
        self._focus_table = focus_table
        self._focus_depth = focus_depth
        self._compact = compact
        self._annotations = annotations
        self._fresh = fresh
        self._resolved: dict[str, Any] | None = None

    # -- fluent filters (each returns a new builder) ----------------------
    def connection(self, alias: str) -> ExportBuilder:
        return self._copy(alias=alias)

    def only(self, tables: list[str]) -> ExportBuilder:
        return self._copy(only=list(tables))

    def exclude(self, tables: list[str]) -> ExportBuilder:
        return self._copy(exclude=list(tables))

    def focus(self, table: str, depth: int | None = None) -> ExportBuilder:
        return self._copy(focus_table=table, focus_depth=depth)

    def compact(self, on: bool = True) -> ExportBuilder:
        return self._copy(compact=on)

    def without_annotations(self) -> ExportBuilder:
        return self._copy(annotations=False)

    def fresh(self, on: bool = True) -> ExportBuilder:
        return self._copy(fresh=on)

    # -- terminals ----------------------------------------------------------
    def to_array(self) -> list[dict[str, Any]]:
        """The selected, filtered, focused, compacted, annotated tables."""
        return self._resolve()["tables"]

    def notes(self) -> list[str]:
        """The resolved global notes (empty when annotations are off)."""
        return self._resolve()["notes"]

    def render(self, fmt: str) -> str:
        """Render in one structural format, normalised to exactly one trailing
        newline so a file write, a piped stdout, and a ``--check`` comparison
        all compare the same bytes."""
        # Validate the format before touching the database: an unknown format
        # is a usage error, not a reason to build a snapshot.
        if not self._exporter.supports(fmt):
            raise ValueError(
                f"Unknown export format [{fmt}]. Supported: {', '.join(self._exporter.formats())}."
            )
        resolved = self._resolve()
        raw = self._exporter.generate(fmt, resolved["tables"], resolved["notes"])
        return raw.rstrip("\n") + "\n"

    def to_dbml(self) -> str:
        return self.render("dbml")

    def to_json(self) -> str:
        return self.render("json")

    def to_csv(self) -> str:
        return self.render("csv")

    def to_markdown(self) -> str:
        return self.render("markdown")

    def to_mermaid(self) -> str:
        return self.render("mermaid")

    def to_llm(self) -> str:
        return self.render("llm")

    # -- internals ----------------------------------------------------------
    def _resolve(self) -> dict[str, Any]:
        """Load the snapshot and run the full pipeline. Memoised, so several
        terminals on the same instance resolve once."""
        if self._resolved is not None:
            return self._resolved

        if self._alias is not None and self._alias not in self._cache.managed_aliases():
            raise ValueError(
                f"Connection [{self._alias}] is not managed by Joist. "
                "Add it under JOIST['connections']."
            )

        snapshot = (
            self._cache.rebuild(self._alias) if self._fresh else self._cache.get(self._alias)
        )
        alias = str(snapshot.get("connection") or self._alias or "default")

        tables = self._exporter.tables_for(
            snapshot.get("tables") or [],
            only=self._only,
            exclude=self._exclude,
            config_excluded=excluded_tables_for(alias),
        )
        if not tables:
            raise ValueError("No tables matched the given filters.")

        if self._focus_table is not None:
            depth = self._focus_depth
            if depth is None:
                depth = int(joist_settings.get("focus.default_depth", 1))
            tables = FocusTransform().apply(tables, self._focus_table, depth)

        if self._compact:
            tables = CompactTransform().apply(tables)

        tables, notes = self._apply_annotations(tables, snapshot)

        self._resolved = {"tables": tables, "notes": notes}
        return self._resolved

    def _apply_annotations(
        self, tables: list[dict[str, Any]], snapshot: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if not self._annotations:
            return tables, []

        config = dict(joist_settings.get("annotations") or {})
        sources = list(config.get("source") or ["config"])
        comments = (
            comments_from_snapshot(snapshot.get("tables") or []) if "database" in sources else {}
        )
        annotator = Annotator.from_config(config, comments)
        return annotator.annotate(tables), annotator.notes_list()

    def _copy(self, **overrides: Any) -> ExportBuilder:
        state = {
            "alias": self._alias,
            "only": self._only,
            "exclude": self._exclude,
            "focus_table": self._focus_table,
            "focus_depth": self._focus_depth,
            "compact": self._compact,
            "annotations": self._annotations,
            "fresh": self._fresh,
        }
        state.update(overrides)
        return ExportBuilder(self._cache, self._exporter, **state)
