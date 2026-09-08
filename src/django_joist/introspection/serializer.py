"""The serialization boundary: typed value objects -> the plain dict shape.

This is the only place that knows the wire shape. The envelope fields
(``connection``, ``generated_at``) are *not* added here; those belong to the
caching layer, keeping this layer pure and deterministic.

The shape is composite-first (``primary_key``, index ``columns`` and FK
``columns``/``references_columns`` are all lists) and matches the reference
implementation's API contract, so the dashboard front end consumes either.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .data import Column, ForeignKey, Index, Table


class SchemaSerializer:
    def tables(self, tables: list[Table]) -> list[dict[str, Any]]:
        return [self.table(t) for t in tables]

    def table(self, table: Table) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": table.name,
            "columns": [self.column(c) for c in table.columns],
            "primary_key": list(table.primary_key),
            "indexes": [self.index(i) for i in table.indexes],
            "foreign_keys": [self.foreign_key(fk) for fk in table.foreign_keys],
        }
        if table.comment:
            out["comment"] = table.comment
        return out

    def column(self, column: Column) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": column.name,
            "type": column.type,
            "nullable": column.nullable,
            "default": column.default,
        }
        if column.comment:
            out["comment"] = column.comment
        return out

    def index(self, index: Index) -> dict[str, Any]:
        return {
            "name": index.name,
            "columns": list(index.columns),
            "unique": index.unique,
        }

    def foreign_key(self, fk: ForeignKey) -> dict[str, Any]:
        return {
            "name": fk.name,
            "columns": list(fk.columns),
            "references_table": fk.references_table,
            "references_columns": list(fk.references_columns),
            "on_update": fk.on_update,
            "on_delete": fk.on_delete,
        }
