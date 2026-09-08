"""A bespoke plaintext format tuned for feeding a coding agent: one indented
line per column, foreign keys inline with ``->``, annotations indented
beneath the column they describe, and a short header with the table count
and any global notes. It trades the ceremony of DBML/Markdown for density.

Its nullability convention is inverted from SQL for compactness: a column is
not-null unless marked ``null``, so the common case costs no tokens.
Structure only, deterministic, and free of any metadata that changes between
runs (no connection, no timestamp), so two runs on the same schema are
byte-identical.
"""

from __future__ import annotations

import re
from typing import Any


class LlmGenerator:
    def generate(self, tables: list[dict[str, Any]], notes: list[str] | None = None) -> str:
        count = len(tables)
        header = [f"# {count} {'table' if count == 1 else 'tables'}"]
        for note in notes or []:
            header.append(f"# note: {self._flatten(note)}")

        blocks = [self._table_block(t) for t in tables]
        joined: list[str] = []
        for i, block in enumerate(blocks):
            if i:
                joined.append("")
            joined.append(block)

        return "\n".join([*header, "", *joined])

    # -- internals ---------------------------------------------------------
    def _table_block(self, table: dict[str, Any]) -> str:
        pk = table.get("primary_key") or []
        unique_columns = self._unique_columns(table)
        references = self._references(table)

        heading = table["name"]
        if table.get("annotation") is not None:
            heading += "  -- " + self._flatten(table["annotation"])

        lines = [heading]
        for column in table.get("columns") or []:
            name = column["name"]
            marker = (
                "  "
                + name
                + " "
                + str(column["type"])
                + (" null" if column.get("nullable") else "")
                + (" pk" if name in pk else "")
                + (" unique" if name in unique_columns else "")
                + (f" -> {references[name]}" if name in references else "")
            )
            lines.append(marker.rstrip())
            if column.get("annotation") is not None:
                lines.append("    # " + self._flatten(column["annotation"]))
        return "\n".join(lines)

    @staticmethod
    def _unique_columns(table: dict[str, Any]) -> list[str]:
        """Sole columns of unique indexes, so they can be marked inline."""
        return [
            idx["columns"][0]
            for idx in (table.get("indexes") or [])
            if idx.get("unique") and len(idx["columns"]) == 1
        ]

    @staticmethod
    def _references(table: dict[str, Any]) -> dict[str, str]:
        """Source column -> "table.column" target, paired positionally so
        composite keys map column by column."""
        mapping: dict[str, str] = {}
        for fk in table.get("foreign_keys") or []:
            for i, column in enumerate(fk["columns"]):
                target = (
                    fk["references_columns"][i]
                    if i < len(fk["references_columns"])
                    else fk["references_columns"][0]
                )
                mapping[column] = f"{fk['references_table']}.{target}"
        return mapping

    @staticmethod
    def _flatten(value: str) -> str:
        return re.sub(r"\s+", " ", str(value).strip())
