"""Markdown data dictionary: a title, then one section per table with a
column table and index / foreign-key lines. Pairs with the client-side
dashboard export.

The export is intentionally connection-agnostic (no "Connection:" line): the
output must be identical whatever connection produced it, so the artifact a
CI job commits does not churn when the alias name changes.
"""

from __future__ import annotations

import re
from typing import Any, Callable


class MarkdownGenerator:
    def generate(self, tables: list[dict[str, Any]], notes: list[str] | None = None) -> str:
        notes = notes or []
        intro = ["\n".join("> " + self._flatten(note) for note in notes)] if notes else []
        sections = [self._table_section(t) for t in tables]
        return "\n\n".join(["# Data dictionary", *intro, *sections]) + "\n"

    # -- internals ---------------------------------------------------------
    def _table_section(self, table: dict[str, Any]) -> str:
        key = self._key_resolver(table)
        columns = table.get("columns") or []

        # The Description column appears only when a column in this table is
        # annotated, so an un-annotated table renders exactly as before.
        describe = any(c.get("annotation") is not None for c in columns)

        head = "| Column | Type | Null | Default | Key |" + (" Description |" if describe else "")
        rule = "| --- | --- | --- | --- | --- |" + (" --- |" if describe else "")

        lines = [f"## {table['name']}"]
        if table.get("annotation") is not None:
            lines += ["", "> " + self._flatten(table["annotation"])]
        lines += ["", head, rule]

        for c in columns:
            row = (
                "| "
                + self._cell(c["name"])
                + " | "
                + self._cell(c["type"])
                + " | "
                + ("yes" if c.get("nullable") else "no")
                + " | "
                + self._cell(c.get("default"))
                + " | "
                + key(c["name"])
                + " |"
            )
            if describe:
                row += " " + self._cell(c.get("annotation")) + " |"
            lines.append(row)

        indexes = table.get("indexes") or []
        if indexes:
            rendered = "; ".join(
                ((idx.get("name") or "") + " (").strip()
                + ", ".join(idx["columns"])
                + ")"
                + (" UNIQUE" if idx.get("unique") else "")
                for idx in indexes
            )
            lines += ["", f"Indexes: {rendered}"]

        fks = table.get("foreign_keys") or []
        if fks:
            lines += ["", "Foreign keys: " + "; ".join(self._fk_line(fk) for fk in fks)]

        return "\n".join(lines)

    @staticmethod
    def _fk_line(fk: dict[str, Any]) -> str:
        s = (
            ", ".join(fk["columns"])
            + " -> "
            + fk["references_table"]
            + "."
            + ", ".join(fk["references_columns"])
        )
        acts = []
        if fk.get("on_delete"):
            acts.append(f"on delete: {fk['on_delete']}")
        if fk.get("on_update"):
            acts.append(f"on update: {fk['on_update']}")
        if acts:
            s += " (" + ", ".join(acts) + ")"
        return s

    @staticmethod
    def _key_resolver(table: dict[str, Any]) -> Callable[[str], str]:
        """Derive the PK / FK badge for a column, mirroring the diagram and CSV."""
        pk = table.get("primary_key") or []
        fk_columns = [c for fk in (table.get("foreign_keys") or []) for c in fk["columns"]]
        return lambda name: ", ".join(
            badge
            for badge in (
                "PK" if name in pk else None,
                "FK" if name in fk_columns else None,
            )
            if badge
        )

    @staticmethod
    def _cell(value: Any) -> str:
        """A Markdown cell cannot contain a raw pipe or newline."""
        s = "" if value is None else str(value)
        return s.replace("|", "\\|").replace("\n", " ")

    @staticmethod
    def _flatten(value: str) -> str:
        return re.sub(r"\s+", " ", str(value).strip())
