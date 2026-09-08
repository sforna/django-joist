"""Annotation resolution: the business meaning a type cannot carry.

Annotations come from config and/or native schema comments, with a
configurable precedence. This module resolves the merged set and enriches the
snapshot tables with it. Enrichment is additive and conditional: a table or
column with no resolved annotation is returned untouched (no ``annotation``
key), so an un-annotated export is byte-identical to one produced without an
Annotator at all.

Difference from the reference: the reference injects a ``CommentReader`` that
re-introspects the *live* connection for comments. Here the introspection
builder already carries each native comment on the snapshot table/column
(the same structure-only ``CREATE TABLE`` data), so :func:`comments_from_snapshot`
derives the comment map from the snapshot instead of touching a connection.
Same output, one fewer DB round-trip, and it works identically in the
SQLite-fallback mode (where there is no live connection to read).
"""

from __future__ import annotations

from typing import Any


class Annotator:
    def __init__(
        self,
        source: list[str] | None = None,
        table_notes: dict[str, str] | None = None,
        column_notes: dict[str, str] | None = None,
        comments: dict[str, str] | None = None,
        notes: list[str] | None = None,
    ) -> None:
        self._source = list(source or ["config"])
        self._table_notes = table_notes or {}
        self._column_notes = column_notes or {}
        self._comments = comments or {}
        self._notes = notes or []

    @classmethod
    def from_config(cls, config: dict[str, Any], comments: dict[str, str] | None = None) -> Annotator:
        return cls(
            source=list(config.get("source") or ["config"]),
            table_notes=config.get("tables") or {},
            column_notes=config.get("columns") or {},
            comments=comments or {},
            notes=list(config.get("notes") or []),
        )

    def for_key(self, key: str) -> str | None:
        """Resolve one annotation by walking the sources in order; the first
        non-empty value wins. A key containing a dot is a column, else a table."""
        is_column = "." in key
        for source in self._source:
            if source == "config":
                value = (self._column_notes if is_column else self._table_notes).get(key)
            elif source == "database":
                value = self._comments.get(key)
            else:
                value = None
            if value is not None and str(value).strip() != "":
                return str(value)
        return None

    def notes_list(self) -> list[str]:
        """The trimmed, non-empty global notes, in order."""
        return [trimmed for trimmed in (str(n).strip() for n in self._notes) if trimmed]

    def annotate(self, tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Attach resolved annotations. Only non-empty annotations are added; a
        key that matches no remaining table is simply never matched, never an
        error."""
        out: list[dict[str, Any]] = []
        for table in tables:
            name = table["name"]
            table = dict(table)
            table_note = self.for_key(name)
            if table_note is not None:
                table["annotation"] = table_note
            columns = []
            for column in table.get("columns") or []:
                column = dict(column)
                column_note = self.for_key(f"{name}.{column['name']}")
                if column_note is not None:
                    column["annotation"] = column_note
                columns.append(column)
            table["columns"] = columns
            out.append(table)
        return out


def comments_from_snapshot(snapshot_tables: list[dict[str, Any]]) -> dict[str, str]:
    """The native comments map keyed by table name and "table.column", read
    off the already-introspected snapshot. Empty comments are skipped."""

    def present(value: Any) -> bool:
        return value is not None and str(value).strip() != ""

    comments: dict[str, str] = {}
    for table in snapshot_tables:
        if present(table.get("comment")):
            comments[table["name"]] = str(table["comment"])
        for column in table.get("columns") or []:
            if present(column.get("comment")):
                comments[f"{table['name']}.{column['name']}"] = str(column["comment"])
    return comments
