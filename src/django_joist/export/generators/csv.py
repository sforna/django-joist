"""A flat, spreadsheet-friendly view of every column across every table,
with a derived PK / FK key column mirroring the diagram badges.

Structure only. The `table` column is what makes the whole schema fit one
sheet. The annotation column appears only when some column is annotated, so
an un-annotated export keeps the exact six-column shape.
"""

from __future__ import annotations

import re
from typing import Any

_NEEDS_QUOTES = re.compile(r'[",\n]')

HEADER = ["table", "name", "type", "nullable", "default", "key"]


class CsvGenerator:
    def generate(self, tables: list[dict[str, Any]], notes: list[str] | None = None) -> str:
        describe = self._has_column_annotation(tables)
        header = [*HEADER, "annotation"] if describe else list(HEADER)
        rows: list[list[Any]] = [header]

        for table in tables:
            pk = table.get("primary_key") or []
            fk_columns = [
                column for fk in (table.get("foreign_keys") or []) for column in fk["columns"]
            ]
            for column in table.get("columns") or []:
                key = ", ".join(
                    badge
                    for badge in (
                        "PK" if column["name"] in pk else None,
                        "FK" if column["name"] in fk_columns else None,
                    )
                    if badge
                )
                row = [
                    table["name"],
                    column["name"],
                    column["type"],
                    "true" if column.get("nullable") else "false",
                    column.get("default") if column.get("default") is not None else "",
                    key,
                ]
                if describe:
                    row.append(column.get("annotation") or "")
                rows.append(row)

        return "\n".join(",".join(self._cell(value) for value in row) for row in rows)

    @staticmethod
    def _cell(value: Any) -> str:
        s = "" if value is None else str(value)
        if _NEEDS_QUOTES.search(s):
            return '"' + s.replace('"', '""') + '"'
        return s

    @staticmethod
    def _has_column_annotation(tables: list[dict[str, Any]]) -> bool:
        return any(
            column.get("annotation") is not None
            for table in tables
            for column in (table.get("columns") or [])
        )
