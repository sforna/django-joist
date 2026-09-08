"""DBML serializer: a Table block per table, then Ref lines for the FKs.

Opens in dbdiagram.io and other DBML tools. Type mapping is deliberately
lossy: the native type passes through, quoted only when it would otherwise
misparse. Ref lines are emitted only when both endpoint tables are inside
the selection, so a filtered or focused export stays valid DBML.
"""

from __future__ import annotations

import re
from typing import Any

_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_KEYWORD = re.compile(r"^(true|false|null)$", re.IGNORECASE)
_SQL_EXPR = re.compile(r"^current_timestamp", re.IGNORECASE)
_NEEDS_QUOTES = re.compile(r"[\s,\"']")


class DbmlGenerator:
    def generate(self, tables: list[dict[str, Any]], notes: list[str] | None = None) -> str:
        notes = notes or []
        header = [self._project_block(notes)] if notes else []
        blocks = [self._table_block(t) for t in tables]
        refs = self._ref_lines(tables)
        return "\n\n".join([*header, *blocks, *refs]) + "\n"

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _project_block(notes: list[str]) -> str:
        body = "\n".join(f"    {note}" for note in notes)
        # The DBML project identifier is "joist"; the package's full name with
        # its hyphen would need quoting in every consumer of the file.
        return f"Project joist {{\n  Note: '''\n{body}\n  '''\n}}"

    def _table_block(self, table: dict[str, Any]) -> str:
        lines = [f"Table {table['name']} {{"]
        for column in table.get("columns") or []:
            lines.append(self._column_line(table, column))

        idx: list[str] = []
        pk = table.get("primary_key") or []
        # A composite PK is expressed in the indexes block, not on a column.
        if len(pk) > 1:
            idx.append(f"    ({', '.join(pk)}) [pk]")
        for index in table.get("indexes") or []:
            cols = (
                f"({', '.join(index['columns'])})"
                if len(index["columns"]) > 1
                else index["columns"][0]
            )
            idx.append(f"    {cols}" + (" [unique]" if index.get("unique") else ""))
        if idx:
            lines += ["", "  indexes {", *idx, "  }"]

        if table.get("annotation") is not None:
            lines.append(f"  Note: {self._note_token(table['annotation'])}")

        lines.append("}")
        return "\n".join(lines)

    def _column_line(self, table: dict[str, Any], column: dict[str, Any]) -> str:
        pk = table.get("primary_key") or []
        sole_pk = len(pk) == 1 and pk[0] == column["name"]

        parts: list[str] = []
        # pk implies not null, so a sole PK never also emits [not null].
        if sole_pk:
            parts.append("pk")
        elif not column.get("nullable"):
            parts.append("not null")
        if column.get("default") is not None:
            parts.append(f"default: {self._default_token(column['default'])}")
        if column.get("annotation") is not None:
            parts.append(f"note: {self._note_token(column['annotation'])}")

        settings = f" [{', '.join(parts)}]" if parts else ""
        return f"  {column['name']} {self._type_token(column['type'])}{settings}"

    @staticmethod
    def _note_token(note: str) -> str:
        """A single-quoted DBML note: newlines flatten to spaces (a bare note
        is single-line) and quotes escape, so the value cannot break out."""
        flat = re.sub(r"\s*\n\s*", " ", str(note).strip())
        return "'" + flat.replace("'", "\\'") + "'"

    @staticmethod
    def _type_token(native_type: str | None) -> str:
        t = str(native_type or "")
        if _NEEDS_QUOTES.search(t):
            return '"' + t.replace('"', '\\"') + '"'
        return t

    @staticmethod
    def _default_token(value: Any) -> str:
        s = str(value)
        if _NUMBER.match(s):
            return s  # bare number
        if _KEYWORD.match(s):
            return s.lower()  # boolean/null keyword
        if _SQL_EXPR.match(s) or "(" in s:
            return f"`{s}`"  # SQL expression
        return "'" + s.replace("'", "\\'") + "'"  # string literal

    @staticmethod
    def _ref_lines(tables: list[dict[str, Any]]) -> list[str]:
        present = {t["name"] for t in tables}
        refs: list[str] = []
        for table in tables:
            for fk in table.get("foreign_keys") or []:
                if fk["references_table"] not in present:
                    continue
                src = (
                    f"({', '.join(fk['columns'])})"
                    if len(fk["columns"]) > 1
                    else fk["columns"][0]
                )
                tgt = (
                    f"({', '.join(fk['references_columns'])})"
                    if len(fk["references_columns"]) > 1
                    else fk["references_columns"][0]
                )
                refs.append(f"Ref: {table['name']}.{src} > {fk['references_table']}.{tgt}")
        return refs
